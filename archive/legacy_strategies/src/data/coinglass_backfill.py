"""Coinglass data backfill — fetch historical derivatives data to CSV.

Usage:
    python -m data.coinglass_backfill --api-key KEY --output-dir src/data
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

from adapters.coinglass_client import (
    BasisBar,
    CVDBar,
    CoinglassClient,
    FundingRateBar,
    LiquidationBar,
    OIBar,
    TakerVolumeBar,
    TopLSRatioBar,
)


def save_oi_csv(bars: list[OIBar], path: str | Path) -> Path:
    p = Path(path)
    with open(p, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close"])
        for b in bars:
            writer.writerow([b.timestamp.isoformat(), b.open, b.high, b.low, b.close])
    return p


def load_oi_csv(path: str | Path) -> list[OIBar]:
    bars = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append(OIBar(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
            ))
    return bars


def save_funding_csv(bars: list[FundingRateBar], path: str | Path) -> Path:
    p = Path(path)
    with open(p, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close"])
        for b in bars:
            writer.writerow([b.timestamp.isoformat(), b.open, b.high, b.low, b.close])
    return p


def load_funding_csv(path: str | Path) -> list[FundingRateBar]:
    bars = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append(FundingRateBar(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
            ))
    return bars


def save_liquidation_csv(bars: list[LiquidationBar], path: str | Path) -> Path:
    p = Path(path)
    with open(p, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "long_usd", "short_usd"])
        for b in bars:
            writer.writerow([b.timestamp.isoformat(), b.long_usd, b.short_usd])
    return p


def load_liquidation_csv(path: str | Path) -> list[LiquidationBar]:
    bars = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append(LiquidationBar(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                long_usd=float(row["long_usd"]),
                short_usd=float(row["short_usd"]),
            ))
    return bars


def save_taker_volume_csv(bars: list[TakerVolumeBar], path: str | Path) -> Path:
    p = Path(path)
    with open(p, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "buy_usd", "sell_usd"])
        for b in bars:
            writer.writerow([b.timestamp.isoformat(), b.buy_usd, b.sell_usd])
    return p


def load_taker_volume_csv(path: str | Path) -> list[TakerVolumeBar]:
    bars = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append(TakerVolumeBar(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                buy_usd=float(row["buy_usd"]),
                sell_usd=float(row["sell_usd"]),
            ))
    return bars


def save_top_ls_ratio_csv(bars: list[TopLSRatioBar], path: str | Path) -> Path:
    p = Path(path)
    with open(p, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "long_percent", "short_percent", "ratio"])
        for b in bars:
            writer.writerow([b.timestamp.isoformat(), b.long_percent, b.short_percent, b.ratio])
    return p


def load_top_ls_ratio_csv(path: str | Path) -> list[TopLSRatioBar]:
    bars = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append(TopLSRatioBar(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                long_percent=float(row["long_percent"]),
                short_percent=float(row["short_percent"]),
                ratio=float(row["ratio"]),
            ))
    return bars


def save_cvd_csv(bars: list[CVDBar], path: str | Path) -> Path:
    p = Path(path)
    with open(p, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "buy_vol", "sell_vol", "cvd"])
        for b in bars:
            writer.writerow([b.timestamp.isoformat(), b.buy_vol, b.sell_vol, b.cvd])
    return p


def load_cvd_csv(path: str | Path) -> list[CVDBar]:
    bars = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append(CVDBar(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                buy_vol=float(row["buy_vol"]),
                sell_vol=float(row["sell_vol"]),
                cvd=float(row["cvd"]),
            ))
    return bars


def save_basis_csv(bars: list[BasisBar], path: str | Path) -> Path:
    p = Path(path)
    with open(p, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open_basis", "close_basis"])
        for b in bars:
            writer.writerow([b.timestamp.isoformat(), b.open_basis, b.close_basis])
    return p


def load_basis_csv(path: str | Path) -> list[BasisBar]:
    bars = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append(BasisBar(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                open_basis=float(row["open_basis"]),
                close_basis=float(row["close_basis"]),
            ))
    return bars


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Coinglass derivatives data to CSV")
    parser.add_argument("--api-key", required=True, help="Coinglass API key")
    parser.add_argument("--symbol", default="BTC", help="Symbol (default: BTC)")
    parser.add_argument("--interval", default="4h", help="Interval (default: 4h)")
    parser.add_argument("--output-dir", default="src/data", help="Output directory")
    parser.add_argument("--exchange-list", default="Binance", help="Exchange for liquidation/taker volume")
    args = parser.parse_args()

    client = CoinglassClient(api_key=args.api_key)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    interval = args.interval
    suffix = interval.replace("h", "h").replace("d", "d")
    print(f"Backfilling {args.symbol} {interval} data from Coinglass...")

    # 1. OI history
    print("\n[1/7] Fetching OI history...")
    oi_bars = client.fetch_oi_history(symbol=args.symbol, interval=interval)
    if oi_bars:
        path = save_oi_csv(oi_bars, out / f"coinglass_oi_{suffix}.csv")
        print(f"  Saved {len(oi_bars)} bars to {path}")
        print(f"  Range: {oi_bars[0].timestamp} to {oi_bars[-1].timestamp}")
    else:
        print("  No OI data returned")

    # 2. Funding rate history
    print("\n[2/7] Fetching funding rate history...")
    funding_bars = client.fetch_funding_rate_history(symbol=args.symbol, interval=interval)
    if funding_bars:
        path = save_funding_csv(funding_bars, out / f"coinglass_funding_{suffix}.csv")
        print(f"  Saved {len(funding_bars)} bars to {path}")
        print(f"  Range: {funding_bars[0].timestamp} to {funding_bars[-1].timestamp}")
    else:
        print("  No funding rate data returned")

    # 3. Liquidation history
    print("\n[3/7] Fetching liquidation history...")
    liq_bars = client.fetch_liquidation_history(
        symbol=args.symbol, interval=interval, exchange_list=args.exchange_list,
    )
    if liq_bars:
        path = save_liquidation_csv(liq_bars, out / f"coinglass_liquidation_{suffix}.csv")
        print(f"  Saved {len(liq_bars)} bars to {path}")
        print(f"  Range: {liq_bars[0].timestamp} to {liq_bars[-1].timestamp}")
    else:
        print("  No liquidation data returned")

    # 4. Taker buy/sell volume
    print("\n[4/7] Fetching taker buy/sell volume history...")
    taker_bars = client.fetch_taker_volume_history(
        symbol=args.symbol, interval=interval, exchange_list=args.exchange_list,
    )
    if taker_bars:
        path = save_taker_volume_csv(taker_bars, out / f"coinglass_taker_volume_{suffix}.csv")
        print(f"  Saved {len(taker_bars)} bars to {path}")
        print(f"  Range: {taker_bars[0].timestamp} to {taker_bars[-1].timestamp}")
    else:
        print("  No taker volume data returned")

    # 5. Top trader L/S position ratio
    pair = f"{args.symbol}USDT"
    print(f"\n[5/7] Fetching top trader L/S position ratio ({pair})...")
    top_ls_bars = client.fetch_top_ls_ratio_history(
        exchange=args.exchange_list, symbol=pair, interval=interval,
    )
    if top_ls_bars:
        path = save_top_ls_ratio_csv(top_ls_bars, out / f"coinglass_top_ls_{suffix}.csv")
        print(f"  Saved {len(top_ls_bars)} bars to {path}")
        print(f"  Range: {top_ls_bars[0].timestamp} to {top_ls_bars[-1].timestamp}")
    else:
        print("  No top L/S data returned")

    # 6. CVD (Cumulative Volume Delta)
    print("\n[6/7] Fetching CVD history...")
    cvd_bars = client.fetch_cvd_history(
        symbol=args.symbol, exchange_list=args.exchange_list, interval=interval,
    )
    if cvd_bars:
        path = save_cvd_csv(cvd_bars, out / f"coinglass_cvd_{suffix}.csv")
        print(f"  Saved {len(cvd_bars)} bars to {path}")
        print(f"  Range: {cvd_bars[0].timestamp} to {cvd_bars[-1].timestamp}")
    else:
        print("  No CVD data returned")

    # 7. Basis (futures premium)
    print(f"\n[7/7] Fetching basis history ({pair})...")
    basis_bars = client.fetch_basis_history(
        exchange=args.exchange_list, symbol=pair, interval=interval,
    )
    if basis_bars:
        path = save_basis_csv(basis_bars, out / f"coinglass_basis_{suffix}.csv")
        print(f"  Saved {len(basis_bars)} bars to {path}")
        print(f"  Range: {basis_bars[0].timestamp} to {basis_bars[-1].timestamp}")
    else:
        print("  No basis data returned")

    print("\nBackfill complete!")


if __name__ == "__main__":
    main()
