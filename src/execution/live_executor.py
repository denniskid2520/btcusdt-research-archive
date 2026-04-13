"""Phase 13.6 — live executor with corrected stop semantics.

Stop model (CORRECTED):
  alpha stop = CLIENT-SIDE close-stop
    - evaluated only on completed 1h bars
    - if bar.close <= alpha_level → queue exit at next bar open
    - matches backtest strategy_close_stop semantics exactly
    - NO exchange order placed for alpha stop
  catastrophe stop = EXCHANGE-SIDE STOP_MARKET
    - placed as a resting STOP_MARKET order on Binance
    - intrabar wick protection (fires between bars)
    - reduceOnly=true
    - full lifecycle logging: request → ack → reject → trigger → fill

Capital mode: equity_linked
  - reads Binance futures availableBalance on each tick
  - strategy_equity = availableBalance * allocation_pct
  - optional max_cap_usd for micro-live acceptance stage
  - dual reporting: live_equity + $10k benchmark normalized

Execution: bar-close triggered (~10s poll loop)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import traceback
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from adapters.base import MarketBar
from execution.paper_runner_v2 import CandidateConfig, PaperRunnerV2, TradeRecord

DATA_DIR = PROJECT_ROOT / "data" / "live_state"
LOGS_DIR = PROJECT_ROOT / "logs"
ALERTS_FILE = LOGS_DIR / "live_alerts.jsonl"
ENV_FILE = PROJECT_ROOT / ".env"
BENCHMARK_EQUITY = 10_000.0


# ── load env ────────────────────────────────────────────────────────

def load_env() -> dict[str, str]:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


# ── capital config ──────────────────────────────────────────────────

@dataclass
class CapitalConfig:
    capital_mode: str = "equity_linked"
    allocation_pct: float = 1.0
    min_required_usd: float = 100.0
    max_cap_usd: float | None = None  # micro-live cap


@dataclass
class AccountSnapshot:
    timestamp: datetime
    available_balance: float
    total_balance: float
    strategy_equity: float
    benchmark_equity: float = BENCHMARK_EQUITY


# ── stop order events ──────────────────────────────────────────────

@dataclass
class StopOrderEvent:
    timestamp: str
    event_type: str   # request / ack / reject / trigger / fill / cancel
    order_type: str   # catastrophe_stop (alpha is client-side, no exchange order)
    side: str
    stop_price: float
    quantity: float
    order_id: str | None = None
    fill_price: float | None = None
    error: str | None = None


# ── deployment config ──────────────────────────────────────────────

@dataclass
class LiveDeploymentConfig:
    candidate_config: CandidateConfig
    capital_config: CapitalConfig
    mode: str        # "live" or "paper"
    stage: int       # 1=live, 2=paper-until-promotion, 3=shadow
    dry_run: bool = True  # True = log decisions but place no orders


DEPLOYMENT_CONFIGS = {
    "B_balanced_3x": LiveDeploymentConfig(
        candidate_config=CandidateConfig(
            candidate_id="B_balanced_3x",
            regime_rsi_period=20, regime_threshold=70.0,
            entry_mode="hybrid", pullback_pct=0.0075, breakout_pct=0.0025,
            max_entries_per_zone=6, cooldown_bars=2, hold_bars=24,
            exchange_leverage=3.0, base_frac=2.0, max_frac=3.0,
            alpha_stop_pct=0.0125, catastrophe_stop_pct=0.025,
        ),
        capital_config=CapitalConfig(
            capital_mode="equity_linked",
            allocation_pct=1.0,
            min_required_usd=100.0,
            max_cap_usd=None,  # set during micro-live, remove after
        ),
        mode="live",
        stage=1,
        dry_run=True,  # flip to False after micro-live passes
    ),
    "B_balanced_4x": LiveDeploymentConfig(
        candidate_config=CandidateConfig(
            candidate_id="B_balanced_4x",
            regime_rsi_period=20, regime_threshold=70.0,
            entry_mode="hybrid", pullback_pct=0.0075, breakout_pct=0.0025,
            max_entries_per_zone=6, cooldown_bars=2, hold_bars=24,
            exchange_leverage=4.0, base_frac=3.0, max_frac=4.0,
            alpha_stop_pct=0.0125, catastrophe_stop_pct=0.025,
        ),
        capital_config=CapitalConfig(capital_mode="equity_linked"),
        mode="paper", stage=2,
    ),
    "A_density_4x": LiveDeploymentConfig(
        candidate_config=CandidateConfig(
            candidate_id="A_density_4x",
            regime_rsi_period=20, regime_threshold=70.0,
            entry_mode="hybrid", pullback_pct=0.0075, breakout_pct=0.005,
            max_entries_per_zone=6, cooldown_bars=2, hold_bars=8,
            exchange_leverage=4.0, base_frac=3.0, max_frac=4.0,
            alpha_stop_pct=0.0125, catastrophe_stop_pct=0.025,
        ),
        capital_config=CapitalConfig(capital_mode="equity_linked"),
        mode="paper", stage=3,
    ),
    "B_balanced_5x": LiveDeploymentConfig(
        candidate_config=CandidateConfig(
            candidate_id="B_balanced_5x",
            regime_rsi_period=20, regime_threshold=70.0,
            entry_mode="hybrid", pullback_pct=0.0075, breakout_pct=0.0025,
            max_entries_per_zone=6, cooldown_bars=2, hold_bars=24,
            exchange_leverage=5.0, base_frac=3.33, max_frac=5.0,
            alpha_stop_pct=0.0125, catastrophe_stop_pct=0.025,
        ),
        capital_config=CapitalConfig(capital_mode="equity_linked"),
        mode="paper", stage=3,
    ),
}


# ── Binance API helpers ─────────────────────────────────────────────

# Server-time offset (ms): server_time - local_time.
# Updated by sync_server_time_offset() on startup.
_server_time_offset_ms: int = 0

RECV_WINDOW_MS = 5000  # Binance default max is 60000; 5s is safe


def sync_server_time_offset() -> int:
    """Fetch Binance server time and compute offset from local clock.

    Returns offset in ms (positive = server ahead of local).
    Updates module-level _server_time_offset_ms for use in _signed_request.
    """
    global _server_time_offset_ms
    try:
        url = "https://fapi.binance.com/fapi/v1/time"
        local_before = int(time.time() * 1000)
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        local_after = int(time.time() * 1000)
        server_time = data["serverTime"]
        # Estimate: server_time ≈ midpoint of local_before..local_after
        local_mid = (local_before + local_after) // 2
        _server_time_offset_ms = server_time - local_mid
        return _server_time_offset_ms
    except Exception:
        return _server_time_offset_ms  # keep previous offset


def _signed_request(method: str, endpoint: str, params: dict,
                    api_key: str, api_secret: str) -> dict:
    # Use server-time-offset-adjusted timestamp to prevent rejects
    params["timestamp"] = str(int(time.time() * 1000) + _server_time_offset_ms)
    params["recvWindow"] = str(RECV_WINDOW_MS)
    query = urllib.parse.urlencode(params)
    sig = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://fapi.binance.com{endpoint}?{query}&signature={sig}"
    req = urllib.request.Request(url, method=method,
                                 headers={"X-MBX-APIKEY": api_key})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def fetch_server_time() -> datetime:
    url = "https://fapi.binance.com/fapi/v1/time"
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read())
    return datetime.fromtimestamp(
        data["serverTime"] / 1000, tz=timezone.utc
    ).replace(tzinfo=None)


def fetch_account_balance(api_key: str, api_secret: str) -> AccountSnapshot:
    data = _signed_request("GET", "/fapi/v2/balance", {}, api_key, api_secret)
    usdt = next((a for a in data if a["asset"] == "USDT"), None)
    if usdt is None:
        raise ValueError("No USDT balance found")
    avail = float(usdt["availableBalance"])
    total = float(usdt["balance"])
    return AccountSnapshot(
        timestamp=datetime.utcnow(),
        available_balance=avail,
        total_balance=total,
        strategy_equity=avail,
    )


def fetch_latest_1h_bar() -> MarketBar | None:
    url = "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=2"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        if len(data) < 2:
            return None
        k = data[0]
        ts = datetime.fromtimestamp(
            k[0] / 1000, tz=timezone.utc
        ).replace(tzinfo=None)
        return MarketBar(
            timestamp=ts, open=float(k[1]), high=float(k[2]),
            low=float(k[3]), close=float(k[4]), volume=float(k[5]),
        )
    except Exception:
        return None


def fetch_funding_rate() -> float:
    try:
        url = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        return float(data.get("lastFundingRate", 0))
    except Exception:
        return 0.0


def fetch_open_orders(api_key: str, api_secret: str) -> list[dict]:
    return _signed_request(
        "GET", "/fapi/v1/openOrders",
        {"symbol": "BTCUSDT"}, api_key, api_secret,
    )


def fetch_position(api_key: str, api_secret: str) -> dict | None:
    data = _signed_request(
        "GET", "/fapi/v2/positionRisk",
        {"symbol": "BTCUSDT"}, api_key, api_secret,
    )
    for p in data:
        if p["symbol"] == "BTCUSDT" and float(p["positionAmt"]) != 0:
            return p
    return None


# ── catastrophe stop (exchange-side STOP_MARKET) ────────────────────

def place_catastrophe_stop(
    api_key: str, api_secret: str,
    side: str, stop_price: float, quantity: float,
) -> StopOrderEvent:
    """Place catastrophe stop as exchange STOP_MARKET (reduceOnly)."""
    params = {
        "symbol": "BTCUSDT",
        "side": "SELL" if side == "long" else "BUY",
        "type": "STOP_MARKET",
        "stopPrice": f"{stop_price:.2f}",
        "quantity": f"{quantity:.3f}",
        "reduceOnly": "true",
    }
    try:
        data = _signed_request(
            "POST", "/fapi/v1/order", params, api_key, api_secret,
        )
        return StopOrderEvent(
            timestamp=datetime.utcnow().isoformat(),
            event_type="ack",
            order_type="catastrophe_stop",
            side=side,
            stop_price=stop_price,
            quantity=quantity,
            order_id=str(data.get("orderId", "")),
        )
    except Exception as e:
        return StopOrderEvent(
            timestamp=datetime.utcnow().isoformat(),
            event_type="reject",
            order_type="catastrophe_stop",
            side=side,
            stop_price=stop_price,
            quantity=quantity,
            error=str(e),
        )


def cancel_all_orders(api_key: str, api_secret: str) -> dict:
    """Cancel all open orders for BTCUSDT.

    Returns {"ok": True} on success, {"ok": False, "error": str} on failure.
    Callers must check the result and decide whether to WARN/HALT.
    Previously this swallowed all exceptions with `except: pass`.
    """
    try:
        _signed_request(
            "DELETE", "/fapi/v1/allOpenOrders",
            {"symbol": "BTCUSDT"}, api_key, api_secret,
        )
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── alpha stop (CLIENT-SIDE close-stop, NO exchange order) ──────────
#
# Alpha stop is evaluated by the paper_runner_v2 on each completed
# bar: if bar.close <= alpha_stop_level → queue exit at next bar open.
# This matches the backtest's strategy_close_stop semantics exactly.
# The live executor reads the runner's pending_exit and executes a
# MARKET order at the next bar open. No STOP_MARKET is placed.
#
# This is the CORRECT behavior:
#   - alpha stop = strategy timing decision (close-only)
#   - catastrophe stop = exchange safety net (intrabar wick)


# ── file helpers ────────────────────────────────────────────────────

def atomic_write(path: Path, content: str) -> None:
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_append(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def emit_alert(cid: str, level: str, msg: str) -> None:
    alert = {"ts": datetime.utcnow().isoformat(), "candidate": cid,
             "level": level, "message": msg}
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    atomic_append(ALERTS_FILE, json.dumps(alert))
    print(f"[{level}] [{cid}] {msg}", file=sys.stderr)


def log_stop_event(cid: str, event: StopOrderEvent) -> None:
    state_dir = DATA_DIR / cid
    state_dir.mkdir(parents=True, exist_ok=True)
    atomic_append(
        state_dir / "stop_events.jsonl",
        json.dumps(asdict(event), default=str),
    )
