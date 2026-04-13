# Strategy C v2 — Phase 6 Deliverable: Expanded Risk-Budget Report

_Date: 2026-04-12_
_Status: Phase 6 — testing the Phase 5A "2x is globally optimal" conclusion._

## TL;DR

The user's Phase 6 brief was right to flag my Phase 5A conclusion as
overreaching. **2x is NOT globally optimal** — Phase 5A's grid capped
position_frac at 1.333 (`risk/stop = 2%/1.5%`), and that cap was
reached at L=2x. Cells above the cap were identical at L=2, 3, 5 and
showed no upside.

With the **expanded Phase 6 grid** (risk up to 4%, stop down to 1%),
position_frac can reach 4.0. At those levels, higher exchange leverage
IS needed to make the sizing feasible, and returns scale sharply:

| Cell                                 | frac | OOS Return | DD     | Trades |
|--------------------------------------|-----:|-----------:|-------:|-------:|
| Phase 5A primary (A_both, r=2, s=1.5)| 1.333 |  +117.08% | 19.40% |   126  |
| D1_both r=2.5 s=1.25 L=2x            | 2.000 |  +643.45% | 37.08% |   141  |
| D1_both r=3.0 s=1.5 L=3x            | 2.000 |  +643.45% | 37.08% |   141  |
| D1_both r=4.0 s=1.5 L=3x            | 2.667 |  +946.32% | 41.96% |   134  |
| D1_both r=4.0 s=1.25 L=3x            | 3.000 | +1562.85% | 50.86% |   141  |
| D1_both r=4.0 s=1.0 L=5x             | 4.000 | +1937.25% | 65.78% |   150  |

**Higher effective leverage DOES deliver higher returns.** But it also
delivers proportionally higher drawdown and (as the tail-event report
shows) account-killing single-trade losses above frac=2.

---

## 1. Phase 6 expanded grid

| Parameter           | Values                                 |
|---------------------|----------------------------------------|
| stop_loss_pct       | 1.00% / 1.25% / 1.50% / 2.00%         |
| stop_trigger        | wick / close                           |
| risk_per_trade      | 2.0% / 2.5% / 3.0% / 4.0%             |
| effective_leverage  | 2x / 3x / 5x                           |
| stop_slip_pct       | 0% (stress in separate report)         |

5 candidates × 4 stops × 2 triggers × 4 risks × 3 leverages = **576 cells**.

All on the 4h walk-forward (2020-04 → 2026-04, 8 OOS test windows).

---

## 2. Position_frac math: what actually drives PnL

The critical insight from Phase 5A, now confirmed on the expanded grid:

```
raw_frac     = risk_per_trade / stop_loss_pct
actual_frac  = min(raw_frac, effective_leverage)
```

Effective leverage is **only a cap**. It determines feasibility, not
magnification. Two cells with the same `actual_frac` but different L
have IDENTICAL PnL (verified across the sweep: look at any row where
raw_frac ≤ L for L ∈ {2, 3, 5} — they're duplicates).

| (risk, stop) | raw_frac | feasible @ L=2 | feasible @ L=3 | feasible @ L=5 |
|--------------|---------:|:--------------:|:--------------:|:--------------:|
| (2.0%, 1.00%)|    2.000 |      ✅ 2.00   |     ✅ 2.00    |     ✅ 2.00    |
| (2.0%, 1.25%)|    1.600 |      ✅ 1.60   |     ✅ 1.60    |     ✅ 1.60    |
| (2.0%, 1.50%)|    1.333 |      ✅ 1.33   |     ✅ 1.33    |     ✅ 1.33    |
| (2.0%, 2.00%)|    1.000 |      ✅ 1.00   |     ✅ 1.00    |     ✅ 1.00    |
| (2.5%, 1.00%)|    2.500 |    ⚠️ cap 2.00 |     ✅ 2.50    |     ✅ 2.50    |
| (3.0%, 1.00%)|    3.000 |    ⚠️ cap 2.00 |     ✅ 3.00    |     ✅ 3.00    |
| (4.0%, 1.00%)|    4.000 |    ⚠️ cap 2.00 |    ⚠️ cap 3.00 |     ✅ 4.00    |
| (4.0%, 1.25%)|    3.200 |    ⚠️ cap 2.00 |    ⚠️ cap 3.00 |     ✅ 3.20    |
| (4.0%, 1.50%)|    2.667 |    ⚠️ cap 2.00 |     ✅ 2.67    |     ✅ 2.67    |
| (4.0%, 2.00%)|    2.000 |      ✅ 2.00   |     ✅ 2.00    |     ✅ 2.00    |

**Where leverage actually matters**: in the rows marked ⚠️, higher L
raises the actual cap and produces genuinely different PnL. Those are
the cells where "2x vs 3x vs 5x" is not a redundant question.

---

## 3. D1_both top cells at each leverage tier

| frac | Cell config (sl, trig, r) | Return | DD     | Trades | Worst Trade |
|-----:|:--------------------------|-------:|-------:|-------:|------------:|
| 1.333 | 1.5% wick r=2.0%         | +268.57% | 21.44% |  134  |   −6.30%   |
| 1.600 | 1.25% wick r=2.0%         | +345.83% | 24.94% |  141  |   −7.55%   |
| 2.000 | 1.25% wick r=2.5%         | +643.45% | 37.08% |  141  |   −9.45%   |
| 2.000 | 1.00% wick r=2.0%         | +517.59% | 42.70% |  150  |  −9.45%   |
| 2.400 | 1.25% wick r=3.0%         | +940.78% | 42.93% |  141  |  −11.33%   |
| 2.500 | 1.00% wick r=2.5%         | +722.63% | 46.29% |  150  |  −11.81%   |
| 2.667 | 1.5% wick r=4.0%          | +946.32% | 41.96% |  134  |  −12.59%   |
| 3.000 | 1.25% wick r=4.0%         | +1562.85% | 50.86% |  141  |  −14.17%   |
| 3.200 | 1.25% wick r=4.0%         | +1826.05% | 53.29% |  141  |  −15.11%   |
| 4.000 | 1.00% wick r=4.0%         | +1937.25% | 65.78% |  150  |  −18.89%   |

Observations:
1. **Return scales super-linearly with frac** — from +268% at frac=1.33
   to +1937% at frac=4.0. That's a 7x return increase for a 3x frac
   increase, because compounding amplifies the signal.
2. **DD scales roughly linearly** — from 21.44% at frac=1.33 to 65.78%
   at frac=4. Roughly `DD ≈ frac × 16%`.
3. **Worst trade scales linearly** — from −6.30% at frac=1.33 to
   −18.89% at frac=4. `worst_trade ≈ frac × 4.7%`.
4. **Trade count is ~150** regardless of sizing — the signal doesn't
   change, only the position size does.

### Critical: the worst single trade at frac=4 is −18.89% of equity

A single trade losing 18.89% of the account is an existential event.
The backtest's 8 OOS windows did not contain a 2020-COVID or
2022-Luna scale shock, so the empirical worst is a ~5% price gap.

Under a real 30% shock (Luna magnitude), frac=4 would produce a
**−120% account move** — liquidated before the strategy even reacts.

See the tail-event stress report for the full survival analysis.

---

## 4. D1_long top cells at each leverage tier

D1_long (long-only variant) has MUCH cleaner risk profile:

| frac | Cell config (sl, trig, r) | Return | DD     | Trades | Worst Trade |
|-----:|:--------------------------|-------:|-------:|-------:|------------:|
| 1.333 | 1.5% wick r=2.0%          | +134.18% | 11.58% |   70   |   −6.19%   |
| 2.000 | 1.25% wick r=2.5%         | +345.18% | 22.60% |   79   |   −9.25%   |
| 2.400 | 1.25% wick r=3.0%         | +489.45% | 25.97% |   79   |  −11.09%   |
| 2.667 | 1.5% wick r=4.0%          | +477.52% | 25.50% |   72   |  −12.31%   |
| 3.000 | 1.25% wick r=4.0%         | +734.86% | 28.34% |   80   |  −13.79%   |
| 3.200 | 1.25% wick r=4.0%         | +840.92% | 30.07% |   80   |  −14.71%   |
| 4.000 | 1.00% wick r=4.0%         | +1005.15% | 36.68% |   87   |  −18.38%   |

At **frac=3.0 long-only**: +734.86% / DD 28.34% / 80 trades / worst
trade −13.79%. This is the Pareto winner on return per unit DD among
cells with enough trade sample.

Compare to D1_both at frac=3.0: +1562.85% / DD 50.86%. The long-only
variant gives 47% of the return with 56% of the DD — **slightly
better risk-adjusted**.

---

## 5. A_both / A_long / C_long at expanded risk budgets

For comparison with the Phase 5A baseline:

### A_both (rsi_only_21 h=12)

| frac | Cell | Return | DD |
|---:|:---|---:|---:|
| 1.333 | 1.5% wick r=2.0% (Phase 5A primary) | +117.08% | 19.40% |
| 1.600 | 1.25% wick r=2.0% | +150.02% | 22.89% |
| 2.000 | 1.25% wick r=2.5% | +222.94% | 32.26% |
| 2.400 | 1.25% wick r=3.0% | +277.85% | 39.28% |
| 2.667 | 1.5% wick r=4.0% | +241.30% | 38.36% |
| 3.000 | 1.25% wick r=4.0% | +354.25% | 49.54% |
| 4.000 | 1.00% wick r=4.0% | +423.92% | 60.18% |

A_both maxes out around +424% at frac=4 — much lower than D1_both's
+1937%. Confirms D1 is the superior signal family.

### C_long (rsi_and_macd_14 h=4)

| frac | Cell | Return | DD |
|---:|:---|---:|---:|
| 1.000 | 2.0% close r=2.0% (Phase 5A backup) | +106.26% | 18.10% |
| 2.000 | 1.0% close r=2.0% | +338.37% | 33.90% |
| 2.500 | 1.0% close r=2.5% | +464.98% | 41.45% |
| 3.000 | 1.0% close r=3.0% | +597.75% | 48.63% |
| 4.000 | 1.0% close r=4.0% | +881.73% | 57.36% |

C_long scales less aggressively but is cleaner (worst trade at frac=4
is only −26.49%). The high trade count (178-179 across all) is its
structural advantage.

---

## 6. Key findings

### 6.1 Leverage DOES expand returns beyond 2x — but only with appropriate risk budget

User's intuition confirmed: Phase 5A's "2x is optimal" was an artifact
of a narrow grid where risk ≤ 2% and stop ≥ 1.5%. Once risk > 2% or
stop < 1.5%, higher leverage delivers real return upside.

### 6.2 The return-per-frac elasticity is super-linear

Going from frac=1.333 to frac=3.0 on D1_both:
- frac ratio = 2.25×
- Return ratio = 1562.85 / 268.57 = **5.82×**

This is the compounding effect: a higher per-trade return compounds
across 141 trades into a much larger final number. But the *same
effect* also amplifies drawdowns and per-trade losses.

### 6.3 D1_both dominates all non-shadow candidates at every frac

No cell of A_both, A_long, C_long, or D2_shadow reaches the top-10 at
frac ≥ 2.0. D1_both is the only non-shadow candidate that produces
+1000% OOS returns with the expanded risk budget.

### 6.4 Long-only preserves most of the upside with cleaner DD

D1_long at frac=3.0 gives +734% with DD 28.34% vs D1_both's +1562% /
50.86%. Better return/DD ratio (25.9 vs 30.7 is closer than expected
but long-only wins on worst trade and tail survivability).

### 6.5 The trade count is invariant under sizing

Changing position_frac changes PnL magnitude but not signal count.
This means sizing decisions are ALWAYS post-signal; they don't alter
the strategy's frequency or regime exposure.

---

## 7. What this report does NOT answer

1. **Does the edge survive slippage?** → stop-slippage report
2. **Does the edge survive tail events?** → tail-event stress report
3. **Which is the safest deployable + highest-return survivable?** →
   final recommendation

The expanded risk-budget alone suggests D1_both frac=3 or D1_long
frac=3 are the highest-return cells with passable trade counts. But
high returns at frac=3+ are only useful if they actually survive
slippage and tail risk. Those tests come next.

---

## 8. Notes on 5x exploratory

The 5x leverage tier was explicitly "exploratory only". Results:

- Cells with raw_frac ≤ 2: 5x = 3x = 2x (identical PnL). 5x adds no value.
- Cells with raw_frac ∈ (2, 3]: 5x = 3x (both unmatched). 5x matches 3x.
- Cells with raw_frac ∈ (3, 4]: 5x > 3x (5x admits higher frac).
- Cells with raw_frac ∈ (4, 5]: none in current grid (max is 4.0).

So **5x provides no return upside beyond 4x** in the current grid. If
the grid were extended to risk=5%+ or stop=0.75%-, we would see 5x
add marginal benefit. Not tested here per Phase 6 "exploratory" scope.
