#!/usr/bin/env python
"""Runner for Strategy D — BB Swing paper trading (USDT-M).

Usage:
    PYTHONPATH=src python run_paper_d.py --once      # single tick
    PYTHONPATH=src python run_paper_d.py --status     # show current state
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from execution.bb_live_engine import BBLiveConfig, BBLiveEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="Strategy D — BB Swing Paper Trading")
    parser.add_argument("--once", action="store_true", help="Run single tick and exit")
    parser.add_argument("--status", action="store_true", help="Print current status")
    parser.add_argument("--state-dir", default="state", help="State directory")
    args = parser.parse_args()

    state_path = Path(args.state_dir) / "paper_d_state.json"

    config = BBLiveConfig(
        symbol="BTCUSDT",
        leverage=5,
        initial_usdt=10000.0,
        bb_period=20,
        bb_k=2.5,
        stop_loss_pct=0.03,
        risk_per_trade=0.065,
        use_ma200=True,
        use_trailing_stop=True,
        trailing_activation_pct=0.03,
        trailing_atr_multiplier=1.5,
        max_hold_bars=180,
    )

    engine = BBLiveEngine(state_path=state_path, config=config)

    if args.status:
        engine.print_status()
        return

    if args.once:
        result = engine.tick()
        _print_tick_result(result)
        engine.print_status()
        return

    # Default: continuous loop (4h interval)
    logging.info("Starting continuous mode — checking every 4h candle")
    while True:
        try:
            result = engine.tick()
            _print_tick_result(result)
            import time
            time.sleep(30)
        except KeyboardInterrupt:
            logging.info("Stopped by user")
            break
        except Exception as e:
            logging.error("Error: %s", e)
            import time
            time.sleep(60)


def _print_tick_result(result: dict) -> None:
    """Pretty-print a tick result."""
    action = result.get("action", "none")
    diag = result.get("diagnostics", {})

    if diag:
        price = diag.get("price", 0)
        bb_u = diag.get("bb_upper", 0)
        bb_m = diag.get("bb_middle", 0)
        bb_l = diag.get("bb_lower", 0)
        pct_b = diag.get("pct_b", 0)
        ma200 = diag.get("ma200")
        pos = diag.get("position", "flat")
        bal = diag.get("balance", 0)

        print(f"\n--- Tick {diag.get('timestamp', '')} ---")
        print(f"  Price:   ${price:,.0f}  |  %B: {pct_b:.2f}")
        print(f"  BB:      ${bb_l:,.0f} / ${bb_m:,.0f} / ${bb_u:,.0f}  ({diag.get('bb_width_pct', 0):.1f}%)")
        if ma200:
            print(f"  MA200:   ${ma200:,.0f}  ({diag.get('price_vs_ma200', '')})")
        print(f"  Balance: ${bal:,.2f}  |  Position: {pos}")

    if action == "entry":
        sig = result.get("signal", "")
        print(f"  >>> ENTRY {sig.upper()} | {result.get('qty', 0):.4f} BTC @ ${result.get('price', 0):,.0f}")
    elif action == "exit":
        print(f"  >>> EXIT {result.get('reason', '')} | PnL ${result.get('pnl_usdt', 0):+,.0f} ({result.get('pnl_pct', 0):+.1f}%)")
    elif action == "hold":
        print(f"  ... holding | unrealized {result.get('unrealized_pnl_pct', 0):+.1f}% | bars: {result.get('bars_held', 0)}")
    elif action == "skip_duplicate":
        print("  (same candle, skipped)")
    elif action == "blocked_ma200":
        print(f"  ✋ {result.get('signal', '')} blocked: {result.get('reason', '')}")
    elif action == "no_signal":
        print("  — no signal")
    else:
        print(f"  [{action}]")


if __name__ == "__main__":
    main()
