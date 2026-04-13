# Strategy C v2 — Phase 7 Deliverable: Execution Quality + Safety Controls

_Date: 2026-04-12_
_Status: Phase 7 — design spec + retrospective quality metrics._

## TL;DR

The live runner must enforce **six safety controls** and must produce
**telemetry in the `PaperTradeLogEntry` format** (TDD-covered schema).
The retrospective simulation over 30 days shows the baseline execution
quality metrics the live run must reproduce within tolerance:

| Metric                       | 30-day retrospective value | Live tolerance         |
|------------------------------|---------------------------:|------------------------|
| Entry fill vs model          | 0 bp                       | ≤ 2 bp                 |
| Stop-loss fire rate (D1 pri) | 100% (1 of 1)              | ± 0.25 per trade      |
| Cost per trade (D1 pri)      | 0.16%                      | 0.16% ± 0.01%         |
| Funding per trade            | ≤ 0.02% abs                | ≤ 0.05% abs           |
| Signal latency               | 0 bars (backtest baseline) | ≤ 1 bar (live)        |
| Monitor state consistency    | N/A                        | 100% — any drift = alert |

---

## 1. The telemetry schema (already TDD-built)

`src/strategies/strategy_c_v2_paper_log.py` defines `PaperTradeLogEntry`
with these fields:

| Field | Source | Purpose |
|---|---|---|
| `cell_label` | config | Which cell this trade belongs to |
| `signal_timestamp` | bar | When the signal was evaluated |
| `completed_bar_timestamp` | bar | Bar close used (must be completed) |
| `intended_entry_price` | model | What the backtest said the fill should be |
| `paper_fill_entry` | live | Actual paper fill price |
| `side` | signal | long / short |
| `stop_semantics` | config | strategy_close_stop or exchange_intrabar_stop |
| `stop_level` | derived | Absolute stop price at entry time |
| `stop_trigger_timestamp` | live | When the stop actually triggered (if it did) |
| `stop_fill_price` | live | Actual fill at stop (if stopped) |
| `stop_slippage_vs_model` | derived | (fill − model) / model |
| `actual_position_frac` | config | Sizing fraction used |
| `exit_reason` | runner | time_stop / opposite_flip / stop_loss_long / stop_loss_short |
| `exit_timestamp` | live | When the position closed |
| `exit_price` | live | Actual exit fill |
| `hold_bars` | derived | Number of execution bars held |
| `gross_pnl` | derived | Price move × frac × side |
| `funding_pnl` | derived | Accrued funding × frac × −side |
| `cost_pnl` | derived | −round_trip × frac |
| `net_pnl` | derived | gross + funding − cost |
| `monitor_flags` | safety | Any alert strings attached to this trade |

Every field is mandatory in the log output. Missing fields = schema
violation alert.

---

## 2. Safety controls — hard alerts + soft alerts

### 2.1 Hard alerts — flat-all-and-pause immediately

| Alert                          | Condition                                          | Action                |
|--------------------------------|----------------------------------------------------|-----------------------|
| **stale_data**                 | No 4h bar received for > 6 hours                   | flat all, pause       |
| **incomplete_bar_used**        | Signal computed on a bar whose close time > now    | flat all, pause       |
| **stop_not_triggered**         | Price crossed stop level but no fill event within 2 min | flat all, investigate |
| **stop_trigger_fill_mismatch** | Trigger price and fill price differ by > 1%       | flat all, investigate |
| **abnormal_slippage**          | Fill vs model > 2% on any single event             | flat all, pause       |
| **abnormal_drawdown**          | Session DD > 15%                                   | flat all, pause       |

Each hard alert writes a record to the safety journal and emits a
notification (email/webhook/SMS). The live runner enters a PAUSED
state and does not enter new positions until manually resumed.

### 2.2 Soft alerts — log + flag but do not halt

| Alert                            | Condition                                          | Action        |
|----------------------------------|----------------------------------------------------|---------------|
| hostile_funding_long_flagged    | funding_rate > 0.0005 and position is long         | flag + log    |
| hostile_funding_short_blocked    | funding_rate < −0.0005 and new short attempted    | block + flag  |
| wick_near_stop                   | bar.low within 0.25% of stop level during hold    | flag + log    |
| trade_count_drift                | live trade count < 75% of retrospective counterpart after 2 weeks | flag |
| feature_drift                    | Live RSI(20) differs from retrospective by > 0.5 at same timestamp | alert |

Soft alerts do not halt trading but should be visible on the live
dashboard and reviewed daily.

### 2.3 Implementation sketch

```python
# In the live runner loop (pseudo-code):

state = load_state_from_journal()
bar = fetch_latest_4h_bar()

# HARD: stale data
if (now - bar.timestamp) > timedelta(hours=6):
    emit_alert("stale_data", bar=bar.timestamp)
    flat_all()
    return

# HARD: incomplete bar
if bar.timestamp + timedelta(hours=4) > now:
    emit_alert("incomplete_bar_used", bar=bar.timestamp)
    flat_all()
    return

feature = compute_feature_snapshot(bar, funding_records)
monitor_state = compute_monitor_state(feature, state.position, cfg)

# Hard DD check
if session_dd > 0.15:
    emit_alert("abnormal_drawdown", dd=session_dd)
    flat_all()
    return

# Soft: funding flag
flags = []
if feature.funding_rate > 0.0005 and state.position and state.position.side == "long":
    flags.append("hostile_funding_long_flagged")
if state.position is None and monitor_state.blocked_reason == "hostile_funding_short_entry":
    flags.append("hostile_funding_short_blocked")

# Execute action
if monitor_state.action == "enter_long":
    fill = exchange.submit_market_order(symbol, "buy", qty)
    state.position = LivePositionState(...)
    log.append(trade_log_entry_open(state.position, flags))
elif monitor_state.action == "exit":
    fill = exchange.submit_market_order(symbol, "sell", qty)
    entry = trade_log_entry_close(state.position, fill, monitor_state.early_exit_reason, flags)
    log.append(entry)
    state.position = None

save_state_to_journal(state)
```

---

## 3. 30-day retrospective execution quality

The retrospective doesn't measure live fills — it uses modeled fills
as both "model" and "paper". But it produces the baseline numbers
the live run must match.

### Per-trade fields from the retrospective

| Trade # | Cell | Side | intended_entry | paper_entry | Δ | exit_price | stop_slip |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | D1_long_primary (close_stop)   | long | 74,885.0 | 74,885.0 | 0 | 72,953.0 | N/A (stop level 73,771.7) |
| 1 | D1_long_primary (intrabar_stop)| long | 74,885.0 | 74,885.0 | 0 | 73,761.7 | ~0 bp (fill = stop level) |
| 1 | C_long_backup (close_stop)     | long | 73,573.0 | 73,573.0 | 0 | 73,963.0 | N/A (time_stop)       |
| 2 | C_long_backup (close_stop)     | long | 74,885.0 | 74,885.0 | 0 | 73,914.0 | N/A (time_stop)       |

**Entry-fill delta**: **0 bp** on every trade because the retrospective
uses the same model for "intended" and "paper" fills. Live will have
real slippage — the tolerance should be ≤ 2 bp per trade.

**Stop-fill slippage**: 0 bp in the retrospective (exchange_intrabar
fills exactly at stop level). Live slippage typically 1-10 bp on
normal fills, 50-200 bp on gap events. Alert threshold is 2%.

### Per-cell cost profile

| Cell                  | Trades | Σ cost | Per-trade cost | Model | OK? |
|-----------------------|-------:|-------:|---------------:|------:|-----|
| D1_long_primary       |   1    | 0.16%  |     0.16%      | 0.16% | ✅  |
| C_long_backup         |   2    | 0.24%  |     0.12%      | 0.12% | ✅  |
| D1_long_frac2_shadow  |   1    | 0.24%  |     0.24%      | 0.24% | ✅  |

Cost matches the formula `2 × (fee + slip) × frac` exactly. Any live
run with costs > 5% above these numbers is a fee-config bug.

### Per-cell funding profile

| Cell                  | Funding % | Per-trade funding | OK? |
|-----------------------|----------:|------------------:|:----|
| D1_long_primary       |    +0.02% |            +0.02% | ✅  |
| C_long_backup         |    −0.01% |            −0.005% | ✅  |
| D1_long_frac2_shadow  |    +0.00% |            +0.00% | ✅  |

Funding is near zero for all cells in this 30-day window. The hold
horizons (2-9 bars = 0.33-1.5 days) produce at most 1-5 funding events
per trade, and each event is typically ~0.001-0.005%. Total funding
drag per trade < 0.05%.

---

## 4. Live deployment configuration checklist

Before the forward 30-day run starts, verify:

**Feature plumbing**
- [ ] `compute_features_v2` runs on a Binance 4h kline snapshot
- [ ] RSI(20) for D1_long matches the retrospective value at the
      same timestamp (difference < 0.1)
- [ ] `rsi_series` override is passed correctly (don't hit the Phase 3
      silent-fallthrough bug)
- [ ] MACD(12,26,9) for C_long matches retrospective values

**Signal wiring**
- [ ] `rsi_only_signals(period=20, rsi_override=...)` called for D1_long
- [ ] `rsi_and_macd_signals(period=14)` called for C_long
- [ ] `apply_side_filter(side="long")` called for all three cells

**Stop framework**
- [ ] For strategy_close_stop cells: market-order-on-close logic wired
- [ ] For exchange_intrabar_stop cells: exchange stop-loss order placed
      at entry time, refreshed on partial fills
- [ ] Stop level matches `entry × (1 − stop_pct)` for longs

**Position sizing**
- [ ] Risk/stop → position_frac calculation matches backtester
- [ ] `effective_leverage` cap applied correctly
- [ ] Exchange side order size = `position_frac × equity / entry_price`
      (converted to contract units)

**Cost model**
- [ ] Fee rates: 0.05% taker, 0.01% slippage budget
- [ ] Funding applied at Binance 00:00 / 08:00 / 16:00 UTC
- [ ] Per-trade cost matches `0.12% × frac` formula within 2 bp

**Safety**
- [ ] Stale data check (> 6h) wired
- [ ] Incomplete bar check wired
- [ ] Session DD threshold (15%) wired
- [ ] Stop-trigger-fill mismatch threshold (1%) wired

---

## 5. Daily reconciliation schema

The live runner should emit a daily reconciliation record
comparing live PnL to retrospective-backtest PnL for the same
calendar day:

```json
{
  "date": "2026-04-13",
  "cell": "D1_long_primary",
  "semantics": "strategy_close_stop",
  "live_trades": 1,
  "live_net_pnl": -0.0358,
  "retrospective_net_pnl": -0.0358,
  "pnl_delta": 0.0,
  "delta_explained_by": {
    "slippage": 0.0,
    "funding": 0.0,
    "fee": 0.0,
    "timing": 0.0
  },
  "flags": [],
  "alert": null
}
```

If `pnl_delta` > 10 bp for 3 consecutive days, that's a FLAG — the
live run is diverging from the retrospective in a way that warrants
investigation.

---

## 6. Weekly reconciliation schema

Same format but aggregated by week. Additional checks:

- Cumulative trade count vs retrospective (target: within ± 2)
- Cumulative PnL delta (target: within 50 bp)
- Stop fire count vs retrospective (target: exact match for
  strategy_close_stop, ± 1 for exchange_intrabar_stop)
- Worst-trade comparison (live worst ≥ −10% for D1_long_primary —
  the retrospective's worst was −3.58%)

See the `strategy_c_v2_phase7_funding_slippage_reconciliation.md`
report for the reconciliation format details.

---

## 7. Summary

1. **Telemetry schema is defined and TDD-adjacent** — the
   `PaperTradeLogEntry` dataclass captures every field the Phase 7
   brief listed.
2. **Safety controls are specified** — 6 hard alerts + 5 soft alerts.
3. **30-day retrospective baseline is clean** — 0 bp entry slippage,
   0 bp stop slippage, cost and funding match the model exactly.
4. **Live deployment checklist** is in §4 — work through it before
   starting the forward run.
5. **Daily + weekly reconciliation format** is defined — the live
   runner emits structured records and the reconciler compares
   against the retrospective.
6. **Any live deviation > 10 bp / 3 days** is a FLAG, > 1% / 1 day is
   an ALERT, > 2% single event is a HARD ALERT.
