from __future__ import annotations

import argparse
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
from strategies.trend_breakout import (
    RULE_NAMES,
    StrategyEvaluation,
    TrendBreakoutConfig,
    TrendBreakoutStrategy,
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


@dataclass(frozen=True)
class RuleStat:
    signal_name: str
    trigger_count: int
    filled_entries: int
    win_rate_pct: float
    pnl: float
    contribution_pct: float


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
) -> BacktestResult:
    if len(bars) < 2:
        raise ValueError("Backtest requires at least two bars.")

    initial_cash = broker.get_cash()
    equity_curve: list[float] = [initial_cash]
    fills: list[FillReport] = []
    trades: list[TradeRecord] = []
    signal_counts: dict[str, int] = {}
    open_entries: dict[str, dict[str, Any]] = {}
    rejection_stats: dict[str, dict[str, int]] = {name: {} for name in RULE_NAMES}
    rule_eval_counts: dict[str, int] = {name: 0 for name in RULE_NAMES}
    time_stop_bars = getattr(getattr(strategy, "config", None), "time_stop_bars", None)

    for index in range(1, len(bars)):
        history = bars[: index + 1]
        current_bar = history[-1]
        position = broker.get_position(symbol)
        order: OrderRequest | None = None

        if position.is_open and symbol in open_entries and time_stop_bars is not None:
            bars_held = index - open_entries[symbol]["entry_index"]
            if bars_held >= time_stop_bars:
                order = OrderRequest(
                    symbol=symbol,
                    side="sell" if position.side == "long" else "cover",
                    quantity=position.quantity,
                    timestamp=current_bar.timestamp,
                    metadata={"reason": "time_stop"},
                )

        if order is None:
            signal, evaluation = _evaluate_strategy(strategy=strategy, symbol=symbol, history=history, position=position)
            if evaluation is not None:
                for item in evaluation.rule_evaluations:
                    rule_eval_counts[item.rule_name] = rule_eval_counts.get(item.rule_name, 0) + 1
                    if item.triggered:
                        signal_counts[item.rule_name] = signal_counts.get(item.rule_name, 0) + 1
                    elif item.first_failed_condition:
                        bucket = rejection_stats.setdefault(item.rule_name, {})
                        reason = item.first_failed_condition
                        bucket[reason] = bucket.get(reason, 0) + 1
            elif signal.action in {"buy", "short"} and signal.reason:
                signal_counts[signal.reason] = signal_counts.get(signal.reason, 0) + 1

            if signal.action in {"buy", "short"}:
                quantity = calculate_order_quantity(
                    cash=broker.get_cash(),
                    market_price=current_bar.close,
                    limits=limits,
                )
                order = OrderRequest(
                    symbol=symbol,
                    side=signal.action,
                    quantity=quantity,
                    timestamp=current_bar.timestamp,
                    metadata={
                        "reason": signal.reason,
                        "stop_price": signal.stop_price,
                        "target_price": signal.target_price,
                        "second_target_price": signal.metadata.get("second_target_price"),
                    },
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
        ):
            fill = broker.submit_order(order=order, market_price=current_bar.close)
            if fill is not None:
                fills.append(fill)
                if fill.side in {"buy", "short"}:
                    open_entries[fill.symbol] = {
                        "symbol": fill.symbol,
                        "entry_rule": order.metadata.get("reason", ""),
                        "side": fill.side,
                        "entry_time": fill.timestamp,
                        "entry_price": fill.fill_price,
                        "entry_fee": fill.fee,
                        "entry_index": index,
                    }
                elif fill.side in {"sell", "cover"} and fill.symbol in open_entries:
                    entry = open_entries.pop(fill.symbol)
                    trades.append(
                        _build_trade_record(
                            entry=entry,
                            exit_fill=fill,
                            exit_reason=order.metadata.get("reason", ""),
                        )
                    )
                LOGGER.info(
                    "filled %s %s qty=%.6f price=%.2f",
                    fill.side,
                    fill.symbol,
                    fill.quantity,
                    fill.fill_price,
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
            pivot_window=2,
            min_pivot_highs=2,
            min_pivot_lows=2,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.18,
            stop_buffer_pct=0.08,
        )
    )


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
) -> tuple[StrategySignal, StrategyEvaluation | None]:
    evaluate_fn = getattr(strategy, "evaluate", None)
    if callable(evaluate_fn):
        evaluation = evaluate_fn(symbol=symbol, bars=history, position=position)
        return evaluation.signal, evaluation
    return strategy.generate_signal(symbol=symbol, bars=history, position=position), None


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
) -> TradeRecord:
    if entry["side"] == "buy":
        pnl = ((exit_fill.fill_price - entry["entry_price"]) * exit_fill.quantity) - entry["entry_fee"] - exit_fill.fee
        return_pct = ((exit_fill.fill_price - entry["entry_price"]) / entry["entry_price"]) * 100
        side = "long"
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


if __name__ == "__main__":
    main()
