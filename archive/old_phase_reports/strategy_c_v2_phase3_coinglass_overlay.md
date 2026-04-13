# Strategy C v2 — Phase 3 Deliverable: Track B Coinglass Overlay Test

_Date: 2026-04-11_
_Status: Phase 3 — directional single-slice evidence, not OOS measurement._

## 0. Read this first

This report is **explicitly NOT an out-of-sample measurement** of Coinglass
lift on Strategy C v2. The honest constraint is:

> Coinglass STANDARD plan has ~90 days of 15m history. The available
> Track B dataset is 83 days (`strategy_c_btcusdt_15m_nocvd.csv`,
> 2026-01-11 → 2026-04-03, 7,967 15m bars). A rolling 24m/6m walk-forward
> requires ≥30 months of history — this dataset is ~1/11th of that.

So the experimental design collapses to a single temporal 70/30 split
(Baseline C style). The test slice is **24 days** long (2,391 bars).
Any result is a *point estimate on one regime* — it tells you nothing
about out-of-sample behaviour across market cycles.

The Phase 3 brief asked for a Track A vs Track A+Coinglass overlay
comparison. We honour that brief by running the overlays, but we label
the numbers as directional evidence and do NOT let them drive the
primary Strategy C v2 candidate selection. The primary recommendation
is grounded in the 5-year Track A walk-forward (see
`strategy_c_v2_phase3_recommendation.md`).

---

## 1. What was tested

Data:
- `src/data/strategy_c_btcusdt_15m_nocvd.csv` — 83 days, 7,967 bars
- Columns include Coinglass-sourced `oi_pct_change`, `funding`,
  `long_liq_usd`, `short_liq_usd`, `liq_imbalance`, `taker_delta_usd`,
  `basis`, `funding_oi_weighted`, `stablecoin_oi`.
- High/low not in the CSV — synthesized from open/close for backtester
  compatibility (does not affect entry/exit, which use open prices).

Baseline Track A strategy:
- `rsi_only_14` on 15m, trend-following thresholds 70/30
- Hold horizons: 32 / 64 / 128 bars (8h / 16h / 32h)
- 15m execution (because that's the only frame the 83-day dataset
  supports cleanly)
- Cost: 0.12% round-trip (fee + slip). **Funding zeroed** — the
  funding column in the CSV is Coinglass-sourced aggregated funding,
  not the same series as the Binance 5-year fundingRate CSV Track A
  uses. Mixing them would confound the measurement. A proper Track B
  measurement needs to rebuild funding alignment, which is Phase 4 work.

Overlay filters tested (applied on top of the baseline signal stream):
1. `block_short_if_liq_imbalance_above=0.3` — block shorts when the
   liquidation mix is tilted heavily toward shorts (likely long squeeze)
2. `block_long_if_liq_imbalance_below=-0.3` — block longs when tilted
   heavily toward longs (likely short cascade)
3. `block_long_if_funding_oi_weighted_above=0.0005` — block longs in
   hot-funding regimes (Coinglass OI-weighted variant)
4. Asymmetric combo: #1 + #3 together

---

## 2. Results (single 24-day test slice)

### 2.1 Baseline: rsi_only_14 at three hold horizons

| Side  | Hold | Trades | Return     | DD     | PF   |
|-------|-----:|-------:|-----------:|-------:|-----:|
| both  |   32 |     32 |  **−11.71%** | 12.08% | 0.48 |
| both  |   64 |     27 |  **−22.68%** | 22.68% | 0.24 |
| both  |  128 |     19 |  −14.28%   | 15.54% | 0.46 |
| long  |   32 |     16 |   −9.65%   |  9.86% | 0.19 |
| long  |   64 |     15 |  −13.98%   | 13.98% | 0.12 |
| long  |  128 |     10 |  −15.53%   | 17.90% | 0.18 |
| short |   32 |     16 |   −2.21%   |  6.42% | 0.81 |
| short |   64 |     12 |   −3.16%   |  6.00% | 0.72 |
| short |  128 |      9 |   −0.55%   |  6.73% | 0.99 |

Every baseline cell is negative on this test slice. This is a
down-regime for the rsi_only_14 family at 15m execution — matches the
Phase 2 finding that 15m rule-based trading is cost-dominated.

Interesting nuance: on THIS slice, short-only loses the least (−0.55%
to −3.16%), reversing the Phase 3 directional decomposition finding
where long was always the stronger side. This is a regime-dependent
reversal — exactly why a 24-day slice cannot be used for OOS lift
measurement.

### 2.2 Overlay deltas at hold=64

| Overlay                           | Return    | Δ return | Trades | DD      |
|-----------------------------------|----------:|---------:|-------:|--------:|
| Baseline (both, hold=64)          |  −22.68%  |     —    |   27   | 22.68%  |
| block_short_if_liq_imb > 0.3      |  −22.68%  |  +0.00pp |   27   | 22.68%  |
| block_long_if_liq_imb < −0.3      |  −23.80%  |  −1.12pp |   27   | 23.80%  |
| **block_long_if_fund_oiw > 5e-4** |  **−6.07%** | **+16.61pp** | **18** | **7.78%** |
| asymmetric (both of above)        |   −6.07%  | +16.61pp |   18   |  7.78%  |

### 2.3 Full overlay table (all hold horizons)

| Overlay / hold        |  32  |  64  |  128 |
|-----------------------|-----:|-----:|-----:|
| baseline both         | −11.71 | −22.68 | −14.28 |
| short_liqimb>0.3      | −11.71 | −22.68 | −14.28 |
| long_liqimb<−0.3      | −11.71 | −23.80 | −14.28 |
| long_fundOI>5e-4      |  −5.21 |  −6.07 |  −0.42 |
| asymmetric            |  −5.21 |  −6.07 |  −0.42 |

---

## 3. What this tells us

### The one positive finding

**`funding_oi_weighted > 0.0005` as a long-veto produces +16.61pp of
lift on this test slice.** It drops the baseline return from −22.68%
to −6.07% at hold=64, and from −14.28% to −0.42% at hold=128. Trade
count drops from 27 to 18 → 19 long trades were blocked because the
OI-weighted funding was hot.

This is **consistent with the Phase 3 funding filter finding on Track A**
(`strategy_c_v2_phase3_funding_filter.md`), where vetoing longs in hot
funding was generally harmful across 4 years but helpful on this
specific 24-day slice. The reversal matters: it suggests the filter is
regime-dependent, not universally useful.

### The null findings

- **Liquidation imbalance doesn't help** as either a long or short
  veto. `block_short_if_liq_imb>0.3` had zero effect (filter never
  triggered on this slice — the liquidation imbalance simply didn't
  spike high enough during the test window). The long-veto variant
  blocked one winning trade, net −1.12pp.
- **The asymmetric combo is not additive** — the short filter zero-
  effect combined with the long_fundOI +16.61pp gives exactly the
  +16.61pp of the long filter alone.

### Why Track A trumps Track B here

The Phase 3 funding filter report already measured a very similar
filter on 4 YEARS of Track A data and found it was **net harmful**
(average −29pp across anchor cells). The 24-day slice says the
OPPOSITE. Neither is a lie — both are measurements of the same knob on
different regime windows. But:

- The 4-year walk-forward covers 48 months with 8 independent test
  windows. The result is stable across multiple regimes.
- The 24-day slice is one regime. The result cannot be generalised.

**The 4-year walk-forward measurement is the honest one.** The 24-day
slice is supplementary evidence — and when the two conflict, the 4-year
result wins.

---

## 4. Implications for the Strategy C v2 recommendation

1. **Do not use Coinglass `funding_oi_weighted` as a long-veto in the
   primary Strategy C v2 candidate.** The Track A 4-year evidence says
   it hurts on average. The Track B 24-day evidence says it helps on
   one regime. The primary candidate has to survive OOS across
   regimes — 24 days of +16pp lift is not enough to overcome 4 years
   of average −29pp drag.

2. **Do not use `liq_imbalance` as an entry veto in its raw form.**
   Either it didn't trigger (Track B) or the Track A 90-day Baseline B
   results already showed it adds noise. Revisit only if we find a
   z-scored or percentile-based version that's smarter than raw thresholds.

3. **Coinglass remains interesting as a regime FEATURE**, not an entry
   veto. The directional evidence suggests that when OI-weighted funding
   is very hot AND the market is in a specific macro regime, it may be
   useful. That's a Phase 4 score-model question, not a Phase 3 rule-
   filter question.

4. **The primary Strategy C v2 candidate does not depend on Coinglass.**
   See `strategy_c_v2_phase3_recommendation.md`. Track A on Binance-only
   5-year data produces cells that already clear all promotion bars; the
   recommendation selects from those.

---

## 5. What Phase 4 should do with Track B

When a Phase 4 session takes on the Track B overlay properly, it should:

1. **Fetch a longer Coinglass window** — either via a paid plan upgrade
   or by stitching together multiple non-overlapping 90-day Coinglass
   pulls over many months. A year or more of Track B data would allow
   multiple temporal splits.
2. **Compute Coinglass z-scores on a train slice only**, never
   globally. Baseline C already established this as the correct path.
3. **Layer Coinglass as a SCORE model feature**, not a rule-filter.
   The 4 families × binary threshold regime this report tested is too
   coarse. A logistic or XGBoost model on the 12-14 Coinglass features
   + Track A features is a richer question.
4. **Run on EVERY available Coinglass 15m window**, not just the
   most recent 83 days. The rolling windows give OOS evidence that
   one 24-day slice cannot.

Until that work happens, **Coinglass stays in "descriptive / suggestive"
status**, not "driver of the primary candidate" status.

---

## 6. Summary

- **Track B dataset is too short for OOS measurement.** 83 days, one
  temporal split, 24-day test slice.
- **One overlay filter showed +16.61pp lift on the slice** — block
  longs when `funding_oi_weighted > 0.0005`. But the same kind of
  filter was net −29pp on the Track A 4-year walk-forward.
- **The conflict is resolved in favour of the 4-year evidence.** The
  primary Strategy C v2 candidate does not use Coinglass as an entry
  veto.
- **Track B work is deferred to Phase 4** with explicit prerequisites:
  longer Coinglass window, train-only normalisation, score-model
  integration. The current 83-day window cannot do that work.
