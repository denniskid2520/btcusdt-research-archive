# Strategy C v2 — Phase 4 Deliverable: Candidate Comparison Table

_Date: 2026-04-12_
_Status: Phase 4 — candidate consolidation._

This report runs the three explicit Phase 4 candidates through a proper
5-year Binance-only walk-forward with the extended PnL decomposition
(gross / funding / cost split). Purpose: a side-by-side comparison so
the primary + backup selection is unambiguous.

All numbers come from a single run of
`run_strategy_c_v2_phase4_sweep.py` on the on-disk 6-year 4h OHLCV +
5-year funding CSV, 24m/6m/6m rolling walk-forward, 8 OOS test windows,
0.12% round-trip cost, real Binance funding settlements applied when
the position is held through the tick.

---

## 1. The three candidates

| Label | Name                        | Rule                                       | Hold | Side        |
|------:|-----------------------------|--------------------------------------------|-----:|-------------|
| **A** | `rsi_only_21_both`          | `rsi(21) > 70` long; `rsi(21) < 30` short  |  12  | both        |
| **B** | `rsi_only_30_both`          | `rsi(30) > 70` long; `rsi(30) < 30` short  |  16  | both        |
| **C** | `rsi_and_macd_14_long`      | `rsi(14) > 70 AND macd_hist > 0` long only |   4  | long-only   |

All three execute on 4h bars, entry at t+1 open, exit at time-stop OR
opposite-flip (whichever first), 1x notional.

---

## 2. Headline comparison

| Metric                    | **Candidate A** | **Candidate B** | **Candidate C** |
|---------------------------|----------------:|----------------:|----------------:|
| OOS compounded return     |     **+142.77%** |     **+138.41%** |     **+114.16%** |
| Combined max drawdown     |           20.89% |       **13.92%** |           20.64% |
| Profit factor             |             1.83 |         **2.75** |             1.76 |
| Positive OOS windows      |    **7/8 (87.5%)** |       6/8 (75.0%) |       6/8 (75.0%) |
| OOS trade count           |              107 |               52 |          **177** |
| Avg exposure time         |            14.6% |         **9.4%** |            8.0% |
| Avg hold (bars)           |             12.0 |             15.9 |              4.0 |
| Passes all promotion bars |              ✅ |              ❌ (n < 100) |              ✅ |

---

## 3. PnL decomposition — gross / funding / cost

This is the new column the Phase 4 brief asked for. We decompose the
net OOS P&L of each candidate into its sources to reveal how much
return is "real alpha" vs how much is absorbed by funding and cost.

The compounded return row and the sum-of-pieces row differ because
compounding winning trades amplifies the linear sum. The difference is
reported as "compounding bonus."

### Candidate A (rsi_only_21 hold=12 both)

| Component         |     Value | Note                                          |
|-------------------|----------:|-----------------------------------------------|
| Gross (sum)       |  +116.28% | Sum of (exit − entry) / entry * side          |
| Funding (sum)     |    −3.86% | Sum of −side × funding for bars held          |
| Cost (sum)        |   −12.84% | 107 trades × 0.12% round-trip                 |
| **Linear net**    |   +99.58% | gross + funding − cost                        |
| **Compounded**    |**+142.77%**| Product of (1 + per_trade_net_pnl)           |
| Compounding bonus |   +43.19% | compounded − linear                           |

### Candidate B (rsi_only_30 hold=16 both)

| Component         |     Value | Note                                          |
|-------------------|----------:|-----------------------------------------------|
| Gross (sum)       |  +104.30% |                                               |
| Funding (sum)     |    −3.94% |                                               |
| Cost (sum)        |    −6.24% | 52 trades × 0.12% — materially less cost drag |
| **Linear net**    |   +94.12% |                                               |
| **Compounded**    |**+138.41%**|                                              |
| Compounding bonus |   +44.29% |                                               |

### Candidate C (rsi_and_macd_14 hold=4 long-only)

| Component         |     Value | Note                                           |
|-------------------|----------:|------------------------------------------------|
| Gross (sum)       |  +106.17% |                                                |
| Funding (sum)     |    −3.63% |                                                |
| Cost (sum)        |   −21.24% | 177 trades × 0.12% — highest cost drag of the three |
| **Linear net**    |   +81.30% |                                                |
| **Compounded**    |**+114.16%**|                                               |
| Compounding bonus |   +32.86% |                                                |

### Cross-candidate observations

1. **Funding drag is consistent (~3.6-3.9%) across all three.** Over
   4 years the funding cost per OOS candidate sits in a tight band.
   This is structural — it reflects how much time each candidate spends
   holding a long during typical positive-funding regimes.

2. **Cost varies by 3.4x between B (lowest) and C (highest)**. C pays
   the most because hold=4 + 177 trades = far more round-trips. B is
   the cheapest to run — hold=16 × 52 trades = 6.24% lifetime cost.

3. **Compounding bonus is 30-45%** across all three. The more
   positively-skewed the trade distribution, the bigger the bonus.
   Candidate B's highest bonus (+44.29%) reflects its highest profit
   factor (2.75).

4. **"Real alpha" (linear net) ordering** differs from compounded:
   - Linear net: A (+99.6) > B (+94.1) > C (+81.3)
   - Compounded: A (+142.8) > B (+138.4) > C (+114.2)

---

## 4. Risk / efficiency ratios

| Ratio                          | Candidate A | Candidate B | Candidate C |
|--------------------------------|------------:|------------:|------------:|
| Return / Drawdown              |        6.83 |    **9.94** |        5.53 |
| Return / Exposure              |        9.78 |   **14.72** |       14.27 |
| Return per trade (linear net)  |       0.93% |    **1.81%** |       0.46% |
| Return per trade (compounded)  |       1.33% |    **2.66%** |       0.65% |

**Candidate B dominates every efficiency ratio** — best DD, best return-
per-trade, best return-per-exposure. It is the most *efficient* strategy
but suffers from a thin trade sample (52 trades across 8 windows
= 6.5 per window).

Candidate A wins on volume and consistency (107 trades, 87.5% positive
windows). Candidate C wins on long-only purity (no short tail risk).

---

## 5. Which promotion bars does each candidate clear?

Phase 2 promotion bars: OOS > 100%, DD < 25%, PF > 1.5, ≥5/8 positive, n > 100.

| Bar                   | A  | B  | C  |
|-----------------------|:--:|:--:|:--:|
| OOS ret > 100%        | ✅ | ✅ | ✅ |
| DD < 25%              | ✅ | ✅ | ✅ |
| PF > 1.5              | ✅ | ✅ | ✅ |
| ≥ 5/8 positive        | ✅ | ✅ | ✅ |
| Trades > 100          | ✅ | **❌** (52) | ✅ |
| **All clear?**        | ✅ | ❌ | ✅ |

**A and C clear every promotion bar. B misses only on trade count.**

---

## 6. Funding drag in context

The 28% 4-year perp funding drag established in Phase 2 is the "cost of
being long all the time." Each Phase 4 candidate pays only a small
fraction of it:

| Candidate | Funding cost | % of 28% full drag |
|-----------|-------------:|-------------------:|
| A         |       −3.86% |             13.8%  |
| B         |       −3.94% |             14.1%  |
| C         |       −3.63% |             13.0%  |

All three candidates spend 86-87% LESS on funding than a passive perp
long. That's a structural advantage of a rule-based selective strategy
on the perp — exposure is only 8-15% of the time, so funding drag is
proportionally smaller than B&H.

This is the "exposure as alpha source" claim from Phase 3 expressed as
a concrete number.

---

## 7. Stability and sample

The Phase 3 recommendation note flagged Candidate B as "statistically
thin at 52 trades." Phase 4 confirms that concern: the trade count is
right above the 30-trade floor, and moves of ±3 trades per window
would shift the aggregate return meaningfully.

A direct mitigation is visible in the Phase 4 robustness band (see
`strategy_c_v2_phase4_robustness_band.md`): neighboring cells to B
(e.g. `rsi_only_28 h=18 both`, +191.98% with 87.5% positive windows
and n=52) produce strictly better outcomes on the same family. That
suggests the candidate list — which was frozen in Phase 3 — may not
contain the optimal cell. The final recommendation discusses this.

---

## 8. What this report concludes

1. **All three candidates are real** — 5-year OOS numbers are positive,
   consistent with Phase 3, and decompose cleanly into gross / funding
   / cost.

2. **A clears all promotion bars** and is the natural default primary
   candidate.

3. **C clears all promotion bars with a long-only risk profile**, and
   is a defensible backup for a long-only portfolio constraint.

4. **B has the best efficiency** (pf 2.75, DD 13.92%, lowest cost) but
   fails on trade count (52 < 100). It is NOT promoted in its current
   form — the next step is either (a) loosen the trade-count bar for
   this specific cell, or (b) migrate to a neighboring cell with
   similar efficiency but higher trade count.

5. **The decision between A and C as primary** hinges on whether the
   paper deployment should carry short-side tail risk. A is higher
   return with both-sides risk; C is lower return with a clean
   long-only risk profile. Both are defensible.

See the following reports for the follow-through:
- `strategy_c_v2_phase4_robustness_band.md` — per-candidate band
- `strategy_c_v2_phase4_exit_refinement.md` — ATR trailing stops
- `strategy_c_v2_phase4_live_monitoring.md` — deployment design
- `strategy_c_v2_phase4_coinglass_overlay.md` — Coinglass overlay on 4h
- `strategy_c_v2_phase4_final_recommendation.md` — primary + backup pick
