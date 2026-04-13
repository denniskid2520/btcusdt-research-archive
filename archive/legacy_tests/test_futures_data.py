"""Tests for futures derivatives data (OI, long/short ratio, taker ratio)."""

from __future__ import annotations

from datetime import datetime

from adapters.futures_data import FuturesSnapshot, FuturesDataProvider, StaticFuturesProvider


def test_futures_snapshot_has_required_fields() -> None:
    snap = FuturesSnapshot(
        timestamp=datetime(2026, 1, 1),
        open_interest=90000.0,
        long_short_ratio=1.85,
        taker_buy_sell_ratio=0.95,
    )
    assert snap.open_interest == 90000.0
    assert snap.long_short_ratio == 1.85
    assert snap.taker_buy_sell_ratio == 0.95


def test_static_provider_returns_snapshot_for_known_timestamp() -> None:
    ts = datetime(2026, 3, 15, 12, 0)
    data = {ts: FuturesSnapshot(timestamp=ts, open_interest=85000.0, long_short_ratio=1.5, taker_buy_sell_ratio=1.1)}
    provider = StaticFuturesProvider(data)
    snap = provider.get_snapshot("BTCUSDT", ts)
    assert snap is not None
    assert snap.open_interest == 85000.0


def test_static_provider_returns_nearest_snapshot() -> None:
    """Should return the closest available snapshot within tolerance."""
    ts1 = datetime(2026, 3, 15, 12, 0)
    ts2 = datetime(2026, 3, 15, 16, 0)
    data = {
        ts1: FuturesSnapshot(timestamp=ts1, open_interest=85000.0, long_short_ratio=1.5, taker_buy_sell_ratio=1.1),
        ts2: FuturesSnapshot(timestamp=ts2, open_interest=86000.0, long_short_ratio=1.6, taker_buy_sell_ratio=0.9),
    }
    provider = StaticFuturesProvider(data)
    # Query between the two — should return nearest
    query = datetime(2026, 3, 15, 15, 0)
    snap = provider.get_snapshot("BTCUSDT", query)
    assert snap is not None
    assert snap.open_interest == 86000.0  # ts2 is closer (1h vs 3h)


def test_static_provider_returns_none_when_empty() -> None:
    provider = StaticFuturesProvider({})
    snap = provider.get_snapshot("BTCUSDT", datetime(2026, 1, 1))
    assert snap is None


def test_futures_snapshot_long_pct() -> None:
    snap = FuturesSnapshot(
        timestamp=datetime(2026, 1, 1),
        open_interest=90000.0,
        long_short_ratio=1.85,
        taker_buy_sell_ratio=1.0,
    )
    # L/S = 1.85 means long_pct = 1.85 / (1 + 1.85) = 64.9%
    assert abs(snap.long_pct - 64.9) < 0.5
    assert abs(snap.short_pct - 35.1) < 0.5


def test_futures_snapshot_new_coinglass_fields() -> None:
    """FuturesSnapshot supports top_ls_ratio, cvd, and basis fields."""
    snap = FuturesSnapshot(
        timestamp=datetime(2026, 1, 1),
        open_interest=90000.0,
        long_short_ratio=1.85,
        taker_buy_sell_ratio=1.0,
        top_ls_ratio=1.53,
        cvd=10_975_605.00,
        basis=0.0495,
    )
    assert snap.top_ls_ratio == 1.53
    assert snap.cvd == 10_975_605.00
    assert snap.basis == 0.0495


def test_futures_snapshot_new_fields_default_none() -> None:
    """New fields default to None when not provided."""
    snap = FuturesSnapshot(
        timestamp=datetime(2026, 1, 1),
        open_interest=90000.0,
        long_short_ratio=1.0,
        taker_buy_sell_ratio=1.0,
    )
    assert snap.top_ls_ratio is None
    assert snap.cvd is None
    assert snap.basis is None


def test_static_provider_from_coinglass_csvs_with_new_fields(tmp_path) -> None:
    """from_coinglass_csvs merges top_ls, cvd, basis CSVs into snapshots."""
    import csv

    ts = "2024-01-01T00:00:00"

    # OI CSV
    oi_path = tmp_path / "oi.csv"
    with open(oi_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "open", "high", "low", "close"])
        w.writerow([ts, "100", "110", "90", "105"])

    # Top L/S CSV
    top_ls_path = tmp_path / "top_ls.csv"
    with open(top_ls_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "long_percent", "short_percent", "ratio"])
        w.writerow([ts, "55.2", "44.8", "1.232"])

    # CVD CSV
    cvd_path = tmp_path / "cvd.csv"
    with open(cvd_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "buy_vol", "sell_vol", "cvd"])
        w.writerow([ts, "280504501.21", "247025969.49", "10975605.0"])

    # Basis CSV
    basis_path = tmp_path / "basis.csv"
    with open(basis_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "open_basis", "close_basis"])
        w.writerow([ts, "0.0512", "0.0495"])

    provider = StaticFuturesProvider.from_coinglass_csvs(
        oi_csv=str(oi_path),
        top_ls_csv=str(top_ls_path),
        cvd_csv=str(cvd_path),
        basis_csv=str(basis_path),
    )
    snap = provider.get_snapshot("BTCUSDT", datetime(2024, 1, 1))
    assert snap is not None
    assert snap.oi_close == 105.0
    assert snap.top_ls_ratio == 1.232
    assert snap.cvd == 10975605.0
    assert snap.basis == 0.0495
