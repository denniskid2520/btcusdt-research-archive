"""Cross-check narrative Parent A-G key points against real BTCUSDT 1D klines.

For each key_high: compare narrative price vs actual daily HIGH on that date.
For each key_low:  compare narrative price vs actual daily LOW  on that date.
Also checks structure date boundaries against available data range.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from research.narrative_case_mapping import ParentStructure, build_parent_structure_timeline


@dataclass
class PointCheck:
    parent_id: str
    point_type: str  # "key_high" or "key_low"
    narrative_date: str
    narrative_price: float
    actual_price: float | None  # actual daily high or low
    diff: float | None  # narrative - actual
    diff_pct: float | None
    status: str  # "match", "close", "mismatch", "no_data"


@dataclass
class VerificationReport:
    data_range: tuple[str, str]
    total_points: int
    matches: int
    close: int
    mismatches: int
    no_data: int
    checks: list[PointCheck]


def _load_daily_bars(csv_path: Path) -> dict[str, dict]:
    """Load 1D bars into {date_str: {open, high, low, close, volume}} dict."""
    bars: dict[str, dict] = {}
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = row["timestamp"]
            dt = datetime.fromisoformat(ts).date()
            bars[dt.isoformat()] = {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }
    return bars


def _find_best_bar(bars: dict[str, dict], target_date: str, point_type: str) -> tuple[str | None, float | None]:
    """Find bar on target_date. If missing, search ±2 days for nearest extremum."""
    if target_date in bars:
        bar = bars[target_date]
        return target_date, bar["high"] if point_type == "key_high" else bar["low"]

    # Search ±2 days window
    dt = date.fromisoformat(target_date)
    best_date = None
    best_price = None
    for offset in range(-2, 3):
        candidate = (dt.__class__.fromordinal(dt.toordinal() + offset)).isoformat()
        if candidate in bars:
            bar = bars[candidate]
            price = bar["high"] if point_type == "key_high" else bar["low"]
            if best_price is None:
                best_date, best_price = candidate, price
            elif point_type == "key_high" and price > best_price:
                best_date, best_price = candidate, price
            elif point_type == "key_low" and price < best_price:
                best_date, best_price = candidate, price
    return best_date, best_price


def verify_narrative(csv_path: Path | str | None = None) -> VerificationReport:
    """Run full verification of narrative key points against real data."""
    if csv_path is None:
        csv_path = Path(__file__).resolve().parent.parent / "data" / "btcusdt_1d_real.csv"
    else:
        csv_path = Path(csv_path)

    bars = _load_daily_bars(csv_path)
    dates_sorted = sorted(bars.keys())
    data_range = (dates_sorted[0], dates_sorted[-1])

    timeline = build_parent_structure_timeline()
    checks: list[PointCheck] = []

    for parent in timeline:
        for kh in parent.key_highs:
            _check_point(checks, bars, parent, "key_high", kh)
        for kl in parent.key_lows:
            _check_point(checks, bars, parent, "key_low", kl)

    matches = sum(1 for c in checks if c.status == "match")
    close = sum(1 for c in checks if c.status == "close")
    mismatches = sum(1 for c in checks if c.status == "mismatch")
    no_data = sum(1 for c in checks if c.status == "no_data")

    return VerificationReport(
        data_range=data_range,
        total_points=len(checks),
        matches=matches,
        close=close,
        mismatches=mismatches,
        no_data=no_data,
        checks=checks,
    )


def _check_point(
    checks: list[PointCheck],
    bars: dict[str, dict],
    parent: ParentStructure,
    point_type: str,
    point: dict,
) -> None:
    narrative_date = point["date"]
    narrative_price = float(point["price"])

    found_date, actual_price = _find_best_bar(bars, narrative_date, point_type)

    if actual_price is None:
        checks.append(PointCheck(
            parent_id=parent.structure_id,
            point_type=point_type,
            narrative_date=narrative_date,
            narrative_price=narrative_price,
            actual_price=None,
            diff=None,
            diff_pct=None,
            status="no_data",
        ))
        return

    diff = narrative_price - actual_price
    diff_pct = (diff / actual_price) * 100 if actual_price != 0 else 0.0
    abs_pct = abs(diff_pct)

    if abs_pct < 0.5:
        status = "match"
    elif abs_pct < 2.0:
        status = "close"
    else:
        status = "mismatch"

    note_suffix = ""
    if found_date != narrative_date:
        note_suffix = f" (used {found_date})"

    checks.append(PointCheck(
        parent_id=parent.structure_id,
        point_type=point_type,
        narrative_date=narrative_date + note_suffix,
        narrative_price=narrative_price,
        actual_price=actual_price,
        diff=round(diff, 2),
        diff_pct=round(diff_pct, 2),
        status=status,
    ))


def render_report(report: VerificationReport) -> str:
    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("NARRATIVE vs REAL DATA VERIFICATION REPORT")
    lines.append("=" * 80)
    lines.append(f"Data range: {report.data_range[0]} to {report.data_range[1]}")
    lines.append(f"Total key points checked: {report.total_points}")
    lines.append(f"  Match  (<0.5% diff): {report.matches}")
    lines.append(f"  Close  (<2.0% diff): {report.close}")
    lines.append(f"  Mismatch (>=2.0%):   {report.mismatches}")
    lines.append(f"  No data:             {report.no_data}")
    lines.append("")

    current_parent = None
    for c in report.checks:
        if c.parent_id != current_parent:
            current_parent = c.parent_id
            lines.append(f"--- Parent {current_parent} ---")

        icon = {"match": "OK", "close": "~", "mismatch": "XX", "no_data": "??"}[c.status]
        if c.actual_price is not None:
            lines.append(
                f"  [{icon}] {c.point_type:9s} {c.narrative_date:22s} "
                f"narrative={c.narrative_price:>10.1f}  actual={c.actual_price:>10.1f}  "
                f"diff={c.diff:>+8.1f} ({c.diff_pct:>+6.2f}%)"
            )
        else:
            lines.append(
                f"  [{icon}] {c.point_type:9s} {c.narrative_date:22s} "
                f"narrative={c.narrative_price:>10.1f}  actual=     N/A"
            )
    lines.append("")

    # Summary of problems
    problems = [c for c in report.checks if c.status in ("mismatch", "no_data")]
    if problems:
        lines.append("ISSUES REQUIRING ATTENTION:")
        for c in problems:
            lines.append(f"  - Parent {c.parent_id} {c.point_type} on {c.narrative_date}: {c.status}")
    else:
        lines.append("ALL KEY POINTS VERIFIED SUCCESSFULLY.")

    return "\n".join(lines)


if __name__ == "__main__":
    report = verify_narrative()
    print(render_report(report))
