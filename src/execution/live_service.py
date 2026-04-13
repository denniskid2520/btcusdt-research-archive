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
import uuid
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
    sync_server_time_offset,
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

        # Restore persisted live-position fields from state.json
        self.has_live_position = False
        self.live_entry_price: float = 0.0
        self.live_quantity: float = 0.0
        self.live_alpha_level: float = 0.0
        self.live_catastrophe_level: float = 0.0
        self.open_catastrophe_order_id: str | None = None
        # HALT state: position_unknown means we can't confirm whether
        # a position exists. No new entries allowed until reconciliation
        # confirms zero position on the exchange.
        self.halted: bool = False
        self.halt_reason: str = ""
        self._order_in_progress: bool = False  # P0-5: reentrancy guard
        self._restore_live_position_state()
        # P2 FIX: after restoring state, if halted, run a reconciliation
        # immediately so the halt can be cleared BEFORE the first bar
        # is processed. Otherwise the first ENTRY_FILL after restart
        # would be blocked even if the exchange is already flat.
        if self.halted and not self.dry_run and self.api_key:
            self._log_tick("Halted on startup — running immediate reconciliation...")
            try:
                self._reconcile()
            except Exception as e:
                emit_alert(CANDIDATE_ID, "WARN",
                           f"Startup reconciliation failed: {e}")

    def _restore_live_position_state(self) -> None:
        """Restore live-position fields from state.json, then cross-check
        against exchange state.

        CODEX FIX 3: if state.json says has_live_position=True but the
        exchange shows no position (e.g., catastrophe stop triggered while
        service was down), clear the flag so new entries aren't blocked.
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
            self.halted = saved.get("halted", False)
            self.halt_reason = saved.get("halt_reason", "")
        except Exception as e:
            emit_alert(CANDIDATE_ID, "WARN", f"Failed to restore live position: {e}")
            return

        if self.halted:
            self._log_tick(
                f"HALTED state restored: {self.halt_reason}")

        if not self.has_live_position:
            return

        self._log_tick(
            f"Restored live position: entry={self.live_entry_price:.2f} "
            f"qty={self.live_quantity:.4f}"
        )

        # Cross-check with exchange — don't blindly trust state.json
        if not self.dry_run and self.api_key:
            try:
                exchange_pos = fetch_position(self.api_key, self.api_secret)
                has_exchange_pos = (
                    exchange_pos is not None
                    and float(exchange_pos.get("positionAmt", 0)) != 0
                )
                if not has_exchange_pos:
                    self._log_tick(
                        "WARN: state.json says position open but exchange "
                        "shows flat — clearing internal position flag"
                    )
                    emit_alert(CANDIDATE_ID, "WARN",
                               "Position closed while service was down "
                               "(likely catastrophe stop triggered). "
                               "Clearing internal position flag.")
                    self.has_live_position = False
                    self.live_entry_price = 0.0
                    self.live_quantity = 0.0
                    self.open_catastrophe_order_id = None
                    self._save_runner()
                else:
                    self._log_tick("Exchange confirms position still open")
            except Exception as e:
                emit_alert(CANDIDATE_ID, "WARN",
                           f"Could not verify position on startup: {e}. "
                           f"Trusting state.json.")

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
                # Persist ALL live-position fields for restart recovery
                "has_live_position": self.has_live_position,
                "live_entry_price": self.live_entry_price,
                "live_quantity": self.live_quantity,
                "live_alpha_level": self.live_alpha_level,
                "live_catastrophe_level": self.live_catastrophe_level,
                "open_catastrophe_order_id": self.open_catastrophe_order_id,
                "halted": self.halted,
                "halt_reason": self.halt_reason,
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
                    # P0-4 FIX: if re-place fails, HALT — naked position
                    # is too dangerous to continue trading with.
                    emit_alert(CANDIDATE_ID, "CRITICAL",
                               f"Catastrophe re-place FAILED: {evt.error} "
                               f"— HALTING, position unprotected")
                    self.halted = True
                    self.halt_reason = (
                        f"catastrophe_replace_failed: {evt.error}"
                    )
                    self._save_runner()
            else:
                # P0-4: no stop level/qty to re-place → halt
                emit_alert(CANDIDATE_ID, "CRITICAL",
                           "Position exists, catastrophe stop missing, "
                           "but no stop level/qty to re-place — HALTING")
                self.halted = True
                self.halt_reason = "catastrophe_missing_no_replace_data"
                self._save_runner()

        if not has_exchange_pos and has_cat_stop and not self.dry_run:
            self._log_tick("Orphaned stop orders found, cancelling")
            cr = cancel_all_orders(self.api_key, self.api_secret)
            if not cr.get("ok"):
                emit_alert(CANDIDATE_ID, "WARN",
                           f"Orphan stop cancel failed: {cr.get('error')}")

        # If halted due to position_unknown, check if exchange now
        # confirms zero → clear halt and allow new entries.
        if self.halted and not has_exchange_pos:
            self._log_tick(
                "HALT cleared: exchange confirms zero position. "
                f"Previous halt reason: {self.halt_reason}")
            emit_alert(CANDIDATE_ID, "WARN",
                       "HALT cleared by reconciliation — "
                       "exchange confirmed zero position")
            self.halted = False
            self.halt_reason = ""
            self.has_live_position = False
            self.live_entry_price = 0.0
            self.live_quantity = 0.0
            self._save_runner()

        self._log_event({
            "type": "reconciliation",
            "ts": datetime.utcnow().isoformat(),
            "has_exchange_pos": has_exchange_pos,
            "has_cat_stop": has_cat_stop,
            "internal_has_pos": self.has_live_position,
            "halted": self.halted,
        })

    # ── bar processing ──────────────────────────────────────────

    def _process_bar(
        self, bar: MarketBar, *, replay_only: bool = False,
    ) -> None:
        """Process one completed 1h bar.

        Args:
            bar: the completed bar to process.
            replay_only: if True, update internal strategy state but
                do NOT place live orders. Used during missed-bar
                catch-up to avoid executing stale signals on the
                exchange. The paper runner still ticks normally so
                regime/RSI/position state stays consistent.
        """
        label = "[REPLAY] " if replay_only else ""
        self._log_tick(
            f"{label}bar {bar.timestamp} O={bar.open:.2f} H={bar.high:.2f} "
            f"L={bar.low:.2f} C={bar.close:.2f}"
        )

        funding = 0.0
        if bar.timestamp.hour in (0, 8, 16):
            funding = fetch_funding_rate()

        # Feed to paper runner (strategy logic — always runs)
        prev_count = len(self.runner.trades)
        events = self.runner.tick(bar, funding)

        for e in events:
            self._log_tick(f"  {label}event: {e}")

        new_trades = self.runner.trades[prev_count:]
        state = self.runner.state

        if replay_only:
            # ASYMMETRIC REPLAY: entries always skipped, exits execute
            # if a real live position is open (to close real risk).
            if "ENTRY_FILL" in " ".join(events):
                self._log_tick(
                    "  [REPLAY] entry signal SKIPPED (stale bar)")
            if "TRADE_CLOSE" in " ".join(events):
                if self.has_live_position:
                    self._log_tick(
                        "  [REPLAY] exit signal EXECUTING "
                        "(live position open — must close real risk)")
                    exit_reason = next(
                        (e for e in events if "TRADE_CLOSE" in e), "")
                    self._handle_exit(bar, exit_reason)
                else:
                    self._log_tick(
                        "  [REPLAY] exit signal skipped (no live position)")
        else:
            # Live bar: execute signals normally
            if "ENTRY_FILL" in " ".join(events) and not self.has_live_position:
                if self.halted:
                    self._log_tick(
                        f"ENTRY BLOCKED — system halted: {self.halt_reason}")
                else:
                    self._handle_entry(bar)

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
        # P0-5: reentrancy guard — prevent duplicate entry from
        # exception-retry or duplicate event
        if self._order_in_progress:
            self._log_tick("ENTRY SKIPPED — order already in progress")
            return
        self._order_in_progress = True
        try:
            self._handle_entry_inner(bar)
        finally:
            self._order_in_progress = False

    def _handle_entry_inner(self, bar: MarketBar) -> None:
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

        # Submit entry order BEFORE marking position open.
        # Internal OPEN state must only be set after exchange confirms FILLED.
        # Use newClientOrderId for idempotent retry: if the request times
        # out, we can query by this ID to resolve "placed or not".
        client_oid = f"entry_{uuid.uuid4().hex[:16]}"
        self._log_tick(f"Placing MARKET BUY (clientOrderId={client_oid})...")
        entry_evt = self._place_market_order("BUY", quantity, client_order_id=client_oid)

        # If entry_evt is None (timeout/exception), query by clientOrderId
        # to check if the order actually went through before giving up.
        if entry_evt is None:
            self._log_tick("Entry returned None — querying by clientOrderId...")
            entry_evt = self._query_order_by_client_id(client_oid)
            if entry_evt is not None:
                self._log_tick(
                    f"Order found via query: status={entry_evt.get('status')}")
            else:
                # Also check if position appeared on exchange
                try:
                    pos = fetch_position(self.api_key, self.api_secret)
                    pos_amt = float(pos.get("positionAmt", 0)) if pos else 0
                    if abs(pos_amt) > 0.0001:
                        # Prefer exchange entryPrice over bar.open
                        # for more accurate stop level derivation.
                        entry_px = float(pos.get("entryPrice", 0))
                        if entry_px <= 0:
                            entry_px = price  # fallback to bar.open
                        emit_alert(CANDIDATE_ID, "CRITICAL",
                                   f"Entry order unknown but exchange has "
                                   f"position {pos_amt} @ {entry_px:.2f} — HALTING")
                        self.halted = True
                        self.halt_reason = (
                            f"entry_unknown_but_position_exists: {pos_amt}")
                        self.has_live_position = True
                        self.live_quantity = abs(pos_amt)
                        self.live_entry_price = entry_px
                        # CODEX P1: persist stop levels so _reconcile()
                        # can re-place catastrophe stop automatically.
                        self.live_alpha_level = entry_px * (
                            1 - self.candidate_cfg.alpha_stop_pct)
                        self.live_catastrophe_level = entry_px * (
                            1 - self.candidate_cfg.catastrophe_stop_pct)
                        self._save_runner()
                        return
                except Exception:
                    pass

        # CODEX FIX 1: require explicit FILLED status, not just "not REJECTED".
        # A NEW or PARTIALLY_FILLED response means the order isn't done yet —
        # we must not derive fill_price/fill_qty from incomplete data.
        if entry_evt is None:
            emit_alert(CANDIDATE_ID, "CRITICAL",
                       "Entry order returned None — not opening position")
            return
        entry_status = entry_evt.get("status", "UNKNOWN")
        if entry_status != "FILLED":
            # Cancel remaining open quantity first
            cr = cancel_all_orders(self.api_key, self.api_secret)
            if not cr.get("ok"):
                emit_alert(CANDIDATE_ID, "WARN",
                           f"Entry cancel failed: {cr.get('error')}")

            # CODEX FIX: if PARTIALLY_FILLED with executedQty > 0, the
            # already-filled portion is a real position on the exchange.
            # We must flatten it and confirm zero before returning FLAT.
            partial_qty = float(entry_evt.get("executedQty", 0))
            if partial_qty > 0:
                emit_alert(CANDIDATE_ID, "CRITICAL",
                           f"Entry {entry_status} with executedQty={partial_qty} "
                           f"— cancelling remainder and flattening filled qty")
                flatten_evt = self._place_market_order("SELL", partial_qty)
                flatten_ok = (
                    flatten_evt is not None
                    and flatten_evt.get("status") == "FILLED"
                )
                if flatten_ok:
                    # Verify exchange position is actually zero.
                    # If verification FAILS (API error), we CANNOT assume
                    # flat — position state is UNKNOWN → HALT.
                    try:
                        pos = fetch_position(self.api_key, self.api_secret)
                        pos_amt = float(pos.get("positionAmt", 0)) if pos else 0
                        if abs(pos_amt) > 0.0001:
                            emit_alert(CANDIDATE_ID, "CRITICAL",
                                       f"Flatten sent but position still "
                                       f"{pos_amt} — HALT, manual intervention")
                            self.has_live_position = True
                            self.live_entry_price = float(
                                entry_evt.get("avgPrice", price))
                            self.live_quantity = abs(pos_amt)
                            self._save_runner()
                            return
                        self._log_tick(
                            "Partial fill flattened and confirmed zero")
                    except Exception as e:
                        # CODEX FIX: verification failure = position_unknown.
                        # Must HALT — do NOT assume flat.
                        emit_alert(CANDIDATE_ID, "CRITICAL",
                                   f"Post-flatten position verification FAILED: "
                                   f"{e} — HALTING, position state unknown")
                        self.halted = True
                        self.halt_reason = (
                            f"position_unknown: flatten reported FILLED but "
                            f"fetch_position failed: {e}"
                        )
                        self.has_live_position = True
                        self.live_entry_price = float(
                            entry_evt.get("avgPrice", price))
                        self.live_quantity = partial_qty
                        self._save_runner()
                        return
                else:
                    # Flatten failed — naked partial position
                    emit_alert(CANDIDATE_ID, "CRITICAL",
                               f"PARTIAL FILL FLATTEN FAILED — "
                               f"executedQty={partial_qty} still on exchange, "
                               f"HALT, manual intervention required")
                    self.has_live_position = True
                    self.live_entry_price = float(
                        entry_evt.get("avgPrice", price))
                    self.live_quantity = partial_qty
                    self._save_runner()
                    return
            else:
                emit_alert(CANDIDATE_ID, "CRITICAL",
                           f"Entry order status={entry_status} with zero qty "
                           f"— cancelled, staying flat")
            return

        fill_price = float(entry_evt.get("avgPrice", price))
        fill_qty = float(entry_evt.get("executedQty", quantity))
        if fill_qty <= 0:
            emit_alert(CANDIDATE_ID, "CRITICAL",
                       f"Entry FILLED but executedQty={fill_qty} — aborting")
            return
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
            # CODEX FIX 2: verify emergency flatten succeeds.
            # If SELL also fails, mark position as live so reconciliation
            # can detect and handle the naked position.
            emit_alert(CANDIDATE_ID, "CRITICAL",
                       f"Catastrophe stop REJECTED: {evt.error} — FLATTENING")
            flatten_evt = self._place_market_order("SELL", fill_qty)
            flatten_ok = (
                flatten_evt is not None
                and flatten_evt.get("status") == "FILLED"
            )
            if not flatten_ok:
                # Flatten failed — we have a NAKED LIVE POSITION.
                # Mark it as open so _reconcile() can detect and re-attempt.
                emit_alert(CANDIDATE_ID, "CRITICAL",
                           "EMERGENCY FLATTEN FAILED — naked position, "
                           "manual intervention required")
                self.has_live_position = True
                self.live_entry_price = fill_price
                self.live_quantity = fill_qty
                self.live_alpha_level = alpha_level
                self.live_catastrophe_level = cat_level
                self._save_runner()
            return
        self.open_catastrophe_order_id = evt.order_id

        # NOW mark position open — exchange has confirmed both orders
        self.has_live_position = True
        self.live_entry_price = fill_price
        self.live_quantity = fill_qty
        self.live_alpha_level = alpha_level
        self.live_catastrophe_level = cat_level

    def _place_market_order(
        self, side: str, quantity: float,
        client_order_id: str | None = None,
    ) -> dict | None:
        """Place a MARKET order on Binance and return the response.

        Uses newOrderRespType=RESULT so the response includes
        status=FILLED, executedQty, and avgPrice for MARKET orders.
        Without this, Binance may return status=NEW with no fill data.

        If client_order_id is provided, it's sent as newClientOrderId
        for idempotent retry: on timeout, we can query by this ID to
        check if the order actually went through.
        """
        from execution.live_executor import _signed_request
        params: dict = {
            "symbol": "BTCUSDT", "side": side, "type": "MARKET",
            "quantity": f"{quantity:.3f}",
            "newOrderRespType": "RESULT",
        }
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        try:
            return _signed_request(
                "POST", "/fapi/v1/order", params,
                self.api_key, self.api_secret,
            )
        except Exception as e:
            emit_alert(CANDIDATE_ID, "CRITICAL", f"MARKET {side} failed: {e}")
            return None

    def _place_reduce_only_order(self, side: str, quantity: float) -> dict | None:
        """Place a MARKET order with reduceOnly=true.

        Uses newOrderRespType=RESULT for reliable fill data.
        If the position was already closed (e.g., by catastrophe stop),
        Binance will EXPIRE or REJECT the reduceOnly order instead of
        opening a new opposite position.

        Binance error -2022 ('ReduceOnly Order is rejected') comes as an
        API exception, not as order status=REJECTED. We detect this and
        return a synthetic REJECTED response so the caller can handle it
        the same way (verify exchange, clear if flat, else HALT).
        """
        from execution.live_executor import _signed_request
        try:
            return _signed_request(
                "POST", "/fapi/v1/order",
                {"symbol": "BTCUSDT", "side": side, "type": "MARKET",
                 "quantity": f"{quantity:.3f}", "reduceOnly": "true",
                 "newOrderRespType": "RESULT"},
                self.api_key, self.api_secret,
            )
        except Exception as e:
            err_str = str(e)
            # Binance -2022: 'ReduceOnly Order is rejected' — position
            # was already closed. Return synthetic REJECTED so caller
            # can verify exchange and clear if flat (avoids unnecessary HALT).
            if "-2022" in err_str:
                emit_alert(CANDIDATE_ID, "WARN",
                           f"reduceOnly {side} got -2022 (no position to reduce): {e}")
                return {"status": "REJECTED", "code": -2022,
                        "msg": "ReduceOnly Order is rejected"}
            emit_alert(CANDIDATE_ID, "CRITICAL",
                       f"MARKET {side} (reduceOnly) failed: {e}")
            self._last_reduce_only_error = err_str
            return None

    def _query_order_by_client_id(self, client_order_id: str) -> dict | None:
        """Query an order by newClientOrderId to resolve 'placed or not'.

        Used for idempotent retry: when _place_market_order returns None
        (timeout), we query to check if the order actually went through.
        Returns the order dict if found, None if not found or error.
        """
        from execution.live_executor import _signed_request
        try:
            return _signed_request(
                "GET", "/fapi/v1/order",
                {"symbol": "BTCUSDT",
                 "origClientOrderId": client_order_id},
                self.api_key, self.api_secret,
            )
        except Exception as e:
            self._log_tick(f"Query by clientOrderId failed: {e}")
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

        if self.dry_run:
            self.has_live_position = False
            self.live_entry_price = 0.0
            self.live_quantity = 0.0
            self.open_catastrophe_order_id = None
            return

        # Send reduceOnly SELL first. Do NOT cancel catastrophe stop yet —
        # if the SELL fails, the catastrophe stop is our last line of defense.
        self._log_tick(f"Placing MARKET SELL (reduceOnly) qty={self.live_quantity:.4f}...")
        exit_evt = self._place_reduce_only_order("SELL", self.live_quantity)

        exit_ok = (
            exit_evt is not None
            and exit_evt.get("status") == "FILLED"
        )

        if exit_ok:
            fill_price = float(exit_evt.get("avgPrice", bar.open))
            fill_qty = float(exit_evt.get("executedQty", 0))
            self._log_tick(f"Exit FILLED: price={fill_price:.2f} qty={fill_qty:.4f}")

            # NOW cancel catastrophe stop — SELL is confirmed FILLED,
            # so position is closed and the stop is orphaned.
            cancel_result = cancel_all_orders(self.api_key, self.api_secret)
            if not cancel_result.get("ok"):
                emit_alert(CANDIDATE_ID, "WARN",
                           f"cancel_all_orders after FILLED exit failed: "
                           f"{cancel_result.get('error')}")

            # Verify exchange position is zero after exit.
            # Retry with bounded backoff — a single timeout should not
            # cause us to assume flat when exposure could be real.
            verify_ok = False
            for attempt in range(3):
                try:
                    pos = fetch_position(self.api_key, self.api_secret)
                    pos_amt = float(pos.get("positionAmt", 0)) if pos else 0
                    if abs(pos_amt) > 0.0001:
                        emit_alert(CANDIDATE_ID, "CRITICAL",
                                   f"Exit FILLED but position still {pos_amt} — "
                                   f"HALTING for manual review")
                        self.halted = True
                        self.halt_reason = f"exit_residual_position: {pos_amt}"
                        self.live_quantity = abs(pos_amt)
                        self._save_runner()
                        return
                    verify_ok = True
                    break
                except Exception as e:
                    emit_alert(CANDIDATE_ID, "WARN",
                               f"Post-exit position verify attempt "
                               f"{attempt + 1}/3 failed: {e}")
                    if attempt < 2:
                        time.sleep(1 + attempt)  # 1s, 2s backoff
            if not verify_ok:
                # All retries failed — can't confirm flat, HALT
                emit_alert(CANDIDATE_ID, "CRITICAL",
                           "Post-exit position verify failed after 3 retries "
                           "— HALTING, position state unknown")
                self.halted = True
                self.halt_reason = "exit_verify_failed: fetch_position 3x timeout"
                self._save_runner()
                return

            self.has_live_position = False
            self.live_entry_price = 0.0
            self.live_quantity = 0.0
            self.open_catastrophe_order_id = None

        elif exit_evt is not None and exit_evt.get("status") in ("EXPIRED", "REJECTED"):
            # reduceOnly SELL expired/rejected = position was already closed
            # (catastrophe stop likely triggered before our SELL).
            # Also handle REJECTED with error code -2022 (reduceOnly no position).
            self._log_tick(
                f"Exit SELL {exit_evt.get('status')} (reduceOnly) — "
                f"position may already be closed")
            try:
                pos = fetch_position(self.api_key, self.api_secret)
                pos_amt = float(pos.get("positionAmt", 0)) if pos else 0
                if abs(pos_amt) < 0.0001:
                    self._log_tick("Confirmed flat after EXPIRED/REJECTED SELL")
                    # Cancel orphaned stop orders if any — check result
                    cr = cancel_all_orders(self.api_key, self.api_secret)
                    if not cr.get("ok"):
                        emit_alert(CANDIDATE_ID, "WARN",
                                   f"Orphan stop cancel failed after "
                                   f"EXPIRED/REJECTED flat: {cr.get('error')}")
                    self.has_live_position = False
                    self.live_entry_price = 0.0
                    self.live_quantity = 0.0
                    self.open_catastrophe_order_id = None
                    return
            except Exception:
                pass
            # Can't confirm flat — halt. DO NOT cancel catastrophe stop
            # (it may be the only protection left).
            emit_alert(CANDIDATE_ID, "CRITICAL",
                       f"Exit SELL {exit_evt.get('status')} but cannot "
                       f"confirm flat — HALTING (catastrophe stop preserved)")
            self.halted = True
            self.halt_reason = f"exit_sell_{exit_evt.get('status','unknown')}_unverified"
            self._save_runner()

        else:
            # Exit failed — position may still be open on exchange.
            # DO NOT cancel catastrophe stop — it's the last protection.
            status = exit_evt.get("status", "None") if exit_evt else "None"
            emit_alert(CANDIDATE_ID, "CRITICAL",
                       f"Exit SELL failed (status={status}) — "
                       f"position may still be open, HALTING "
                       f"(catastrophe stop preserved)")
            self.halted = True
            self.halt_reason = f"exit_sell_failed: status={status}"
            self._save_runner()

    # ── main loop ───────────────────────────────────────────────

    def run(self) -> None:
        mode_label = "DRY-RUN" if self.dry_run else "LIVE"
        cap_label = f" max_cap=${self.max_cap_usd}" if self.max_cap_usd else ""
        self._log_tick(f"=== Phase 14 {mode_label}{cap_label} service starting ===")
        self._log_tick(f"candidate={CANDIDATE_ID} lev={self.candidate_cfg.exchange_leverage}x")

        # Sync server-time offset for accurate timestamps
        offset = sync_server_time_offset()
        self._log_tick(f"Server-time offset: {offset}ms")

        # Initial balance check
        equity = self._get_strategy_equity()
        if equity is not None:
            self._log_tick(f"Initial strategy_equity=${equity:.2f}")

        # Warmup: if no RSI buffer, fetch historical bars
        if len(self.runner._rsi_buffer) < 100:
            self._log_tick("RSI buffer short, fetching warmup bars...")
            self._warmup()

        # Missed-bar catch-up on startup (replay_only — no live orders).
        if not self._catch_up_missed_bars():
            self._log_tick("WARN: startup catch-up failed, will retry in loop")

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

                # CODEX FIX: if there's a gap, catch up first.
                # Only process the newest bar if catch-up succeeds.
                # If catch-up fails, skip this tick entirely — do NOT
                # process the latest bar with intermediate bars missing.
                if self.last_bar_ts is not None:
                    expected_next = self.last_bar_ts + timedelta(hours=1)
                    if bar.timestamp > expected_next:
                        self._log_tick(
                            f"Gap detected: last={self.last_bar_ts} "
                            f"current={bar.timestamp} — catching up")
                        if not self._catch_up_missed_bars():
                            self._log_tick(
                                "Catch-up FAILED — skipping this tick, "
                                "will retry next poll")
                            time.sleep(POLL_INTERVAL)
                            continue

                # Process the current bar (live — may place orders)
                if self.last_bar_ts is None or bar.timestamp > self.last_bar_ts:
                    self._process_bar(bar)  # replay_only=False (default)

            except KeyboardInterrupt:
                self._log_tick("Shutting down (KeyboardInterrupt)")
                self._save_runner()
                break
            except Exception as e:
                emit_alert(CANDIDATE_ID, "CRITICAL", f"Loop error: {e}")
                traceback.print_exc()
                time.sleep(30)

            time.sleep(POLL_INTERVAL)

    def _catch_up_missed_bars(self) -> bool:
        """Fetch and replay all completed bars since last_processed_ts.

        Returns True if catch-up succeeded (or no catch-up needed).
        Returns False if catch-up failed (fetch error, etc.).
        Caller must NOT process the latest bar if this returns False.
        """
        if self.last_bar_ts is None:
            return True
        try:
            server_time = fetch_server_time()
        except Exception:
            return False
        last_completed = server_time.replace(
            minute=0, second=0, microsecond=0
        ) - timedelta(hours=1)

        if last_completed <= self.last_bar_ts:
            return True  # already up to date

        fetch_start = self.last_bar_ts + timedelta(hours=1)
        missed_count = int(
            (last_completed - self.last_bar_ts).total_seconds() / 3600
        )
        if missed_count <= 0:
            return True

        self._log_tick(
            f"Catching up {missed_count} missed bars: "
            f"{fetch_start} to {last_completed}")
        if missed_count > 1:
            emit_alert(CANDIDATE_ID, "WARN",
                       f"Catching up {missed_count} missed bars after downtime")

        # Fetch all missed bars from Binance
        import urllib.request
        start_ms = int(
            fetch_start.replace(tzinfo=timezone.utc).timestamp() * 1000
        )
        end_ms = int(
            last_completed.replace(tzinfo=timezone.utc).timestamp() * 1000
        )
        url = (f"https://fapi.binance.com/fapi/v1/klines"
               f"?symbol=BTCUSDT&interval=1h&limit=1500"
               f"&startTime={start_ms}&endTime={end_ms}")
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            emit_alert(CANDIDATE_ID, "WARN", f"Catch-up fetch failed: {e}")
            return False

        for k in data:
            ts = datetime.fromtimestamp(
                k[0] / 1000, tz=timezone.utc
            ).replace(tzinfo=None)
            if ts <= self.last_bar_ts:
                continue
            bar = MarketBar(
                timestamp=ts, open=float(k[1]), high=float(k[2]),
                low=float(k[3]), close=float(k[4]), volume=float(k[5]),
            )
            # CODEX FIX: replay_only=True — do NOT place live orders
            # for stale bars. Only update internal strategy state.
            self._process_bar(bar, replay_only=True)

        self._log_tick(f"Catch-up complete, now at {self.last_bar_ts}")

        # Post-catch-up reconciliation: if the runner thinks we're flat
        # but exchange still has a position, something is wrong.
        if not self.dry_run and self.api_key:
            runner_flat = (
                self.runner.state.position_state != "open"
                and not self.has_live_position
            )
            try:
                pos = fetch_position(self.api_key, self.api_secret)
                exchange_has_pos = (
                    pos is not None
                    and float(pos.get("positionAmt", 0)) != 0
                )
            except Exception as e:
                emit_alert(CANDIDATE_ID, "WARN",
                           f"Post-catch-up position check failed: {e}")
                exchange_has_pos = False  # can't verify, proceed cautiously

            if runner_flat and exchange_has_pos:
                pos_amt = float(pos.get("positionAmt", 0)) if pos else 0
                emit_alert(CANDIDATE_ID, "CRITICAL",
                           f"Post-catch-up mismatch: runner is flat but "
                           f"exchange has position {pos_amt} — HALTING")
                self.halted = True
                self.halt_reason = (
                    f"post_catchup_mismatch: runner flat but "
                    f"exchange position={pos_amt}"
                )
                self.has_live_position = True
                self.live_quantity = abs(pos_amt)
                self._save_runner()

        return True

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
