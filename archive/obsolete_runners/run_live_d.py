#!/usr/bin/env python
"""Runner for Strategy D — BB Swing LIVE trading (USDT-M).

Sends REAL orders to Binance Futures. Use with caution.

Usage:
    PYTHONPATH=src python run_live_d.py --once      # single tick
    PYTHONPATH=src python run_live_d.py --status     # show current state
    PYTHONPATH=src python run_live_d.py --check      # verify API + balance only
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
    parser = argparse.ArgumentParser(description="Strategy D — BB Swing LIVE Trading")
    parser.add_argument("--once", action="store_true", help="Run single tick and exit")
    parser.add_argument("--status", action="store_true", help="Print current status")
    parser.add_argument("--check", action="store_true", help="Check API connection + balance")
    parser.add_argument("--state-dir", default="state", help="State directory")
    args = parser.parse_args()

    state_path = Path(args.state_dir) / "live_d_state.json"

    # Config [E]: optimized via 1080-config sweep (2026-04-10)
    # BB(20,2.5) SMA, mid target, 3.5% stop, 10% risk, trail+15m
    # Backtest: +552%, DD 41.2%, R/DD 13.40, WR 70.7%, PF 2.60
    config = BBLiveConfig(
        symbol="BTCUSDT",
        leverage=5,
        initial_usdt=10000.0,
        bb_period=20,
        bb_k=2.5,
        bb_type="sma",
        stop_loss_pct=0.035,          # widened from 3% to 3.5%
        risk_per_trade=0.10,           # raised from 6.5% to 10%
        use_ma200=True,
        use_trailing_stop=True,
        trailing_activation_pct=0.03,
        trailing_atr_multiplier=2.0,   # raised from 1.5 to 2.0
        max_hold_bars=180,
        use_15m_confirmation=True,     # NEW: wait for micro-breakout
        confirm_max_wait_bars=6,
        live_mode=True,  # <-- REAL ORDERS
    )

    engine = BBLiveEngine(state_path=state_path, config=config)

    if args.check:
        _check_api(engine)
        return

    if args.status:
        engine.print_status()
        # Also show exchange position
        if engine.broker:
            pos = engine.broker.get_position(config.symbol)
            bal = engine.broker.get_balance()
            print(f"  [Exchange] Position: {pos['side']} {pos['qty']:.3f} BTC @ ${pos['entry_price']:,.0f}")
            print(f"  [Exchange] Balance:  ${bal['wallet']:,.2f} USDT (avail: ${bal['available']:,.2f})")
            print()
        return

    if args.once:
        result = engine.tick()
        _print_tick_result(result)
        engine.print_status()
        return

    # Default: continuous loop (4h interval)
    logging.info("Starting LIVE continuous mode — checking every 4h candle")
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


def _check_api(engine: BBLiveEngine) -> None:
    """Verify API connection, balance, and position."""
    print("\n=== Strategy D — LIVE API Check ===\n")

    if not engine.broker:
        print("ERROR: Broker not initialized (live_mode not enabled)")
        return

    try:
        bal = engine.broker.get_balance()
        print(f"  Balance:   ${bal['wallet']:,.2f} USDT")
        print(f"  Available: ${bal['available']:,.2f} USDT")
        print(f"  Unreal PnL: ${bal['unrealized_pnl']:+,.2f}")
    except Exception as e:
        print(f"  Balance ERROR: {e}")
        return

    try:
        pos = engine.broker.get_position("BTCUSDT")
        print(f"  Position:  {pos['side']} {pos['qty']:.3f} BTC")
        print(f"  Leverage:  {pos.get('leverage', '?')}x {pos.get('margin_type', '?')}")
    except Exception as e:
        print(f"  Position ERROR: {e}")
        return

    try:
        orders = engine.broker.get_open_orders("BTCUSDT")
        print(f"  Open orders: {len(orders)}")
    except Exception as e:
        print(f"  Orders ERROR: {e}")

    print(f"\n  API OK\n")


def _print_tick_result(result: dict) -> None:
    """Pretty-print a tick result."""
    action = result.get("action", "none")
    diag = result.get("diagnostics", {})
    live = result.get("live", False)
    tag = "[LIVE]" if live else ""

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
        print(f"  >>> {tag} ENTRY {sig.upper()} | {result.get('qty', 0):.4f} BTC @ ${result.get('price', 0):,.0f}")
    elif action == "exit":
        print(f"  >>> {tag} EXIT {result.get('reason', '')} | PnL ${result.get('pnl_usdt', 0):+,.0f} ({result.get('pnl_pct', 0):+.1f}%)")
    elif action == "hold":
        print(f"  ... holding | unrealized {result.get('unrealized_pnl_pct', 0):+.1f}% | bars: {result.get('bars_held', 0)}")
    elif action == "skip_duplicate":
        print("  (same candle, skipped)")
    elif action == "blocked_ma200":
        print(f"  {result.get('signal', '')} blocked: {result.get('reason', '')}")
    elif action == "entry_failed":
        print(f"  ENTRY FAILED: {result.get('error', '')}")
    elif action == "exit_failed":
        print(f"  EXIT FAILED: {result.get('error', '')}")
    elif action == "no_signal":
        print("  -- no signal")
    else:
        print(f"  [{action}]")


if __name__ == "__main__":
    main()
