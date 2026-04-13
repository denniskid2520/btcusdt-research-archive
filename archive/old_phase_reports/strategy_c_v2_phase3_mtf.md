# Strategy C v2 — Phase 3 Deliverable: Multi-Timeframe Framework Report

_Date: 2026-04-11_
_Status: Phase 3. Tests the 4h → 1h → 15m hierarchical framework._

The Phase 3 brief asked for a "hierarchical strategy family: 4h for regime
/ direction, 1h for setup confirmation, 15m for execution timing only."
This report is the answer to whether that framework, with the existing
persistent-signal literature rules, produces a better trade-off than
single-TF strategies.

**TL;DR: It does not. With persistent RSI signals, 15m execution is
cost-dominated regardless of higher-TF confirmation. The MTF hypothesis
is REJECTED in its current form.** The honest finding is more valuable
than a fake win would be: it tells us the missing piece is *edge-
triggered* signals, not more timeframes.

---

## 1. Test design

- **Execution frame**: 15m (per Phase 3 brief — "15m should be execution-only")
- **Signal rules** tested:
  1. `4h_rsi21_midline` — 4h rsi(21) > 50 → +1, < 50 → −1 (baseline)
  2. `1h_rsi14_midline` — 1h rsi(14) > 50 → +1, < 50 → −1 (baseline)
  3. `mtf_rsi21x14_midline` — AND gate: 4h rsi(21) AND 1h rsi(14) both > 50 → +1 (both < 50 → −1)
  4. `mtf_rsi21(70)x14(50)` — tighter 4h threshold: 4h rsi(21) > 70 AND 1h rsi(14) > 50
  5. `mtf_rsi21x14_long_only` — rule #3 but with short signals zeroed out
- **Hold bars** (15m execution): 32 / 64 / 128 (8h / 16h / 32h wall time)
- Same 8 rolling 24m/6m walk-forward windows, same 0.12% round-trip cost,
  same real funding cashflows.
- Higher-TF features are aligned to 15m via `align_higher_to_lower`,
  which is causally safe: a higher-TF feature at bar k is only visible
  to the lower-TF stream once its period has closed (bar k+1 has opened).

---

## 2. Results

| Strategy              | Hold | Trades | OOS return | Max DD | Pos% | PF    | Exposure |
|-----------------------|-----:|-------:|-----------:|-------:|-----:|------:|---------:|
| 4h_rsi21_midline      |   32 |  4,519 |  −99.63%   | 99.67% |  0.0 | 0.79  |   96.8%  |
| 4h_rsi21_midline      |   64 |  2,508 |  −95.26%   | 95.97% | 12.5 | 0.86  |   98.2%  |
| 4h_rsi21_midline      |  128 |  1,502 |  −83.77%   | 86.89% | 25.0 | 0.90  |   98.9%  |
| 1h_rsi14_midline      |   32 |  6,838 |  −99.96%   | 99.96% |  0.0 | 0.75  |   95.1%  |
| 1h_rsi14_midline      |   64 |  5,136 |  −99.68%   | 99.69% |  0.0 | 0.78  |   96.3%  |
| 1h_rsi14_midline      |  128 |  4,374 |  −99.22%   | 99.25% |  0.0 | 0.77  |   96.9%  |
| mtf_rsi21x14_midline  |   32 |  3,800 |  −99.10%   | 99.18% |  0.0 | 0.80  |   83.8%  |
| mtf_rsi21x14_midline  |   64 |  2,195 |  −94.75%   | 95.58% | 12.5 | 0.86  |   90.1%  |
| mtf_rsi21x14_midline  |  128 |  1,331 |  −82.03%   | 85.55% | 25.0 | 0.90  |   94.5%  |
| mtf_rsi21(70)x14(50)  |   32 |  3,000 |  −97.34%   | 98.25% |  0.0 | 0.80  |   67.9%  |
| mtf_rsi21(70)x14(50)  |   64 |  1,715 |  −82.47%   | 92.43% | 25.0 | 0.90  |   76.6%  |
| mtf_rsi21(70)x14(50)  |  128 |    983 |  −72.16%   | 88.31% | 25.0 | 0.92  |   85.0%  |
| **mtf_rsi21x14_long_only** | **128** |  **632** | **−36.17%** | 51.92% | 50.0 | 0.97  |   57.4%  |
| mtf_rsi21x14_long_only |   64 |  1,086 |  −60.24%   | 62.29% | 25.0 | 0.91  |   49.5%  |
| mtf_rsi21x14_long_only |   32 |  1,924 |  −81.92%   | 82.57% | 25.0 | 0.85  |   43.8%  |

**Every cell is negative.** The best cell (`mtf_rsi21x14_long_only
hold=128`) is still −36.17% over 4 years of OOS, versus the 4h-native
equivalent (`4h rsi_only_21 hold=12 on 4h` → **+142.77%**). That is a
spread of roughly 180 percentage points between the same rule on 4h
execution vs 15m execution.

---

## 3. Why the framework fails in this form

The diagnosis is mechanical, not strategic:

1. **Persistent signals + dense execution frame = trade count explosion.**
   The literature signal emits +1 at every bar where RSI > 50. In 4h
   bars that's ~2-4 consecutive signals per regime cycle; the backtester
   opens one trade per regime and holds it. In 15m bars the same
   regime emits 16x as many signals. With a hold=32 time-stop and
   cooldown=0, the backtester enters a fresh trade every 32 bars, so
   one 4-day long regime becomes **12 back-to-back long trades** on 15m
   execution instead of 1 on 4h execution.
2. **Each trade pays the full 0.12% round-trip.** 12 trades = 1.44% in
   cost where a single 4h trade would have paid 0.12%.
3. **Each trade also pays pro-rated funding.** Exposure time stays near
   100% because the strategy is almost always long or short — the 28%
   4-year funding drag compounds on top of the trading cost.
4. **The AND-gate does not reduce the trade count enough.** Requiring
   1h confirmation drops exposure from ~96% to ~84%, but 84% of 15m bars
   is still ~176,000 bar-signals, which produces thousands of trades.

The 4h execution of the same rule wins because it generates **one trade
per signal epoch**, not dozens. It's not that 4h is a "better" timeframe
— it's that 4h execution naturally produces a sparse trade stream, and
sparse-trade + 0.12% cost = viable. Dense-trade + 0.12% cost = not viable.

---

## 4. Comparison against the single-TF native benchmarks

For orientation, the Phase 3 robustness winners (same walk-forward,
same cost, same funding):

| Cell                                   | Execution | OOS return | DD     |
|----------------------------------------|----------:|-----------:|-------:|
| 4h rsi_only_21 hold=12                 | **4h**    | **+142.77%** | 20.89% |
| 4h rsi_only_30 hold=16                 | 4h        | +138.41%   | 13.92% |
| 1h rsi_and_macd_14 hold=32             | 1h        | +106.11%   | 41.61% |
| mtf_rsi21x14_long_only hold=128        | **15m**   | **−36.17%** | 51.92% |
| 4h_rsi21_midline hold=128              | **15m**   | **−83.77%** | 86.89% |

**The spread between 4h execution of RSI(21) and 15m execution of the
same feature is ~230 percentage points.** The signal is identical; only
the trade frequency differs.

---

## 5. What would be needed to rescue MTF on 15m execution

Two structural changes would unlock 15m execution for MTF strategies:

1. **Edge-triggered signals instead of persistent signals.** Fire +1 at
   the exact 15m bar where the higher-TF rsi crossed 50 (not at every
   bar it stays above 50). One signal per regime flip, not thousands.
2. **Stronger cooldown between trades on 15m execution.** Even with
   persistent signals, a large cooldown (e.g. 64-128 bars) would force
   sparser trading and let the cost model breathe. But this is just
   simulating "fewer trades via cooldown" — it's a workaround, not a
   principled fix.

Both are legitimate Phase 4 work. Neither fits in the remaining Phase 3
time budget.

---

## 6. What the MTF test DID prove (the positive finding)

1. **The `align_higher_to_lower` primitive works** — it correctly maps
   4h and 1h feature values down to 15m bar timestamps without
   look-ahead. Verified by 12 unit tests. This is a reusable infra
   component for any future MTF work.
2. **The long-only filter cuts drawdowns on MTF too.** The long-only
   variant of `mtf_rsi21x14` has ~40% lower drawdown than the
   long-short variant at hold=128 (51.92% vs 85.55%) — consistent with
   the directional decomposition finding.
3. **Higher hold_bars are less bad than shorter** on 15m execution —
   because they thin out the trade count. hold=128 cells are
   systematically better than hold=32 cells across every MTF variant.
4. **Multi-timeframe confirmation DOES thin the signal stream** —
   `mtf_rsi21(70)x14(50)` has the lowest exposure (67.9-85% vs 95-99%
   for single-TF) and the best returns among MTF variants — but still
   not enough to cross zero.

---

## 7. Implications for the Phase 3 recommendation

1. **Drop 15m-execution MTF from consideration as a primary Strategy C
   candidate.** It doesn't work under persistent-signal rules and the
   cost model we're committed to.
2. **Keep 15m as a pure EXECUTION frame**, not a signal frame — i.e.,
   the 4h signal should trigger entry at the NEXT 15m bar open (not
   replicate across all 15m bars). That's a trivial refinement and
   doesn't change the Phase 3 choice of primary candidate.
3. **The primary candidate remains the 4h rsi_only family** (see
   `strategy_c_v2_phase3_recommendation.md`). The Phase 3 robustness
   + directional + funding work identifies the right cell; the MTF
   framework does not improve it in its current form.
4. **Revisit MTF in Phase 4** with edge-triggered signals AND a more
   sophisticated exit rule (ATR trailing, score-based). The
   infrastructure (`align_higher_to_lower`, `mtf_trend_signals`) is in
   place for reuse.

---

## 8. Honest note on what this report is not

This report does NOT disprove the general idea that multi-timeframe
confirmation is useful. It disproves a specific, naive implementation:
persistent signals + dense execution + full-market exposure. A smarter
MTF design — edge-triggered, low-exposure, with ATR stops — could
plausibly succeed. But that's future work, and the Phase 3 candidate
selection does not depend on it.

The Phase 3 rule-based framework lands in `strategy_c_v2_phase3_recommendation.md`
on the back of the robustness + directional + funding findings, with
MTF as a deferred line item.
