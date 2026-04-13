#!/usr/bin/env python3
"""Paper Trading — BTC Inverse Perpetual.

Polls Binance Futures 4h candles and evaluates channel strategy.
All fills are simulated (paper). State saved to state/paper_state.json.

Usage:
    PYTHONPATH=src python run_paper.py              # start paper trading
    PYTHONPATH=src python run_paper.py --status      # show current state
    PYTHONPATH=src python run_paper.py --once        # run one tick and exit
    PYTHONPATH=src python run_paper.py --reset       # reset state to fresh
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from execution.live_engine import LiveConfig, LiveEngine


def _setup_logging() -> None:
    fmt = "%(asctime)s | %(name)-12s | %(levelname)-5s | %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt, stream=sys.stdout)
    # Quiet noisy loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="BTC Paper Trading")
    parser.add_argument("--status", action="store_true", help="Show current state and exit")
    parser.add_argument("--once", action="store_true", help="Run one tick and exit")
    parser.add_argument("--reset", action="store_true", help="Reset state to fresh")
    parser.add_argument("--btc", type=float, default=1.0, help="Initial BTC (default: 1.0)")
    parser.add_argument("--leverage", type=int, default=3, help="Leverage (default: 3)")
    args = parser.parse_args()

    _setup_logging()
    state_path = Path("state/paper_state.json")

    if args.reset:
        if state_path.exists():
            state_path.unlink()
            print("State reset.")
        else:
            print("No state file to reset.")
        return

    cfg = LiveConfig(initial_btc=args.btc, leverage=args.leverage)
    engine = LiveEngine(state_path=state_path, config=cfg)

    if args.status:
        s = engine.status()
        print(f"\n{'=' * 60}")
        print("PAPER TRADING STATUS")
        print(f"{'=' * 60}")
        print(f"BTC Balance:  {s['btc_balance']:.6f} BTC")
        print(f"Position:     {s['position']}")
        if s["position"] != "flat":
            print(f"  Entry:      ${s['entry_price']:,.0f}")
            print(f"  Rule:       {s['entry_rule']}")
            print(f"  Qty:        {s['position_qty']:.6f}")
            print(f"  Trail ATR:  {s['trailing_stop_atr']}x")
            print(f"  Best Price: ${s['best_price']:,.0f}")
        print(f"Total Trades: {s['total_trades']}")
        print(f"Last Candle:  {s['last_candle']}")

        # Show recent trades
        if engine.state.trades:
            print(f"\n--- Recent Trades ---")
            for t in engine.state.trades[-5:]:
                wl = "WIN" if t["pnl_btc"] > 0 else "LOSS"
                print(f"  {t['entry_time'][:10]} {t['side']:5s} {t['entry_rule']:40s} "
                      f"PnL={t['pnl_btc']:+.6f} BTC ({t['pnl_pct']:+.1f}%) [{wl}]")
        return

    if args.once:
        from data.mtf_bars import MultiTimeframeBars

        print("Fetching multi-timeframe bars...")
        multi = engine.adapter.fetch_multi(
            cfg.symbol, {"4h": cfg.history_bars, "1h": 500, "15m": 500},
        )
        bars = multi.get("4h", [])
        if bars:
            print(f"Got 4h={len(bars)} 1h={len(multi.get('1h', []))} "
                  f"15m={len(multi.get('15m', []))} bars")
            print(f"Latest: {bars[-1].timestamp} ${bars[-1].close:,.0f}")
            mtf = MultiTimeframeBars(multi)
            action = engine.tick(bars, mtf_bars=mtf)
            if action:
                print(f"Action: {action}")
            else:
                print("No action (hold)")
            engine.state.save(state_path)
            s = engine.status()
            print(f"Balance: {s['btc_balance']:.6f} BTC | Position: {s['position']}")
        else:
            print("Failed to fetch bars")
        return

    # Main loop
    print(f"\n{'=' * 60}")
    print("PAPER TRADING — BTC INVERSE PERPETUAL")
    print(f"{'=' * 60}")
    print(f"Capital:   {cfg.initial_btc} BTC")
    print(f"Leverage:  {cfg.leverage}x")
    print(f"Symbol:    {cfg.symbol}")
    print(f"Timeframe: {cfg.timeframe}")
    print(f"State:     {state_path}")
    print(f"Polling every {cfg.poll_interval_sec}s for new candles...")
    print(f"{'=' * 60}\n")

    engine.run_loop()


if __name__ == "__main__":
    main()
