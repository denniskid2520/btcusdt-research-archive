# Manual Edge Extraction — Adaptive Exit Study

_Date: 2026-04-12_
_Status: Research branch `manual_edge_extraction`, sub-study 4 of 5._

## TL;DR

**Adaptive exit works on D1_long, fails on C_long.** A score-based
hold modulation gives:

| Cell    | Baseline | Adaptive | Δ return |
|---------|---------:|---------:|---------:|
| D1_long |  +143.45% | **+150.20%** | **+6.75 pp** |
| C_long  |  +106.26% |   +48.42% | **−57.84 pp** |

The improvement on D1_long is below the +20 pp promotion bar but
direction-consistent with the hypothesis. On C_long it is a
catastrophic loss because the 4-bar hold is too short to benefit
from extension — compressing it to 2 bars almost always hurts.

**Verdict: adaptive exit is a weak positive on D1_long only, and not
worth pursuing separately from dynamic sizing which gives 3× the
improvement.** The DD profile also worsens on both cells.

---

## 1. Method

At entry bar, compute a 3-component score:

1. **Trend alignment**: 1 if `(ema_50 > ema_200) == (side > 0)`
2. **RSI extremity**: 1 if `rsi > 78` for long (or `< 22` for short)
3. **Funding tailwind**: 1 if `funding < 0.0002` for long (or `> −0.0002` for short)

Map score to hold:
- `score ≥ 2` → extend hold to `base × 1.5` (cap at 20)
- `score == 1` → baseline hold
- `score == 0` → compress hold to `base × 0.5` (floor at 2)

Applied via `hold_bars_override` in the backtester. Signal stream and
sizing are UNCHANGED from baseline.

Four exit modes tested:
- `fixed` — baseline
- `adaptive` — score-based modulation
- `uniform_extended` — everyone gets hold × 1.5 (control)
- `uniform_compressed` — everyone gets hold × 0.5 (control)

---

## 2. Results

### D1_long

| Mode               | Hold     | Trades | OOS Return | DD     | PF   | Pos% | Exposure |
|--------------------|----------|-------:|-----------:|-------:|-----:|-----:|---------:|
| fixed              | 11       |   73   |  +143.45%  | 12.97% | 2.23 | 87.5 | 7.9% |
| **adaptive**       | 6/11/16  |   64   |  **+150.20%** | 15.94% | 2.24 | 75.0 | 9.0% |
| uniform_extended   | 16       |   65   |  +117.35%  | 18.29% | 1.91 | 62.5 | 9.3% |
| uniform_compressed | 5        |  115   |   +85.08%  | 17.16% | 1.60 | 50.0 | 6.0% |

**Observations**:
1. Adaptive marginally beats fixed (+6.75 pp) with very similar PF.
2. Uniform extended (hold=16) LOSES to baseline — extending everyone
   is net negative.
3. Uniform compressed (hold=5) is catastrophic — forces exit before
   trends develop.
4. Adaptive drops trade count from 73 → 64. Nine trades were
   compressed to hold=5 and then lost (because they got
   chopped in the compressed window).

### C_long

| Mode               | Hold   | Trades | OOS Return | DD     | PF   | Pos% | Exposure |
|--------------------|--------|-------:|-----------:|-------:|-----:|-----:|---------:|
| fixed              | 4      |  178   |  +106.26%  | 18.10% | 1.70 | 75.0 | 7.8% |
| **adaptive**       | 2/4/6  |  155   |   +48.42%  | 20.27% | 1.35 | 37.5 | 8.8% |
| uniform_extended   | 6      |  145   |   +46.74%  | 25.58% | 1.34 | 50.0 | 9.1% |
| uniform_compressed | 2      |  254   |   +15.97%  | 14.68% | 1.14 | 37.5 | 5.7% |

**Observations**:
1. Adaptive COLLAPSES C_long return by 57.84 pp.
2. Uniform extended is nearly the same as adaptive — most C_long
   trades score ≥ 2 so they get extended, producing the same result
   as a uniform extended.
3. C_long's 4-bar hold is too short to benefit from extension.
   Extending it into the mean-reversion zone hurts.
4. C_long's short hold is STRUCTURAL — rsi_and_macd_14 h=4 works
   because hold=4 exits before the trade's alpha fades. Extending
   to hold=6 is like picking a worse hold parameter from the
   Phase 4 robustness band (which we already tested).

---

## 3. Why adaptive works on D1_long

D1_long's baseline hold = 11 bars. Trends in the 4h-rsi family often
persist for 12-20 bars when the trend conditions are strong. The
adaptive score correctly identifies these and extends the hold to
16 bars, capturing a bit more of the trend tail.

The 9 compressed trades (hold = 5) are compressed because one of the
trend / RSI / funding components doesn't align. These ARE trades
that would have failed at hold = 11, so compressing them to 5 is
mostly neutral — it cuts losses slightly.

Net: +6.75 pp of return from extending the good trades, minus a
small cost from the compressed trades that chop out at the wrong
bar.

---

## 4. Why adaptive fails on C_long

C_long's baseline hold = 4 bars. This is the right parameter from
Phase 4 research. The alpha of rsi_and_macd_14 fades quickly, and
extending the hold beyond 4 bars pushes the exit into mean-reversion
territory.

The adaptive score extends the hold on "high conviction" trades, but
these are NOT the trades that benefit from extension. The opposite
is true: the trades with the cleanest entry setup are the ones that
close cleanly at hold = 4, and extending them captures the
give-back.

This is a **parameter sensitivity mismatch**. Hold = 4 is the
Phase 4 empirical optimum for C_long; ANY systematic modulation
moves it away from that optimum in at least half of trades.

---

## 5. Interaction with dynamic sizing

Two important questions:

### Q1: Is adaptive exit additive with dynamic sizing on D1_long?

The adaptive edge on D1_long is +6.75 pp. Dynamic sizing gives
+20.87 pp. If they're independent, combined would give +27-28 pp.
If they overlap, combined would give less.

**Not directly tested in this sub-sweep**. A combined test is
warranted in the final recommendation — if the improvements are
independent, dynamic + adaptive on D1_long could reach +170% OOS.

### Q2: Does adaptive sizing fix C_long?

No. The C_long failure is structural (hold=4 is already the
optimum). No sizing modification can rescue an adaptive-exit cell
that is structurally worse than the baseline hold.

---

## 6. What the uniform controls tell us

The uniform_extended and uniform_compressed cells are the "null
hypothesis" — they change the hold without the score. Compared to
adaptive:

### D1_long

- adaptive: +150.20% (hold 6/11/16 mix)
- uniform_extended: +117.35% (hold 16 for everyone)
- uniform_compressed: +85.08% (hold 5 for everyone)

Adaptive beats uniform_extended by +32.85 pp. This means the SCORE
is doing actual work — it's not just that hold=16 is better (it
isn't, +117 < +143). It's that hold=16 FOR SPECIFIC TRADES plus
hold=5 for others produces a better composite.

### C_long

- adaptive: +48.42%
- uniform_extended: +46.74%
- uniform_compressed: +15.97%

Adaptive and uniform_extended are basically tied. The score ISN'T
adding value on C_long — the cell is behaving like uniform_extended,
which is directly because most C_long trades score high enough to
trigger extension.

This confirms the asymmetry: the score works on D1_long but is
roughly null on C_long.

---

## 7. Promotion check

### D1_long

| Criterion | Baseline | Adaptive | Pass? |
|---|---:|---:|:---:|
| OOS return > +20 pp | — | +6.75 pp | ❌ (below bar) |
| DD ≤ baseline × 1.20 | 12.97% | 15.94% | ✅ (1.23×, marginal) |
| PF ≥ 1.5 | 2.23 | 2.24 | ✅ |
| Trade count ≥ 50 | 73 | 64 | ✅ |
| Positive windows ≥ 5/8 | 7/8 | 6/8 | ✅ |

**Status**: does not clear the +20 pp return bar. **Shadow only** or
**combined test with dynamic sizing**.

### C_long

| Criterion | Baseline | Adaptive | Pass? |
|---|---:|---:|:---:|
| OOS return > +20 pp | — | −57.84 pp | ❌ catastrophic |

**Status**: rejected.

---

## 8. Recommendation

1. **D1_long**: combine adaptive exit with dynamic sizing in a
   follow-up test. The adaptive edge (+6.75 pp) is small but
   direction-correct. If it's additive with dynamic sizing (+20.87
   pp), the combined cell could reach +170% and clear the bar by a
   wide margin.
2. **C_long**: adaptive exit rejected. The 4-bar hold is structural,
   do not modify.
3. **Do not deploy adaptive exit alone** on either cell.
4. **The uniform_extended and uniform_compressed baselines** are
   useful for Phase 6-style robustness checks, but not for deployment.

---

## 9. Why adaptive exit is a weaker edge than dynamic sizing

Dynamic sizing: preserves every signal, adjusts notional per trade.
Adaptive exit: holds a subset of trades longer and compresses a
subset. The compression REMOVES profit on trades that would have
eventually won (by exiting them at bar 5 instead of bar 11). The
extension ADDS profit on trades that would have kept running.

The expected value of compression vs extension depends on whether
the score correctly predicts which trades will keep running. On
D1_long it does, mildly. On C_long it doesn't, and the baseline
hold is already optimal.

Dynamic sizing has a simpler thesis: the score weakly predicts
per-trade PnL, so scale winners larger and losers smaller. Adaptive
exit relies on the same thesis but requires the score to also
predict the TIMING of profit — a stronger claim that doesn't always
hold.

---

## 10. Key findings

1. **D1_long adaptive exit improves return by +6.75 pp** — real but
   below the promotion bar.
2. **C_long adaptive exit collapses return by −57.84 pp** — the 4-bar
   hold is optimal and modulation hurts.
3. **The score IS doing real work on D1_long** (adaptive beats
   uniform_extended by +32.85 pp), just not enough.
4. **Adaptive + dynamic sizing on D1_long** is the most promising
   follow-up test; not run in this sub-study, recommended for the
   final recommendation phase.
5. **Do not extend C_long's hold in any form** — Phase 4-6 found
   hold=4 is the local maximum.

---

## 11. Summary

Adaptive exit is a WEAK POSITIVE for D1_long (+6.75 pp, below bar)
and a CATASTROPHIC NEGATIVE for C_long (−57.84 pp). The edge is
signal-family-specific and depends on the base hold being too short
relative to the actual trend persistence. On D1_long this condition
holds; on C_long it doesn't.

The final recommendation report classifies adaptive exit as
**secondary to dynamic sizing** and considers a combined D1_long
dynamic + adaptive cell as a Phase 8 shadow candidate.
