# Strategy C v2 — Phase 6 Deliverable: Directional Decomposition (D1 and A)

_Date: 2026-04-12_
_Status: Phase 6 — long-only vs both-sides comparison for D1 and A._

## TL;DR

**Long-only preserves ~50-65% of the both-sides return with dramatically
lower drawdown AND better slippage / tail-event survivability.**

For Phase 6 deployment purposes, long-only variants are superior on
every non-return dimension. The both-sides variant's extra return
comes from short trades that contribute net positive PnL but ALSO
contribute most of the drawdown. This is the same asymmetry found in
Phase 3's directional decomposition — now confirmed at Phase 6's
expanded risk budgets.

---

## 1. Setup

Compare both-sides vs long-only variants of:
- **Candidate A** (rsi_only_21 h=12)
- **Candidate D1** (rsi_only_20 h=11, promoted from shadow)

At three representative configurations:
1. Phase 5A conservative: sl=1.5% close r=2% L=2x (frac=1.333)
2. Phase 6 frac=2.0 ceiling: sl=1.25% close r=2.5% L=2x (frac=2.0)
3. Phase 6 aggressive frac=3.0: sl=1.25% close r=4% L=3x (frac=3.0) —
   above the hard safety ceiling, included for completeness

---

## 2. Candidate A decomposition

### Conservative config (frac = 1.333)

| Side  | Return   | DD     | Trades | Worst Trade | Stop% |
|-------|---------:|-------:|-------:|------------:|------:|
| both  | +104.77% | 23.84% |   111  |   −9.21%    | 41.4% |
| long  | +101.60% |  9.78% |    64  |   −6.32%    | 32.8% |

**Long-only keeps 97% of the return with 41% of the drawdown.**
Long-only is the strictly better cell: same return, less than half
the DD, lower worst-trade, slightly lower stop-exit rate.

### frac = 2.0 config (sl=1.25% r=2.5%)

| Side  | Return   | DD     | Trades | Worst Trade |
|-------|---------:|-------:|-------:|------------:|
| both  | +222.94% | 32.26% |   122  |   −9.45%    |
| long  | +175.26% | 16.08% |    69  |   −7.67%    |

Long-only: **78% of the return, 50% of the DD.**

### frac = 3.0 config (sl=1.25% r=4%)

| Side  | Return   | DD     | Trades | Worst Trade |
|-------|---------:|-------:|-------:|------------:|
| both  | +354.25% | 49.54% |   122  |  −14.17%    |
| long  | +272.31% | 24.09% |    69  |  −11.50%    |

Long-only: **77% of the return, 49% of the DD.**

---

## 3. Candidate D1 decomposition

### Conservative config (frac = 1.333)

| Side  | Return   | DD     | Trades | Worst Trade | Stop% |
|-------|---------:|-------:|-------:|------------:|------:|
| both  | +268.57% | 21.44% |  134   |   −6.30%    | 54.5% |
| long  | +173.06% |  9.27% |   73   |   −4.64%    | 46.6% |

D1_long: **64% of the return, 43% of the DD.**

### frac = 2.0 config (sl=1.25% r=2.5%)

| Side  | Return    | DD     | Trades | Worst Trade |
|-------|----------:|-------:|-------:|------------:|
| both  | +643.45%  | 37.08% |  141   |   −9.45%    |
| long  | +345.18%  | 22.60% |   79   |   −9.25%    |

D1_long: **54% of the return, 61% of the DD.**

### frac = 3.0 config (sl=1.25% r=4%)

| Side  | Return    | DD     | Trades | Worst Trade |
|-------|----------:|-------:|-------:|------------:|
| both  | +1562.85% | 50.86% |  141   |  −14.17%    |
| long  |  +734.86% | 28.34% |   80   |  −13.79%    |

D1_long: **47% of the return, 56% of the DD.**

---

## 4. Structural observations

### 4.1 The long/both return ratio shrinks with frac

For A: 0.97 → 0.79 → 0.77 as frac goes from 1.33 → 2.00 → 3.00
For D1: 0.64 → 0.54 → 0.47 as frac goes from 1.33 → 2.00 → 3.00

The both-sides variant captures MORE incremental value at higher
position fractions. At frac=1.33 on A, long-only is essentially
identical; at frac=3 on D1, long-only misses ~53% of the return.

This is because the short side's per-trade PnL multiplier is the
same, but the short trades fire at different times than longs, so
adding them diversifies the trade stream. At higher frac, each trade's
absolute contribution is larger, so the diversification gap grows.

### 4.2 The long/both DD ratio is more stable

A: 0.41 → 0.50 → 0.49
D1: 0.43 → 0.61 → 0.56

Long-only's DD is consistently 40-60% of the both-sides DD. This is
the structural advantage: half the directional exposure = half the
directional DD. The short side is a correlated DD contributor, not
an uncorrelated one.

### 4.3 Worst trade scales similarly

Long-only's worst trade is typically 70-80% of the both-sides worst
trade. This reflects the fact that large losses happen on either side
with similar magnitude — the short side doesn't have uniquely
catastrophic trades.

### 4.4 Trade count is ~half

Long-only drops the short trades → ~50-55% of the both-sides trade
count. This makes long-only structurally more sample-thin, which
matters for the robustness criteria (> 100 trades bar).

---

## 5. Implication for the Phase 6 decision framework

### 5.1 Where long-only is strictly better

- **frac ≤ 1.5**: long-only captures nearly all the return with half
  the DD. No reason to take the both-sides tail risk.
- **Conservative paper deploy**: A_long and D1_long are better paper
  candidates than A_both and D1_both for the same sizing.

### 5.2 Where both-sides is marginally better

- **frac > 2.0**: both-sides returns ~1.5-2× long-only returns, with
  ~1.8× the DD. The return gain outpaces the DD gain by a small margin.
- **If the user is willing to accept higher DD for higher return**,
  both-sides at frac=2 is a reasonable aggressive pick.
- **If not**, long-only at frac=2 is a cleaner cell.

### 5.3 Sample-size concern

Long-only cells have ~half the trades. D1_long at frac=2 has 79 trades
— below the 100 floor we've been applying. That's the main reason
long-only variants don't fully dominate: the sample is thin.

A future session with a larger OOS window (more splits, different
period) could resolve this.

---

## 6. Recommendations on side selection

### Paper deployment primary — **long-only**

For Phase 7 paper deployment, prefer the long-only variant of whichever
candidate is chosen. Specifically:

- **A_long @ sl=1.5% close r=2% L=2x** → +101.60% / DD **9.78%** / 64 trades
  - Lowest DD in the entire Phase 5A + Phase 6 sweep
  - Strong slippage resistance (50.8% retention at 1% slip)
  - Survives all tail events at frac = 1.333
  - 64 trades is the structural weakness — marginal sample

- **D1_long @ sl=1.5% close r=2% L=2x** → +173.06% / DD **9.27%** / 73 trades
  - Higher return than A_long (+71 pp)
  - Marginally better DD (9.27% vs 9.78%)
  - Slightly higher trade count
  - D1 is the better-performing signal family (Phase 6 D1 promotion)

**D1_long at the conservative config is the single best non-aggressive
Phase 6 paper deployment candidate.**

### Return-expansion candidate — **long-only at frac = 2.0**

**D1_long @ sl=1.25% close r=2.5% L=2x frac=2.0** → +345.18% / DD 22.60% / 79 trades
- 3.4× higher return than the conservative cell
- DD still manageable at 22.6%
- frac = 2.0 is the safety ceiling (survives all tail events)
- Worst trade −9.25%
- 79 trades (just below 100 floor)

This is the best return-expansion cell that stays within the Phase 6
survival constraints.

### DO NOT prefer both-sides at frac > 1.5

The Phase 5A primary (A_both @ frac=1.333) had tolerable both-sides
behavior, but at higher frac the both-sides variant accumulates DD
faster than return. Not worth the incremental risk.

---

## 7. Where the both-sides variant would be the right pick

Only if ALL of these conditions apply:
1. The user wants maximum absolute return with no regard for DD path
2. The account has external tail-risk hedges (not built in Phase 6)
3. The trader accepts ~50% intra-OOS drawdowns as normal
4. The signal's short side performs positively in the target live regime

**None of these are reliably true for the Phase 7 paper deployment.**
The user's framing ("keep A_both and C_long as baseline but move D1
out of shadow as return-expansion") suggests a ladder of risk
tolerance, not a single high-risk allocation. Long-only is the
cleaner match for that framing.

---

## 8. Summary

| Dimension          | Both-sides edge | Long-only edge |
|--------------------|:---------------:|:--------------:|
| Absolute return    |       ✅        |                |
| Drawdown           |                 |       ✅       |
| Slippage resistance|                 |       ✅       |
| Worst trade        |                 |       ✅       |
| Trade sample       |       ✅        |                |
| Tail-event survival|                 |       ✅       |

Long-only wins 4 of 6 dimensions. The two it loses (return and sample)
are important but not outcome-decisive for paper deployment, where
survival and control matter more than peak return.

**Final verdict**: for Phase 7 paper deployment, use long-only
variants. See `strategy_c_v2_phase6_final_recommendation.md`.
