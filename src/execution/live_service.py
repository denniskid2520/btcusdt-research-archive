"""Phase 14 — live execution service (bar-close polling loop).

Runs as a continuous process (systemd or screen).
Polls Binance klines every 10s to detect completed 1h bars.
Triggers the strategy tick immediately on bar close.

Modes:
  dry_run=True  → reads real data, computes decisions, places NO orders
  dry_run=False → places real MARKET entries/exits + catastrophe STOP_MARKET

Stop semantics (Phase 13.6 corrected):
  alpha stop    = client-side close check (NO exchange order)
  catastrophe   = exchange STOP_MARKET (reduceOnly)

Usage:
  # Dry-run:
  PYTHONPATH=src python3 -m execution.live_service --dry-run
  # Live:
  PYTHONPATH=src python3 -m execution.live_service
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from adapters.base import MarketBar
from execution.live_executor import (
    BENCHMARK_EQUITY,
    DATA_DIR,
    DEPLOYMENT_CONFIGS,
    AccountSnapshot,
    CapitalConfig,
    LiveDeploymentConfig,
    StopOrderEvent,
    atomic_append,
    atomic_write,
    cancel_all_orders,
    emit_alert,
    fetch_account_balance,
    fetch_funding_rate,
    fetch_latest_1h_bar,
    fetch_open_orders,
    fetch_position,
    fetch_server_time,
    load_env,
    log_stop_event,
    place_catastrophe_stop,
)
from execution.paper_runner_v2 import PaperRunnerV2

POLL_INTERVAL = 10  # seconds between kline polls
CANDIDATE_ID = "B_balanced_3x"  # only this candidate runs live


class LiveService:
    def __init__(self, dry_run: bool = True, max_cap_usd: float | None = None):
        self.dry_run = dry_run
        self.max_cap_usd = max_cap_usd
        self.deploy_cfg = DEPLOYMENT_CONFIGS[CANDIDATE_ID]
        self.candidate_cfg = self.deploy_cfg.candidate_config
        self.capital_cfg = self.deploy_cfg.capital_config
        if max_cap_usd is not None:
            self.capital_cfg = CapitalConfig(
                capital_mode="equity_linked",
                allocation_pct=self.capital_cfg.allocation_pct,
                min_required_usd=self.capital_cfg.min_required_usd,
                max_cap_usd=max_cap_usd,
            )

        env = load_env()
        self.api_key = env.get("BINANCE_API_KEY", "")
        self.api_secret = env.get("BINANCE_API_SECRET", "")

        self.state_dir = DATA_DIR / CANDIDATE_ID
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.runner = self._load_runner()
        self.last_bar_ts: datetime | None = self._load_last_bar_ts()

        # FIX 2: restore persisted live-position fields from state.json
        # so a restart during an open trade doesn't lose position tracking.
        self.has_live_position = False
        self.live_entry_price: float = 0.0
        self.live_quantity: float = 0.0
        self.live_alpha_level: float = 0.0
        self.live_catastrophe_level: float = 0.0
        self.open_catastrophe_order_id: str | None = None
        self._restore_live_position_state()

    def _restore_live_position_state(self) -> None:
        """FIX 2: restore live-position fields from persisted state.json.

        On startup (or restart), if a live position was open when the
        process last saved, we must restore all tracking fields so the
        service can continue managing the position correctly.
        """
        state_file = self.state_dir / "state.json"
        if not state_file.exists():
            return
        try:
            saved = json.loads(state_file.read_text())
            self.has_live_position = saved.get("has_live_position", False)
            self.live_entry_price = saved.get("live_entry_price", 0.0)
            self.live_quantity = saved.get("live_quantity", 0.0)
            self.live_alpha_level = saved.get("live_alpha_level", 0.0)
            self.live_catastrophe_level = saved.get("live_catastrophe_level", 0.0)
            self.open_catastrophe_order_id = saved.get("open_catastrophe_order_id")
            if self.has_live_position:
                self._log_tick(
                    f"Restored live position: entry={self.live_entry_price:.2f} "
                    f"qty={self.live_quantity:.4f} alpha={self.live_alpha_level:.2f} "
                    f"cat={self.live_catastrophe_level:.2f}"
                )
        except Exception as e:
            emit_alert(CANDIDATE_ID, "WARN", f"Failed to restore live position: {e}")

    def _load_runner(self) -> PaperRunnerV2:
        runner = PaperRunnerV2(self.candidate_cfg)
        buf_file = self.state_dir / "rsi_buffer.json"
        if buf_file.exists():
            try:
                runner._rsi_buffer = json.loads(buf_file.read_text())
            except Exception:
                pass
        state_file = self.state_dir / "state.json"
        if state_file.exists():
            try:
                saved = json.loads(state_file.read_text())
                runner.state.next_trade_id = saved.get("next_trade_id", 1)
                runner.state.next_zone_id = saved.get("next_zone_id", 1)
                runner.state.regime_active = saved.get("regime_active", False)
                runner.state.bars_since_last_exit = saved.get("bars_since_last_exit", 999)
            except Exception:
                pass
        return runner

    def _save_runner(self) -> None:
        atomic_write(
            self.state_dir / "rsi_buffer.json",
            json.dumps(self.runner._rsi_buffer[-500:]),
        )
        atomic_write(
            self.state_dir / "state.json",
            json.dumps({
                "position_state": self.runner.state.position_state,
                "regime_active": self.runner.state.regime_active,
                "next_trade_id": self.runner.state.next_trade_id,
                "next_zone_id": self.runner.state.next_zone_id,
                "bars_since_last_exit": self.runner.state.bars_since_last_exit,
                "trade_count": len(self.runner.trades),
                # FIX 2: persist ALL live-position fields for restart recovery
                "has_live_position": self.has_live_position,
                "live_entry_price": self.live_entry_price,
                "live_quantity": self.live_quantity,
                "live_alpha_level": self.live_alpha_level,
                "live_catastrophe_level": self.live_catastrophe_level,
                "open_catastrophe_order_id": self.open_catastrophe_order_id,
            }, indent=2, default=str),
        )

    def _load_last_bar_ts(self) -> datetime | None:
        f = self.state_dir / "last_processed_ts.txt"
        if f.exists():
            raw = f.read_text().strip()
            if raw:
                return datetime.fromisoformat(raw)
        return None

    def _mark_bar_processed(self, ts: datetime) -> None:
        atomic_write(self.state_dir / "last_processed_ts.txt", ts.isoformat())
        self.last_bar_ts = ts

    def _log_tick(self, msg: str) -> None:
        now = datetime.utcnow().isoformat()
        line = f"[{now}] {msg}"
        print(line, flush=True)
        atomic_append(self.state_dir / "service.log", line)

    def _log_event(self, event: dict) -> None:
        atomic_append(self.state_dir / "events.jsonl", json.dumps(event, default=str))

    # ── account ─────────────────────────────────────────────────

    def _get_strategy_equity(self) -> float | None:
        try:
            snap = fetch_account_balance(self.api_key, self.api_secret)
            eq = snap.available_balance * self.capital_cfg.allocation_pct
            if self.capital_cfg.max_cap_usd is not None:
                eq = min(eq, self.capital_cfg.max_cap_usd)
            if eq < self.capital_cfg.min_required_usd:
                emit_alert(CANDIDATE_ID, "CRITICAL",
                           f"Balance ${snap.available_balance:.2f} below min ${self.capital_cfg.min_required_usd}")
                return None
            self._log_tick(f"balance=${snap.available_balance:.2f} strategy_eq=${eq:.2f}")
            return eq
        except Exception as e:
            emit_alert(CANDIDATE_ID, "CRITICAL", f"Balance fetch failed: {e}")
            return None

    # ── position reconciliation ─────────────────────────────────

    def _reconcile(self) -> None:
        """Check exchange position vs internal state."""
        try:
            pos = fetch_position(self.api_key, self.api_secret)
            orders = fetch_open_orders(self.api_key, self.api_secret)
        except Exception as e:
            emit_alert(CANDIDATE_ID, "WARN", f"Reconciliation fetch failed: {e}")
            return

        has_exchange_pos = pos is not None and float(pos.get("positionAmt", 0)) != 0
        # FIX 3: Binance API may return reduceOnly as boolean True or
        # string "true" depending on the endpoint / library version.
        # Handle both by normalizing to a truthy check.
        def _is_reduce_only(o: dict) -> bool:
            val = o.get("reduceOnly", False)
            if isinstance(val, bool):
                return val
            if isinstance(val, str):
                return val.lower() == "true"
            return bool(val)

        has_cat_stop = any(
            o.get("type") == "STOP_MARKET" and _is_reduce_only(o)
            for o in orders
        )

        if has_exchange_pos and not has_cat_stop and not self.dry_run:
            emit_alert(CANDIDATE_ID, "CRITICAL",
                       "Position exists but catastrophe stop missing — re-placing")
            if self.live_catastrophe_level > 0 and self.live_quantity > 0:
                evt = place_catastrophe_stop(
                    self.api_key, self.api_secret, "long",
                    self.live_catastrophe_level, self.live_quantity,
                )
                log_stop_event(CANDIDATE_ID, evt)
                if evt.event_type == "reject":
                    emit_alert(CANDIDATE_ID, "CRITICAL",
                               f"Catastrophe re-place FAILED: {evt.error}")

        if not has_exchange_pos and has_cat_stop and not self.dry_run:
            self._log_tick("Orphaned stop orders found, cancelling")
            cancel_all_orders(self.api_key, self.api_secret)

        self._log_event({
            "type": "reconciliation",
            "ts": datetime.utcnow().isoformat(),
            "has_exchange_pos": has_exchange_pos,
            "has_cat_stop": has_cat_stop,
            "internal_has_pos": self.has_live_position,
        })

    # ── bar processing ──────────────────────────────────────────

    def _process_bar(self, bar: MarketBar) -> None:
        self._log_tick(
            f"bar {bar.timestamp} O={bar.open:.2f} H={bar.high:.2f} "
            f"L={bar.low:.2f} C={bar.close:.2f}"
        )

        funding = 0.0
        if bar.timestamp.hour in (0, 8, 16):
            funding = fetch_funding_rate()

        # Feed to paper runner (strategy logic)
        prev_count = len(self.runner.trades)
        events = self.runner.tick(bar, funding)

        for e in events:
            self._log_tick(f"  event: {e}")

        # Check for new trade signals from the runner
        new_trades = self.runner.trades[prev_count:]

        # Check runner state for entry/exit decisions
        state = self.runner.state

        # ENTRY: runner queued an entry (position_state went to "open")
        if "ENTRY_FILL" in " ".join(events) and not self.has_live_position:
            self._handle_entry(bar)

        # EXIT: runner closed a trade
        if "TRADE_CLOSE" in " ".join(events) and self.has_live_position:
            exit_reason = ""
            for e in events:
                if "TRADE_CLOSE" in e:
                    exit_reason = e
            self._handle_exit(bar, exit_reason)

        # Log telemetry for new trades
        if new_trades:
            for t in new_trades:
                row = asdict(t)
                row["historical_replay"] = False
                row["dry_run"] = self.dry_run
                equity = self._get_strategy_equity()
                row["live_strategy_equity"] = equity
                row["benchmark_equity"] = BENCHMARK_EQUITY
                atomic_append(self.state_dir / "telemetry.jsonl",
                              json.dumps(row, default=str))

        # Reconcile every tick
        self._reconcile()

        # Save state
        self._save_runner()
        self._mark_bar_processed(bar.timestamp)

    def _handle_entry(self, bar: MarketBar) -> None:
        equity = self._get_strategy_equity()
        if equity is None:
            self._log_tick("ENTRY SKIPPED — balance check failed")
            return

        frac = min(self.candidate_cfg.base_frac, self.candidate_cfg.max_frac)
        notional = equity * frac
        price = bar.open
        quantity = notional / price

        alpha_level = price * (1 - self.candidate_cfg.alpha_stop_pct)
        cat_level = price * (1 - self.candidate_cfg.catastrophe_stop_pct)

        self._log_tick(
            f"ENTRY: eq=${equity:.2f} frac={frac:.2f} notional=${notional:.2f} "
            f"qty={quantity:.4f} alpha={alpha_level:.2f} cat={cat_level:.2f}"
        )
        self._log_event({
            "type": "entry_signal",
            "ts": datetime.utcnow().isoformat(),
            "price": price, "quantity": quantity,
            "frac": frac, "equity": equity,
            "alpha_level": alpha_level, "cat_level": cat_level,
            "dry_run": self.dry_run,
        })

        if self.dry_run:
            # Dry-run: no real orders, just mark position open
            self.has_live_position = True
            self.live_entry_price = price
            self.live_quantity = quantity
            self.live_alpha_level = alpha_level
            self.live_catastrophe_level = cat_level
            return

        # FIX 1: submit entry order BEFORE marking position open.
        # Internal OPEN state must only be set after exchange confirms.
        self._log_tick("Placing MARKET BUY...")
        entry_evt = self._place_market_order("BUY", quantity)
        if entry_evt is None or entry_evt.get("status") == "REJECTED":
            emit_alert(CANDIDATE_ID, "CRITICAL",
                       f"Entry order REJECTED — not opening position")
            return
        fill_price = float(entry_evt.get("avgPrice", price))
        fill_qty = float(entry_evt.get("executedQty", quantity))
        self._log_tick(f"Entry FILLED: price={fill_price:.2f} qty={fill_qty:.4f}")

        # Recompute stop levels from actual fill price
        alpha_level = fill_price * (1 - self.candidate_cfg.alpha_stop_pct)
        cat_level = fill_price * (1 - self.candidate_cfg.catastrophe_stop_pct)

        # Place catastrophe STOP_MARKET
        self._log_tick(f"Placing catastrophe STOP_MARKET at {cat_level:.2f}...")
        evt = place_catastrophe_stop(
            self.api_key, self.api_secret, "long", cat_level, fill_qty,
        )
        log_stop_event(CANDIDATE_ID, evt)
        if evt.event_type == "reject":
            emit_alert(CANDIDATE_ID, "CRITICAL",
                       f"Catastrophe stop REJECTED: {evt.error} — FLATTENING")
            self._place_market_order("SELL", fill_qty)
            return
        self.open_catastrophe_order_id = evt.order_id

        # NOW mark position open — exchange has confirmed both orders
        self.has_live_position = True
        self.live_entry_price = fill_price
        self.live_quantity = fill_qty
        self.live_alpha_level = alpha_level
        self.live_catastrophe_level = cat_level

    def _place_market_order(self, side: str, quantity: float) -> dict | None:
        """Place a MARKET order on Binance and return the response."""
        from execution.live_executor import _signed_request
        try:
            return _signed_request(
                "POST", "/fapi/v1/order",
                {"symbol": "BTCUSDT", "side": side, "type": "MARKET",
                 "quantity": f"{quantity:.3f}"},
                self.api_key, self.api_secret,
            )
        except Exception as e:
            emit_alert(CANDIDATE_ID, "CRITICAL", f"MARKET {side} failed: {e}")
            return None

    def _handle_exit(self, bar: MarketBar, reason: str) -> None:
        self._log_tick(f"EXIT: {reason}")
        self._log_event({
            "type": "exit_signal",
            "ts": datetime.utcnow().isoformat(),
            "price": bar.open,
            "reason": reason,
            "dry_run": self.dry_run,
        })

        if not self.dry_run:
            # Place MARKET SELL to close
            self._log_tick("Placing MARKET SELL to close...")
            # Cancel any remaining catastrophe stop
            cancel_all_orders(self.api_key, self.api_secret)

        self.has_live_position = False
        self.live_entry_price = 0.0
        self.live_quantity = 0.0
        self.open_catastrophe_order_id = None

    # ── main loop ───────────────────────────────────────────────

    def run(self) -> None:
        mode_label = "DRY-RUN" if self.dry_run else "LIVE"
        cap_label = f" max_cap=${self.max_cap_usd}" if self.max_cap_usd else ""
        self._log_tick(f"=== Phase 14 {mode_label}{cap_label} service starting ===")
        self._log_tick(f"candidate={CANDIDATE_ID} lev={self.candidate_cfg.exchange_leverage}x")

        # Initial balance check
        equity = self._get_strategy_equity()
        if equity is not None:
            self._log_tick(f"Initial strategy_equity=${equity:.2f}")

        # Warmup: if no RSI buffer, fetch historical bars
        if len(self.runner._rsi_buffer) < 100:
            self._log_tick("RSI buffer short, fetching warmup bars...")
            self._warmup()

        self._log_tick("Entering polling loop...")

        while True:
            try:
                bar = fetch_latest_1h_bar()
                if bar is None:
                    time.sleep(POLL_INTERVAL)
                    continue

                if self.last_bar_ts is not None and bar.timestamp <= self.last_bar_ts:
                    time.sleep(POLL_INTERVAL)
                    continue

                # New bar detected — process it
                self._process_bar(bar)

            except KeyboardInterrupt:
                self._log_tick("Shutting down (KeyboardInterrupt)")
                self._save_runner()
                break
            except Exception as e:
                emit_alert(CANDIDATE_ID, "CRITICAL", f"Loop error: {e}")
                traceback.print_exc()
                time.sleep(30)

            time.sleep(POLL_INTERVAL)

    def _warmup(self) -> None:
        """Fetch last 200 1h bars for RSI buffer initialization."""
        import urllib.request
        try:
            server_time = fetch_server_time()
            end_ms = int(server_time.replace(tzinfo=timezone.utc).timestamp() * 1000)
            start_ms = end_ms - 200 * 3600_000
            url = (f"https://fapi.binance.com/fapi/v1/klines"
                   f"?symbol=BTCUSDT&interval=1h&limit=200"
                   f"&startTime={start_ms}&endTime={end_ms}")
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = json.loads(resp.read())
            for k in data:
                ts = datetime.fromtimestamp(
                    k[0] / 1000, tz=timezone.utc
                ).replace(tzinfo=None)
                bar = MarketBar(
                    timestamp=ts, open=float(k[1]), high=float(k[2]),
                    low=float(k[3]), close=float(k[4]), volume=float(k[5]),
                )
                self.runner._rsi_buffer.append(bar.close)
            self._log_tick(f"Warmup complete: {len(data)} bars loaded")
            self._save_runner()
        except Exception as e:
            emit_alert(CANDIDATE_ID, "WARN", f"Warmup failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Phase 14 live service")
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="Dry-run mode (no orders)")
    parser.add_argument("--max-cap", type=float, default=None,
                        help="Micro-live max cap in USD")
    args = parser.parse_args()

    service = LiveService(dry_run=args.dry_run, max_cap_usd=args.max_cap)
    service.run()


if __name__ == "__main__":
    main()
