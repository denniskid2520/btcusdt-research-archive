"""Watch / alert mode for Case10 live setup.

No order placement.  No strategy rule changes.  This module only:
1. Evaluates the current live setup conditions
2. Prints a human-readable status
3. Saves the report to disk

Usage:
    python -m context.watch_mode --live              # auto-fetch from Binance
    python -m context.watch_mode --price 67500       # manual price
    python -m context.watch_mode --price 67500 --date 2026-04-03
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from context.live_setup_validator import save_report, validate_case10_live_setup


DEFAULT_REPORT_PATH = "data/reports/current_live_setup_report.json"


def _fetch_live_price() -> float:
    """Fetch current BTCUSDT price from Binance public API (no auth needed)."""
    import sys
    from pathlib import Path

    # quant_trading lives at project root, one level above src/
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from quant_trading.binance import BinanceClient
    from quant_trading.config import BinanceConfig

    client = BinanceClient(BinanceConfig(use_testnet=False))
    price = client.get_ticker_price("BTCUSDT")
    print(f"  [live] Fetched BTCUSDT price from Binance: {price:.2f}")
    return price


def _print_status(report: dict) -> None:
    print("=" * 68)
    print("  CASE10 LIVE SETUP WATCH — ascending channel breakdown retest short")
    print("=" * 68)
    print(f"  Date:  {report['evaluation_date']}")
    print(f"  Price: {report['current_price']}")
    print()

    # Parent summary
    pf = report["parent_structure_summary"]["parent_f"]
    pg = report["parent_structure_summary"]["parent_g"]
    print(f"  Parent F: {pf['type']}")
    print(f"            {pf['period']}")
    print(f"            Transition: {pf['transition']}")
    print()
    print(f"  Parent G: {pg['type']}")
    print(f"            {pg['period']}")
    print(f"            Midline retest: {pg['midline_retest']}")
    print()

    # Channel boundaries
    ch = report.get("channel_boundaries", {})
    if ch:
        print(f"  Channel upper boundary (now): {ch.get('upper_boundary_current')}")
        print(f"  Channel lower boundary (now): {ch.get('lower_boundary_current')}")
        print(f"  Channel width (now):          {ch.get('channel_width_current')}")
        print()

    # Local structure
    ls = report["local_structure_summary"]
    print(f"  Breakdown: {ls['breakdown_date']} at {ls['breakdown_price']}")
    print(f"  Retest:    {ls['retest_date']} at {ls['retest_price']}")
    print()

    # Conditions
    print("  CONDITIONS:")
    for c in report["conditions"]:
        icon = "PASS" if c["passed"] else "FAIL"
        print(f"    [{icon}] {c['name']}")
        print(f"           {c['detail']}")
    print()

    # Verdict
    if report["trade_valid"]:
        tp = report["trade_plan"]
        print("  >>> TRADE VALID <<<")
        print(f"  Side:           {tp['side']}")
        print(f"  Entry:          {tp['entry']}")
        print(f"  Stop:           {tp['stop']}")
        print(f"  Target 1:       {tp['target_1']}")
        print(f"  Target 2:       {tp['target_2']}")
        print(f"  Invalidation:   {tp['invalidation']}")
        print(f"  R:R (T1):       {tp['risk_reward_t1']}")
        print(f"  R:R (T2):       {tp['risk_reward_t2']}")
    else:
        print("  >>> TRADE NOT YET VALID <<<")
        for b in report.get("blocking_conditions", []):
            print(f"  - {b['name']}: {b['detail']}")
        print()
        print(f"  Next action: {report['next_action']}")

    print()
    print("  MODE: WATCH ONLY — no orders placed")
    print("=" * 68)


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch mode for Case10 live setup")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Auto-fetch current BTCUSDT price from Binance (public API, no key needed)",
    )
    parser.add_argument(
        "--price",
        type=float,
        default=None,
        help="Manual BTCUSDT price (ignored if --live is used)",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Evaluation date in YYYY-MM-DD format (default: today)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=DEFAULT_REPORT_PATH,
        help=f"Output path for JSON report (default: {DEFAULT_REPORT_PATH})",
    )
    args = parser.parse_args()

    # Resolve price
    current_price = args.price
    if args.live:
        try:
            current_price = _fetch_live_price()
        except Exception as e:
            print(f"  [error] Failed to fetch live price: {e}", file=sys.stderr)
            if current_price is None:
                print("  [error] No --price fallback provided. Exiting.", file=sys.stderr)
                sys.exit(1)
            print(f"  [fallback] Using manual price: {current_price}")

    eval_date: date | None = None
    if args.date:
        eval_date = datetime.strptime(args.date, "%Y-%m-%d").date()

    report = validate_case10_live_setup(
        current_price=current_price,
        current_date=eval_date,
    )

    _print_status(report)
    path = save_report(report, args.output)
    print(f"  Report saved to: {path}")


if __name__ == "__main__":
    main()
