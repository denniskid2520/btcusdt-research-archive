# Strategy C v2 — Manual Edge Extraction: Hypothesis Framework

_Date: 2026-04-12_
_Status: Research branch `manual_edge_extraction`, hypothesis stage._

## 0. The question

The systematic D1_long / C_long framework delivers +143% / +106% OOS
over 4 years with modest drawdown. That is not zero — but the user
has observed manual trading outperform it. **The question is not
"why does systematic work" but "what does the manual trader do that
the current systematic doesn't".**

This document enumerates the plausible manual-edge sources, maps them
to measurable backtest experiments, and sets up the four Phase-branch
studies.

---

## 1. Where can manual edge come from, structurally?

A manual trader has four categories of freedom that a fixed-parameter
systematic strategy does not:

1. **Selective participation** — the trader decides WHEN to engage.
   They skip low-confidence regimes, choppy markets, event-risk days,
   hostile funding regimes, and any period where "this doesn't feel
   right."
2. **Variable conviction sizing** — the trader sizes smaller when
   uncertain and bigger when the setup feels obvious. A systematic
   cell with fixed `position_frac = 1.333` ignores this.
3. **Pyramiding / scaling in** — the trader adds on confirmation
   after the first entry is profitable, creating a higher-expectancy
   composite position without increasing the initial risk.
4. **Dynamic exit judgement** — the trader holds longer when the
   trade is "running" and cuts faster when it's "not working". The
   systematic cell just counts bars.

These are the four families the Phase 8 brief asks us to research.
Each is a separate experiment, each has independent measurability,
and each has a specific risk of being a curve-fit or a genuine edge.

---

## 2. Mapping manual behaviors to measurable experiments

### 2.1 Regime selection

**Plausible manual behavior**: "I don't short in a bull market", "I
don't trade when funding is toxic", "I stand aside when vol is low
and there's no trend", "I skip the week of a Fed meeting".

**Measurable proxies we can compute from existing data**:

| Regime filter       | Feature                                    | Available |
|---------------------|--------------------------------------------|-----------|
| 4h trend            | `ema_50 > ema_200` on 4h                  | ✅ Family A |
| 1d trend            | `close > sma_200` on 4h-derived            | ✅ Family A |
| Volatility expansion | `rv_1h > percentile(rv_1h, 70)` rolling  | ✅ Family A |
| Volatility compression | `rv_4h < percentile(rv_4h, 30)` rolling | ✅ Family A |
| Funding veto        | `|funding_rate| > 0.0005`                 | ✅ Family B |
| Funding 24h regime  | `|funding_cum_24h| > 0.001`               | ✅ Family B |
| Long-only bull gate | `1d close > sma_50(1d)`                    | ✅ Family A |

Event-risk (Fed meetings, CPI, FOMC) requires an external calendar
feed we don't have. Phase 8 uses only the filters computable from
existing data.

**Experiment**: apply each filter individually and in small
combinations as an ENTRY GATE on D1_long_primary's signal stream.
Report per-filter delta vs baseline on return, DD, trade count,
exposure, worst trade, slippage resistance.

**Null hypothesis**: regime filters reduce both the good trades and
the bad trades proportionally, so net PnL is roughly flat. This is
the default expectation — filter doesn't help UNLESS the filter
specifically removes a subset of trades with lower-than-average
expectancy.

### 2.2 Dynamic sizing

**Plausible manual behavior**: "When RSI is at 85 with funding
rising, I go smaller because the trade is crowded. When RSI is at
72 coming out of a consolidation with OI expanding, I size up."

**Measurable proxies for "conviction score"**:

| Conviction signal                               | Direction |
|-------------------------------------------------|-----------|
| RSI value FAR from the 70/30 trigger threshold  | Higher conviction (less reflex, more trend) |
| MACD histogram magnitude                        | Higher for stronger momentum |
| `funding_cum_24h` aligned with signal direction | Higher when not crowded |
| `bars_to_next_funding` short (< 4)              | Lower — pay funding sooner |
| `rv_4h` in the 40-70 percentile band            | Higher than extreme high/low vol |
| 4h EMA cross alignment                          | Higher when aligned |
| Hour-of-day (weekend, low-vol hours)            | Lower |

**Experiment**: Compute a composite conviction score per signal bar.
Map the score to a position_frac multiplier (e.g. base_frac × score ∈
[0.5, 1.5]). Run D1_long with dynamic sizing vs fixed sizing and
measure return, DD, worst trade.

**Null hypothesis**: dynamic sizing is a reweighting of an already-
measured trade set. Unless the score is genuinely predictive of
per-trade outcomes, average return is unchanged.

**Sharpe/DD benefit hypothesis**: even without return improvement,
if the score is *weakly* predictive, DD and worst-trade improve
because the biggest losses are sized smaller.

### 2.3 Pyramiding / add-on

**Plausible manual behavior**: "I enter 1/3 at the signal, add 1/3
when it's in profit 1%, add final 1/3 on retest of prior high. Total
position is the same as a single entry but the second and third
lots have better entry prices on average."

**Experimental structure**:
- Base trade: enter at `bars[i+1].open` with 1/3 of normal frac.
- Add 1: if `bars[i+k].close > entry_price * (1 + 0.5%)` for long,
  add another 1/3 at `bars[i+k+1].open`.
- Add 2: same rule at a higher threshold (e.g. 1.5%).
- Exit: same time-stop from the ORIGINAL entry bar. Stop applies
  to the average entry price.

**Null hypothesis**: pyramiding is mathematically equivalent to
sizing up the final trade. If the signal is stationary, splitting
one entry into three produces the same expected return minus extra
cost drag.

**Where pyramiding COULD win**: if the add-on condition is
predictive, the composite trade's expected value is higher than a
single-entry trade's. Specifically, the second and third lots only
enter if the market has already validated the signal. This is a
selection effect, not a sizing effect.

**Where pyramiding COULD lose**: more trades means more slippage and
fee drag. At 0.12% round-trip × 3 legs, cost rises from 0.12% to
0.36% of notional per composite trade. If the add-on selection effect
doesn't clear that hurdle, pyramiding loses.

### 2.4 Adaptive exit

**Plausible manual behavior**: "When the trade is up 3%+ by hour 8
with a clean trend, I hold for 24 more hours. When the trade is
break-even at hour 8 in a choppy tape, I close."

**Experimental structure**: extend `hold_bars` dynamically:
- Base hold: 11 bars (D1_long default).
- If at bar 5, trade is up > threshold AND higher-TF trend is strong,
  extend hold to 16 bars.
- If at bar 5, trade is flat/negative AND higher-TF trend is weak,
  compress hold to 7 bars.

**Structural rule the backtester needs**: per-trade hold is not fixed
at entry; it is modulated mid-trade by a "progress check" at bar k.

**Null hypothesis**: bar-by-bar PnL is a random walk around the mean
return per bar. The midpoint PnL is not predictive of final PnL.
Extending or compressing based on midpoint PnL is reweighting, not
selection.

**Where adaptive exit COULD win**: the bar-by-bar PnL IS weakly
predictive if the signal family has trend-persistence. D1_long is
trend-following (RSI > 70), so winning trades often keep running.
Extending winners and cutting losers should monotonically improve
both return and PF.

**The trap**: if we peek ahead and extend only the winners, we
curve-fit. The experiment must use INFORMATION AVAILABLE AT BAR K,
not the final PnL. Specifically: RSI at bar k, funding at bar k,
higher-TF trend at bar k, realized vol at bar k. No look-ahead.

---

## 3. Priority ranking and prior-belief strength

Based on Phase 1-7 findings, my prior on each family:

| Family          | Prior belief of edge | Why |
|-----------------|:--------------------:|-----|
| Regime selection | **Moderate-high**   | Phase 3 directional work already showed long-only cells cut DD by half. A "bull regime only" gate is the obvious extension. |
| Dynamic sizing  | **Moderate**         | Phase 5A showed position_frac linearly scales return AND DD. If the score is weakly predictive, dynamic sizing improves DD without hurting return. |
| Pyramiding      | **Low**              | The math says pyramiding is equivalent to final-leg sizing unless the add-on condition is genuinely selective. Cost drag is high. Most pyramiding literature is post-hoc curve fit. |
| Adaptive exit   | **Moderate**         | D1_long is trend-following; trends persist. Extending winners should work IF the midpoint signal is predictive. Risk is curve-fitting specific hold horizons. |

**Expected outcome**: regime selection and adaptive exit produce the
biggest honest wins. Dynamic sizing is a cleaner DD lever than a
return lever. Pyramiding is likely a curve-fit trap and should be
treated skeptically.

---

## 4. Methodology guardrails (what prevents curve-fitting)

1. **Walk-forward discipline**: every experiment runs on the same 8
   rolling 24m/6m OOS windows used in Phase 4-7. No parameter is set
   using test-window data. Features used in filters and scores are
   computed causally (existing feature module).

2. **Baseline pinning**: the baseline is D1_long strategy_close_stop
   at +143.45% / DD 12.97% / 73 trades. Every modifier is reported as
   a delta against this exact cell.

3. **Minimum trade count floor**: any modifier that reduces trade count
   below 30 is FLAGGED even if it increases return. Thin samples are
   the primary curve-fit signature.

4. **Tail test**: every promoted modifier is checked against the
   Phase 6 tail-event model. A modifier that improves return at the
   cost of worse worst-trade or worse tail-event survival is
   DOWNGRADED.

5. **Slippage test**: every promoted modifier is checked under 0.3%
   stop slippage. A modifier that improves return but raises stop-
   exit fraction and therefore loses to slippage is DOWNGRADED.

6. **Symmetry test**: a filter that only helps on one of D1_long /
   C_long and hurts the other is likely overfit to one signal family.
   We report both.

---

## 5. What this branch produces (6 deliverables)

1. **Hypothesis framework** (this file)
2. **Regime-filter study** — 4h trend, 1d trend, RV filter, funding
   filter, long-only bull gate applied individually and in combos
3. **Dynamic-sizing study** — composite conviction score × position_frac
   multiplier mapped to D1_long
4. **Pyramiding study** — 3-leg scaling-in with continuation rules
5. **Adaptive-exit study** — midpoint-PnL + higher-TF-trend based
   hold modulation
6. **Recommendation** — which of the four to systematize, and which
   to leave as discretionary or reject

Each report reports: return delta, DD delta, trade count delta,
slippage retention, worst-trade change, long/short decomposition,
and a final verdict (promote / shadow / reject).

---

## 6. Success criteria per modifier

A modifier is **promoted** to the D1_long production path if ALL
hold:

1. OOS aggregate return > D1_long baseline by ≥ +20 pp
2. Combined max DD ≤ D1_long baseline × 1.20 (i.e. no more than 20%
   worse)
3. Worst single trade ≤ D1_long baseline × 1.20 (bounded tail)
4. Trade count ≥ 50 (60 preferred)
5. 5-of-8 OOS positive windows, matching or exceeding baseline
6. Profit factor ≥ 1.5
7. The improvement SURVIVES 0.3% stop slippage

A modifier is **shadow-only** if it clears 1-3 but not 4-5 (thin
sample) or loses >50% of improvement under slippage.

A modifier is **rejected** if it fails any of 1, 2, 3, 6.

---

## 7. What this branch deliberately does NOT do

- Does not replace D1_long or C_long as base strategies
- Does not test new signal families (e.g. liquidation reversal, MTF)
- Does not use ATR trailing stops (Phase 4 rejected these)
- Does not rely on Coinglass overlays (83-day window insufficient)
- Does not consume event-calendar data (not available)
- Does not re-run the full Phase 2-6 research cycle

The branch is narrow by design. It tests whether the four manual-
edge hypotheses can be codified — nothing more, nothing less.

---

## 8. One-paragraph summary for the next reports

> The manual_edge_extraction branch tests four hypotheses about
> where a discretionary BTC futures trader outperforms the current
> D1_long / C_long systematic path: regime selection (trade only in
> favorable regimes), dynamic sizing (vary position_frac by
> conviction score), pyramiding (add to winners), and adaptive exit
> (extend winners, cut losers). All four are tested as additive
> modifiers on D1_long_primary's 5-year walk-forward, with the
> Phase 7 stop-semantics split and the Phase 5A/6 cost model. Prior
> beliefs: regime selection and adaptive exit are most likely to
> produce honest edge; dynamic sizing is cleaner as a DD lever than
> a return lever; pyramiding is likely a curve-fit trap. Promotion
> criteria are return > +20 pp, DD ≤ 1.2× baseline, worst trade
> bounded, walk-forward stable, slippage-resistant.
