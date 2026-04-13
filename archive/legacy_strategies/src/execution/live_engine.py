"""Live paper trading engine for BTC inverse perpetual.

Polls Binance Futures for 4h candle closes, evaluates the channel strategy,
and manages paper positions with trailing stops. State persisted to JSON.

Run via: PYTHONPATH=src python -m execution.live_engine
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from adapters.base import MarketBar, OrderRequest, Position
from adapters.binance_futures import BinanceFuturesAdapter
from data.mtf_bars import MultiTimeframeBars
from research.daily_flag import detect_daily_flag
from risk.limits import RiskLimits, calculate_order_quantity, allow_order
from strategies.base import StrategySignal
from strategies.trend_breakout import TrendBreakoutConfig, TrendBreakoutStrategy


LOGGER = logging.getLogger("live_engine")


# ── Config ──

@dataclass
class LiveConfig:
    symbol: str = "BTCUSDT"
    timeframe: str = "4h"
    leverage: int = 3
    initial_btc: float = 1.0
    risk_per_trade_pct: float = 0.05
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005
    poll_interval_sec: int = 30      # check for new candle every N seconds
    history_bars: int = 500          # 4h bars to load for strategy context
    daily_bars: int = 120            # 1d bars for daily flag
    contract_type: str = "inverse"


# ── Persistent State ──

@dataclass
class LiveState:
    btc_balance: float = 1.0
    # Position
    position_side: str = "flat"      # "long", "short", "flat"
    position_qty: float = 0.0
    entry_price: float = 0.0
    entry_rule: str = ""
    entry_time: str = ""
    stop_price: float = 0.0
    target_price: float = 0.0
    trailing_stop_atr: float = 0.0
    best_price: float = 0.0
    entry_bar_index: int = 0
    # Trade log
    trades: list[dict] = field(default_factory=list)
    # Last processed candle timestamp (ISO string)
    last_candle_ts: str = ""
    # Tick counter for daily flag interval (check every 6 ticks = 1 day)
    tick_count: int = 0
    # Macro cycle
    usdt_reserves: float = 0.0
    macro_daily_sold: bool = False

    @property
    def is_position_open(self) -> bool:
        return self.position_side != "flat" and self.position_qty > 0

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: Path) -> LiveState:
        if not path.exists():
            return cls()
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (json.JSONDecodeError, TypeError):
            return cls()


# ── Engine ──

class LiveEngine:
    """Paper trading engine: evaluate strategy on live 4h bars."""

    def __init__(
        self,
        state_path: Path | None = None,
        config: LiveConfig | None = None,
        strategy_config: TrendBreakoutConfig | None = None,
    ) -> None:
        self.cfg = config or LiveConfig()
        self.state_path = state_path or Path("state/paper_state.json")
        self.state = LiveState.load(self.state_path)
        if self.state.btc_balance == 1.0 and self.cfg.initial_btc != 1.0:
            self.state.btc_balance = self.cfg.initial_btc
        self.adapter = BinanceFuturesAdapter()
        self.strategy = TrendBreakoutStrategy(strategy_config or _default_strategy_config())
        self.limits = RiskLimits(
            max_position_pct=0.90,
            risk_per_trade_pct=self.cfg.risk_per_trade_pct,
            leverage=self.cfg.leverage,
        )

    def run_loop(self) -> None:
        """Main polling loop — runs forever, evaluates on each new 4h candle."""
        LOGGER.info("Paper trading started | %s | %.4f BTC | %dx leverage",
                     self.cfg.symbol, self.state.btc_balance, self.cfg.leverage)
        while True:
            try:
                # Fetch multi-timeframe bars: 4h (primary), 1h + 15m (MTF confirmation)
                multi = self.adapter.fetch_multi(
                    self.cfg.symbol,
                    {"4h": self.cfg.history_bars, "1h": 500, "15m": 500},
                )
                bars_4h = multi.get("4h", [])
                if not bars_4h:
                    LOGGER.warning("No bars received, retrying...")
                    time.sleep(self.cfg.poll_interval_sec)
                    continue

                latest = bars_4h[-1]
                latest_ts = latest.timestamp.isoformat()

                # Only process when we see a new candle
                if latest_ts == self.state.last_candle_ts:
                    time.sleep(self.cfg.poll_interval_sec)
                    continue

                LOGGER.info("New candle: %s | $%.0f", latest_ts, latest.close)
                self.state.last_candle_ts = latest_ts

                # Build MTF container for strategy evaluation
                mtf = MultiTimeframeBars(multi)

                action = self.tick(bars_4h, mtf_bars=mtf)
                if action:
                    LOGGER.info("ACTION: %s", action)

                self.state.save(self.state_path)

            except KeyboardInterrupt:
                LOGGER.info("Shutting down...")
                self.state.save(self.state_path)
                break
            except Exception:
                LOGGER.exception("Error in main loop, retrying...")
                time.sleep(60)

    def tick(
        self,
        bars_4h: list[MarketBar],
        *,
        mtf_bars: MultiTimeframeBars | None = None,
        futures_provider: Any | None = None,
    ) -> dict | None:
        """Process one tick (new 4h candle). Returns action dict or None.

        This is the core method — called by run_loop or directly for testing.

        Args:
            bars_4h: Full 4h bar history (500+ bars).
            mtf_bars: Multi-timeframe bars (1h, 15m) for entry confirmation.
            futures_provider: Coinglass data provider for indicator filters.
        """
        if len(bars_4h) < 100:
            return None

        current = bars_4h[-1]
        action: dict | None = None
        self.state.tick_count += 1

        # ── 1. Check trailing stop / exits on open position ──
        if self.state.is_position_open:
            self._update_best_price(current)
            exit_action = self._check_exits(bars_4h, current)
            if exit_action:
                self._close_position(current, exit_action["reason"])
                action = exit_action

        # ── 2. Macro cycle: check top sell every tick ──
        if not self.state.is_position_open:
            macro_result = self.check_macro_sell(current, bars_4h)
            if macro_result:
                action = macro_result

        # ── 3. Evaluate strategy for new entry ──
        if not self.state.is_position_open:
            position = Position(symbol=self.cfg.symbol)
            evaluation = self.strategy.evaluate(
                symbol=self.cfg.symbol,
                bars=bars_4h,
                position=position,
                futures_provider=futures_provider,
                mtf_bars=mtf_bars,
            )
            signal = evaluation.signal

            # ── 3. Daily flag overlay: check every 6th tick (~1 day) ──
            # When 4h strategy says "hold", daily flag can override.
            # Daily flag detects bear/bull flags on ~60-day daily channel.
            if (
                signal.action == "hold"
                and self.state.tick_count % 6 == 0
                and len(bars_4h) > 360
            ):
                flag_sig = detect_daily_flag(
                    bars_4h,
                    lookback_days=60,
                    pivot_window=3,
                    min_pivots=3,
                    min_r_squared=0.15,
                )
                if flag_sig.action in {"short", "long"}:
                    _trail_atr = getattr(
                        self.strategy.config, "impulse_trailing_stop_atr", 6.0
                    ) or 6.0
                    # Map "long" → "buy" (strategy convention)
                    _action = "buy" if flag_sig.action == "long" else flag_sig.action
                    signal = StrategySignal(
                        action=_action,
                        confidence=flag_sig.confidence,
                        reason=f"daily_{flag_sig.flag_type}",
                        stop_price=(
                            flag_sig.resistance
                            if flag_sig.action == "short"
                            else flag_sig.support
                        ),
                        target_price=None,
                        metadata={
                            "trailing_stop_atr": _trail_atr,
                            "trade_type": "impulse",
                        },
                    )

            if signal.action in {"buy", "short"}:
                action = self._open_position(current, signal)

        return action

    def _open_position(self, bar: MarketBar, signal: StrategySignal) -> dict:
        """Paper-open a position."""
        price = bar.close
        # Position sizing: inverse contract → BTC cash * price = USD equivalent
        sizing_cash_usd = self.state.btc_balance * price
        stop_dist = 0.0
        if signal.stop_price and signal.stop_price > 0:
            stop_dist = abs(price - signal.stop_price) / price

        quantity = calculate_order_quantity(
            cash=sizing_cash_usd,
            market_price=price,
            limits=self.limits,
            stop_distance_pct=stop_dist,
        )
        if quantity <= 0:
            return {"action": "skip", "reason": "zero_qty"}

        # Slippage + fees
        fill_price = price * (1 + self.cfg.slippage_rate if signal.action == "buy" else 1 - self.cfg.slippage_rate)
        fee_btc = (quantity * self.cfg.fee_rate)  # inverse: fee in BTC terms
        # For inverse: margin = qty / leverage (qty is in BTC)
        margin_btc = quantity / self.cfg.leverage

        self.state.position_side = "long" if signal.action == "buy" else "short"
        self.state.position_qty = quantity
        self.state.entry_price = fill_price
        self.state.entry_rule = signal.reason or "unknown"
        self.state.entry_time = bar.timestamp.isoformat()
        self.state.stop_price = signal.stop_price or 0.0
        self.state.target_price = signal.target_price or 0.0
        self.state.trailing_stop_atr = (signal.metadata or {}).get("trailing_stop_atr", 3.5)
        self.state.best_price = bar.high if signal.action == "buy" else bar.low
        self.state.btc_balance -= fee_btc

        LOGGER.info(
            "OPEN %s | %s @ $%.0f | qty=%.6f | stop=$%.0f | trail=%.1fx ATR | fee=%.6f BTC",
            self.state.position_side.upper(), signal.reason, fill_price,
            quantity, self.state.stop_price, self.state.trailing_stop_atr, fee_btc,
        )
        return {
            "action": signal.action,
            "side": self.state.position_side,
            "rule": signal.reason,
            "price": fill_price,
            "quantity": quantity,
            "stop": self.state.stop_price,
        }

    def _close_position(self, bar: MarketBar, reason: str) -> dict:
        """Paper-close position."""
        price = bar.close
        if self.state.position_side == "long":
            fill_price = price * (1 - self.cfg.slippage_rate)
        else:
            fill_price = price * (1 + self.cfg.slippage_rate)

        # PnL: inverse contract
        pnl_pct = (fill_price - self.state.entry_price) / self.state.entry_price
        if self.state.position_side == "short":
            pnl_pct = -pnl_pct
        pnl_btc = self.state.position_qty * pnl_pct * self.cfg.leverage
        fee_btc = self.state.position_qty * self.cfg.fee_rate
        pnl_btc -= fee_btc
        self.state.btc_balance += pnl_btc

        trade = {
            "side": self.state.position_side,
            "entry_rule": self.state.entry_rule,
            "entry_time": self.state.entry_time,
            "entry_price": self.state.entry_price,
            "exit_time": bar.timestamp.isoformat(),
            "exit_price": fill_price,
            "exit_reason": reason,
            "pnl_btc": round(pnl_btc, 8),
            "pnl_pct": round(pnl_pct * 100 * self.cfg.leverage, 2),
            "quantity": self.state.position_qty,
            "btc_after": round(self.state.btc_balance, 8),
        }
        self.state.trades.append(trade)

        LOGGER.info(
            "CLOSE %s | %s | entry=$%.0f exit=$%.0f | PnL=%+.6f BTC (%+.1f%%) | balance=%.4f BTC",
            self.state.position_side.upper(), reason,
            self.state.entry_price, fill_price,
            pnl_btc, pnl_pct * 100 * self.cfg.leverage,
            self.state.btc_balance,
        )

        # Reset position
        self.state.position_side = "flat"
        self.state.position_qty = 0.0
        self.state.entry_price = 0.0
        self.state.entry_rule = ""
        self.state.stop_price = 0.0
        self.state.target_price = 0.0
        self.state.trailing_stop_atr = 0.0
        self.state.best_price = 0.0

        return trade

    def _check_exits(self, bars: list[MarketBar], current: MarketBar) -> dict | None:
        """Check trailing stop, structural stop, time stop."""
        # Trailing stop
        if self.state.trailing_stop_atr > 0:
            atr = self._compute_atr(bars, 14)
            if atr > 0:
                if self.state.position_side == "long":
                    trail_stop = self.state.best_price - self.state.trailing_stop_atr * atr
                    if current.close <= trail_stop:
                        return {"reason": "trailing_stop", "stop_level": trail_stop}
                elif self.state.position_side == "short":
                    trail_stop = self.state.best_price + self.state.trailing_stop_atr * atr
                    if current.close >= trail_stop:
                        return {"reason": "trailing_stop", "stop_level": trail_stop}

        # Structural stop
        if self.state.stop_price > 0:
            if self.state.position_side == "long" and current.close <= self.state.stop_price:
                return {"reason": "structural_stop"}
            elif self.state.position_side == "short" and current.close >= self.state.stop_price:
                return {"reason": "structural_stop"}

        # Time stop: 168 bars (4 weeks)
        if self.state.entry_time:
            entry_dt = datetime.fromisoformat(self.state.entry_time)
            bars_held = 0
            for i in range(len(bars) - 1, -1, -1):
                if bars[i].timestamp <= entry_dt:
                    bars_held = len(bars) - 1 - i
                    break
            if bars_held >= 168:
                return {"reason": "time_stop"}

        return None

    def _update_best_price(self, bar: MarketBar) -> None:
        """Update the best (most favorable) price for trailing stop."""
        if self.state.position_side == "long":
            self.state.best_price = max(self.state.best_price, bar.high)
        elif self.state.position_side == "short":
            self.state.best_price = min(self.state.best_price, bar.low)

    @staticmethod
    def _compute_atr(bars: list[MarketBar], period: int = 14) -> float:
        """Compute ATR from the last `period+1` bars."""
        if len(bars) < period + 1:
            return 0.0
        trs = []
        recent = bars[-(period + 1):]
        for i in range(1, len(recent)):
            b, pb = recent[i], recent[i - 1]
            tr = max(b.high - b.low, abs(b.high - pb.close), abs(b.low - pb.close))
            trs.append(tr)
        return sum(trs) / len(trs) if trs else 0.0

    # ── Macro cycle: top sell ──

    MACRO_DAILY_RSI_TRIGGER = 75.0
    MACRO_WEEKLY_RSI_CONFIRM = 70.0
    MACRO_MONTHLY_RSI_GUARD = 65.0
    MACRO_SELL_PCT = 0.45
    MACRO_MIN_BTC_RESERVE = 1.0

    def check_macro_sell(self, current_bar: MarketBar, bars_4h: list[MarketBar] | None = None) -> dict | None:
        """Check macro top-sell conditions and execute if met."""
        if self.state.macro_daily_sold:
            return None
        if self.state.is_position_open:
            return None

        d_rsi, w_rsi, m_rsi = self._get_macro_rsi(current_bar, bars_4h)
        if d_rsi is None or w_rsi is None or m_rsi is None:
            return None
        if d_rsi < self.MACRO_DAILY_RSI_TRIGGER:
            return None
        if w_rsi < self.MACRO_WEEKLY_RSI_CONFIRM:
            return None
        if m_rsi < self.MACRO_MONTHLY_RSI_GUARD:
            return None

        free_btc = self.state.btc_balance
        sellable = max(0.0, free_btc - self.MACRO_MIN_BTC_RESERVE)
        sell_btc = min(free_btc * self.MACRO_SELL_PCT, sellable)
        if sell_btc < 0.001:
            return None

        sell_usdt = sell_btc * current_bar.close
        self.state.btc_balance -= sell_btc
        self.state.usdt_reserves += sell_usdt
        self.state.macro_daily_sold = True

        LOGGER.info(
            "MACRO SELL | %.4f BTC @ $%.0f → $%.0f USDT | balance=%.4f BTC | USDT=$%.0f",
            sell_btc, current_bar.close, sell_usdt,
            self.state.btc_balance, self.state.usdt_reserves,
        )
        return {
            "action": "macro_sell",
            "btc_sold": sell_btc,
            "price": current_bar.close,
            "usdt_gained": sell_usdt,
            "btc_after": self.state.btc_balance,
            "usdt_after": self.state.usdt_reserves,
        }

    def _get_macro_rsi(self, current_bar: MarketBar, bars_4h: list[MarketBar] | None = None) -> tuple[float | None, float | None, float | None]:
        """Compute daily, weekly, monthly RSI from 4h bars. Override in tests."""
        try:
            from research.macro_cycle import aggregate_to_daily, aggregate_to_weekly
            from strategies.trend_breakout import _compute_rsi
            if bars_4h is None or len(bars_4h) < 200:
                return None, None, None
            d_bars = aggregate_to_daily(bars_4h)
            w_bars = aggregate_to_weekly(bars_4h)
            d_rsi = _compute_rsi(d_bars[-60:], 14) if len(d_bars) > 20 else None
            w_rsi = _compute_rsi(w_bars[-30:], 14) if len(w_bars) > 20 else None
            # Monthly: aggregate weekly to ~4-week bars
            m_bars = []
            for i in range(0, len(w_bars) - 3, 4):
                chunk = w_bars[i:i + 4]
                m_bars.append(MarketBar(
                    timestamp=chunk[-1].timestamp,
                    open=chunk[0].open, high=max(b.high for b in chunk),
                    low=min(b.low for b in chunk), close=chunk[-1].close,
                    volume=sum(b.volume for b in chunk),
                ))
            m_rsi = _compute_rsi(m_bars[-20:], 14) if len(m_bars) > 15 else None
            return d_rsi, w_rsi, m_rsi
        except Exception:
            LOGGER.exception("Failed to compute macro RSI")
            return None, None, None

    def status(self) -> dict:
        """Return current engine status for display."""
        return {
            "btc_balance": self.state.btc_balance,
            "usdt_reserves": self.state.usdt_reserves,
            "position": self.state.position_side,
            "position_qty": self.state.position_qty,
            "entry_price": self.state.entry_price,
            "entry_rule": self.state.entry_rule,
            "trailing_stop_atr": self.state.trailing_stop_atr,
            "best_price": self.state.best_price,
            "total_trades": len(self.state.trades),
            "last_candle": self.state.last_candle_ts,
            "macro_sold": self.state.macro_daily_sold,
        }


def _default_strategy_config() -> TrendBreakoutConfig:
    """Same config as inverse_backtest.py best config (54 trades, +264.7% BTC)."""
    return TrendBreakoutConfig(
        impulse_lookback=12,
        structure_lookback=24,
        secondary_structure_lookback=48,
        pivot_window=2,
        min_pivot_highs=2,
        min_pivot_lows=2,
        impulse_threshold_pct=0.02,
        entry_buffer_pct=0.30,
        stop_buffer_pct=0.08,
        min_r_squared=0.0,
        min_stop_atr_multiplier=1.5,
        time_stop_bars=168,
        enable_ascending_channel_resistance_rejection=True,
        enable_descending_channel_breakout_long=True,
        enable_ascending_channel_breakdown_short=True,
        use_trailing_exit=True,
        trailing_stop_atr=3.5,
        impulse_trailing_stop_atr=7.0,
        impulse_harvest_pct=0.0,
        impulse_harvest_min_pnl=0.05,
        rsi_filter=True,
        rsi_period=3,
        rsi_oversold=20.0,
        adx_filter=True,
        adx_threshold=25.0,
        adx_mode="smart",
        oi_divergence_lookback=48,
        oi_divergence_threshold=-0.10,
        top_ls_contrarian=True,
        top_ls_threshold=1.5,
        liq_cascade_filter=True,
        liq_cascade_threshold=5e7,
        taker_imbalance_filter=True,
        taker_imbalance_threshold=1.3,
        cvd_divergence_filter=True,
        cvd_divergence_lookback=48,
        weekly_macd_short_gate=False,
        accel_trail_multiplier=3.0,
        bear_flag_max_weekly_rsi=0.0,
        loss_cooldown_count=0,
        loss_cooldown_bars=24,
        bear_reversal_enabled=False,
        mtf_entry_confirmation=True,
        mtf_1h_sizing_mode="scale",
        mtf_1h_lookback=4,
        mtf_1h_min_wick_ratio=0.3,
        mtf_1h_no_confirm_confidence=0.8,
        mtf_stop_refinement=True,
        mtf_15m_lookback=16,
        mtf_stop_max_tighten_pct=0.30,
        scale_in_enabled=False,
    )
