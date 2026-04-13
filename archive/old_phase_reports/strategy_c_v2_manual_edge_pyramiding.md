# Manual Edge Extraction — Pyramiding Study

_Date: 2026-04-12_
_Status: Research branch `manual_edge_extraction`, sub-study 3 of 5._

## TL;DR

**Pyramiding via delayed-entry confirmation is rejected on both
cells.** Every variant tested loses 60-140 pp of return vs baseline,
the opposite of the manual-trader hypothesis.

| Cell    | Baseline | Best pyramid | Δ return |
|---------|---------:|-------------:|---------:|
| D1_long |  +143.45% |     +42.83%  | **−100.62 pp** |
| C_long  |  +106.26% |     +46.63%  |  **−59.63 pp** |

The reason is mechanical: confirming a signal N bars later forces
entry at a worse price AND skips ~50% of trades that were good but
didn't produce the confirmation bar's PnL pattern. The manual
"I add on continuation" intuition is plausibly a POST-HOC storytelling
bias, not a real execution edge.

---

## 1. Method

Pyramiding is hard to simulate in a single-position backtester. Phase
8 uses a **delayed-entry approximation**: instead of layering multiple
legs of one trade, we re-enter at a later bar if the original signal's
direction has been confirmed by a price move.

Variants tested:

| Variant               | Rule                                                 |
|-----------------------|------------------------------------------------------|
| baseline              | original signal, no delay                            |
| delayed_2bar_0.5pct   | wait 2 bars; enter only if +0.5% in direction       |
| delayed_3bar_0.5pct   | wait 3 bars; enter only if +0.5%                    |
| delayed_2bar_1pct     | wait 2 bars; enter only if +1.0%                    |
| delayed_4bar_0.5pct   | wait 4 bars; enter only if +0.5%                    |

This tests whether a "confirmed continuation" subset is systematically
better than the unfiltered signal. If so, a real pyramiding system
(add leg-2 on confirmation) should work; if not, it doesn't.

---

## 2. Results

### D1_long

| Variant                | Trades | OOS Return | DD     | PF   | Pos% |
|------------------------|-------:|-----------:|-------:|-----:|-----:|
| baseline               |   73   |  +143.45%  | 12.97% | 2.23 | 87.5 |
| delayed_3bar_0.5pct    |   48   |   +42.83%  | 14.86% | 1.60 | 75.0 |
| delayed_2bar_0.5pct    |   48   |   +21.68%  | 17.65% | 1.32 | 50.0 |
| delayed_4bar_0.5pct    |   51   |   +18.62%  | 19.66% | 1.29 | 37.5 |
| delayed_2bar_1pct      |   43   |    +5.42%  | 22.11% | 1.14 | 25.0 |

Best variant: **delayed_3bar_0.5pct at +42.83%**, which is still
**−100.62 pp** below baseline.

### C_long

| Variant                | Trades | OOS Return | DD     | PF   | Pos% |
|------------------------|-------:|-----------:|-------:|-----:|-----:|
| baseline               |  178   |  +106.26%  | 18.10% | 1.70 | 75.0 |
| delayed_3bar_0.5pct    |   83   |   +46.63%  |  9.49% | 1.89 | 75.0 |
| delayed_2bar_1pct      |   64   |   +29.02%  |  8.16% | 1.56 | 50.0 |
| delayed_2bar_0.5pct    |   88   |   +22.47%  | 12.53% | 1.34 | 37.5 |
| delayed_4bar_0.5pct    |   73   |    +6.54%  | 14.82% | 1.15 | 25.0 |

Best variant: **delayed_3bar_0.5pct at +46.63%**, which is
**−59.63 pp** below baseline.

---

## 3. Why pyramiding loses here

### 3.1 The confirmation bar costs ~50% of trades

Delayed_3bar_0.5pct cuts D1_long trades from 73 → 48 (−34%) and
C_long trades from 178 → 83 (−53%). That's half the signals
removed. The signals removed include:

- Winners that failed to produce a 3-bar 0.5% follow-through
- Signals that chopped sideways before eventually winning
- Signals near regime transitions that produced big moves later but
  didn't confirm in 3 bars

The selection removes ~50% of the signal count, and the remaining
50% are not systematically better — they're just "confirmed" in a
specific mechanical sense.

### 3.2 The entry price is strictly worse

If the base signal fires at price P and the confirmation requires
+0.5% move in 3 bars, the confirmed entry is at price P × 1.005.
Every subsequent move from entry is measured against the confirmed
entry price, which is 0.5% worse than the original entry.

At hold = 11 bars, the typical winning D1_long trade captures ~1-3%
of upside. Losing 0.5% to the confirmation bar cuts ~15-50% of that
per-trade profit.

### 3.3 Cost drag is unchanged, but gross is worse

Pyramiding variants have fewer trades but the same per-trade cost
(0.12% × frac). The cost drag per trade is identical, but the
per-trade gross PnL is worse because of the late entry. Net result:
the average net-per-trade falls, and total compounded return falls
by more than the trade count reduction would suggest.

### 3.4 The "3-bar 0.5%" version is the best by accident

delayed_3bar_0.5pct has PF = 1.60 (D1) / 1.89 (C), which are
reasonable. This is because a 3-bar 0.5% confirmation IS weakly
predictive — it filters out the chop trades. But the filter isn't
strong enough to clear the "lost trades" hurdle.

Shorter delays (2-bar) OR stronger confirmations (1% move) cut
trades even more aggressively and hurt returns further. The 3-bar
0.5% is a local sweet spot, not a genuine edge.

---

## 4. What the results say about the manual-trader hypothesis

The intuition "adding on confirmation is a real edge" is ubiquitous
in manual trading literature. The backtest says:

1. **For these specific signal families, pyramiding is strictly
   worse than single entry.** There's no variant of delay ×
   confirmation that beats baseline.
2. **The intuition may still be correct for OTHER signal families**
   (e.g., mean-reversion, event-driven) where the initial signal is
   uncertain and a confirmation bar genuinely improves the prior.
   D1_long and C_long are trend-following; the signal is already a
   confirmation of an emerging trend, so additional confirmation is
   redundant.
3. **Post-hoc storytelling bias** is the most plausible explanation
   for why experienced traders "remember" pyramiding as profitable.
   They remember the trades that worked (where they added on a
   winner) more vividly than the trades that failed to confirm
   (where they missed entirely). The backtest has no memory bias.

---

## 5. Could real multi-leg pyramiding help?

The delayed-entry approximation is only ONE model of pyramiding.
The "real" version is different:

1. Enter a partial position at the original signal (e.g., 1/3 frac)
2. Add another partial if the trade goes +X% in your favor
3. Add the final partial on a second +Y% confirmation
4. Stop / exit applies to the composite position average entry

This is not what the backtester tested, because it requires a
multi-position model. But we can estimate:

- A 1/3-frac initial entry captures 1/3 of the baseline return on the
  ~50% of trades that would have won anyway
- The add-on legs only fire on already-profitable trades
- The composite entry price is strictly better than the pure delayed
  entry (it averages a good original entry with a later confirmed
  one)

Even so, the cost is 3× higher (three trades × 0.12% × frac) and the
net improvement over a single full-frac entry depends on whether the
add-on selection effect outweighs the 3× cost drag.

For a trend-following signal where the base signal ALREADY confirms
the trend, the expected value of the add-on rule is not clearly
positive. The backtest result here supports that prior.

---

## 6. Failure mode of the study

One criticism of this study: it tests delayed entry, not real
pyramiding. A skeptic could say "you didn't actually test pyramiding."

True. But consider:

1. **If delayed entry itself loses**, then pyramiding via a series of
   delayed entries would also lose — each leg pays the cost AND the
   delay penalty.
2. **If the add-on confirmation is a genuine edge**, it would show
   up in the delayed-entry test as a positive result (more PF on the
   subset). Instead, PF on the filtered subset is LOWER than baseline
   on D1_long (2.23 → 1.60) — the filter doesn't capture a
   higher-expectancy subset.
3. **The 50% trade count reduction** means we'd need the ~50%
   surviving trades to have at least 2× the per-trade profit to
   break even. Not observed.

So while this isn't a pure pyramid test, it falsifies the
"confirmation picks winners" claim which is the core premise of
pyramiding on top of a trend-following signal.

---

## 7. Verdict

**REJECT pyramiding for D1_long and C_long.**

| Promotion criterion | D1_long best | C_long best | Pass? |
|---|---:|---:|:---:|
| OOS return > baseline + 20 pp | −100.62 pp | −59.63 pp | ❌ |
| DD ≤ baseline × 1.20 | 14.86% | 9.49% | ✅ (unclear — this is a NEGATIVE improvement) |
| PF ≥ 1.5 | 1.60 | 1.89 | ✅ |
| Trade count ≥ 50 | 48 | 83 | marginal |

Pyramiding fails the return bar by a wide margin. The PF and DD are
respectable but only because the undertrading filters out SOME bad
trades along with the good. Net expected value is negative.

**Status**: rejected from further systematic research on this branch.

---

## 8. What this doesn't foreclose

Pyramiding COULD still work if:

1. The base signal family is mean-reversion (where initial signals
   are high-variance and confirmation genuinely de-risks)
2. The add-on rule uses a predictive SIGNAL (e.g., OI expansion, tape
   confirmation) rather than just "price moved X%"
3. The backtester simulates true multi-leg positions with average
   entry pricing (not just delayed entry)

None of these are in scope for the current branch. The branch
explicitly tests "can we add pyramiding to D1_long / C_long?" and the
answer is NO.

---

## 9. Key findings

1. **Every tested pyramid variant loses return** — the best variant
   is still −60 to −100 pp below baseline.
2. **The confirmation bar costs ~50% of trades AND imposes a late
   entry price**, compounding the damage.
3. **PF on the confirmed subset is LOWER than baseline** on D1_long,
   which directly falsifies the "confirmation picks winners" claim.
4. **DD does decrease** on some variants but only because the filter
   cuts overall market exposure, not because it selects better
   trades.
5. **Manual-trader pyramiding intuition is likely post-hoc storytelling
   bias** for trend-following signals where the base signal is
   already a trend confirmation.
6. **Rejected for systematization.** Dynamic sizing (sub-study 2) is
   the only promoted modifier so far.

---

## 10. One-line summary

**Pyramiding via delayed confirmation is a strict loss on both D1_long
and C_long.** The trend-following base signal already captures the
confirmation information; adding another confirmation cuts 50% of
trades and worsens entry prices without improving per-trade PnL.
