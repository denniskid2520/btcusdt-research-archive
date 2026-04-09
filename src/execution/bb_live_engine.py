"""Live paper trading engine for Strategy D — BB Swing (USDT-M).

Fetches Binance native 1d bars, calculates BB(20,2.5) + MA200,
checks entry/exit signals on 4h bars, and manages paper positions.
State persisted to JSON.

Run via: PYTHONPATH=src python run_paper_d.py --once
"""
from __future__ import annotations

import json
import logging
import statistics
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from adapters.binance_futures import BinanceFuturesAdapter
from research.bb_swing_backtest import (
    BBConfig,
    calculate_atr,
    calculate_bb,
    calculate_sma,
)


LOGGER = logging.getLogger("bb_live_engine")


# ── Config ──

@dataclass
class BBLiveConfig:
    symbol: str = "BTCUSDT"
    leverage: int = 5
    initial_usdt: float = 10000.0
    fee_rate: float = 0.001
    # BB strategy params
    bb_period: int = 20
    bb_k: float = 2.5
    band_touch_pct: float = 0.01
    stop_loss_pct: float = 0.03
    risk_per_trade: float = 0.065
    max_margin_pct: float = 0.90
    use_ma200: bool = True
    use_trailing_stop: bool = True
    trailing_activation_pct: float = 0.03
    trailing_atr_multiplier: float = 1.5
    max_hold_bars: int = 180  # 30 days * 6 bars/day
    cooldown_days: int = 1
    min_band_width_pct: float = 3.0
    max_band_width_pct: float = 30.0


# ── Persistent State ──

@dataclass
class BBLiveState:
    usdt_balance: float = 10000.0
    # Position
    position_side: str = "flat"
    position_qty: float = 0.0
    entry_price: float = 0.0
    entry_time: str = ""
    entry_bar_count: int = 0
    best_price: float = 0.0
    max_profit_pct: float = 0.0
    # BB at entry
    bb_upper: float = 0.0
    bb_middle: float = 0.0
    bb_lower: float = 0.0
    bb_width_pct: float = 0.0
    # Trade log
    trades: list[dict] = field(default_factory=list)
    # Last processed candle
    last_candle_ts: str = ""
    bars_since_entry: int = 0
    last_exit_ts: str = ""

    @property
    def is_position_open(self) -> bool:
        return self.position_side != "flat" and self.position_qty > 0

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: Path) -> "BBLiveState":
        if not path.exists():
            return cls()
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (json.JSONDecodeError, TypeError):
            return cls()


# ── Engine ──

class BBLiveEngine:
    """Paper trading engine for BB Swing Strategy D."""

    def __init__(
        self,
        state_path: Path | None = None,
        config: BBLiveConfig | None = None,
    ) -> None:
        self.cfg = config or BBLiveConfig()
        self.state_path = state_path or Path("state/paper_d_state.json")
        self.state = BBLiveState.load(self.state_path)
        if self.state.usdt_balance == 10000.0 and self.cfg.initial_usdt != 10000.0:
            self.state.usdt_balance = self.cfg.initial_usdt
        self.adapter = BinanceFuturesAdapter()

    def tick(self) -> dict[str, Any]:
        """Single evaluation tick. Call this on each 4h candle."""
        result: dict[str, Any] = {"action": "none", "signal": None}

        # Fetch data
        bars_4h = self.adapter.fetch_ohlcv(self.cfg.symbol, "4h", 30)
        bars_1d = self.adapter.fetch_ohlcv(self.cfg.symbol, "1d", 220)

        if not bars_4h or not bars_1d:
            LOGGER.warning("No bars received")
            return result

        latest_4h = bars_4h[-1]
        latest_ts = latest_4h.timestamp.isoformat()

        # Skip if already processed
        if latest_ts == self.state.last_candle_ts:
            result["action"] = "skip_duplicate"
            return result

        self.state.last_candle_ts = latest_ts
        close = latest_4h.close

        # Calculate indicators from native 1d bars
        daily_closes = [b.close for b in bars_1d]
        bb = calculate_bb(daily_closes, period=self.cfg.bb_period, k=self.cfg.bb_k)
        if bb is None:
            LOGGER.warning("Not enough daily bars for BB")
            self._save()
            return result

        ma200 = calculate_sma(daily_closes, 200) if self.cfg.use_ma200 else None

        # ATR for trailing stop (on 4h bars)
        atr = None
        if self.cfg.use_trailing_stop:
            atr_bars = [{"high": b.high, "low": b.low, "close": b.close} for b in bars_4h[-20:]]
            atr = calculate_atr(atr_bars, period=14)

        # Build diagnostic info
        result["diagnostics"] = {
            "timestamp": latest_ts,
            "price": close,
            "bb_upper": round(bb.upper, 2),
            "bb_middle": round(bb.middle, 2),
            "bb_lower": round(bb.lower, 2),
            "bb_width_pct": round(bb.width_pct, 2),
            "pct_b": round((close - bb.lower) / (bb.upper - bb.lower), 3) if bb.upper != bb.lower else 0.5,
            "ma200": round(ma200, 2) if ma200 else None,
            "price_vs_ma200": "above" if ma200 and close > ma200 else "below",
            "atr_4h": round(atr, 2) if atr else None,
            "balance": round(self.state.usdt_balance, 2),
            "position": self.state.position_side,
        }

        if not self.state.is_position_open:
            result.update(self._check_entry(close, bb, ma200))
        else:
            self.state.bars_since_entry += 1
            result.update(self._check_exit(close, bb, atr))

        self._save()
        return result

    def _check_entry(self, close: float, bb: Any, ma200: float | None) -> dict:
        """Check for new entry signal."""
        # Cooldown check
        if self.state.last_exit_ts:
            from datetime import timedelta
            last_exit = datetime.fromisoformat(self.state.last_exit_ts)
            now = datetime.fromisoformat(self.state.last_candle_ts)
            if (now - last_exit).total_seconds() < self.cfg.cooldown_days * 86400:
                return {"action": "cooldown"}

        # Band width filter
        if bb.width_pct < self.cfg.min_band_width_pct:
            return {"action": "skip_narrow_bands", "bb_width": bb.width_pct}
        if bb.width_pct > self.cfg.max_band_width_pct:
            return {"action": "skip_wide_bands", "bb_width": bb.width_pct}

        # Signal detection
        signal = None
        touch_lower = bb.lower * (1 + self.cfg.band_touch_pct)
        touch_upper = bb.upper * (1 - self.cfg.band_touch_pct)

        if close <= touch_lower:
            signal = "long"
        elif close >= touch_upper:
            signal = "short"

        if signal is None:
            return {"action": "no_signal"}

        # MA200 filter
        if self.cfg.use_ma200 and ma200 is not None:
            if signal == "long" and close < ma200:
                return {"action": "blocked_ma200", "signal": signal, "reason": "price below MA200, long blocked"}
            if signal == "short" and close > ma200:
                return {"action": "blocked_ma200", "signal": signal, "reason": "price above MA200, short blocked"}

        # Position sizing
        qty = self._calc_position_size(close)
        if qty <= 0:
            return {"action": "size_zero"}

        # Execute entry
        self.state.position_side = signal
        self.state.position_qty = qty
        self.state.entry_price = close
        self.state.entry_time = self.state.last_candle_ts
        self.state.bars_since_entry = 0
        self.state.max_profit_pct = 0.0
        self.state.best_price = close
        self.state.bb_upper = bb.upper
        self.state.bb_middle = bb.middle
        self.state.bb_lower = bb.lower
        self.state.bb_width_pct = bb.width_pct

        notional = qty * close
        LOGGER.info("ENTRY %s | %.4f BTC @ $%.0f | notional $%.0f | BB: %.0f/%.0f/%.0f",
                     signal.upper(), qty, close, notional, bb.lower, bb.middle, bb.upper)

        return {
            "action": "entry",
            "signal": signal,
            "qty": qty,
            "price": close,
            "notional": notional,
            "bb_upper": bb.upper,
            "bb_middle": bb.middle,
            "bb_lower": bb.lower,
        }

    def _check_exit(self, close: float, bb: Any, atr: float | None) -> dict:
        """Check exit conditions for open position."""
        side = self.state.position_side
        entry = self.state.entry_price

        # Track profit
        if side == "long":
            pnl_pct = (close / entry) - 1
        else:
            pnl_pct = 1 - (close / entry)
        self.state.max_profit_pct = max(self.state.max_profit_pct, pnl_pct)

        # 1. Stop loss
        if side == "long" and close <= entry * (1 - self.cfg.stop_loss_pct):
            return self._execute_exit(close, "stop_loss")
        if side == "short" and close >= entry * (1 + self.cfg.stop_loss_pct):
            return self._execute_exit(close, "stop_loss")

        # 2. Target: middle band
        if side == "long" and close >= bb.middle:
            return self._execute_exit(close, "target_middle")
        if side == "short" and close <= bb.middle:
            return self._execute_exit(close, "target_middle")

        # 3. Trailing stop
        if (self.cfg.use_trailing_stop and atr and
                self.state.max_profit_pct >= self.cfg.trailing_activation_pct):
            if side == "long":
                peak = entry * (1 + self.state.max_profit_pct)
                trail_level = peak - self.cfg.trailing_atr_multiplier * atr
                if close <= trail_level:
                    return self._execute_exit(close, "trailing_stop")
            else:
                trough = entry * (1 - self.state.max_profit_pct)
                trail_level = trough + self.cfg.trailing_atr_multiplier * atr
                if close >= trail_level:
                    return self._execute_exit(close, "trailing_stop")

        # 4. Time stop
        if self.state.bars_since_entry >= self.cfg.max_hold_bars:
            return self._execute_exit(close, "time_stop")

        return {
            "action": "hold",
            "unrealized_pnl_pct": round(pnl_pct * 100, 2),
            "max_profit_pct": round(self.state.max_profit_pct * 100, 2),
            "bars_held": self.state.bars_since_entry,
        }

    def _execute_exit(self, close: float, reason: str) -> dict:
        """Close position and record trade."""
        side = self.state.position_side
        qty = self.state.position_qty
        entry = self.state.entry_price

        # Linear PnL
        if side == "long":
            gross = qty * (close - entry)
        else:
            gross = qty * (entry - close)
        fees = qty * entry * self.cfg.fee_rate + qty * close * self.cfg.fee_rate
        pnl = gross - fees
        pnl_pct = pnl / self.state.usdt_balance * 100 if self.state.usdt_balance > 0 else 0

        self.state.usdt_balance += pnl
        self.state.usdt_balance = max(self.state.usdt_balance, 1.0)

        trade = {
            "entry_ts": self.state.entry_time,
            "exit_ts": self.state.last_candle_ts,
            "side": side,
            "entry_price": entry,
            "exit_price": close,
            "exit_reason": reason,
            "qty_btc": qty,
            "pnl_usdt": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "bb_upper": self.state.bb_upper,
            "bb_middle": self.state.bb_middle,
            "bb_lower": self.state.bb_lower,
        }
        self.state.trades.append(trade)

        LOGGER.info("EXIT %s %s | %.4f BTC @ $%.0f | PnL $%.0f (%.1f%%) | Balance $%.0f",
                     reason.upper(), side.upper(), qty, close, pnl, pnl_pct, self.state.usdt_balance)

        # Reset position
        self.state.position_side = "flat"
        self.state.position_qty = 0.0
        self.state.entry_price = 0.0
        self.state.bars_since_entry = 0
        self.state.max_profit_pct = 0.0
        self.state.last_exit_ts = self.state.last_candle_ts

        return {
            "action": "exit",
            "reason": reason,
            "pnl_usdt": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "balance": round(self.state.usdt_balance, 2),
            "trade": trade,
        }

    def _calc_position_size(self, price: float) -> float:
        """Risk-based position size in BTC."""
        if self.cfg.stop_loss_pct <= 0 or price <= 0:
            return 0.0
        risk_based = (self.state.usdt_balance * self.cfg.risk_per_trade) / self.cfg.stop_loss_pct / price
        cap = self.state.usdt_balance * self.cfg.max_margin_pct * self.cfg.leverage / price
        return min(risk_based, cap)

    def _save(self) -> None:
        self.state.save(self.state_path)

    def print_status(self) -> None:
        """Print current status to stdout."""
        s = self.state
        print(f"\n{'='*60}")
        print(f"  Strategy D — BB Swing Paper Trading")
        print(f"{'='*60}")
        print(f"  Balance:   ${s.usdt_balance:,.2f} USDT")
        print(f"  Position:  {s.position_side}")
        if s.is_position_open:
            print(f"  Entry:     ${s.entry_price:,.0f} ({s.position_side})")
            print(f"  Qty:       {s.position_qty:.4f} BTC")
            print(f"  Bars held: {s.bars_since_entry}")
        print(f"  Trades:    {len(s.trades)}")
        if s.trades:
            wins = sum(1 for t in s.trades if t["pnl_usdt"] > 0)
            total_pnl = sum(t["pnl_usdt"] for t in s.trades)
            print(f"  Win rate:  {wins}/{len(s.trades)} ({wins/len(s.trades)*100:.0f}%)")
            print(f"  Total PnL: ${total_pnl:+,.2f}")
        print()
