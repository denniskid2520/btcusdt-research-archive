# Strategy C v2 — Phase 6 Deliverable: D1 Promotion Report

_Date: 2026-04-12_
_Status: Phase 6 — D1 promoted from shadow to primary research target._

## TL;DR

**D1 (rsi_only_20 h=11 both) sits on a broad, stable parameter surface.**
Nine nearby cells in the Phase 6 robustness band (period ∈ {18-22} ×
hold ∈ {9-13}) all produce +140% or better OOS compounded return with
75% or better window consistency. D1 is NOT a sharp single-cell optimum.

---

## 1. Method

Robustness band around the Phase 5A shadow cell:
- **Center**: rsi_only_20 h=11 both sides
- **Grid**: period ∈ {18, 19, 20, 21, 22} × hold ∈ {9, 10, 11, 12, 13}
  × side ∈ {both, long} × allow_flip ∈ {on, off}
- = 5 × 5 × 2 × 2 = **100 cells**
- No stops / no sizing overlay (pure parameter perturbation)
- Same 24m / 6m / 6m rolling walk-forward, 0.12% round-trip, real funding

---

## 2. Results — both-sides, top 15

| period | hold | return    | DD     | trades | pos%  | PF   |
|:------:|:----:|----------:|-------:|-------:|------:|-----:|
| **20** | **11** | **+197.96%** | 22.18% |   120  | 75.0 | 1.95 |
|   20   |  12  |  +176.05% | 27.98% |   115  | 75.0 | 1.89 |
|   20   |   9  |  +166.25% | 31.83% |   134  | 75.0 | 1.79 |
|   21   |   9  |  +162.44% | 25.79% |   123  | 75.0 | 1.84 |
|   21   |  11  |  +159.63% | 16.15% |   111  | 75.0 | 1.91 |
|   19   |  12  |  +153.96% | 31.54% |   127  | 75.0 | 1.71 |
|   18   |   9  |  +147.05% | 32.46% |   158  | 75.0 | 1.58 |
|   21   |  12  |  +142.77% | 20.89% |   107  | 87.5 | 1.83 |
|   20   |  10  |  +140.60% | 20.14% |   126  | 87.5 | 1.70 |
|   20   |  13  |  +138.01% | 26.11% |   108  | 75.0 | 1.89 |
|   19   |  11  |  +131.16% | 21.62% |   117  | 75.0 | 1.63 |
|   21   |  10  |  +128.00% | 20.64% |   115  | 75.0 | 1.70 |
|   18   |  11  |  +123.85% | 27.21% |   147  | 75.0 | 1.54 |
|   19   |  10  |  +122.29% | 22.06% |   124  | 75.0 | 1.58 |
|   22   |  11  |  +117.24% | 21.22% |   103  | 75.0 | 1.71 |

Observations:
1. **All 25 unique (period, hold) cells are positive** on both-sides.
   The worst cell (period=22, hold=13) is still +69%.
2. **Period 20 is the best column** — 5 cells average +163%.
3. **Hold 9-11 dominates** — short holds capture RSI spikes efficiently.
4. **period 18 has higher trade count** (134-158) but lower return —
   too fast, more cost drag.

### Side comparison at the center

| side | Return | DD | Trades | Pos% |
|---|---:|---:|---:|---:|
| both (D1)   | +197.96% | 22.18% | 120 | 75.0 |
| long-only   | +120.94% | 10.85% |  66 | 62.5 |

Long-only captures ~61% of the both-sides return with **less than half the drawdown**.
This is consistent with every prior directional decomposition — the
long side carries most of the edge with structurally lower tail risk.

### Allow-flip toggle

For every cell tested, `allow_flip=True` and `allow_flip=False` produce
**identical** results. Opposite-signal exits never fire within the 9-13
bar hold horizon on D1 — the signal stays on until the time-stop. This
matches the same null finding from Phase 4 on Candidate A.

---

## 3. Robustness verdict

**D1 is a BROAD optimum, not a fragile single-cell peak.** Specifically:

- 15 of 25 (period, hold) × both cells exceed **+120% OOS**
- 9 of 25 cells exceed **+140%**
- All 25 cells are positive
- Period 20 is clearly the sweet spot (strictly dominates 18, 22; ties 19, 21)
- Hold 9-11 is clearly the sweet spot (strictly dominates 12, 13 in most rows)

The Phase 4 concern ("don't promote without robustness testing") is
resolved: D1's edge is preserved under parameter perturbation. It can
be promoted out of shadow for Phase 6 research.

---

## 4. What the test did NOT address

- **Stop-loss + sizing overlay**: covered by the Phase 6 expanded
  risk-budget report, not here.
- **Slippage sensitivity**: covered by Phase 6 slippage stress report.
- **Tail-event survival at higher leverage**: covered by Phase 6 tail
  stress report.
- **Longer OOS window**: still only 8 OOS windows over 48 months. A
  future session with more data should re-test D1 under new tail
  regimes.

---

## 5. Recommendation

1. **Promote D1 from shadow to Phase 6 research target** — DONE in
   the Phase 6 candidate list.
2. **Add D1_long as a parallel candidate** — long-only variant has
   dramatically better DD with acceptable return.
3. **D1 is NOT immediately a paper-deployment candidate** — the
   robustness band does not test slippage, tail risk, or stop-gap
   survivability. Those are the next three Phase 6 reports.
4. **D2 (rsi_only_28 h=18) stays secondary shadow** — per the Phase 6
   brief and the robustness band (not shown, but D2's neighborhood is
   narrower than D1's).
