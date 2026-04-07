from __future__ import annotations

import argparse
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from adapters.base import FillReport, MarketBar, OrderRequest
from adapters.binance_stub import BinanceStubAdapter
from data.backfill import backfill_to_csv, load_bars_from_csv
from execution.paper_broker import PaperBroker
from monitoring.logging_utils import configure_logger
from risk.limits import RiskLimits, allow_order, calculate_order_quantity
from strategies.base import Strategy, StrategySignal
from research.macro_cycle import (
    MacroCycleConfig,
    MacroCycleRecord,
    aggregate_to_daily,
    aggregate_to_weekly,
    check_daily_rsi_buy,
    check_daily_rsi_buy_native,
    check_daily_rsi_sell,
    check_daily_rsi_sell_native,
    check_weekly_rsi_buy,
    check_weekly_rsi_buy_native,
    compute_macd,
    detect_cycle_signal,
    get_monthly_rsi,
    get_monthly_rsi_native,
)
from research.daily_flag import detect_daily_flag
from strategies.channel_detector import ChannelDetector, DailyIndicators
from strategies.trend_breakout import (
    RULE_NAMES,
    StrategyEvaluation,
    TrendBreakoutConfig,
    TrendBreakoutStrategy,
    _BREAKOUT_RULES,
)


LOGGER = configure_logger("research.backtest")


@dataclass(frozen=True)
class TradeRecord:
    symbol: str
    side: str
    entry_rule: str
    exit_reason: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: float
    entry_fee: float
    exit_fee: float
    pnl: float
    return_pct: float
    metadata: dict[str, Any] | None = None  # stop_price, target, trailing_atr, confidence


@dataclass(frozen=True)
class RuleStat:
    signal_name: str
    trigger_count: int
    filled_entries: int
    win_rate_pct: float
    pnl: float
    contribution_pct: float


@dataclass(frozen=True)
class EventReviewRecord:
    event_label: str
    first_failed_condition: str
    start_time: datetime
    end_time: datetime
    bars: int
    parent_structure_type: str
    parent_position_in_channel: str
    parent_event_type: str
    rule_names: list[str]


@dataclass(frozen=True)
class HarvestRecord:
    """Record of a BTC-to-USDT profit harvest event."""
    timestamp: datetime
    trade_pnl_btc: float
    harvested_btc: float
    btc_price: float
    usdt_gained: float
    entry_rule: str


@dataclass(frozen=True)
class BacktestResult:
    initial_cash: float
    final_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    total_trades: int
    fills: list[FillReport]
    trades: list[TradeRecord]
    rule_stats: list[RuleStat]
    rejection_stats: dict[str, dict[str, int]]
    rule_eval_counts: dict[str, int]
    event_review_pack: list[EventReviewRecord]
    usdt_reserves: float = 0.0
    btc_harvested: float = 0.0
    harvest_events: list[HarvestRecord] | None = None
    macro_cycle_events: list[MacroCycleRecord] | None = None


@dataclass(frozen=True)
class BacktestComparison:
    baseline: BacktestResult
    enhanced: BacktestResult


def run_backtest(
    bars: list[MarketBar],
    symbol: str,
    strategy: Strategy,
    broker: PaperBroker,
    limits: RiskLimits,
    futures_provider: Any | None = None,
    mtf_bars: Any | None = None,
    macro_cycle: MacroCycleConfig | None = None,
    channel_quality_min_score: int = 0,
) -> BacktestResult:
    if len(bars) < 2:
        raise ValueError("Backtest requires at least two bars.")

    initial_cash = broker.get_cash()
    contract_type = getattr(broker, "contract_type", "linear")
    _cfg = getattr(strategy, "config", None)
    harvest_pct = getattr(_cfg, "impulse_harvest_pct", 0.0)
    harvest_min = getattr(_cfg, "impulse_harvest_min_pnl", 0.0)
    equity_curve: list[float] = [initial_cash]
    fills: list[FillReport] = []
    trades: list[TradeRecord] = []
    usdt_reserves: float = 0.0
    btc_harvested: float = 0.0
    harvest_events: list[HarvestRecord] = []
    macro_cycle_events: list[MacroCycleRecord] = []
    macro_last_action_bar: int = -9999
    macro_last_peak_count: int = 0     # Track processed peaks for dedup
    macro_last_trough_count: int = 0   # Track processed troughs for dedup
    macro_daily_sold_level: int = 0    # Highest daily RSI sell level triggered
    # D+W buy: arm-and-confirm bottom detection
    dw_buy_armed: bool = False          # True when D-RSI < 27 + W-RSI < 47 first seen
    dw_buy_low_price: float = float("inf")  # Lowest price seen while armed
    dw_buy_done: bool = False           # One buy per cycle; reset when D-RSI > 50
    macro_weekly_bought: bool = False   # Whether weekly RSI buy already triggered
    signal_counts: dict[str, int] = {}
    open_entries: dict[str, dict[str, Any]] = {}
    rejection_stats: dict[str, dict[str, int]] = {name: {} for name in RULE_NAMES}
    rule_eval_counts: dict[str, int] = {name: 0 for name in RULE_NAMES}
    event_markers: list[dict[str, Any]] = []
    time_stop_bars = getattr(getattr(strategy, "config", None), "time_stop_bars", None)
    _loss_cooldown_count = getattr(_cfg, "loss_cooldown_count", 0)
    _loss_cooldown_bars = getattr(_cfg, "loss_cooldown_bars", 24)
    consecutive_losses: int = 0
    cooldown_until: int = -1  # bar index until which entries are blocked
    _bear_reversal_enabled = getattr(_cfg, "bear_reversal_enabled", False)
    _bear_reversal_last_bar: int = -9999  # one-shot: cooldown after trigger

    # ── Native 1d/1w bars: use Binance candles directly for RSI ──
    _has_native = (
        mtf_bars is not None
        and "1d" in mtf_bars.timeframes
        and "1w" in mtf_bars.timeframes
    )
    _native_1d = mtf_bars._data["1d"] if _has_native else None
    _native_1w = mtf_bars._data["1w"] if _has_native else None
    _native_1d_ts = [b.timestamp for b in _native_1d] if _native_1d else []
    _native_1w_ts = [b.timestamp for b in _native_1w] if _native_1w else []
    _accel_zone = False  # persists between bars; updated every 6th bar

    for index in range(1, len(bars)):
        history = bars[: index + 1]
        current_bar = history[-1]
        position = broker.get_position(symbol)
        order: OrderRequest | None = None
        _daily_flag_signal: StrategySignal | None = None

        # Liquidation check (leverage)
        if position.is_open and hasattr(broker, "check_liquidation"):
            if broker.check_liquidation(symbol, current_bar.low if position.side == "long" else current_bar.high, current_bar.timestamp):
                entry_info = open_entries.pop(symbol, {})
                _liq_side = entry_info.get("side", position.side)
                if _liq_side == "buy":
                    _liq_side = "long"
                _liq_entry_fee = entry_info.get("entry_fee", 0)
                trades.append(TradeRecord(
                    symbol=symbol, side=_liq_side,
                    entry_rule=entry_info.get("entry_rule", "unknown"),
                    exit_reason="liquidation",
                    entry_time=entry_info.get("entry_time", current_bar.timestamp),
                    exit_time=current_bar.timestamp,
                    entry_price=entry_info.get("entry_price", 0),
                    exit_price=current_bar.low if position.side == "long" else current_bar.high,
                    quantity=position.quantity,
                    entry_fee=_liq_entry_fee,
                    exit_fee=0,
                    pnl=-position.reserved_margin - _liq_entry_fee,
                    return_pct=-100.0,
                    metadata={
                        "stop_price": entry_info.get("stop_price"),
                        "target_price": entry_info.get("target_price"),
                        "trailing_stop_atr": entry_info.get("trailing_stop_atr", 0),
                        "confidence": entry_info.get("confidence"),
                    },
                ))
                # Liquidation is always a loss
                consecutive_losses += 1
                if _loss_cooldown_count > 0 and consecutive_losses >= _loss_cooldown_count:
                    cooldown_until = index + _loss_cooldown_bars
                position = broker.get_position(symbol)

        # Trailing stop: update best price and check stop
        # ACCEL zone: weekly MACD death cross + daily MACD < 0 → widen trail 3x
        if not (position.is_open and symbol in open_entries and open_entries[symbol].get("side") == "short"):
            _accel_zone = False  # reset when not in a short position
        if position.is_open and symbol in open_entries:
            entry_info = open_entries[symbol]
            trail_atr = entry_info.get("trailing_stop_atr", 0)
            if trail_atr and trail_atr > 0:
                atr = _compute_trailing_atr(bars[: index + 1], 14)
                if atr > 0:
                    # ── ACCEL zone: dual-timeframe MACD impulse detection ──
                    # Weekly hist ≤ 0 (death cross) + Daily MACD < 0 (acceleration)
                    # → widen trail 3x to ride the full crash impulse.
                    # When daily MACD turns positive → reverts to 1x (deceleration).
                    _accel_mult = getattr(_cfg, "accel_trail_multiplier", 3.0)
                    if (
                        entry_info["side"] == "short"
                        and entry_info.get("trade_type") == "impulse"
                        and index % 6 == 0
                        and len(bars[: index + 1]) > 240
                    ):
                        # Daily MACD
                        if _native_1d is not None:
                            _ac_di = bisect_right(_native_1d_ts, current_bar.timestamp)
                            _ac_d_bars = _native_1d[:_ac_di]
                        else:
                            _ac_d_bars = aggregate_to_daily(bars[: index + 1])
                        _ac_d_macd, _, _ = compute_macd(_ac_d_bars)

                        # Weekly MACD histogram
                        if _native_1w is not None:
                            _ac_wi = bisect_right(_native_1w_ts, current_bar.timestamp)
                            _ac_w_bars = _native_1w[:_ac_wi]
                        else:
                            _ac_w_bars = aggregate_to_weekly(bars[: index + 1])
                        _, _, _ac_w_hist = compute_macd(_ac_w_bars)

                        _accel_zone = (
                            _ac_w_hist is not None and _ac_w_hist <= 0
                            and _ac_d_macd is not None and _ac_d_macd < 0
                        )

                    # Trail multiplier: ACCEL zone 3x, normal 1x
                    if _accel_zone:
                        effective_trail = trail_atr * _accel_mult
                        entry_info["_accel_active_bars"] = entry_info.get("_accel_active_bars", 0) + 1
                    else:
                        effective_trail = trail_atr

                    if entry_info["side"] == "short":
                        entry_info["best_price"] = min(entry_info["best_price"], current_bar.low)
                        trail_stop = entry_info["best_price"] + effective_trail * atr
                        if current_bar.close >= trail_stop:
                            order = OrderRequest(
                                symbol=symbol, side="cover", quantity=position.quantity,
                                timestamp=current_bar.timestamp,
                                metadata={"reason": "trailing_stop"},
                            )
                    elif entry_info["side"] == "buy":
                        entry_info["best_price"] = max(entry_info["best_price"], current_bar.high)
                        trail_stop = entry_info["best_price"] - effective_trail * atr
                        if current_bar.close <= trail_stop:
                            order = OrderRequest(
                                symbol=symbol, side="sell", quantity=position.quantity,
                                timestamp=current_bar.timestamp,
                                metadata={"reason": "trailing_stop"},
                            )

        if order is None and position.is_open and symbol in open_entries and time_stop_bars is not None:
            bars_held = index - open_entries[symbol]["entry_index"]
            if bars_held >= time_stop_bars:
                order = OrderRequest(
                    symbol=symbol,
                    side="sell" if position.side == "long" else "cover",
                    quantity=position.quantity,
                    timestamp=current_bar.timestamp,
                    metadata={"reason": "time_stop"},
                )

        # ── Consecutive loss cooldown: skip entries when on tilt ──
        _in_cooldown = (
            _loss_cooldown_count > 0
            and not position.is_open
            and consecutive_losses >= _loss_cooldown_count
            and index < cooldown_until
        )

        # ── Daily flag overlay: bear flag breakdown / bull flag breakout ──
        # Check every 6 bars (~1 day) when no position is open.
        # Uses daily-scale channel detection (independent of 4h rules).
        if (
            order is None
            and not position.is_open
            and not _in_cooldown
            and index % 6 == 0
            and index > 360  # need ~60 days of daily data
        ):
            _parent_ctx = None
            try:
                _parent_ctx = strategy.evaluate(
                    symbol=symbol, bars=bars[: index + 1], position=position,
                ).parent_context
            except Exception:
                pass
            _parent_trend = None
            if _parent_ctx and _parent_ctx.get("parent_structure_type"):
                pst = _parent_ctx["parent_structure_type"]
                if "ascending" in str(pst):
                    _parent_trend = "ascending"
                elif "descending" in str(pst):
                    _parent_trend = "descending"

            flag_sig = detect_daily_flag(
                bars[: index + 1],
                lookback_days=60,
                pivot_window=3,
                min_pivots=3,
                min_r_squared=0.15,
                parent_trend=_parent_trend,
            )
            if flag_sig.action in {"short", "long"}:
                # Bear flag weekly RSI guard: block bear flag shorts in bull market
                _bf_ok = True
                _bf_max_wrsi = getattr(getattr(strategy, "config", None), "bear_flag_max_weekly_rsi", 0.0)
                if (
                    flag_sig.action == "short"
                    and _bf_max_wrsi > 0
                    and len(bars[: index + 1]) > 240
                ):
                    from research.macro_cycle import compute_weekly_rsi
                    if _native_1w is not None:
                        _wi_bf = bisect_right(_native_1w_ts, current_bar.timestamp)
                        _bf_wrsi = compute_weekly_rsi(_native_1w[:_wi_bf])
                    else:
                        _bf_wrsi = compute_weekly_rsi(aggregate_to_weekly(bars[: index + 1]))
                    if _bf_wrsi is not None and _bf_wrsi > _bf_max_wrsi:
                        _bf_ok = False  # bull market: bear flag unreliable

                if _bf_ok:
                    _flag_trail_atr = getattr(getattr(strategy, "config", None), "impulse_trailing_stop_atr", 6.0) or 6.0
                    _daily_flag_signal = StrategySignal(
                        action=flag_sig.action,
                        confidence=flag_sig.confidence,
                        reason=f"daily_{flag_sig.flag_type}",
                        stop_price=flag_sig.resistance if flag_sig.action == "short" else flag_sig.support,
                        target_price=None,
                        metadata={"trailing_stop_atr": _flag_trail_atr, "trade_type": "impulse"},
                    )

        # ── Bear reversal combo: daily VP-based bottom detection ──
        # Independent of 4h channel rules. One-shot: 540 bar cooldown (~90 days) after trigger.
        _bear_reversal_signal: StrategySignal | None = None
        if (
            order is None
            and not position.is_open
            and not _in_cooldown
            and _bear_reversal_enabled
            and index % 6 == 0
            and index > 1500  # need 250+ daily bars (~1500 4h bars)
            and index - _bear_reversal_last_bar > 540  # 90-day cooldown between signals
        ):
            if _native_1d is not None:
                _di_br = bisect_right(_native_1d_ts, current_bar.timestamp)
                _br_daily = _native_1d[:_di_br]
            else:
                _br_daily = aggregate_to_daily(bars[: index + 1])
            if len(_br_daily) >= 250:
                from indicators.volume_profile import detect_bear_reversal_phase
                # Only pass last 300 daily bars so old events expire naturally
                _br_phase = detect_bear_reversal_phase(_br_daily[-300:])
                if _br_phase.action == "buy":
                    _bear_reversal_signal = StrategySignal(
                        action="buy",
                        confidence=_br_phase.confidence,
                        reason="bear_reversal_combo",
                        stop_price=_br_phase.stop_price,
                        target_price=None,
                        metadata={
                            "trailing_stop_atr": getattr(_cfg, "impulse_trailing_stop_atr", 6.0) or 6.0,
                            **_br_phase.metadata,
                        },
                    )
                    _bear_reversal_last_bar = index  # one-shot: prevent re-trigger for 540 bars

        if order is None and not _in_cooldown:
            signal, evaluation = _evaluate_strategy(strategy=strategy, symbol=symbol, history=history, position=position, futures_provider=futures_provider, mtf_bars=mtf_bars)

            # Daily flag overrides 4h hold signal (flag is higher priority)
            if signal.action == "hold" and _daily_flag_signal is not None:
                signal = _daily_flag_signal
            # Bear reversal combo: only if no other signal
            if signal.action == "hold" and _bear_reversal_signal is not None:
                signal = _bear_reversal_signal
            if evaluation is not None:
                for item in evaluation.rule_evaluations:
                    rule_eval_counts[item.rule_name] = rule_eval_counts.get(item.rule_name, 0) + 1
                    if item.triggered:
                        signal_counts[item.rule_name] = signal_counts.get(item.rule_name, 0) + 1
                    elif item.first_failed_condition:
                        bucket = rejection_stats.setdefault(item.rule_name, {})
                        reason = item.first_failed_condition
                        bucket[reason] = bucket.get(reason, 0) + 1
                        marker = _build_event_marker(current_bar.timestamp, item)
                        if marker is not None:
                            event_markers.append(marker)
            elif signal.action in {"buy", "short"} and signal.reason:
                signal_counts[signal.reason] = signal_counts.get(signal.reason, 0) + 1

            # ── Channel quality gate: ★★★ indicator filter for ALL channel rules ──
            # SHORT channel signals → score_high_pivot (★★★ HIGH conditions)
            # LONG channel signals → score_low_pivot (★★★ LOW conditions)
            if (
                signal.action in {"buy", "short"}
                and channel_quality_min_score > 0
                and futures_provider is not None
                and signal.reason
                and "channel" in signal.reason
            ):
                signal = _channel_quality_gate(
                    signal, current_bar, futures_provider,
                    bars[: index + 1], channel_quality_min_score,
                )

            # ── Weekly MACD death cross gate: block ALL shorts in bull trend ──
            # 週線 MACD 金叉 (histogram > 0) = 牛市 → 阻擋做空
            # 週線 MACD 死叉 (histogram <= 0) = 熊市 → 做空放行
            _weekly_macd_gate = getattr(_cfg, "weekly_macd_short_gate", False)
            if signal.action == "short" and _weekly_macd_gate and index > 240:
                if _native_1w is not None:
                    _wi_mg = bisect_right(_native_1w_ts, current_bar.timestamp)
                    _wm_bars = _native_1w[:_wi_mg]
                else:
                    _wm_bars = aggregate_to_weekly(bars[: index + 1])
                _, _, _wm_hist = compute_macd(_wm_bars)
                if _wm_hist is not None and _wm_hist > 0:
                    signal = StrategySignal(
                        action="hold", confidence=0,
                        reason="weekly_macd_bullish_block",
                    )

            # ── ACCEL zone: block buy/long signals during impulse ──
            # 週線死叉 + 日線MACD<0 = 加速下跌中 → 阻擋做多，等脈衝結束再放行
            if _accel_zone and signal.action == "buy":
                signal = StrategySignal(
                    action="hold", confidence=0,
                    reason="accel_zone_long_blocked",
                )

            if signal.action in {"buy", "short"}:
                stop_dist = 0.0
                if signal.stop_price and signal.stop_price > 0:
                    stop_dist = abs(current_bar.close - signal.stop_price) / current_bar.close

                # Check if this is a scale-in opportunity
                is_scale_in = False
                if position.is_open and limits.scale_in_max_adds > 0:
                    same_dir = (signal.action == "buy" and position.side == "long") or \
                               (signal.action == "short" and position.side == "short")
                    adds_so_far = open_entries.get(symbol, {}).get("scale_in_count", 0)
                    if same_dir and adds_so_far < limits.scale_in_max_adds:
                        is_scale_in = True

                # MTF 1h scale mode: use mtf_sizing from metadata for position scaling
                conf = signal.metadata.get("mtf_sizing", 1.0) if signal.metadata else 1.0

                # For inverse contracts, convert BTC cash to USD equivalent for sizing
                sizing_cash = broker.get_cash()
                if contract_type == "inverse":
                    sizing_cash = sizing_cash * current_bar.close

                if is_scale_in:
                    # Scale-in: use scale_in_position_pct for sizing
                    scale_in_limits = RiskLimits(
                        max_position_pct=limits.scale_in_position_pct,
                        risk_per_trade_pct=limits.risk_per_trade_pct,
                        leverage=limits.leverage,
                    )
                    quantity = calculate_order_quantity(
                        cash=sizing_cash,
                        market_price=current_bar.close,
                        limits=scale_in_limits,
                        stop_distance_pct=stop_dist,
                        confidence_multiplier=conf,
                    )
                    entry_metadata = {"scale_in": True, "reason": signal.reason}
                else:
                    quantity = calculate_order_quantity(
                        cash=sizing_cash,
                        market_price=current_bar.close,
                        limits=limits,
                        stop_distance_pct=stop_dist,
                        confidence_multiplier=conf,
                    )
                    entry_metadata = {
                        "reason": signal.reason,
                        "stop_price": signal.stop_price,
                        "target_price": signal.target_price,
                        "second_target_price": signal.metadata.get("second_target_price") if signal.metadata else None,
                    }
                    if signal.metadata and signal.metadata.get("trailing_stop_atr"):
                        entry_metadata["trailing_stop_atr"] = signal.metadata["trailing_stop_atr"]
                    if signal.metadata and signal.metadata.get("trade_type"):
                        entry_metadata["trade_type"] = signal.metadata["trade_type"]
                order = OrderRequest(
                    symbol=symbol,
                    side=signal.action,
                    quantity=quantity,
                    timestamp=current_bar.timestamp,
                    metadata=entry_metadata,
                )
            elif signal.action in {"sell", "cover"}:
                order = OrderRequest(
                    symbol=symbol,
                    side=signal.action,
                    quantity=position.quantity,
                    timestamp=current_bar.timestamp,
                    metadata={"reason": signal.reason},
                )

        if order and allow_order(
            cash=broker.get_cash(),
            order=order,
            market_price=current_bar.close,
            open_positions=_count_open_positions(broker, symbol),
            limits=limits,
            existing_position=position,
            contract_type=contract_type,
        ):
            fill = broker.submit_order(order=order, market_price=current_bar.close)
            if fill is not None:
                fills.append(fill)
                if fill.side in {"buy", "short"}:
                    if order.metadata.get("scale_in") and fill.symbol in open_entries:
                        # Scale-in: increment counter, keep original entry info
                        open_entries[fill.symbol]["scale_in_count"] = open_entries[fill.symbol].get("scale_in_count", 0) + 1
                    else:
                        open_entries[fill.symbol] = {
                            "symbol": fill.symbol,
                            "entry_rule": order.metadata.get("reason", ""),
                            "side": fill.side,
                            "entry_time": fill.timestamp,
                            "entry_price": fill.fill_price,
                            "entry_fee": fill.fee,
                            "entry_index": index,
                            "trailing_stop_atr": order.metadata.get("trailing_stop_atr", 0),
                            "trade_type": order.metadata.get("trade_type", ""),
                            "best_price": fill.fill_price,
                            "scale_in_count": 0,
                            "stop_price": order.metadata.get("stop_price"),
                            "target_price": order.metadata.get("target_price"),
                            "confidence": signal.confidence if order is not None else None,
                        }
                elif fill.side in {"sell", "cover"} and fill.symbol in open_entries:
                    entry = open_entries.pop(fill.symbol)
                    trade_rec = _build_trade_record(
                        entry=entry,
                        exit_fill=fill,
                        exit_reason=order.metadata.get("reason", ""),
                        contract_type=contract_type,
                    )
                    trades.append(trade_rec)
                    # Consecutive loss cooldown tracking
                    if trade_rec.pnl > 0:
                        consecutive_losses = 0
                    else:
                        consecutive_losses += 1
                        if _loss_cooldown_count > 0 and consecutive_losses >= _loss_cooldown_count:
                            cooldown_until = index + _loss_cooldown_bars
                    # Impulse harvest: convert % of large-win profit BTC → USDT
                    if (
                        harvest_pct > 0
                        and contract_type == "inverse"
                        and trade_rec.pnl > harvest_min
                    ):
                        harvest_btc = trade_rec.pnl * harvest_pct
                        actual = broker.deduct_cash(harvest_btc)
                        harvest_usdt = actual * fill.fill_price
                        usdt_reserves += harvest_usdt
                        btc_harvested += actual
                        harvest_events.append(HarvestRecord(
                            timestamp=fill.timestamp,
                            trade_pnl_btc=trade_rec.pnl,
                            harvested_btc=actual,
                            btc_price=fill.fill_price,
                            usdt_gained=harvest_usdt,
                            entry_rule=trade_rec.entry_rule,
                        ))
                LOGGER.info(
                    "filled %s %s qty=%.6f price=%.2f",
                    fill.side,
                    fill.symbol,
                    fill.quantity,
                    fill.fill_price,
                )

        # ── Macro cycle overlay: sell/buy on BTC cycle ──
        # D+W sell: daily RSI >= 75 AND weekly RSI >= 70, guarded by monthly RSI >= 65.
        if macro_cycle is not None and contract_type == "inverse":

            # ── Layer 1: D+W RSI sell (D>=75 + W>=70 + M>=65 guard) ──
            if index % 6 == 0 and index > 180:  # need ~30 daily bars
                if _has_native:
                    _di_s = bisect_right(_native_1d_ts, current_bar.timestamp)
                    _wi_s = bisect_right(_native_1w_ts, current_bar.timestamp)
                    _d_sell, _d_rsi, _w_rsi = check_daily_rsi_sell_native(
                        _native_1d[:_di_s], _native_1w[:_wi_s], macro_cycle,
                    )
                else:
                    _d_sell, _d_rsi, _w_rsi = check_daily_rsi_sell(
                        bars[: index + 1], macro_cycle,
                    )

                # Reset daily sell level when daily RSI drops below 50
                if _d_rsi > 0 and _d_rsi < 50.0:
                    macro_daily_sold_level = 0

                # Monthly RSI guard: block sell if market not hot enough
                if _has_native:
                    _sell_m_rsi = get_monthly_rsi_native(
                        _native_1d[:_di_s], macro_cycle,
                    )
                else:
                    _sell_m_rsi = get_monthly_rsi(bars[: index + 1], macro_cycle)

                if (
                    _d_sell
                    and macro_daily_sold_level == 0
                    and _sell_m_rsi >= macro_cycle.dw_sell_min_monthly_rsi
                ):
                    macro_daily_sold_level = 1
                    _sell_pct = macro_cycle.daily_rsi_sell_pct
                    free_btc = broker.get_cash()
                    sellable = max(0.0, free_btc - macro_cycle.min_btc_reserve)
                    sell_btc = min(free_btc * _sell_pct, sellable)
                    if sell_btc > 0.001:
                        actual = broker.deduct_cash(sell_btc)
                        sell_usdt = actual * current_bar.close
                        usdt_reserves += sell_usdt
                        btc_harvested += actual
                        macro_cycle_events.append(MacroCycleRecord(
                            timestamp=current_bar.timestamp,
                            action="sell_top",
                            btc_price=current_bar.close,
                            weekly_rsi=_d_rsi,
                            sma200_ratio=_w_rsi,  # store weekly RSI
                            funding_rate=_sell_m_rsi,  # store monthly RSI
                            top_ls_ratio=None,
                            btc_amount=actual,
                            usdt_amount=sell_usdt,
                            btc_balance_after=broker.get_cash(),
                            usdt_balance_after=usdt_reserves,
                            divergence_score=-1.0,  # marker: D+W RSI sell
                        ))
                        macro_last_action_bar = index

            # ── Layer 1b: Weekly RSI buy (oversold accumulation) ──
            if (
                index % 42 == 0
                and usdt_reserves > 0
                and not macro_weekly_bought
            ):
                if _has_native:
                    _wi_b = bisect_right(_native_1w_ts, current_bar.timestamp)
                    _w_buy, _w_rsi_buy = check_weekly_rsi_buy_native(
                        _native_1w[:_wi_b], macro_cycle,
                    )
                else:
                    _w_buy, _w_rsi_buy = check_weekly_rsi_buy(
                        bars[: index + 1], macro_cycle,
                    )
                if _w_buy:
                    usdt_to_spend = usdt_reserves * macro_cycle.weekly_rsi_buy_pct
                    btc_to_buy = usdt_to_spend / current_bar.close
                    broker.add_cash(btc_to_buy)
                    usdt_reserves -= usdt_to_spend
                    macro_cycle_events.append(MacroCycleRecord(
                        timestamp=current_bar.timestamp,
                        action="buy_bottom",
                        btc_price=current_bar.close,
                        weekly_rsi=_w_rsi_buy,
                        sma200_ratio=0.0,
                        funding_rate=None,
                        top_ls_ratio=None,
                        btc_amount=btc_to_buy,
                        usdt_amount=usdt_to_spend,
                        btc_balance_after=broker.get_cash(),
                        usdt_balance_after=usdt_reserves,
                        divergence_score=0.0,
                    ))
                    macro_last_action_bar = index
                    macro_weekly_bought = True

            # Reset weekly buy flag when RSI recovers above 50
            if macro_weekly_bought and index % 42 == 0:
                if _has_native:
                    _wi_r = bisect_right(_native_1w_ts, current_bar.timestamp)
                    _, _w_chk = check_weekly_rsi_buy_native(
                        _native_1w[:_wi_r], macro_cycle,
                    )
                else:
                    _, _w_chk = check_weekly_rsi_buy(
                        bars[: index + 1], macro_cycle,
                    )
                if _w_chk > macro_cycle.weekly_rsi_buy_trigger + 25:
                    macro_weekly_bought = False

            # ── Layer 1c: D+W buy with arm-and-confirm bottom detection ──
            # Phase 1 (ARM): D-RSI < 27 + W-RSI < 47 -> enter armed mode,
            #   track lowest price seen.
            # Phase 2 (CONFIRM): price bounces >= 5% from lowest -> BUY.
            #   Buys 20% of USDT reserves. One buy per cycle.
            # NOTE: RSI computation + reset MUST run even when usdt_reserves == 0,
            # otherwise dw_buy_armed/dw_buy_done flags never reset.
            if index % 6 == 0 and index > 180:
                if _has_native:
                    _di_b = bisect_right(_native_1d_ts, current_bar.timestamp)
                    _wi_b2 = bisect_right(_native_1w_ts, current_bar.timestamp)
                    _db_buy, _db_rsi, _db_wrsi = check_daily_rsi_buy_native(
                        _native_1d[:_di_b], _native_1w[:_wi_b2], macro_cycle,
                    )
                else:
                    _db_buy, _db_rsi, _db_wrsi = check_daily_rsi_buy(
                        bars[: index + 1], macro_cycle,
                    )

                # ARM: first time D-RSI < 27 + W-RSI < 47
                if _db_buy and not dw_buy_armed and not dw_buy_done:
                    dw_buy_armed = True
                    dw_buy_low_price = current_bar.close

                # Track lowest price while armed
                if dw_buy_armed and current_bar.close < dw_buy_low_price:
                    dw_buy_low_price = current_bar.close

                # CONFIRM: price bounced from low -> bottom confirmed
                if dw_buy_armed and not dw_buy_done and usdt_reserves > 0:
                    _bounce = (current_bar.close - dw_buy_low_price) / dw_buy_low_price
                    if _bounce >= macro_cycle.dw_buy_bounce_pct:
                        usdt_to_spend = usdt_reserves * macro_cycle.daily_rsi_buy_pct
                        btc_to_buy = usdt_to_spend / current_bar.close
                        broker.add_cash(btc_to_buy)
                        usdt_reserves -= usdt_to_spend
                        macro_cycle_events.append(MacroCycleRecord(
                            timestamp=current_bar.timestamp,
                            action="buy_bottom",
                            btc_price=current_bar.close,
                            weekly_rsi=_db_rsi,
                            sma200_ratio=_db_wrsi,  # store weekly RSI
                            funding_rate=None,
                            top_ls_ratio=None,
                            btc_amount=btc_to_buy,
                            usdt_amount=usdt_to_spend,
                            btc_balance_after=broker.get_cash(),
                            usdt_balance_after=usdt_reserves,
                            divergence_score=-2.0,  # marker: D+W RSI buy
                        ))
                        macro_last_action_bar = index
                        dw_buy_armed = False
                        dw_buy_done = True  # one buy per cycle

                # Reset: when D-RSI recovers above 50 -> new cycle
                if _db_rsi > 0 and _db_rsi >= 50.0:
                    dw_buy_armed = False
                    dw_buy_done = False
                    dw_buy_low_price = float("inf")

            # ── Layer 2: Weekly RSI divergence (structural top/bottom) ──
            if (
                index % 42 == 0
                and index - macro_last_action_bar >= macro_cycle.cooldown_bars_4h
            ):
                _funding = None
                _top_ls = None
                if futures_provider is not None:
                    _snap = futures_provider.get_snapshot(symbol, current_bar.timestamp)
                    if _snap is not None:
                        _funding = getattr(_snap, "funding_rate", None)
                        _top_ls = getattr(_snap, "top_ls_ratio", None)
                if _has_native:
                    _di_d = bisect_right(_native_1d_ts, current_bar.timestamp)
                    _wi_d = bisect_right(_native_1w_ts, current_bar.timestamp)
                    cycle_sig = detect_cycle_signal(
                        bars[: index + 1], macro_cycle,
                        funding_rate=_funding, top_ls_ratio=_top_ls,
                        native_daily=_native_1d[:_di_d],
                        native_weekly=_native_1w[:_wi_d],
                    )
                else:
                    cycle_sig = detect_cycle_signal(
                        bars[: index + 1], macro_cycle,
                        funding_rate=_funding, top_ls_ratio=_top_ls,
                    )

                # Monthly RSI guard: block false divergence signals
                if _has_native:
                    _div_m_rsi = get_monthly_rsi_native(
                        _native_1d[:_di_d], macro_cycle,
                    )
                else:
                    _div_m_rsi = get_monthly_rsi(bars[: index + 1], macro_cycle)

                # Sell at bearish divergence (new peak confirmed)
                # Guard: only sell if monthly RSI confirms market is hot
                if (
                    cycle_sig.action == "sell_top"
                    and cycle_sig.peak_count > macro_last_peak_count
                    and _div_m_rsi >= macro_cycle.divergence_sell_min_monthly_rsi
                ):
                    _sell_pct = cycle_sig.sell_pct or macro_cycle.sell_pct
                    free_btc = broker.get_cash()
                    sellable = max(0.0, free_btc - macro_cycle.min_btc_reserve)
                    sell_btc = min(free_btc * _sell_pct, sellable)
                    if sell_btc > 0.001:
                        actual = broker.deduct_cash(sell_btc)
                        sell_usdt = actual * current_bar.close
                        usdt_reserves += sell_usdt
                        btc_harvested += actual
                        macro_cycle_events.append(MacroCycleRecord(
                            timestamp=current_bar.timestamp,
                            action="sell_top",
                            btc_price=current_bar.close,
                            weekly_rsi=cycle_sig.weekly_rsi or 0.0,
                            sma200_ratio=cycle_sig.sma200_ratio or 0.0,
                            funding_rate=_funding,
                            top_ls_ratio=_top_ls,
                            btc_amount=actual,
                            usdt_amount=sell_usdt,
                            btc_balance_after=broker.get_cash(),
                            usdt_balance_after=usdt_reserves,
                            divergence_score=cycle_sig.divergence_score,
                        ))
                        macro_last_action_bar = index
                    macro_last_peak_count = cycle_sig.peak_count

                # Buy at bullish divergence (new trough confirmed)
                # Guard: only buy if monthly RSI confirms market is cold
                elif (
                    cycle_sig.action == "buy_bottom"
                    and cycle_sig.trough_count > macro_last_trough_count
                    and usdt_reserves > 0
                    and _div_m_rsi <= macro_cycle.divergence_buy_max_monthly_rsi
                ):
                    _buy_pct = cycle_sig.buy_pct or macro_cycle.buy_pct
                    usdt_to_spend = usdt_reserves * _buy_pct
                    btc_to_buy = usdt_to_spend / current_bar.close
                    broker.add_cash(btc_to_buy)
                    usdt_reserves -= usdt_to_spend
                    macro_cycle_events.append(MacroCycleRecord(
                        timestamp=current_bar.timestamp,
                        action="buy_bottom",
                        btc_price=current_bar.close,
                        weekly_rsi=cycle_sig.weekly_rsi or 0.0,
                        sma200_ratio=cycle_sig.sma200_ratio or 0.0,
                        funding_rate=_funding,
                        top_ls_ratio=_top_ls,
                        btc_amount=btc_to_buy,
                        usdt_amount=usdt_to_spend,
                        btc_balance_after=broker.get_cash(),
                        usdt_balance_after=usdt_reserves,
                        divergence_score=cycle_sig.divergence_score,
                    ))
                    macro_last_action_bar = index
                    macro_last_trough_count = cycle_sig.trough_count

                else:
                    macro_last_peak_count = max(
                        macro_last_peak_count, cycle_sig.peak_count,
                    )
                    macro_last_trough_count = max(
                        macro_last_trough_count, cycle_sig.trough_count,
                    )

        equity_curve.append(broker.mark_to_market(symbol=symbol, market_price=current_bar.close))

    final_position = broker.get_position(symbol)
    if final_position.is_open and symbol in open_entries:
        last_bar = bars[-1]
        fill = broker.submit_order(
            order=OrderRequest(
                symbol=symbol,
                side="sell" if final_position.side == "long" else "cover",
                quantity=final_position.quantity,
                timestamp=last_bar.timestamp,
                metadata={"reason": "forced_end_of_backtest"},
            ),
            market_price=last_bar.close,
        )
        if fill is not None:
            fills.append(fill)
            trades.append(
                _build_trade_record(
                    entry=open_entries.pop(symbol),
                    exit_fill=fill,
                    exit_reason="forced_end_of_backtest",
                    contract_type=contract_type,
                )
            )
        equity_curve[-1] = broker.mark_to_market(symbol=symbol, market_price=last_bar.close)

    final_equity = equity_curve[-1]
    return BacktestResult(
        initial_cash=initial_cash,
        final_equity=final_equity,
        total_return_pct=((final_equity - initial_cash) / initial_cash) * 100,
        max_drawdown_pct=_max_drawdown_pct(equity_curve),
        total_trades=len(trades),
        fills=fills,
        trades=trades,
        rule_stats=_build_rule_stats(signal_counts, trades),
        rejection_stats={rule: reasons for rule, reasons in rejection_stats.items() if reasons},
        rule_eval_counts=rule_eval_counts,
        event_review_pack=_cluster_event_markers(event_markers),
        usdt_reserves=usdt_reserves,
        btc_harvested=btc_harvested,
        harvest_events=harvest_events,
        macro_cycle_events=macro_cycle_events,
    )


def compare_baseline_enhanced(
    bars: list[MarketBar],
    symbol: str,
    limits: RiskLimits,
    config: TrendBreakoutConfig | None = None,
) -> BacktestComparison:
    base_config = config or build_default_strategy().config
    baseline = run_backtest(
        bars=bars,
        symbol=symbol,
        strategy=TrendBreakoutStrategy(
            TrendBreakoutConfig(
                **{
                    **base_config.__dict__,
                    "enable_rising_channel_breakdown_retest_short": False,
                    "enable_rising_channel_breakdown_continuation_short": False,
                }
            )
        ),
        broker=PaperBroker(initial_cash=100_000.0, fee_rate=0.001, slippage_rate=0.0005),
        limits=limits,
    )
    enhanced = run_backtest(
        bars=bars,
        symbol=symbol,
        strategy=TrendBreakoutStrategy(base_config),
        broker=PaperBroker(initial_cash=100_000.0, fee_rate=0.001, slippage_rate=0.0005),
        limits=limits,
    )
    return BacktestComparison(baseline=baseline, enhanced=enhanced)


def build_default_strategy() -> TrendBreakoutStrategy:
    return TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            secondary_structure_lookback=48,
            pivot_window=2,
            min_pivot_highs=2,
            min_pivot_lows=2,
            impulse_threshold_pct=0.02,
            entry_buffer_pct=0.20,
            stop_buffer_pct=0.08,
            min_r_squared=0.0,
            min_stop_atr_multiplier=1.5,
            time_stop_bars=84,
            enable_ascending_channel_resistance_rejection=False,
            enable_descending_channel_breakout_long=False,
            enable_ascending_channel_breakdown_short=False,
        )
    )


def _channel_quality_gate(
    signal: StrategySignal,
    current_bar: MarketBar,
    futures_provider: Any,
    history: list[MarketBar],
    min_score: int,
) -> StrategySignal:
    """Block channel signals when ★★★ indicator quality is too low.

    Scores the current bar's Coinglass indicators against the empirically
    derived conditions from the 6-channel analysis:
      SHORT → score_high_pivot (7 ★★★ HIGH conditions)
      LONG  → score_low_pivot  (9 ★★★ LOW conditions, includes RSI 3/7/14)
    If the score is below *min_score*, signal is downgraded to hold.
    """
    snap = futures_provider.get_snapshot("", current_bar.timestamp)
    if snap is None:
        return signal  # no data → pass through (don't block)

    # Compute RSI(3,7,14) from price history for ★★★ LOW conditions
    _rsi3 = _rsi7 = _rsi14 = 50.0
    if len(history) >= 15:
        _closes = [b.close for b in history[-60:]]
        from indicators.volume_profile import _rsi_from_closes
        r3 = _rsi_from_closes(_closes, 3)
        r7 = _rsi_from_closes(_closes, 7)
        r14 = _rsi_from_closes(_closes, 14)
        if r3 is not None:
            _rsi3 = r3
        if r7 is not None:
            _rsi7 = r7
        if r14 is not None:
            _rsi14 = r14

    # Build DailyIndicators from the FuturesSnapshot
    ind = DailyIndicators(
        oi=snap.oi_close or 0.0,
        funding_pct=snap.funding_rate or 0.0,
        ls_ratio=snap.top_ls_ratio or 0.0,
        long_liq_usd=snap.liq_long_usd or 0.0,
        short_liq_usd=snap.liq_short_usd or 0.0,
        cvd=snap.cvd or 0.0,
        taker_buy_usd=snap.taker_buy_usd or 0.0,
        taker_sell_usd=snap.taker_sell_usd or 0.0,
        rsi3=_rsi3,
        rsi7=_rsi7,
        rsi14=_rsi14,
    )

    # Previous day's indicators (for OI/CVD delta)
    prev_ind = None
    if len(history) >= 7:
        prev_snap = futures_provider.get_snapshot("", history[-7].timestamp)
        if prev_snap is not None:
            prev_ind = DailyIndicators(
                oi=prev_snap.oi_close or 0.0,
                cvd=prev_snap.cvd or 0.0,
            )

    detector = ChannelDetector()

    if signal.action == "short":
        score = detector.score_high_pivot(ind, prev_ind)
        if score < min_score:
            return StrategySignal(
                action="hold", confidence=0.0,
                reason=f"channel_quality_high_{score}_lt_{min_score}",
            )
    elif signal.action == "buy":
        score = detector.score_low_pivot(ind, prev_ind)
        if score < min_score:
            return StrategySignal(
                action="hold", confidence=0.0,
                reason=f"channel_quality_low_{score}_lt_{min_score}",
            )

    return signal


def build_baseline_strategy() -> TrendBreakoutStrategy:
    return TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            pivot_window=2,
            min_pivot_highs=2,
            min_pivot_lows=2,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.18,
            stop_buffer_pct=0.08,
            enable_rising_channel_breakdown_retest_short=False,
            enable_rising_channel_breakdown_continuation_short=False,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a research backtest with stub exchange data.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--limit", type=int, default=180)
    parser.add_argument("--csv", help="Optional CSV path to load bars from.")
    parser.add_argument("--backfill-csv", help="Optional CSV path to create using the stub adapter.")
    parser.add_argument("--variant", choices=["baseline", "enhanced"], default="enhanced")
    parser.add_argument("--compare", action="store_true", help="Run baseline/enhanced comparison on the same dataset.")
    args = parser.parse_args()

    if args.backfill_csv:
        path = backfill_to_csv(
            adapter=BinanceStubAdapter(),
            symbol=args.symbol,
            timeframe=args.timeframe,
            limit=args.limit,
            output_path=args.backfill_csv,
        )
        print(f"Backfilled stub bars to {path}")
        return

    bars = load_bars_from_csv(args.csv) if args.csv else BinanceStubAdapter().fetch_ohlcv(
        args.symbol,
        args.timeframe,
        args.limit,
    )

    if args.compare:
        comparison = compare_baseline_enhanced(bars=bars, symbol=args.symbol, limits=RiskLimits())
        print("Backtest Comparison")
        _print_result("baseline", comparison.baseline)
        _print_result("enhanced", comparison.enhanced)
        return

    result = run_backtest(
        bars=bars,
        symbol=args.symbol,
        strategy=build_default_strategy() if args.variant == "enhanced" else build_baseline_strategy(),
        broker=PaperBroker(initial_cash=100_000.0, fee_rate=0.001, slippage_rate=0.0005),
        limits=RiskLimits(),
    )
    print("Backtest Result")
    _print_result(args.variant, result)


def _evaluate_strategy(
    strategy: Strategy,
    symbol: str,
    history: list[MarketBar],
    position,
    futures_provider: Any | None = None,
    mtf_bars: Any | None = None,
) -> tuple[StrategySignal, StrategyEvaluation | None]:
    evaluate_fn = getattr(strategy, "evaluate", None)
    if callable(evaluate_fn):
        evaluation = evaluate_fn(symbol=symbol, bars=history, position=position, futures_provider=futures_provider, mtf_bars=mtf_bars)
        return evaluation.signal, evaluation
    return strategy.generate_signal(symbol=symbol, bars=history, position=position, mtf_bars=mtf_bars), None


def _print_result(label: str, result: BacktestResult) -> None:
    print(f"\nVariant        : {label}")
    print(f"Initial Cash   : {result.initial_cash:.2f}")
    print(f"Final Equity   : {result.final_equity:.2f}")
    print(f"Total Return % : {result.total_return_pct:.2f}")
    print(f"Max Drawdown % : {result.max_drawdown_pct:.2f}")
    print(f"Total Trades   : {result.total_trades}")
    if result.rule_stats:
        print("Rule Stats")
        for stat in result.rule_stats:
            print(
                f"{stat.signal_name}: triggers={stat.trigger_count} fills={stat.filled_entries} "
                f"win_rate={stat.win_rate_pct:.2f}% pnl={stat.pnl:.2f} contribution={stat.contribution_pct:.2f}%"
            )
    if result.rejection_stats:
        print("Rejection Funnel")
        for rule_name in sorted(result.rejection_stats):
            parts = ", ".join(f"{reason}={count}" for reason, count in sorted(result.rejection_stats[rule_name].items()))
            print(f"{rule_name}: {parts}")
    if result.event_review_pack:
        print("Event Review Pack")
        for event in result.event_review_pack:
            print(
                f"{event.event_label}: bars={event.bars} "
                f"{event.start_time.isoformat()} -> {event.end_time.isoformat()} "
                f"parent={event.parent_structure_type}/{event.parent_position_in_channel}/{event.parent_event_type}"
            )


def _count_open_positions(broker: PaperBroker, symbol: str) -> int:
    return 1 if broker.get_position(symbol).is_open else 0


def _max_drawdown_pct(equity_curve: list[float]) -> float:
    peak = equity_curve[0]
    drawdown = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak <= 0:
            continue
        drawdown = max(drawdown, (peak - value) / peak)
    return drawdown * 100


def _build_trade_record(
    entry: dict[str, Any],
    exit_fill: FillReport,
    exit_reason: str,
    contract_type: str = "linear",
) -> TradeRecord:
    if entry["side"] == "buy":
        if contract_type == "inverse":
            pnl = (exit_fill.quantity * (exit_fill.fill_price - entry["entry_price"]) / exit_fill.fill_price) - entry["entry_fee"] - exit_fill.fee
        else:
            pnl = ((exit_fill.fill_price - entry["entry_price"]) * exit_fill.quantity) - entry["entry_fee"] - exit_fill.fee
        return_pct = ((exit_fill.fill_price - entry["entry_price"]) / entry["entry_price"]) * 100
        side = "long"
    else:
        if contract_type == "inverse":
            pnl = (exit_fill.quantity * (entry["entry_price"] - exit_fill.fill_price) / exit_fill.fill_price) - entry["entry_fee"] - exit_fill.fee
        else:
            pnl = ((entry["entry_price"] - exit_fill.fill_price) * exit_fill.quantity) - entry["entry_fee"] - exit_fill.fee
        return_pct = ((entry["entry_price"] - exit_fill.fill_price) / entry["entry_price"]) * 100
        side = "short"
    return TradeRecord(
        symbol=entry["symbol"],
        side=side,
        entry_rule=entry["entry_rule"],
        exit_reason=exit_reason,
        entry_time=entry["entry_time"],
        exit_time=exit_fill.timestamp,
        entry_price=entry["entry_price"],
        exit_price=exit_fill.fill_price,
        quantity=exit_fill.quantity,
        entry_fee=entry["entry_fee"],
        exit_fee=exit_fill.fee,
        pnl=pnl,
        return_pct=return_pct,
        metadata={
            "stop_price": entry.get("stop_price"),
            "target_price": entry.get("target_price"),
            "trailing_stop_atr": entry.get("trailing_stop_atr", 0),
            "confidence": entry.get("confidence"),
        },
    )


def _build_rule_stats(signal_counts: dict[str, int], trades: list[TradeRecord]) -> list[RuleStat]:
    names = sorted(set(signal_counts) | {trade.entry_rule for trade in trades if trade.entry_rule})
    if not names:
        return []

    total_realized_pnl = sum(trade.pnl for trade in trades)
    stats: list[RuleStat] = []
    for name in names:
        rule_trades = [trade for trade in trades if trade.entry_rule == name]
        pnl = sum(trade.pnl for trade in rule_trades)
        wins = sum(1 for trade in rule_trades if trade.pnl > 0)
        contribution = (pnl / total_realized_pnl * 100) if total_realized_pnl != 0 else 0.0
        stats.append(
            RuleStat(
                signal_name=name,
                trigger_count=signal_counts.get(name, 0),
                filled_entries=len(rule_trades),
                win_rate_pct=(wins / len(rule_trades) * 100) if rule_trades else 0.0,
                pnl=pnl,
                contribution_pct=contribution,
            )
        )
    return stats


def _compute_trailing_atr(bars: list[MarketBar], lookback: int) -> float:
    window = bars[-lookback:] if len(bars) >= lookback else bars
    if len(window) < 2:
        return 0.0
    from statistics import mean
    true_ranges: list[float] = []
    prev_close = window[0].close
    for bar in window[1:]:
        true_ranges.append(max(bar.high - bar.low, abs(bar.high - prev_close), abs(bar.low - prev_close)))
        prev_close = bar.close
    return mean(true_ranges) if true_ranges else 0.0


def _build_event_marker(timestamp: datetime, evaluation_item) -> dict[str, Any] | None:
    if evaluation_item.first_failed_condition not in {"parent_context_conflict", "shock_override_active"}:
        return None
    context = evaluation_item.context or {}
    parent_type = str(context.get("parent_structure_type", "unknown"))
    parent_position = str(context.get("parent_position_in_channel", "unknown"))
    parent_event = str(context.get("parent_event_type", "none"))
    return {
        "timestamp": timestamp,
        "rule_name": evaluation_item.rule_name,
        "first_failed_condition": evaluation_item.first_failed_condition,
        "parent_structure_type": parent_type,
        "parent_position_in_channel": parent_position,
        "parent_event_type": parent_event,
        "event_label": _reclassify_event_label(
            first_failed_condition=evaluation_item.first_failed_condition,
            parent_structure_type=parent_type,
            parent_position_in_channel=parent_position,
            parent_event_type=parent_event,
        ),
    }


def _reclassify_event_label(
    first_failed_condition: str,
    parent_structure_type: str,
    parent_position_in_channel: str,
    parent_event_type: str,
) -> str:
    if first_failed_condition == "shock_override_active" or parent_event_type in {
        "shock_break_reclaim",
        "post_shock_stabilization",
    }:
        if parent_event_type == "post_shock_stabilization":
            return "post_shock_stabilization_context"
        return "shock_break_reclaim_context"
    if parent_structure_type == "descending_channel" and parent_position_in_channel in {
        "near_lower_boundary",
        "below_lower_boundary",
    }:
        return "major_descending_channel_lower_boundary_support_context"
    if parent_structure_type == "ascending_channel" and parent_position_in_channel in {
        "near_lower_boundary",
        "below_lower_boundary",
    }:
        return "major_ascending_channel_lower_boundary_support_reaction_context"
    return "parent_context_conflict"


def _cluster_event_markers(markers: list[dict[str, Any]]) -> list[EventReviewRecord]:
    if not markers:
        return []
    records: list[EventReviewRecord] = []
    markers = sorted(markers, key=lambda item: item["timestamp"])
    cluster: list[dict[str, Any]] = [markers[0]]
    for item in markers[1:]:
        previous = cluster[-1]
        if (
            item["event_label"] == previous["event_label"]
            and item["parent_structure_type"] == previous["parent_structure_type"]
            and item["parent_event_type"] == previous["parent_event_type"]
        ):
            cluster.append(item)
            continue
        records.append(_cluster_to_record(cluster))
        cluster = [item]
    records.append(_cluster_to_record(cluster))
    return records


def _cluster_to_record(cluster: list[dict[str, Any]]) -> EventReviewRecord:
    return EventReviewRecord(
        event_label=cluster[0]["event_label"],
        first_failed_condition=cluster[0]["first_failed_condition"],
        start_time=cluster[0]["timestamp"],
        end_time=cluster[-1]["timestamp"],
        bars=len(cluster),
        parent_structure_type=cluster[0]["parent_structure_type"],
        parent_position_in_channel=cluster[0]["parent_position_in_channel"],
        parent_event_type=cluster[0]["parent_event_type"],
        rule_names=sorted({item["rule_name"] for item in cluster}),
    )


if __name__ == "__main__":
    main()
