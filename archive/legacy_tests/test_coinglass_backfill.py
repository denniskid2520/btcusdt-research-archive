"""Tests for Coinglass backfill — CSV save/load for new data types.

TDD: write failing tests first, then implement.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from adapters.coinglass_client import TopLSRatioBar, CVDBar, BasisBar
from data.coinglass_backfill import (
    save_top_ls_ratio_csv,
    load_top_ls_ratio_csv,
    save_cvd_csv,
    load_cvd_csv,
    save_basis_csv,
    load_basis_csv,
)


@pytest.fixture
def tmp_csv(tmp_path: Path):
    """Return a factory that creates temp CSV paths."""
    def _make(name: str) -> Path:
        return tmp_path / name
    return _make


# ── Top L/S Ratio CSV ────────────────────────────────────────────────


def test_save_and_load_top_ls_ratio_csv(tmp_csv) -> None:
    bars = [
        TopLSRatioBar(datetime(2024, 1, 1, 0, 0), 55.2, 44.8, 1.232),
        TopLSRatioBar(datetime(2024, 1, 1, 4, 0), 58.1, 41.9, 1.387),
    ]
    path = tmp_csv("top_ls.csv")
    save_top_ls_ratio_csv(bars, path)
    loaded = load_top_ls_ratio_csv(path)
    assert len(loaded) == 2
    assert loaded[0].long_percent == 55.2
    assert loaded[0].short_percent == 44.8
    assert loaded[0].ratio == 1.232
    assert loaded[1].timestamp == datetime(2024, 1, 1, 4, 0)


# ── CVD CSV ───────────────────────────────────────────────────────────


def test_save_and_load_cvd_csv(tmp_csv) -> None:
    bars = [
        CVDBar(datetime(2024, 1, 1, 0, 0), 280504501.21, 247025969.49, 10975605.00),
        CVDBar(datetime(2024, 1, 1, 4, 0), 300000000.00, 310000000.00, -5000000.00),
    ]
    path = tmp_csv("cvd.csv")
    save_cvd_csv(bars, path)
    loaded = load_cvd_csv(path)
    assert len(loaded) == 2
    assert loaded[0].buy_vol == 280504501.21
    assert loaded[0].cvd == 10975605.00
    assert loaded[1].cvd == -5000000.00


# ── Basis CSV ─────────────────────────────────────────────────────────


def test_save_and_load_basis_csv(tmp_csv) -> None:
    bars = [
        BasisBar(datetime(2024, 1, 1, 0, 0), 0.0512, 0.0495),
        BasisBar(datetime(2024, 1, 1, 4, 0), 0.0495, 0.0530),
    ]
    path = tmp_csv("basis.csv")
    save_basis_csv(bars, path)
    loaded = load_basis_csv(path)
    assert len(loaded) == 2
    assert loaded[0].open_basis == 0.0512
    assert loaded[0].close_basis == 0.0495
    assert loaded[1].close_basis == 0.0530
