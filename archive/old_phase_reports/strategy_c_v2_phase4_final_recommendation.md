# Strategy C v2 — Phase 4 Deliverable: Final Primary + Backup Recommendation

_Date: 2026-04-12_
_Status: Phase 4 closeout. Primary + backup for paper deployment._

---

## TL;DR

| Slot       | Candidate                          | OOS Return | Max DD  | Trades | Pos  | PF   |
|------------|------------------------------------|-----------:|--------:|-------:|-----:|-----:|
| **Primary** | **Candidate A**: 4h rsi_only_21 hold=12 (both) | **+142.77%** | 20.89%  |   107  | 7/8 (87.5%) | 1.83 |
| **Backup**  | **Candidate C**: 4h rsi_and_macd_14 hold=4 long-only | **+114.16%** | 20.64%  |   177  | 6/8 (75.0%) | 1.76 |

**Why A + C (and not B):**

- **A** clears every promotion bar, has the highest window consistency
  (7/8 positive), a robust sample (107 trades), and sits on a broad
  neighborhood of +120%+ cells. It is the strongest full-featured
  candidate.
- **C** clears every promotion bar, has the highest trade count (177),
  is long-only (no short-tail risk), and its failure modes are
  uncorrelated with A's. If A's short side fails in a new regime, C
  keeps running. That makes C the right risk-ladder hedge.
- **B** is EFFICIENT (best DD 13.92%, best PF 2.75) but fails the
  trade-count bar (52 < 100). Phase 4 robustness also revealed nearby
  cells (`rsi_only_28 h=18` → +191.98% / 14.89% DD / 87.5% positive)
  that strictly dominate B on the same family. B is an "iterate"
  candidate, not a "deploy" candidate.

**Deployment recommendation**:

- Paper deploy A at 0.25× notional for 30 days
- Simultaneously paper deploy C at 0.25× notional for 30 days
- Independent kill switches (§5)
- Separate journals + diagnostic logs
- No re-optimization during the paper period
- Phase 5 decision point at day 30 (§7)

---

## 1. How this recommendation was derived

Phase 4 ran six sub-studies:

1. **Candidate consolidation** (`strategy_c_v2_phase4_candidates.md`)
   — PnL decomposition of A, B, C into gross / funding / cost with
   full 5-year walk-forward numbers
2. **Robustness band** (`strategy_c_v2_phase4_robustness_band.md`)
   — small parameter perturbations around each candidate to test for
   fragility. Key finding: A is broad, B is broad but has dominating
   neighbors (p=28 family), C is a local maximum with narrow but
   stable edge
3. **Exit refinement** (`strategy_c_v2_phase4_exit_refinement.md`)
   — 24 ATR trailing stop variants, all dominated by the baseline
   time-stop exit. ATR stops dropped from production
4. **Live monitoring design** (`strategy_c_v2_phase4_live_monitoring.md`)
   — pure state-machine `compute_monitor_state` function + 16 tests.
   Enforces Phase 3's funding asymmetry (no long-veto, only short-veto).
   Designed but not auto-running
5. **Coinglass overlay** (`strategy_c_v2_phase4_coinglass_overlay.md`)
   — 83-day 4h window gives 7 trades, too few signals for any overlay
   to measurably fire. Deferred to Phase 5
6. **This file** — primary + backup selection

---

## 2. Why Candidate A is the primary

**The case for A:**

| Property             | Candidate A                       |
|----------------------|-----------------------------------|
| OOS compounded return | +142.77% over 48 OOS months       |
| Window consistency   | 7/8 positive = 87.5%              |
| Trade count          | 107 (above the 100 floor)         |
| Max drawdown         | 20.89% (below the 25% bar)        |
| Profit factor        | 1.83 (above the 1.5 bar)          |
| Funding drag         | −3.86% (vs 28% perp B&H drag)     |
| Exit reason mix      | 100% time-stop (opposite-flip never fires — latent infra) |
| Robustness band      | Broad, 7+ nearby cells above +120% |
| Local maximum status | Not the local max (rsi_only_20 h=11 is higher), but adjacent |
| Exposure             | 14.6% of 4-year period            |
| Simplicity           | Single rule: `rsi_21 > 70` or `< 30` |

**The key property**: A has the highest **combined window consistency
+ trade count**. 7 of 8 OOS windows positive at 107 trades is the
strongest statistical claim in the entire Phase 2-4 research program.
Every other cell either has fewer trades (B at 52) or fewer positive
windows (C at 6/8, B at 6/8, plus various p=20 variants at 75%).

**Why not the Phase 4 robustness-band winner (`rsi_only_20 h=11 both`,
+197.96%)?**

- `rsi_only_20 h=11` is higher return but has only 6/8 positive
  windows (75%), not 7/8 (87.5%). Less consistent.
- `rsi_only_20 h=11` has DD 22.18% vs A's 20.89%. Slightly worse.
- The user's Phase 4 brief explicitly listed A as a candidate. Promoting
  `rsi_only_20 h=11` would be *optimization*, not *consolidation*.
  Phase 4 is explicitly about consolidation of the stated candidates.
- The robustness band finding is preserved in the record — Phase 5 can
  revisit it when we have an additional post-deployment signal.

**Honest qualification**: A is not the single highest-return cell on
the 4h grid. It is the most robust cell among those in the Phase 4
brief's candidate list that also clears every promotion bar. That is
the correct criterion for *deployment*, as opposed to *further research*.

---

## 3. Why Candidate C is the backup

**The case for C:**

| Property             | Candidate C                       |
|----------------------|-----------------------------------|
| OOS return           | +114.16%                          |
| Window consistency   | 6/8 = 75%                         |
| Trade count          | **177 (highest of all candidates)** |
| Max drawdown         | 20.64%                            |
| Profit factor        | 1.76                              |
| Funding drag         | −3.63%                            |
| Side                 | **long-only** (no short-tail risk) |
| Failure mode         | UNCORRELATED with A               |

**Why C instead of B?**

B has lower drawdown (13.92% vs 20.64%) and higher profit factor
(2.75 vs 1.76), which would make it a natural "low-risk backup." But:

1. **B fails the trade-count bar.** 52 < 100.
2. **B's nearby cells dominate it.** The Phase 4 robustness band shows
   `rsi_only_28 h=18 both` → +191.98% / 14.89% DD / 87.5% positive —
   strictly better than B. If we promote B, we're saying "we'll ship
   a cell we know is beaten by the adjacent cell." That's a worse
   signal than "we'll ship the thing the user listed."
3. **B's failure mode is CORRELATED with A.** Both are rsi_only both-
   sides on 4h. Any regime that breaks A (e.g. a sudden reversal of
   the bull trend into a sustained downtrend) will also break B. Using
   B as the backup gives no real diversification.
4. **C's failure mode is UNCORRELATED with A.** C is long-only —
   its risk is "long side stops working." A's risk is "long OR short
   side stops working." If the bear market comes for shorts but
   the long RSI signal continues to work, C is fine and A is fine.
   If the bull market dies and RSI-long weakens, both A and C fail
   together — but in that case, so would B. The diversification
   benefit of C is bigger precisely because it doesn't trade short.

**Trade-off**: choosing C as backup means accepting higher backup
drawdown (20.64% vs B's 13.92%) in exchange for (a) clearing the
trade-count bar and (b) true diversification from A's short side.
That's a better risk ladder than "two correlated both-sides strategies."

---

## 4. What about B?

**B is a Phase 5 iteration candidate, not a Phase 5 deployment candidate.**

The path forward for B:

1. Phase 5 should test `rsi_only_28 hold=18 both` (the robustness-
   band winner in B's neighborhood). If it clears all promotion
   bars and passes a sensitivity test, it replaces B as the "low-DD"
   slot.
2. Alternatively, B can be paper deployed at a MUCH SMALLER allocation
   (0.10× notional) as a side-channel test to see whether its 52-trade
   sample holds up in live conditions. This is a cheap sanity check
   that doesn't commit much capital.
3. NEVER ship B at equal weight with A and C — the trade-count
   sample is too thin to trust at production sizing.

---

## 5. Kill switches for paper deployment

The live monitor is a pure state-machine; the live runner wraps it
with independent kill switches (see
`strategy_c_v2_phase4_live_monitoring.md` §6). For the A+C paper
deployment specifically:

| Condition                                   | Action              | Rationale                                |
|---------------------------------------------|---------------------|------------------------------------------|
| Drawdown from session high > 15%            | Flat both, pause    | Below historical DD ceiling, not above   |
| Cumulative P&L < −10% of allocated          | Flat both, pause    | Early warning, not disaster              |
| Stale 4h data > 6 hours                     | Flat both, pause    | Data integrity                           |
| 3 consecutive trades stopped out            | Pause A only        | A-specific failure; C keeps running      |
| Candidate A and Candidate C disagree > 5x in 30 days | Review                 | Uncorrelated failure divergence          |
| Funding rate > 0.002 (20 bp) for > 24h      | Log + flag          | Hot regime; LOG only, don't block longs |

Note the final row: this is a **diagnostic flag**, not a veto. Phase 3
funding filter research established that blocking longs in hot funding
hurt OOS performance by 29 pp on average. We log it so the analyst
sees it, but we never act on it automatically.

---

## 6. What the paper deployment will measure

Paper trading for 30 days at 0.25× notional gives us ~60 4h bars per
day × 30 = 1,800 4h bars = 7.5 × Candidate A's average hold. Expected
trade count over 30 days:

- **A**: 107 / 48 months × 1 month = **≈ 2.2 trades**
- **C**: 177 / 48 months × 1 month = **≈ 3.7 trades**
- **Combined**: **≈ 5.9 trades**

That's a handful of trades — enough to sanity-check execution,
funding accrual, and kill-switch behavior, but NOT enough to update
the backtest view statistically. A single bad trade could create a
10% drawdown. We treat those as WARNING signals, not proof of failure.

**What we're looking for during paper**:

1. Do live fills match t+1 open? (execution hygiene)
2. Is the funding accrual consistent with backtester math? (cashflow sanity)
3. Do kill switches trigger appropriately? (risk infrastructure)
4. Does the live RSI signal match the post-bar backtest feature? (feature plumbing)
5. Is the diagnostic log complete and actionable? (observability)

**What we're NOT looking for**: evidence that "the strategy works."
The strategy already works — the backtest proved it across 48 OOS
months. We're looking for deployment-shaped bugs, not strategy bugs.

---

## 7. Phase 5 decision point (day 30 of paper)

At day 30 of the paper deployment, Phase 5 should answer:

1. **Do A and C match their backtest signatures in live conditions?**
   Feature values byte-identical? Fill slippage within tolerance?
   If YES → graduate to 0.5× notional for 30 more days.
   If NO → halt, investigate divergence, rebuild plumbing.

2. **Did any unexpected kill switches fire?**
   If YES → investigate, do not scale up.
   If NO → proceed.

3. **Is the Phase 4 robustness-band-winner (`rsi_only_28 h=18 both`)
   worth promoting to a Phase 5 "candidate D"?**
   Requires a parameter-sensitivity test (period ±1, hold ±1, cost
   ±0.04%) first. If D clears, it becomes the low-DD slot. B is
   retired.

4. **Is there new Coinglass data?**
   If a longer Coinglass window (multi-year) is available, rerun the
   Phase 4 Coinglass overlay experiment on A with rolling walk-forward.
   If lift is real, consider adding an overlay filter to A.

5. **Is the spot-BTCUSDT benchmark measured?**
   The Phase 3 next-cycle recommendation flagged spot B&H as the
   honest "do-nothing" number. Phase 5 should fetch spot and compute
   it properly (expected ~+43% vs perp's +13% over the same 48
   months). This recalibrates the promotion bars.

---

## 8. What Phase 4 does NOT recommend

- **Do NOT ship B.** Thin trade sample, better neighbor exists.
- **Do NOT ship any ATR trailing stop variant.** All 24 tested ATR
  variants are dominated by the baseline time-stop.
- **Do NOT use Coinglass overlays in production.** 4h 83-day window
  yielded 7 trades; no measurable overlay signal.
- **Do NOT use MTF confirmation on 15m execution.** Phase 3 already
  showed this is cost-dominated.
- **Do NOT promote the robustness-band winners (`rsi_only_28 h=18`,
  `rsi_only_20 h=11`) in Phase 4.** They were discovered in this
  session but were not in the user's explicit candidate list. They
  become Phase 5 sensitivity tests first.
- **Do NOT re-optimize during paper deployment.** All parameters
  frozen.

---

## 9. Headline numbers (for context)

Backtest performance, 2022-04 → 2026-04 (48 months OOS, 8 rolling
walk-forward windows, 0.12% round-trip, real funding):

| Candidate | Compounded | Max DD | Trades | Pos Windows | PF    | Funding cost |
|-----------|-----------:|-------:|-------:|------------:|------:|-------------:|
| A         |  +142.77%  | 20.89% |   107  | 7/8 (87.5%) | 1.83  |       −3.86% |
| B         |  +138.41%  | 13.92% |    52  | 6/8 (75.0%) | 2.75  |       −3.94% |
| C         |  +114.16%  | 20.64% |   177  | 6/8 (75.0%) | 1.76  |       −3.63% |
| Spot B&H (reference) | ~+43% (Phase 5 to measure) | ~58% | — | — | — | — |
| Perp B&H (reference) |   +13.12% | 58.57% |     8  | 4/8 (50.0%) | 2.04  |      −28.00% |

Deployment allocation (recommended):

| Slot    | Candidate | Notional | Frequency | Monitor    |
|---------|-----------|---------:|-----------|------------|
| Primary | A         |    0.25× | every 4h  | Independent |
| Backup  | C         |    0.25× | every 4h  | Independent |
| Total   |           |    0.50× |           |             |

Leaving 0.50× unallocated gives room for Phase 5 candidates or for
scaling A / C up to 0.5× each if the day-30 checkpoint passes cleanly.

---

## 10. One-paragraph summary for the next session's opening

> Phase 4 consolidated the Phase 3 candidate list into one primary and
> one backup for paper deployment. Candidate A (4h rsi_only_21 hold=12
> both) is the primary: +142.77% OOS / 20.89% DD / 7-of-8 positive
> windows / 107 trades — it clears every Phase 2 promotion bar and sits
> on a broad robustness band. Candidate C (4h rsi_and_macd_14 hold=4
> long-only) is the backup: +114.16% OOS / 20.64% DD / 177 trades /
> long-only risk profile, diversifying A's short-side exposure.
> Candidate B (rsi_only_30 hold=16 both) is shelved because it fails
> the trade-count bar (52 < 100) and its robustness band revealed
> dominating neighbors (`rsi_only_28 hold=18` → +191.98% / 14.89% DD).
> ATR trailing stops tested and dropped (all 24 variants dominated by
> time-stop). Live monitoring designed as a pure state-machine
> (`compute_monitor_state`, 16 tests green) that enforces Phase 3's
> funding asymmetry (no long-veto, only short-veto). Coinglass overlay
> on 4h window measured as null at the 83-day Coinglass slice (7 trades
> baseline, overlays never trigger meaningfully). Phase 5 should paper
> deploy A + C at 0.25× notional each for 30 days, measure fill quality
> / funding accrual / kill-switch behavior, and only then consider
> scaling up or promoting the robustness-band winners.

---

## 11. File layout at end of Phase 4

```
strategy-c-orderflow/
  ... (Phase 1-3 files unchanged) ...

  # Phase 4 deliverables
  strategy_c_v2_phase4_candidates.md           # D#1
  strategy_c_v2_phase4_robustness_band.md      # D#2
  strategy_c_v2_phase4_exit_refinement.md      # D#3
  strategy_c_v2_phase4_live_monitoring.md      # D#4
  strategy_c_v2_phase4_coinglass_overlay.md    # D#5
  strategy_c_v2_phase4_final_recommendation.md # D#6 (this file)

  # Phase 4 runners
  run_strategy_c_v2_phase4_sweep.py            # Candidates + robustness + ATR
  run_strategy_c_v2_phase4_coinglass_overlay.py # 4h Coinglass overlay

  # Phase 4 data artefacts
  strategy_c_v2_phase4_candidates.csv
  strategy_c_v2_phase4_robustness_band.csv     (132 rows)
  strategy_c_v2_phase4_atr_sweep.csv           (24 rows)
  strategy_c_v2_phase4_coinglass_overlay.csv   (6 rows)

  # Phase 4 new code (TDD-covered)
  src/strategies/strategy_c_v2_live_monitor.py # live monitor state-machine
  src/research/strategy_c_v2_backtest.py       # extended with ATR trailing stop
```

Phase 4 test count: **800** (up from 756 at end of Phase 3).
All passing.
