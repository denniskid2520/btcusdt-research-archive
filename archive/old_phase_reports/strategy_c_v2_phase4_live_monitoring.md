# Strategy C v2 — Phase 4 Deliverable: Live Monitoring Design

_Date: 2026-04-12_
_Status: Phase 4 — design-only. No automated re-optimization._

Per the Phase 4 brief:

> Claude has real-time data access, but real-time data should be used for
> live monitoring, execution timing, and risk vetoes — NOT for daily
> re-optimization of the core strategy.

This document describes the design of a live monitoring loop for a
deployed Strategy C v2 candidate. It is intentionally NOT a training
loop — every decision it makes was measurable in the backtest already.

The monitor has been TDD-covered with 16 unit tests in
`tests/test_strategy_c_v2_live_monitor.py` (all green). The
implementation lives in
`src/strategies/strategy_c_v2_live_monitor.py` as a pure
state-machine function with no I/O.

---

## 1. Architecture: pure state-machine, no I/O

```
┌────────────────────────────────────────────────────────────────┐
│                     LIVE RUNNER (external)                     │
│                                                                │
│  1. Fetch latest 4h bar from Binance REST                     │
│  2. Fetch latest funding rate from Binance REST               │
│  3. Fetch last 200 4h bars for RSI(21) computation            │
│  4. Build feature_snapshot object (duck-typed)                 │
│  5. Read open_position from state journal                      │
│  6. Call compute_monitor_state(snapshot, position, config)    │
│  7. Act on state.action:                                       │
│     - "enter_long"  → submit buy-to-open                      │
│     - "enter_short" → submit sell-to-open                     │
│     - "hold"        → no action, log diagnostic               │
│     - "exit"        → submit close order                      │
│     - "stand_aside" → no action, log diagnostic               │
│  8. Update state journal after any fill                        │
│  9. Sleep until next 4h bar close                              │
│                                                                │
└────────────────────────────────────────────────────────────────┘
                            │
                            │ calls (pure)
                            ▼
┌────────────────────────────────────────────────────────────────┐
│   compute_monitor_state(snap, pos, cfg) -> MonitorState       │
│   (implemented in strategy_c_v2_live_monitor.py)              │
│   - reads:  snap.rsi_{14|21|30}, snap.funding_rate            │
│   - returns: current_regime, current_signal, hostile_funding, │
│              early_exit_reason, action, blocked_reason         │
│   - NO file I/O, NO network, NO training, NO state mutation   │
└────────────────────────────────────────────────────────────────┘
```

The monitor function is a **pure transformation**. Same inputs always
produce the same outputs. This is what makes live decisions
reproducible from backtest decisions — the code path is identical.

---

## 2. What the monitor reads (snapshot contract)

```python
class FeatureSnapshot:  # duck-typed
    rsi_14:       float | None  # only one of these is used per config
    rsi_21:       float | None
    rsi_30:       float | None
    funding_rate: float | None  # last settled rate, as returned by /fapi/v1/fundingRate
    close:        float
    timestamp:    datetime
```

The live runner is responsible for constructing this snapshot from the
latest bar. It uses the **same compute_features_v2** path as the
backtester (via `rsi_series` for arbitrary RSI periods), so feature
values in production are byte-identical to what the backtester saw.

---

## 3. What the monitor reads (position contract)

```python
@dataclass
class LivePositionState:
    side:        Literal["long", "short"]
    entry_time:  datetime       # bar timestamp of entry
    entry_price: float          # fill price (post-slippage real)
    bars_held:   int            # count of 4h bars elapsed since entry
```

The live runner maintains this in a small JSON journal
(`state/strategy_c_v2_live_position.json`). On each 4h tick it
increments `bars_held` if a position is open, or leaves it None.

---

## 4. Monitor rules — exactly what fires when

The 16 unit tests pin these rules:

### 4.1 Regime classification (read `config.rsi_field`)

| rsi value          | regime         | signal |
|--------------------|---------------:|-------:|
| None (warmup)      | unknown        |      0 |
| > config.rsi_upper | long_trend     |     +1 |
| < config.rsi_lower | short_trend    |     −1 |
| otherwise          | neutral        |      0 |

### 4.2 Hostile funding detection

| Context                   | Hostile condition                |
|---------------------------|----------------------------------|
| Open long position        | `funding_rate > hostile_long_funding` (default 0.0005) |
| Open short position       | `funding_rate < hostile_short_funding` (default −0.0005) |
| Flat, intended long entry | `funding_rate > hostile_long_funding` |
| Flat, intended short entry| `funding_rate < hostile_short_funding` |
| funding_rate is None      | never hostile (safe default)     |

### 4.3 Action decision — open position branch

If an open position exists, the monitor checks in order:

1. `bars_held >= max_hold_bars` → **exit** (reason: `time_stop`)
2. side=long AND signal=−1 → **exit** (reason: `opposite_signal`)
3. side=short AND signal=+1 → **exit** (reason: `opposite_signal`)
4. side=short AND hostile_funding → **exit** (reason: `hostile_funding_short`)
5. otherwise → **hold**

The key asymmetric line is rule #4. Phase 3's funding filter finding
established that **hostile funding for SHORTS is an exit trigger, but
hostile funding for LONGS is NOT.** The monitor flags hostile long
funding in the diagnostic output but does not act on it. Blocking longs
in hot funding cost the backtest 29 pp of OOS return on average — so
we never do it live.

### 4.4 Action decision — flat branch

If no open position:

- signal=+1 → **enter_long** (funding is informational, never blocks)
- signal=−1 AND hostile_funding → **stand_aside** (blocked: `hostile_funding_short_entry`)
- signal=−1 AND not hostile_funding → **enter_short**
- signal=0 → **stand_aside**

---

## 5. What the monitor deliberately does NOT do

1. **No re-training.** The RSI period, thresholds, hold bars, and
   funding thresholds are FROZEN at deployment time. Changing them
   requires a new offline research cycle.
2. **No signal re-weighting.** The persistent-signal rule is
   evaluated verbatim. No adaptive confidence, no Bayesian update.
3. **No position sizing decisions.** The monitor always outputs 1×
   notional actions. Position sizing is a LAYER BELOW the monitor
   (handled by the live runner after `state.action` is received).
4. **No Coinglass overlay.** Phase 4 found that Coinglass overlays
   are inconclusive at the 83-day window. Until Phase 5 produces a
   longer Coinglass window measurement, the live monitor does not
   read Coinglass fields.
5. **No MTF confirmation.** The Phase 3 MTF study found persistent-
   signal 15m execution is cost-dominated. The monitor operates on the
   4h execution frame only.
6. **No adaptive thresholds.** The upper/lower RSI thresholds are
   constants (70 / 30 by default). No z-scoring, no percentile
   tracking.

If future Phase 5+ work wants to relax any of these constraints, it
must pass the same promotion-bar gate (return > 100%, DD < 25%,
PF > 1.5, >5/8 positive, >100 trades) before the live monitor is
allowed to read the new dimension.

---

## 6. Kill switches — what the live runner should check outside the monitor

The monitor is not a risk manager. It only tells you "what the
strategy says to do." The live runner must also implement independent
kill switches that can override the monitor:

| Condition                              | Action                  |
|----------------------------------------|-------------------------|
| Drawdown from session high > 15%       | Flat all, pause monitor |
| Cumulative P&L < −10% of allocated     | Flat all, pause monitor |
| Stale feature data (no 4h tick > 6h)   | Flat all, pause monitor |
| Funding rate fetch failure (3x retry)  | Continue with last known value + log |
| Exchange API 5xx (3x retry)            | Flat all, pause monitor |
| Manual "stop" flag in state journal    | Flat all, pause monitor |

These live OUTSIDE `compute_monitor_state`. The monitor's job is the
strategy decision; the runner's job is the safety boundary.

---

## 7. Example pseudo-code for the live runner

```python
# ~/strategy_c_v2_live_runner.py (sketch, not implemented)

import json, time
from datetime import datetime, timezone
from data.strategy_c_v2_features import compute_features_v2
from strategies.strategy_c_v2_live_monitor import (
    MonitorConfig,
    LivePositionState,
    compute_monitor_state,
)
from adapters.binance_futures import BinanceFuturesAdapter

CFG = MonitorConfig(
    rsi_field="rsi_21",
    rsi_upper=70.0,
    rsi_lower=30.0,
    hostile_long_funding=0.0005,
    hostile_short_funding=-0.0005,
    max_hold_bars=12,
)
STATE_FILE = "state/strategy_c_v2_live_position.json"

def load_state():
    try:
        with open(STATE_FILE) as f:
            return LivePositionState(**json.load(f))
    except FileNotFoundError:
        return None

def save_state(pos):
    with open(STATE_FILE, "w") as f:
        json.dump(asdict(pos), f, default=str)

def live_loop():
    adapter = BinanceFuturesAdapter()
    while True:
        # 1. Fetch latest 200 4h bars
        bars = adapter.fetch_ohlcv("BTCUSDT", "4h", 200)
        # 2. Fetch recent funding (1 page is enough)
        funding = adapter.fetch_funding_rate_history(
            "BTCUSDT", start=datetime.now() - timedelta(days=2), end=datetime.now()
        )
        # 3. Compute features
        features = compute_features_v2(bars, funding_records=funding, bar_hours=4.0)
        if not features:
            time.sleep(60)
            continue
        snap = features[-1]  # last bar's feature snapshot

        # 4. Load position + age it
        pos = load_state()
        if pos is not None:
            # increment bars_held if we've crossed a new 4h boundary
            new_bars = count_4h_boundaries_since(pos.entry_time)
            pos = replace(pos, bars_held=new_bars)

        # 5. Check external kill switches FIRST
        if check_kill_switches(pos, snap):
            flat_all_and_pause()
            continue

        # 6. Call the monitor
        state = compute_monitor_state(snap, pos, CFG)

        # 7. Act
        if state.action == "enter_long" and pos is None:
            fill = adapter.submit_market_order("BTCUSDT", "buy", qty)
            new_pos = LivePositionState("long", fill.ts, fill.price, 0)
            save_state(new_pos)
        elif state.action == "enter_short" and pos is None:
            ...
        elif state.action == "exit" and pos is not None:
            fill = adapter.submit_market_order("BTCUSDT", "sell" if pos.side == "long" else "buy", qty)
            close_state()
        elif state.action in ("hold", "stand_aside"):
            log_diagnostic(state)

        # 8. Wait for next 4h boundary
        sleep_until_next_4h_close()
```

This is NOT implemented in this session. It's a reference design to
show how the pure monitor function integrates with the real runner.
Implementation is Phase 5 work.

---

## 8. Diagnostic log format

On every 4h tick, the live runner should emit a structured log line:

```json
{
  "ts": "2026-04-12T08:00:00Z",
  "bar_close": "2026-04-12T08:00:00Z",
  "rsi_21": 72.3,
  "funding_rate": 0.00042,
  "regime": "long_trend",
  "signal": 1,
  "hostile_funding": false,
  "position": {"side": "long", "bars_held": 4, "entry_price": 67345.1},
  "action": "hold",
  "early_exit_reason": null,
  "blocked_reason": null
}
```

A flat position emits the same schema with `position: null`. Logs
become the offline audit trail — any divergence between backtest and
live can be reconstructed from this stream alone.

---

## 9. When to re-optimize (the research cycle boundary)

The live monitor is frozen. Re-optimization means a new research
cycle: Phase 5 or later. The boundary is crossed when ANY of:

1. **30+ consecutive live trading days** have accumulated enough new
   4h bars to justify extending the walk-forward.
2. **A regime shift is observed** (drawdown exceeding anything in the
   historical walk-forward). This triggers an off-line review.
3. **A kill switch fires** more than once in a 30-day window.
4. **New data access opens up** (longer Coinglass, new Binance
   endpoints, spot BTCUSDT history).

When re-optimization happens, it is always OFFLINE, always with the
full walk-forward machinery, and always followed by a fresh
promotion-bar pass. No live-data re-tuning.

---

## 10. What the monitor guarantees (the claims)

1. Same snapshot + same position → same action. Always.
2. The decision path is a strict subset of the backtester's decision
   path — the live monitor cannot produce an action that the backtest
   wouldn't have taken under equivalent inputs.
3. Funding asymmetry (Phase 3) is enforced: no long-side funding veto.
4. No state-leakage: the monitor's output depends only on the
   snapshot, the position, and the config.
5. TDD-covered: 16 passing tests pin every rule branch and the
   dataclass surface.

The monitor is the smallest possible unit of "live code" that can
make strategy decisions without re-training. Everything above it (the
runner, the kill switches, the execution) is plumbing around a pure
function.

See `strategy_c_v2_phase4_final_recommendation.md` for the primary
candidate config that the monitor will read at deployment.
