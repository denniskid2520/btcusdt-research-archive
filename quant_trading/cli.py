from __future__ import annotations

import argparse

from quant_trading.binance import BinanceClient, BinanceAPIError
from quant_trading.bot import PaperTradingBot
from quant_trading.config import (
    BacktestConfig,
    BinanceConfig,
    ChannelStrategyConfig,
    MovingAverageConfig,
    PaperTradingConfig,
)
from quant_trading.data import load_ohlcv_csv
from quant_trading.engine import BacktestEngine
from quant_trading.strategies import ChannelStructureStrategy, MovingAverageCrossStrategy
from quant_trading.structure import detect_channel_structure, estimate_market_regime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a quantitative trading backtest.")
    parser.add_argument(
        "--mode",
        default="backtest",
        choices=["backtest", "fetch-binance", "paper-trade"],
        help="Execution mode.",
    )
    parser.add_argument("--data", help="Path to OHLCV CSV data for backtesting.")
    parser.add_argument("--symbol", default="BTCUSDT", help="Binance symbol.")
    parser.add_argument("--interval", default="1h", help="Binance kline interval.")
    parser.add_argument("--limit", type=int, default=200, help="Number of candles to fetch from Binance.")
    parser.add_argument("--use-live", action="store_true", help="Use live Binance instead of Spot Testnet.")
    parser.add_argument("--poll-seconds", type=int, default=60, help="Polling interval for paper trading.")
    parser.add_argument("--max-iterations", type=int, default=1, help="How many loops to run in paper mode. 0 means forever.")
    parser.add_argument(
        "--strategy",
        default="channel_structure",
        choices=["moving_average", "channel_structure"],
        help="Strategy to run.",
    )
    parser.add_argument("--short-window", type=int, default=5, help="Short moving average window.")
    parser.add_argument("--long-window", type=int, default=20, help="Long moving average window.")
    parser.add_argument("--lookback", type=int, default=30, help="Structure detection lookback window.")
    parser.add_argument("--pivot-window", type=int, default=2, help="Pivot detection window size.")
    parser.add_argument("--min-touches", type=int, default=2, help="Minimum channel touches per side.")
    parser.add_argument("--entry-buffer-pct", type=float, default=0.01, help="Entry zone buffer ratio.")
    parser.add_argument("--stop-buffer-pct", type=float, default=0.005, help="Stop loss buffer ratio.")
    parser.add_argument(
        "--allow-countertrend",
        action="store_true",
        help="Allow countertrend longs in ascending channels even if the regime is not bullish.",
    )
    parser.add_argument("--initial-cash", type=float, default=100000.0, help="Starting capital.")
    parser.add_argument("--fee-rate", type=float, default=0.001, help="Fee rate per trade.")
    parser.add_argument("--slippage-rate", type=float, default=0.0005, help="Slippage rate per trade.")
    parser.add_argument("--risk-per-trade", type=float, default=0.02, help="Risk fraction per trade.")
    parser.add_argument("--max-position-pct", type=float, default=0.95, help="Max capital allocation.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.mode == "backtest" and not args.data:
        parser.error("--data is required in backtest mode.")

    backtest_config = BacktestConfig(
        initial_cash=args.initial_cash,
        fee_rate=args.fee_rate,
        slippage_rate=args.slippage_rate,
        risk_per_trade=args.risk_per_trade,
        max_position_pct=args.max_position_pct,
    )
    binance_config = BinanceConfig(
        symbol=args.symbol,
        interval=args.interval,
        limit=args.limit,
        use_testnet=not args.use_live,
    )

    if args.strategy == "moving_average":
        strategy = MovingAverageCrossStrategy(
            MovingAverageConfig(
                short_window=args.short_window,
                long_window=args.long_window,
            )
        )
    elif args.strategy == "channel_structure":
        strategy_config = ChannelStrategyConfig(
            lookback=args.lookback,
            pivot_window=args.pivot_window,
            min_touches=args.min_touches,
            entry_buffer_pct=args.entry_buffer_pct,
            stop_buffer_pct=args.stop_buffer_pct,
            allow_countertrend=args.allow_countertrend,
        )
        strategy = ChannelStructureStrategy(
            lookback=strategy_config.lookback,
            pivot_window=strategy_config.pivot_window,
            min_touches=strategy_config.min_touches,
            entry_buffer_pct=strategy_config.entry_buffer_pct,
            stop_buffer_pct=strategy_config.stop_buffer_pct,
            allow_countertrend=strategy_config.allow_countertrend,
        )
    else:
        raise ValueError(f"Unsupported strategy: {args.strategy}")

    if args.mode == "fetch-binance":
        _run_fetch_binance(binance_config)
        return

    if args.mode == "paper-trade":
        _run_paper_trading(strategy, backtest_config, binance_config, args)
        return

    candles = load_ohlcv_csv(args.data)
    engine = BacktestEngine(backtest_config)
    channel = detect_channel_structure(
        candles,
        lookback=args.lookback,
        pivot_window=args.pivot_window,
        min_touches=args.min_touches,
    )
    regime = estimate_market_regime(candles, lookback=max(args.lookback, 40))
    result, trades = engine.run(candles, strategy)

    print("Backtest Result")
    print(f"Regime         : {regime}")
    if channel is not None:
        print(f"Structure      : {channel.kind} (confidence {channel.confidence:.2f})")
        print(f"Breakout Target: {channel.breakout_target:.2f}")
    else:
        print("Structure      : none detected")
    print(f"Initial Cash   : {result.initial_cash:.2f}")
    print(f"Final Equity   : {result.final_equity:.2f}")
    print(f"Total Return % : {result.total_return_pct:.2f}")
    print(f"Max Drawdown % : {result.max_drawdown_pct:.2f}")
    print(f"Win Rate %     : {result.win_rate_pct:.2f}")
    print(f"Sharpe Ratio   : {result.sharpe_ratio:.2f}")
    print(f"Total Trades   : {result.total_trades}")

    if trades:
        print("\nRecent Trades")
        for trade in trades[-5:]:
            print(
                f"{trade.side.upper()} {trade.entry_time.isoformat()} -> {trade.exit_time.isoformat()} | "
                f"Entry {trade.entry_price:.2f} Exit {trade.exit_price:.2f} | "
                f"PnL {trade.pnl:.2f} ({trade.return_pct:.2f}%)"
            )


def _run_fetch_binance(binance_config: BinanceConfig) -> None:
    client = BinanceClient(binance_config)
    try:
        candles = client.get_klines()
    except BinanceAPIError as error:
        raise SystemExit(str(error)) from error

    print(f"Fetched {len(candles)} candles from {'testnet' if binance_config.use_testnet else 'live'} Binance")
    print(f"Symbol         : {binance_config.symbol}")
    print(f"Interval       : {binance_config.interval}")
    print(f"First Candle   : {candles[0].timestamp.isoformat()} Close {candles[0].close:.2f}")
    print(f"Last Candle    : {candles[-1].timestamp.isoformat()} Close {candles[-1].close:.2f}")


def _run_paper_trading(
    strategy,
    backtest_config: BacktestConfig,
    binance_config: BinanceConfig,
    args: argparse.Namespace,
) -> None:
    bot = PaperTradingBot(
        strategy=strategy,
        backtest_config=backtest_config,
        binance_config=binance_config,
        paper_config=PaperTradingConfig(
            poll_seconds=args.poll_seconds,
            max_iterations=args.max_iterations,
        ),
    )
    try:
        snapshots = bot.run_loop()
    except BinanceAPIError as error:
        raise SystemExit(str(error)) from error

    for snapshot in snapshots:
        print("Paper Snapshot")
        print(f"Timestamp      : {snapshot.timestamp}")
        print(f"Price          : {snapshot.price:.2f}")
        print(f"Action         : {snapshot.action}")
        print(f"Reason         : {snapshot.reason}")
        print(f"Cash           : {snapshot.cash:.2f}")
        print(f"Equity         : {snapshot.equity:.2f}")
        print(f"Position       : {snapshot.position_side} {snapshot.position_qty:.6f}")
        if snapshot.stop_price is not None:
            print(f"Stop Price     : {snapshot.stop_price:.2f}")
        if snapshot.target_price is not None:
            print(f"Target Price   : {snapshot.target_price:.2f}")


if __name__ == "__main__":
    main()
