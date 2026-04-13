# Strategy C v2 — Phase 7 Deliverable: 30-Day Paper Deployment Log

_Date: 2026-04-12_
_Status: Retrospective simulation of the Phase 7 paper deployment
period 2026-03-06 → 2026-04-05 on historical 4h OHLCV + funding data._

## 0. What this log is (and is not)

**This log is NOT a live 30-day paper run.** A live run requires 30
calendar days of forward-looking data. This session delivers the
**infrastructure** that a live runner would use, plus a
**retrospective simulation** of the same 30-day window on the
historical 4h data we already have.

The retrospective gives us:
- Concrete trade-by-trade telemetry in the Phase 7 log format
- Actual numbers for the stop-semantics parity (what would have
  happened if the primary cell had been running live over those 30 days)
- A reconciliation baseline against which a real live run can be
  checked

The retrospective does NOT give us:
- Live fill quality (actual exchange slippage)
- Safety-control alert firings
- Operator-in-the-loop scenarios

Those are Phase 8 (forward live paper).

---

## 1. Deployment set (locked from Phase 6)

| Slot      | Cell                      | Config                                      | actual_frac |
|-----------|---------------------------|----------------------------------------------|------------:|
| Primary   | D1_long                   | sl=1.5% close r=2% L=2x                      |    1.333    |
| Backup    | C_long                    | sl=2% close r=2% L=2x                        |    1.000    |
| Shadow    | D1_long frac=2            | sl=1.25% close r=2.5% L=2x                   |    2.000    |

Each cell runs under BOTH stop semantics (strategy_close_stop and
exchange_intrabar_stop) in parallel for the full 30-day window.

---

## 2. Trade log — all 30-day-window trades

8 trade records total across 6 (cell × semantics) combinations:

### Primary: D1_long with strategy_close_stop

| # | Entry date | Exit date  | Entry $  | Exit $   | Hold | Reason         | Net PnL |
|--:|------------|------------|---------:|---------:|-----:|----------------|--------:|
| 1 | 2026-03-16 | 2026-03-18 |   74,885 |   72,953 |   9  | stop_loss_long | −3.58%  |

### Primary: D1_long with exchange_intrabar_stop

| # | Entry date | Exit date  | Entry $  | Exit $   | Hold | Reason         | Net PnL |
|--:|------------|------------|---------:|---------:|-----:|----------------|--------:|
| 1 | 2026-03-16 | 2026-03-17 |   74,885 |   73,761 |   3  | stop_loss_long | −2.16%  |

**Same signal, same entry, different stop semantics → different exit
day and different price.** Intrabar fired sooner and at a better level
(73,761 vs 72,953). The ~$800 difference in exit price is the
empirical wedge between the two semantics on this specific trade.

### Backup: C_long (both semantics — identical)

| # | Entry date | Exit date  | Entry $  | Exit $   | Hold | Reason    | Net PnL |
|--:|------------|------------|---------:|---------:|-----:|-----------|--------:|
| 1 | 2026-03-16 | 2026-03-16 |   73,573 |   73,963 |   4  | time_stop | +0.40%  |
| 2 | 2026-03-16 | 2026-03-17 |   74,885 |   73,914 |   4  | time_stop | −1.41%  |

**No stops fired for C_long during the 30-day window.** Both trades
exited on time_stop. Stop semantics are irrelevant when stops never
fire — confirms the Phase 6 finding that C_long has a structurally
low stop-exit rate.

### Shadow: D1_long frac=2 strategy_close_stop

| # | Entry date | Exit date  | Entry $  | Exit $   | Hold | Reason         | Net PnL |
|--:|------------|------------|---------:|---------:|-----:|----------------|--------:|
| 1 | 2026-03-16 | 2026-03-17 |   74,885 |   73,914 |   4  | stop_loss_long | −2.83%  |

### Shadow: D1_long frac=2 exchange_intrabar_stop

| # | Entry date | Exit date  | Entry $  | Exit $   | Hold | Reason         | Net PnL |
|--:|------------|------------|---------:|---------:|-----:|----------------|--------:|
| 1 | 2026-03-16 | 2026-03-17 |   74,885 |   73,949 |   2  | stop_loss_long | −2.74%  |

---

## 3. 30-day cell totals

| Cell                 | Semantics              | Trades | Stops | Net PnL | Gross PnL | Funding | Cost   |
|----------------------|------------------------|-------:|------:|--------:|----------:|--------:|-------:|
| D1_long_primary      | strategy_close_stop    |   1    |   1   | −3.58%  |  −3.44%   | +0.02%  | −0.16% |
| D1_long_primary      | exchange_intrabar_stop |   1    |   1   | −2.16%  |  −2.00%   | +0.00%  | −0.16% |
| C_long_backup        | strategy_close_stop    |   2    |   0   | −1.01%  |  −0.77%   | −0.01%  | −0.24% |
| C_long_backup        | exchange_intrabar_stop |   2    |   0   | −1.01%  |  −0.77%   | −0.01%  | −0.24% |
| D1_long_frac2_shadow | strategy_close_stop    |   1    |   1   | −2.83%  |  −2.59%   | +0.00%  | −0.24% |
| D1_long_frac2_shadow | exchange_intrabar_stop |   1    |   1   | −2.74%  |  −2.50%   | −0.00%  | −0.24% |

### Ranking by 30-day net PnL

1. **C_long_backup**: −1.01% (both semantics identical)
2. **D1_long_primary (exchange_intrabar)**: −2.16%
3. **D1_long_frac2_shadow (exchange_intrabar)**: −2.74%
4. **D1_long_frac2_shadow (strategy_close_stop)**: −2.83%
5. **D1_long_primary (strategy_close_stop)**: −3.58%

---

## 4. Observations from this specific 30-day window

1. **All three cells lost money.** The 30-day window (2026-03-06 →
   2026-04-05) is a drawdown period for these rule-based strategies —
   price dipped and re-tested, triggering stops without material
   recovery.

2. **C_long had the best 30-day result (−1.01%).** Time-stop exits
   captured a small gain on one trade and a small loss on the other.
   No stop-loss events fired.

3. **D1_long_primary's single trade was the worst cell** — a stop-out
   at entry 74,885 → exit either 73,761 (intrabar) or 72,953
   (close-stop). This single trade accounts for the entire cell's PnL.

4. **exchange_intrabar_stop outperformed strategy_close_stop on D1
   cells** in this window. This is the OPPOSITE of the 5-year aggregate
   (where strategy_close_stop wins by ~26 pp). On the one specific
   trade in this window, the price moved down through the stop and
   never recovered, so intrabar's earlier exit was strictly better.

5. **Semantics didn't matter for C_long** in this window — because
   stops never fired, both paths produce identical results.

6. **Only 4 calendar trades across 6 (cell × semantics) combinations.**
   The low trade frequency confirms that 4h strategies on a 30-day
   window produce small samples — any 30-day conclusion is noise-
   dominated, not signal-dominated.

---

## 5. Funding drag across the 30-day window

Per-trade funding PnL is near zero (±0.02%) because:
- Funding settles every 8 hours (3× per day)
- Trade holds are 2-36 hours (0.25-4.5 funding events)
- Average funding rate is ~1-5 bp/event → ~2-20 bp per held trade
- At position_frac 1.0-2.0 → ~2-40 bp funding PnL per trade

These numbers match the Phase 5A/6 cost decomposition (funding drag
~3-4% over 4 years → <0.1% per trade on average).

**Funding is not a 30-day risk at these hold horizons.**

---

## 6. Cost drag across the 30-day window

Per-trade cost is fixed at `2 × (fee + slip) × position_frac`:
- fee 0.05% per side, slip 0.01% per side → round-trip = 0.12%
- D1_long_primary: 0.12% × 1.333 = **0.16%** per trade ✓ (matches data)
- C_long_backup: 0.12% × 1.000 = **0.12%** per trade... wait, the
  daily summary shows −0.24% for 2 trades = 0.12% per trade. ✓
- D1_long_frac2_shadow: 0.12% × 2.000 = **0.24%** per trade ✓

The per-trade cost is deterministic. The variance comes from **how
many trades** fire, which is regime-dependent.

---

## 7. Retrospective simulation → live deployment plan

### What this retrospective proves

1. **The backtester + telemetry pipeline produces the correct log
   format.** A live run can reuse the same `PaperTradeLogEntry`
   schema directly.
2. **The stop-semantics split is live in the backtester.** Both modes
   produce distinct results on specific trades (D1_long primary case).
3. **Cell selection from Phase 6 is executable** — all three cells
   run cleanly on the 30-day window with expected trade frequencies
   (1-2 trades per cell).
4. **The funding + cost decomposition matches the model** — no
   plumbing surprises on these specific trades.

### What a real live 30-day run would need in addition

1. A scheduler/loop that ticks every 4h on bar close and evaluates
   the live monitor
2. Real exchange credentials (testnet or live) to place paper orders
3. A state journal persisting open positions between ticks
4. Safety controls that fire on alert conditions (see Phase 7
   execution-quality report)
5. A daily reconciliation job that compares the live log against the
   retrospective-backtest counterfactual for the same calendar day
6. 30 days of patience

The code infrastructure is in place. The missing piece is the runner
loop + scheduler, which is deliberately a Phase 8 task.

---

## 8. What to pay attention to in the live run

When the forward 30-day run happens, Phase 8 should specifically watch:

1. **Do paper fills match the retrospective fills on the same
   timestamps?** (feature plumbing + price source)
2. **Does the stop fire at the expected level?** (exchange wiring)
3. **Does the exit timestamp on a stop-exit match the bar where the
   stop should have been triggered?** (execution timing)
4. **Does the funding accrual match the retrospective?** (settlement
   calculation)
5. **Does the cost drag match the 0.12% × frac formula?** (fee
   configuration)
6. **Are there any trades with monitor flags?** (hostile funding, stale
   data, incomplete bar)

Any deviation > 1 bp per trade is a plumbing bug. Fix before scaling up.

---

## 9. CSV outputs

The retrospective produced two CSVs in the worktree:

- `strategy_c_v2_phase7_retrospective_trades.csv` — 8 rows, one per
  trade, schema matches `PaperTradeLogEntry`. This is the format a
  live runner should emit.
- `strategy_c_v2_phase7_retrospective_daily.csv` — 6 rows, one per
  (cell, semantics) aggregate. Daily reconciliation data.

A future live run should append to these same schemas for direct
comparability.
