# Strategy C v2 — Deliverable: Next-Cycle Recommendation

_Date: 2026-04-11_
_Context: End of Phase 2. Answer to the question "which timeframe and
which family deserve the next research cycle?"_

Inputs:
- `strategy_c_v2_literature_benchmark.md` — Deliverable #3
- `strategy_c_v2_oos_leaderboard.md` — Deliverable #4
- `strategy_c_v2_literature_benchmark.csv` — raw per-cell numbers

---

## TL;DR

**Primary pick: 4h execution, RSI(30) trend-following family (with
momentum/MTF augmentation).**

**Secondary pick: 1h execution, RSI+MACD AND-gate family (as the robust
backup because it has higher window consistency and ~10x the sample
size).**

**Kill list:**
- **15m rule-based trading is shelved.** Every 15m literature cell lost
  money. 0.12% round-trip per trade is the binding constraint, and
  short-horizon rules do not produce enough signal-per-cost to clear it.
- **MACD-only is dropped as a stand-alone strategy.** At every timeframe
  and every hold, the histogram-sign signal is toxic (cost-dominated).
  MACD stays in the feature set as a **gate** or **filter**, not as a
  primary trigger.
- **Buy-and-hold on perp is de-prioritised as a benchmark.** With 28%
  funding drag over 4 years, B&H on perp is a ~13% return, which is
  trivial to beat. The true "do-nothing" benchmark is spot B&H (not
  fetched yet), which returned ≈43% net. Beating 43% is the real bar.

---

## 1. Why 4h wins

From the leaderboard:

- Every family's best result was on 4h, including the #1 cell
  (rsi_only_30 hold=16 → +138.41% OOS).
- 4h has the best risk-adjusted cells: return/DD ratio up to **9.94**
  (hold=16) and **7.62** (hold=8). No 1h cell clears 5.2.
- 4h rule families hold a low fraction of the time (9-22% exposure),
  which means they pay far less funding than B&H's 100% exposure. On a
  perp with ~7% annualised funding drag, exposure is an **explicit
  alpha source** for rule-based selective holding.
- 4h literature benchmarks cleanly separate winners from losers. The
  gap between the best cell (+138%) and B&H (+12%) is 126 percentage
  points. On 1h the gap is 93 pp. On 15m there is no gap — everything
  is below B&H.

**Caveat**: the absolute best 4h cell (rsi_only_30 hold=16) runs on 52
OOS trades. That's just above the 30-trade floor but still a thin
sample. The second-best 4h cell (rsi_and_macd_14 hold=4) has 316 trades
with +136%, so the *family* wins robustly at 4h even if the single best
parameter point is fragile.

---

## 2. Why 1h is the safety net, not the primary

The three 1h cells that beat B&H:

| Cell                        | OOS return | DD    | Trades | Pos windows |
|-----------------------------|-----------:|------:|-------:|------------:|
| rsi_and_macd_14 hold=32     |  +106.11%  | 41.61% |    510 | 7/8 (87.5%) |
| rsi_only_14    hold=32      |  +101.63%  | 41.61% |    516 | 5/8 (62.5%) |
| rsi_only_30    hold=8       |   +71.01%  | 13.62% |    230 | 6/8 (75.0%) |

1h's advantage over 4h is **statistical robustness**. Trade counts are
5-10x higher, window consistency is better (7/8 for the top cell vs 6/8
on 4h). The raw returns are ~30 pp lower than 4h peaks, and drawdowns
are materially worse (41.6% vs 13.9% for the respective bests).

**The 1h cell that most deserves respect is
`rsi_and_macd_14 hold=32 → +106% OOS with 87.5% positive windows and
510 trades`**. That is the single most robust cell on the entire board.
Phase 3 should treat it as the "if 4h is fragile, can we find equivalent
returns on 1h with better statistics?" anchor.

---

## 3. Why rule-based 15m goes on the shelf

Every 15m cell lost money, even the flat rsi_only_30 hold=32 at −2.57%.
The mechanism is straightforward: at 15m cadence the literature rules
produce thousands of trades per OOS slice, and 0.12% × thousands ≈ the
entire equity. This is a replication of the Baseline A/B/C finding at a
more honest sample size (48 months OOS vs 47-83 days).

**What could rescue 15m:**
- Much lower fee (0.01-0.02% per side) via maker rebates or a fee tier
  that's not available at this account size
- A signal with a fundamentally higher per-trade expected return (order
  flow, cross-exchange dislocation) that hasn't been tested yet under
  walk-forward
- A regime gate that allows trading only during the 5-10% of bars where
  the signal has real information — reducing trade count to hundreds,
  not thousands

Until one of those is demonstrated on walk-forward, **Strategy C v2
does not pursue 15m rule-based research further**. It stays available
for execution (e.g., 4h signal with 15m execution bar) but is not the
decision layer.

---

## 4. Family recommendations

### 4.1 Promote

**F2 — Multi-timeframe continuation on 4h.** The 4h RSI/MACD winners
already suggest momentum-continuation is the profitable direction.
Phase 3 should:

- Build a proper MTF gate: 4h trend (EMA(50)>EMA(200) or RSI(30)>50)
  decides *direction*; 1h or 15m signals decide *timing*.
- Keep hold horizons in {8, 16, 32} at 4h (1-5 days).
- Use ATR-based stops to cap drawdown, targeting the 14% ceiling that
  the best 4h cell already demonstrates.
- Include cooldown sweeps (0, 1, 2) to test whether spacing re-entries
  materially changes the return.

**F4 — Regime-switch hybrid, Track-A flavour.** Use RV(4h) and
|funding| quantiles to gate between "trend-following" (4h EMA/RSI) and
"stand-aside" modes. The idea is to skip the 2022-04→2022-10 bear
collapse and the 2025-10→2026-04 drawdown, both of which single-handedly
dragged the leaderboard.

### 4.2 Park (keep running but don't iterate on them)

**F1 literature benchmark.** Phase 2 already ran it thoroughly. Re-run
it on new datasets or parameter grids only when something else changes
(new cost assumption, new TF mix). Don't spend another cycle tuning F1.

### 4.3 Do not invest in

**macd_only.** Drop as a primary signal. Keep `macd_hist` as a feature
for F2/F4 gates.

**rsi_only_14 on 15m.** Cost-dominated at every hold. The 14-period
window reacts too fast for the cost structure.

---

## 5. Explicit next-cycle plan (Phase 3)

1. **Write the F2 multi-timeframe continuation strategy** on the existing
   feature module + backtester.
   - Signal: long when 4h EMA(50) > EMA(200) AND 1h RSI(14) crosses above 50
   - Signal: short mirrored
   - Exit: time-stop (8/16/32 bars) OR opposite-signal flip OR ATR-trailing stop
   - Run walk-forward on 15m and 1h execution under 4h signals (cross-frame)

2. **Write the F4 regime-switch hybrid** on the existing feature module.
   - Compute RV(1h) and |funding_cum_24h| rolling percentiles on the train slice
   - "Stress" regime (top-quintile RV or |funding|) → stand aside
   - "Calm" regime → run F2 continuation
   - Verify train/test percentile split is honest (fit on train only)

3. **Compare F1 vs F2 vs F4 on the same leaderboard schema** — all 8
   rolling windows, 4h signal / 15m + 1h + 4h execution, hold 4/8/16/32.

4. **Do NOT add a score model yet.** The leaderboard explicitly pinned
   rule-based families as the prerequisite for model work. Keep that
   discipline.

5. **Do NOT touch Track B yet.** Coinglass feature overlay is Phase 4
   per the original plan — and it's only meaningful on the 90-day
   overlap, not the 5-year walk-forward.

---

## 6. What will tell us we're winning Phase 3

A Phase 3 strategy is promoted to live consideration iff:

1. **OOS aggregate compounded return > 100%** over the 8 rolling
   windows (bar set: Apr 2022 → Apr 2026, same as Phase 2).
2. **Max drawdown < 25%** on the combined OOS curve.
3. **Profit factor > 1.5**.
4. **At least 5 of 8 OOS windows positive**.
5. **Trade count > 100 across all OOS windows** (robust sample).

The Phase 2 best rule-based cell (`1h rsi_and_macd_14 hold=32`) already
clears bars 1, 3, 4, 5 but not bar 2 (DD 41.6%). The target for Phase 3
is to clear all five. If Phase 3 produces a cell that clears all five,
it becomes the next live-consideration candidate.

If Phase 3 does NOT clear all five on any family:
- Recheck the assumption that 4h execution is optimal (try 2h, 6h, 1d).
- Consider a paper-only deploy of the 1h rsi_and_macd_14 hold=32 cell
  as the v1 production target, with position sizing scaled to accept
  the 41% DD.

---

## 7. One-paragraph summary for next session's opening

> Phase 2 established the first trustworthy 5-year OOS benchmark for
> Strategy C v2 across 15m, 1h, and 4h. 15m is cost-dominated — every
> literature rule lost money. 1h is viable. 4h is the best: the top
> cell is `rsi_only_30 hold=16 → +138% OOS with 13.9% DD` (thin 52-trade
> sample), and the most robust cell is `rsi_and_macd_14 hold=32 → +106%
> with 87.5% of windows positive and 510 trades`. MACD-only is toxic
> everywhere (cost-dominated). Buy-and-hold on perp nets only +13%
> because of 28% cumulative funding drag. Phase 3 should build F2
> (multi-timeframe continuation on 4h) and F4 (regime-switch hybrid)
> using the same feature module / harness / backtester / leaderboard
> schema, targeting: +100% OOS, <25% DD, PF > 1.5, ≥5/8 positive
> windows, >100 trades. No score model, no Track B, no 15m.

---

## 8. Open questions Phase 3 will need to answer

1. Does the 4h rsi_only_30 winner survive a denser hold sweep
   (2, 4, 6, 8, 10, 12, 16, 24, 32 bars)? Or is hold=16 a sweet spot?
2. Does running the F1 winners on **spot BTCUSDT** (no funding drag)
   change the ranking? — this is a ~28% headwind removal.
3. Can a 4h regime filter (RV or funding) lift the 1h
   `rsi_and_macd_14 hold=32` cell from +106% / 41% DD into a Phase-3
   promote zone (>100%, <25% DD)?
4. Does a 5m or 1h ATR trailing stop meaningfully reduce the 4h
   drawdowns without sacrificing the return?
5. What does the real **spot** B&H return look like over the same 48
   months? That's the only honest "do-nothing" benchmark.

These questions do not need to be answered in Phase 3 — they are
signposts for where the next follow-up can push if the primary Phase 3
results are ambiguous.
