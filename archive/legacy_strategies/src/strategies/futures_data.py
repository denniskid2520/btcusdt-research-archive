"""Futures derivatives data: OI, long/short ratio, taker buy/sell ratio.

Provides both a live Binance fetcher and a static provider for backtesting.
"""

from __future__ import annotations

import csv
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class FuturesSnapshot:
    """Single point-in-time derivatives data."""

    timestamp: datetime
    open_interest: float
    long_short_ratio: float
    taker_buy_sell_ratio: float

    # Coinglass extended fields (all optional, None = no data)
    oi_close: float | None = None  # Aggregated OI in USD
    funding_rate: float | None = None  # OI-weighted funding rate
    liq_long_usd: float | None = None  # Long liquidation volume
    liq_short_usd: float | None = None  # Short liquidation volume
    taker_buy_usd: float | None = None  # Taker buy volume
    taker_sell_usd: float | None = None  # Taker sell volume
    top_ls_ratio: float | None = None  # Top trader position L/S ratio
    cvd: float | None = None  # Cumulative Volume Delta
    basis: float | None = None  # Futures basis (premium)

    @property
    def long_pct(self) -> float:
        return self.long_short_ratio / (1 + self.long_short_ratio) * 100

    @property
    def short_pct(self) -> float:
        return 100.0 - self.long_pct


class FuturesDataProvider(ABC):
    @abstractmethod
    def get_snapshot(self, symbol: str, timestamp: datetime) -> FuturesSnapshot | None:
        raise NotImplementedError


class StaticFuturesProvider(FuturesDataProvider):
    """In-memory provider for backtesting — preloaded with historical data."""

    def __init__(self, data: dict[datetime, FuturesSnapshot], tolerance_hours: int = 4) -> None:
        self._data = data
        self._sorted_ts = sorted(data.keys())
        self._tolerance_sec = tolerance_hours * 3600

    def get_snapshot(self, symbol: str, timestamp: datetime) -> FuturesSnapshot | None:
        if not self._sorted_ts:
            return None
        best_ts = min(self._sorted_ts, key=lambda t: abs((t - timestamp).total_seconds()))
        if abs((best_ts - timestamp).total_seconds()) > self._tolerance_sec:
            return None
        return self._data[best_ts]

    @classmethod
    def from_coinglass_csvs(
        cls,
        oi_csv: str | Path | None = None,
        funding_csv: str | Path | None = None,
        liquidation_csv: str | Path | None = None,
        taker_csv: str | Path | None = None,
        top_ls_csv: str | Path | None = None,
        cvd_csv: str | Path | None = None,
        basis_csv: str | Path | None = None,
    ) -> "StaticFuturesProvider":
        """Build provider from Coinglass CSV files, merging by timestamp."""

        def _load_csv(path: str | Path | None) -> dict[datetime, dict]:
            result: dict[datetime, dict] = {}
            if path and Path(path).exists():
                with open(path) as f:
                    for row in csv.DictReader(f):
                        ts = datetime.fromisoformat(row["timestamp"])
                        result[ts] = row
            return result

        oi_by_ts = _load_csv(oi_csv)
        funding_by_ts = _load_csv(funding_csv)
        liq_by_ts = _load_csv(liquidation_csv)
        taker_by_ts = _load_csv(taker_csv)
        top_ls_by_ts = _load_csv(top_ls_csv)
        cvd_by_ts = _load_csv(cvd_csv)
        basis_by_ts = _load_csv(basis_csv)

        all_timestamps = (
            set(oi_by_ts) | set(funding_by_ts) | set(liq_by_ts)
            | set(taker_by_ts) | set(top_ls_by_ts) | set(cvd_by_ts) | set(basis_by_ts)
        )
        data: dict[datetime, FuturesSnapshot] = {}

        for ts in all_timestamps:
            oi = oi_by_ts.get(ts)
            fund = funding_by_ts.get(ts)
            liq = liq_by_ts.get(ts)
            taker = taker_by_ts.get(ts)
            top_ls = top_ls_by_ts.get(ts)
            cvd = cvd_by_ts.get(ts)
            basis = basis_by_ts.get(ts)

            data[ts] = FuturesSnapshot(
                timestamp=ts,
                open_interest=float(oi["close"]) if oi else 0.0,
                long_short_ratio=1.0,
                taker_buy_sell_ratio=1.0,
                oi_close=float(oi["close"]) if oi else None,
                funding_rate=float(fund["close"]) if fund else None,
                liq_long_usd=float(liq["long_usd"]) if liq else None,
                liq_short_usd=float(liq["short_usd"]) if liq else None,
                taker_buy_usd=float(taker["buy_usd"]) if taker else None,
                taker_sell_usd=float(taker["sell_usd"]) if taker else None,
                top_ls_ratio=float(top_ls["ratio"]) if top_ls else None,
                cvd=float(cvd["cvd"]) if cvd else None,
                basis=float(basis["close_basis"]) if basis else None,
            )

        return cls(data)


class BinanceFuturesProvider(FuturesDataProvider):
    """Live provider that fetches from Binance Futures public API."""

    _BASE = "https://fapi.binance.com"

    def get_snapshot(self, symbol: str, timestamp: datetime) -> FuturesSnapshot | None:
        try:
            oi = self._fetch_oi(symbol)
            ls = self._fetch_long_short(symbol)
            taker = self._fetch_taker(symbol)
            return FuturesSnapshot(
                timestamp=timestamp,
                open_interest=oi,
                long_short_ratio=ls,
                taker_buy_sell_ratio=taker,
            )
        except Exception:
            return None

    def fetch_history(self, symbol: str, period: str = "4h", limit: int = 500) -> list[FuturesSnapshot]:
        """Fetch historical snapshots (up to ~30 days back)."""
        oi_data = self._get_json(f"/futures/data/openInterestHist?symbol={symbol}&period={period}&limit={limit}")
        ls_data = self._get_json(f"/futures/data/topLongShortAccountRatio?symbol={symbol}&period={period}&limit={limit}")
        taker_data = self._get_json(f"/futures/data/takerlongshortRatio?symbol={symbol}&period={period}&limit={limit}")

        # Index by timestamp
        ls_by_ts = {d["timestamp"]: d for d in ls_data}
        taker_by_ts = {d["timestamp"]: d for d in taker_data}

        snapshots: list[FuturesSnapshot] = []
        for row in oi_data:
            ts_ms = row["timestamp"]
            ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).replace(tzinfo=None)
            ls_row = ls_by_ts.get(ts_ms, {})
            taker_row = taker_by_ts.get(ts_ms, {})
            snapshots.append(FuturesSnapshot(
                timestamp=ts,
                open_interest=float(row.get("sumOpenInterest", 0)),
                long_short_ratio=float(ls_row.get("longShortRatio", 0)),
                taker_buy_sell_ratio=float(taker_row.get("buySellRatio", 0)),
            ))
        return snapshots

    def _fetch_oi(self, symbol: str) -> float:
        data = self._get_json(f"/fapi/v1/openInterest?symbol={symbol}")
        return float(data["openInterest"])

    def _fetch_long_short(self, symbol: str) -> float:
        data = self._get_json(f"/futures/data/topLongShortAccountRatio?symbol={symbol}&period=4h&limit=1")
        return float(data[0]["longShortRatio"]) if data else 0.0

    def _fetch_taker(self, symbol: str) -> float:
        data = self._get_json(f"/futures/data/takerlongshortRatio?symbol={symbol}&period=4h&limit=1")
        return float(data[0]["buySellRatio"]) if data else 0.0

    def _get_json(self, path: str) -> dict | list:
        url = f"{self._BASE}{path}"
        req = Request(url, method="GET")
        req.add_header("Accept", "application/json")
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
