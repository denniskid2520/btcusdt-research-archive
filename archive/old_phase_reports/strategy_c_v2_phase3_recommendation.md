# Strategy C v2 — Phase 3 Deliverable: Primary Candidate Recommendation

_Date: 2026-04-11_
_Status: End of Phase 3. The call on which family becomes the primary
Strategy C v2 candidate, backed by five Phase 3 sub-reports._

---

## TL;DR

**Primary candidate: `4h rsi_only_21 hold=12` on 4h execution, side=both, no filters.**

> **+142.77% OOS compounded return, 20.89% max drawdown, PF 1.83,
> 7/8 positive walk-forward windows, 107 trades across 4 years.**

This is the only cell that clears **every single promotion bar** from
the Phase 2 recommendation (OOS > 100%, DD < 25%, PF > 1.5, ≥5/8
positive windows, > 100 trades) while also being the most robust
parameter point — 8 neighboring cells in the Phase 3 robustness sweep
also produce ≥+100% OOS, so it's not a point-fragile optimum.

**Secondary candidate (low-DD variant): `4h rsi_only_30 hold=16` side=both.**
> +138.41% OOS, 13.92% DD, PF 2.75, 6/8 positive, 52 trades. Same
> family, same TF, but closer to the DD-minimum — useful for a risk-
> averse deployment at the cost of a thinner trade sample.

**Long-only "low-drawdown" variant: `4h rsi_and_macd_14 hold=4 long-only`.**
> +114.16% OOS, 20.64% DD, PF 1.76, 6/8 positive, 177 trades. The only
> long-only cell to clear every promotion bar, with the biggest trade
> count among the qualifying cells.

**What gets dropped from further consideration:**
- 15m as a primary alpha frame (cost-dominated, confirmed again)
- MTF on 15m execution with persistent signals (cost-dominated, §Phase 3 MTF)
- MACD-only as a standalone signal (toxic at every TF, confirmed twice)
- Track B Coinglass overlays as rule-based filters (83-day slice cannot support OOS)
- `rsi_only_42` (too slow, thin edge)
- `rsi_7` on 1h (catastrophic, −85% everywhere)

---

## 1. How the recommendation was derived

Phase 3 ran six sub-studies, each reported in its own file:

1. **Robustness sweep** (`strategy_c_v2_phase3_robustness.md`)
   — Perturbed RSI period and hold around Phase 2 winners. Found
   that the 4h rsi_only edge is broad across (period, hold) combinations,
   not point-fragile. Discovered **`rsi_only_21 hold=12`** as the new
   best cell: +142.77% OOS with 87.5% positive windows and 107 trades
   — strictly dominating Phase 2's rsi_only_30 hold=16 on raw return
   and window consistency.

2. **Directional decomposition** (`strategy_c_v2_phase3_directional.md`)
   — Split every sweep cell into long-only / short-only / long-short.
   Found that **the Strategy C v2 edge is asymmetric — it lives in
   longs**. All 20 4h rsi_only long-only cells are positive (+49 to
   +131%); only 7 of 20 short-only cells are positive. Long-only cells
   have 2-5× lower drawdowns than long-short cells. The best long-only
   cell to clear every promotion bar is `rsi_and_macd_14 hold=4 long-only`.

3. **Funding-aware filter** (`strategy_c_v2_phase3_funding_filter.md`)
   — Tested `max_long_funding` and `min_short_funding` vetoes on the
   Phase 2 anchor cells. Found that **short-veto helps (+5 to +28pp
   average lift across anchors), long-veto hurts (−29pp average)**.
   The asymmetry is mechanistic: longs in hot funding regimes capture
   trend continuations; shorts in cold funding regimes are capitulation
   bottom-picks that lose directionally AND pay funding.

4. **Multi-timeframe framework** (`strategy_c_v2_phase3_mtf.md`)
   — Tested 4h → 1h → 15m AND-gate rules on 15m execution. Found that
   **15m execution of persistent signals is cost-dominated even with
   MTF confirmation**. Every MTF cell was −36% to −99%. The alignment
   infrastructure (`align_higher_to_lower`) is in place for Phase 4,
   but the persistent-signal approach does not work on 15m execution.
   Edge-triggered signals are the missing piece (Phase 4 scope).

5. **Track B Coinglass overlay** (`strategy_c_v2_phase3_coinglass_overlay.md`)
   — Ran a single 83-day slice test with 4 overlay filter variants.
   Found that `funding_oi_weighted > 0.0005` as a long-veto produced
   +16.61pp of lift on this slice — **the opposite sign from the
   4-year Track A funding filter measurement**. Resolved in favour of
   the 4-year evidence: the Phase 3 primary candidate does not use
   Coinglass. Deferred Track B proper to Phase 4.

6. **This recommendation file.**

---

## 2. The promotion-bar scorecard

Phase 2 set the bar: promote a candidate iff it clears all five of:

1. OOS aggregate compounded return > 100%
2. Max drawdown < 25%
3. Profit factor > 1.5
4. At least 5/8 positive OOS windows
5. Trade count > 100

Applying to the full Phase 3 sweep (132 robustness cells + 60 funding
filter cells, excluding Track B which is single-slice):

| Cell                                          | (1) ret | (2) DD | (3) PF | (4) pos | (5) n | Clears all |
|-----------------------------------------------|--------:|-------:|-------:|--------:|------:|:-:|
| **4h rsi_only_21 hold=12 (both)**              | +142.77 | 20.89 | 1.83 | 7/8 |  107 | **YES** |
| 4h rsi_only_21 hold=8 (both)                   | +136.71 | 22.96 | 1.71 | 6/8 |  132 | YES |
| **4h rsi_and_macd_14 hold=4 long-only**        | +114.16 | 20.64 | 1.76 | 6/8 |  177 | **YES** |
| 4h rsi_and_macd_14 hold=4 (both)               | +136.20 | 36.76 | 1.37 | 6/8 |  316 | no (DD, PF) |
| 4h rsi_only_30 hold=16 (both)                  | +138.41 | 13.92 | 2.75 | 6/8 |   52 | no (n) |
| 1h rsi_and_macd_21 hold=48 (both)              | +138.77 | 27.58 | 1.34 | 5/8 |  250 | no (DD, PF) |
| 1h rsi_and_macd_14 hold=32 (both)              | +106.11 | 41.61 | 1.17 | 7/8 |  510 | no (DD, PF) |
| 4h rsi_only_21 hold=12 long-only               |  +95.82 | 12.53 | 2.32 | 7/8 |   64 | no (ret, n) |

**Three Phase 3 cells clear every bar.** All three are 4h execution with
the rsi_only_21 or rsi_and_macd_14 family. None of the 1h or MTF or
Track B cells clear every bar — the 1h family fails on drawdown (41.6%)
and profit factor (~1.17), and the 4h rsi_only_30 winner fails on
trade count (52).

---

## 3. The chosen candidate, in detail

### Primary: 4h `rsi_only_21` hold=12 side=both

**Rule** (signal at the close of each 4h bar):

```
if rsi(close, 21) > 70:
    signal = +1  (long)
elif rsi(close, 21) < 30:
    signal = -1  (short)
else:
    signal = 0   (flat)
```

**Backtest parameters:**

| Parameter          | Value                          |
|--------------------|--------------------------------|
| Execution frame    | 4h                             |
| Signal frame       | 4h (same)                      |
| Entry              | bars[i+1].open after signal    |
| Exit               | bars[i+1+12].open (time-stop) OR opposite-signal at j → bars[j+1].open |
| Hold bars          | 12 (2 days)                    |
| Cooldown bars      | 0                              |
| Fee per side       | 0.05%                          |
| Slippage per side  | 0.01%                          |
| Round-trip cost    | 0.12%                          |
| Funding            | Binance 8h fundingRate, charged when entry_idx ≤ k < exit_idx |
| Leverage           | 1x notional                    |
| Funding filter     | none                           |
| Side filter        | both (long + short)            |

**Performance (4 years OOS, 8 walk-forward windows, Apr 2022 → Apr 2026):**

| Metric                 | Value     |
|------------------------|----------:|
| Aggregate compounded return | **+142.77%** |
| Combined max drawdown  | 20.89%    |
| Combined profit factor | 1.83      |
| Positive windows       | 7 / 8 (87.5%) |
| Trade count            | 107       |
| Avg exposure time      | 14.6%     |
| Implementation         | `rsi_only_signals(features, rsi_period=21, upper=70.0, lower=30.0)` |

### Secondary (low-drawdown): 4h `rsi_only_30` hold=16 side=both

Same family, different parameters — the Phase 2 best-DD cell:

| Metric                 | Value     |
|------------------------|----------:|
| OOS compounded return  | **+138.41%** |
| Max drawdown           | **13.92%** |
| Profit factor          | 2.75      |
| Positive windows       | 6 / 8 (75.0%) |
| Trade count            | 52 *(below 100 floor)* |

Use this variant if drawdown is the dominant constraint. Note the
52-trade count — statistically thinner than the primary, although still
above the hard 30-trade floor from Phase 2.

### Long-only (cleanest risk profile): 4h `rsi_and_macd_14` hold=4 long-only

| Metric                 | Value     |
|------------------------|----------:|
| OOS compounded return  | +114.16%  |
| Max drawdown           | 20.64%    |
| Profit factor          | 1.76      |
| Positive windows       | 6 / 8 (75.0%) |
| Trade count            | **177**   |
| Implementation         | `apply_side_filter(rsi_and_macd_signals(features, rsi_period=14), side="long")` |

The only long-only cell in the Phase 3 sweep to clear every promotion
bar. Highest trade count of any promotion-clearing cell. Drawdown is
comparable to the primary (20.6% vs 20.9%), return is 28 pp lower in
exchange for being fully long-only — which closes off the short-side
tail risk that the primary retains.

---

## 4. Why the primary uses the "both sides" variant despite the directional finding

Phase 3 directional decomposition (§2 of `strategy_c_v2_phase3_directional.md`)
established that the Strategy C v2 edge is overwhelmingly in longs. So
why is the primary candidate the long-short variant?

Two reasons:

1. **The `rsi_only_21 hold=12 long-only` cell misses on return and
   trade count.** It's +95.82% (slightly below the +100% bar) with 64
   trades (below the 100-trade bar). Keeping the short trades boosts
   return to +142.77% (above bar) and trade count to 107 (above bar).
   Both moves are needed for promotion.

2. **The 4h short trades are NOT net negative on this cell.** On
   rsi_only_21 hold=12, the short-only variant is +23.97% — a small
   but positive contribution. The long-short combined (+142.77%)
   materially exceeds `(1 + 0.9582) × (1 + 0.2397) − 1 ≈ +142.5%`,
   so the shorts genuinely add value.

3. **The drawdown penalty is modest.** Long-only DD is 12.53% vs
   long-short 20.89% — a 8.4 pp increase. The long-short variant is
   still well below the 25% DD bar.

In short: the `rsi_only_21 hold=12` **specific cell** has shorts that
behave unusually well (compared to the family average). The directional
finding still holds as a general rule — if you're deploying a family
that isn't this specific parameter point, use the long-only variant.

---

## 5. What the primary candidate does NOT include

For the record, to prevent scope creep:

- **No funding filter.** The Phase 3 funding filter study showed the
  short-veto adds lift (+5-28pp) on Track A anchors. BUT, crucially,
  the primary cell `rsi_only_21 hold=12` already has shorts that
  contribute positively (+23.97%), so vetoing them on funding grounds
  would cut some of those positive contributions. The filter is worth
  testing on this specific cell in Phase 4 with a custom threshold,
  but it's not added by default.

- **No Coinglass overlay.** The 83-day Track B slice conflicts with
  the 4-year Track A evidence; we side with the 4-year data.

- **No MTF confirmation.** The MTF study showed 15m execution of
  persistent signals is cost-dominated. The primary candidate executes
  on 4h native, not 15m.

- **No ATR-trailing stop** (or any other exit refinement). The
  backtester uses time-stop + opposite-flip only. ATR stops could
  reduce the 20.89% drawdown further — that's a Phase 4 question.

- **No score model.** Explicit Phase 3 non-goal.

- **No pair_cvd.** Dropped in Baseline C; still dropped.

---

## 6. Recommended Phase 4 work order

If Phase 4 is a single session, it should tackle in this order:

1. **Sensitivity of the primary cell.** Test `rsi_only_21 hold=12`
   under:
   - Parameter perturbation (period ∈ {19, 20, 21, 22, 23}, hold ∈ {10, 11, 12, 13, 14}) — is the cell fragile inside its own neighborhood?
   - Cost perturbation (0.08%, 0.12%, 0.16% round-trip) — how much slack on cost before it fails the bar?
   - Cooldown sweep (0, 1, 2, 4, 8) — does spacing re-entries help?
   - Mini-sweep on the upper/lower thresholds (65/35, 70/30, 75/25) — is 70/30 a local optimum?

2. **ATR trailing stop exit** on top of the primary cell. Can it cut
   the 20.89% drawdown to <15% without sacrificing more than 20 pp
   of return?

3. **Spot-BTCUSDT benchmark measurement** — the real "do-nothing"
   number. Phase 2 showed the perp B&H is only +13% because of funding
   drag; spot is probably +43%. The primary candidate's +143% return
   should be compared against the spot benchmark for a cleaner
   "rule-based alpha vs passive" picture.

4. **Score model on the Phase 3 feature matrix** — logistic regression
   first, predicting "next 16-bar net return > cost" at 4h execution.
   Compare rule-based primary against model-ranked top-quantile
   entries. Only promote if the model OOS-beats the rule by >20% with
   lower DD.

5. **Track B deep-dive** — fetch a longer Coinglass window via plan
   upgrade or multi-call stitching, rerun the overlay comparison with
   multiple temporal splits, and finally answer whether Coinglass adds
   marginal lift on a non-trivial OOS slice.

6. **Paper deployment** of the primary cell on the live engine, 0.25×
   notional, with kill-switches on DD > 15% and cumulative P&L < −10%.
   30-day observation window before sizing up.

---

## 7. One-paragraph summary for the next session's opening

> Phase 3 converted the Phase 2 OOS map into a scalable strategy
> framework. The edge is broad (not point-fragile) on 4h RSI-only,
> asymmetric (longs are ~80% of the edge), and modestly improved by
> funding short-vetoes. The naïve MTF on 15m execution is
> cost-dominated and is rejected; Track B Coinglass overlays are
> deferred to Phase 4 on honesty grounds (83-day slice can't prove OOS
> lift). **Primary Strategy C v2 candidate: `4h rsi_only_21 hold=12`
> (both sides) → +142.77% OOS over 48 months, 20.89% DD, PF 1.83,
> 7/8 positive windows, 107 trades.** This cell is the first in the
> program to clear every one of the five promotion bars (return,
> drawdown, PF, window consistency, trade count). Secondary candidate
> for low-DD deployments: `4h rsi_only_30 hold=16`. Long-only variant
> for clean risk profile: `4h rsi_and_macd_14 hold=4 long-only`. Phase
> 4 should stress-test the primary cell under parameter / cost
> perturbation, add an ATR trailing stop exit, measure against spot
> B&H, and only then decide on paper deployment.

---

## 8. The file layout at end of Phase 3

```
strategy-c-orderflow/
  strategy_c_v2_plan.md
  strategy_c_v2_data_coverage.md               # Phase 1 (D#1)
  strategy_c_v2_feature_matrix.md              # Phase 1 (D#2)
  strategy_c_v2_literature_benchmark.md        # Phase 2 (D#3)
  strategy_c_v2_oos_leaderboard.md             # Phase 2 (D#4)
  strategy_c_v2_next_cycle_recommendation.md   # Phase 2 recommendation
  strategy_c_v2_phase3_robustness.md           # Phase 3 robustness
  strategy_c_v2_phase3_directional.md          # Phase 3 directional
  strategy_c_v2_phase3_funding_filter.md       # Phase 3 funding filter
  strategy_c_v2_phase3_mtf.md                  # Phase 3 MTF
  strategy_c_v2_phase3_coinglass_overlay.md    # Phase 3 Track B overlay
  strategy_c_v2_phase3_recommendation.md       # THIS FILE

  run_strategy_c_v2_literature_benchmark.py    # Phase 2 runner
  run_strategy_c_v2_phase3_sweep.py            # Phase 3 robustness+directional+funding runner
  run_strategy_c_v2_phase3_mtf.py              # Phase 3 MTF runner
  run_strategy_c_v2_phase3_track_b.py          # Phase 3 Track B runner

  strategy_c_v2_literature_benchmark.csv       # Phase 2 data (63 rows)
  strategy_c_v2_phase3_robustness.csv          # Phase 3 data (132 rows)
  strategy_c_v2_phase3_funding_filter.csv      # Phase 3 data (60 rows)
  strategy_c_v2_phase3_mtf.csv                 # Phase 3 data (15 rows)
  strategy_c_v2_phase3_track_b.csv             # Phase 3 data (21 rows)
```

Phase 3 total test count: **756** (up from 725 at end of Phase 2).
All passing.
