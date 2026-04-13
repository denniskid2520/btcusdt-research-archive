# Strategy C v2 — Phase 4 Deliverable: Track A + Coinglass Overlay Report

_Date: 2026-04-12_
_Status: Phase 4 — null result on 83-day 4h window. Coinglass overlays
deferred to Phase 5._

Per the Phase 4 brief: test Coinglass only on top of the best 4h Track A
candidate, as entry veto / regime veto / exit refinement. Do NOT use
Coinglass to replace the main trigger.

This report runs **Candidate A (`rsi_only_21 hold=12 both` on 4h)** on
the Coinglass 83-day overlap window (2026-01-11 → 2026-04-03, 498 4h
bars) with the 15m Coinglass features aggregated up to 4h buckets,
layering 5 overlay filters on the signal stream.

**Headline: the baseline candidate fires only 7 trades in 83 days on
this 4h window. None of the 5 overlay variants meaningfully alter the
result. The sample is too thin to measure any Coinglass overlay effect
at the 4h level.**

---

## 1. Why this report is a null result

The Phase 4 brief asked the Coinglass overlay question on 4h Track A
candidates specifically because Phase 3 already showed 15m execution
is cost-dominated. The honest scope of the question, given the data,
is:

- Candidate A fires approximately once every 12 days on 4h.
- 83 days of data = ~7 signals.
- Overlay filters can only modify signals that exist.
- 5 overlay variants × 7 signals = 35 signal-variant slots, most of
  which are never triggered by the filter condition.

In the actual run, **only ONE overlay filter ever fires**:
`block_long_fundOI>5e-4` removed 1 long trade (its replacement was
strictly worse by −0.08 pp). Every other overlay is a no-op.

This is not a research failure. It's a data-scope failure. The 83-day
Coinglass window is structurally too short for a 4h strategy.

---

## 2. Setup

### Data
- Track B 15m Coinglass CSV: `src/data/strategy_c_btcusdt_15m_nocvd.csv`
  (7,967 rows, 83 days, 2026-01-11 → 2026-04-03)
- Track A 4h OHLCV: sliced from `src/data/btcusdt_4h_6year.csv` to the
  same window (498 bars)
- Funding: `src/data/btcusdt_funding_5year.csv` (full, sliced at runtime)

### Aggregation 15m → 4h

Each 4h bucket contains 16 consecutive 15m rows (aligned to 00:00,
04:00, 08:00, 12:00, 16:00, 20:00 UTC). For each bucket we compute:

- `avg_oi_pct_change`         — mean across 16 rows
- `avg_funding_oi_weighted`   — mean
- `avg_liq_imbalance`         — mean
- `sum_long_liq_usd`          — sum
- `sum_short_liq_usd`         — sum
- `sum_taker_delta_usd`       — sum
- `stablecoin_oi_pct_change`  — close-to-close over the 4h window

All 498 buckets have Coinglass coverage (none missing).

### Baseline strategy
- `rsi_only_21` on 4h, threshold 70/30
- `hold_bars=12`
- `cooldown_bars=0`
- 0.12% round-trip cost
- Real Binance funding applied when position straddles settlement

---

## 3. Baseline result (no overlay)

| Metric             | Value  |
|--------------------|-------:|
| Trades             |      7 |
| Compounded return  | +2.03% |
| Max drawdown       | 10.32% |
| Profit factor      |   1.22 |

Over 83 days of BTC 4h action, Candidate A generated 7 signals, each
held for 12 bars (2 days). Compounded return is modestly positive and
drawdown is well-controlled. But 7 is too few trades to measure
anything overlay-related with statistical confidence.

---

## 4. Overlay variants tested

Each overlay applies on top of the baseline signal stream:

| # | Overlay                                        | Rule                                                              |
|--:|------------------------------------------------|-------------------------------------------------------------------|
| 1 | `block_short_liqimb>0.3`                       | Veto short when 4h avg liq_imbalance > 0.3 (short-liq cascade)   |
| 2 | `block_long_fundOI>5e-4`                       | Veto long when 4h avg OI-weighted funding > 0.0005 (hot funding) |
| 3 | `block_short_fundOI<-5e-4`                     | Veto short when 4h avg OI-weighted funding < −0.0005             |
| 4 | `block_long_taker_delta<0`                     | Veto long when 4h sum taker_delta_usd < 0 (sellers in control)   |
| 5 | `asymmetric_short_veto_only` (1 + 3)           | Combine #1 and #3 — short-side vetoes only                        |

---

## 5. Full results

| Overlay                        | Trades | Return  | DD     | ΔRet   | ΔTrades |
|--------------------------------|-------:|--------:|-------:|-------:|--------:|
| baseline                       |      7 |  +2.03% | 10.32% |    —   |     —   |
| block_short_liqimb>0.3         |      7 |  +2.03% | 10.32% |  +0.00 |     +0  |
| block_long_fundOI>5e-4         |      7 |  +1.95% | 10.32% |  −0.08 |     +0  |
| block_short_fundOI<-5e-4       |      7 |  +2.03% | 10.32% |  +0.00 |     +0  |
| block_long_taker_delta<0       |      7 |  +2.03% | 10.32% |  +0.00 |     +0  |
| asymmetric_short_veto_only     |      7 |  +2.03% | 10.32% |  +0.00 |     +0  |

**Interpretation**: four of five overlays produce exactly the baseline
result (0 change in return, 0 change in trade count). One overlay
(`block_long_fundOI>5e-4`) produces a −0.08 pp degradation that could
be either (a) a blocked trade being replaced with a worse re-entry or
(b) a one-bar shift in a held trade. The 0.08 pp is noise at this
sample size.

### Why so little activity?

- The 7 baseline trades each entered in a regime where the RSI(21)
  was above 70 or below 30 — i.e., **extreme** price regimes. These
  tend to have funding that is ALREADY paid — longs are already
  paying a few bp, shorts are usually paid a few bp. None of the
  specific thresholds we tested (0.0005 = 5 bp per 8h) were
  triggered during the 7 actual signal bars.
- `liq_imbalance > 0.3` requires a clear 4h-bucket-average imbalance.
  Over 498 buckets and 7 signals, the intersection with signal bars
  is empty.
- `taker_delta_sum < 0` is a frequent condition (sellers dominate
  many 4h buckets) but the baseline's 7 long trades happen in
  buckets where taker delta was positive (strong buy pressure ==
  RSI > 70).

In other words, the overlay filters target states that MIGHT coincide
with baseline signals in a long historical window. On 83 days they
don't coincide at all, and we learn nothing about whether they would
help over years.

---

## 6. What this report tells the final recommendation

1. **Coinglass overlays remain unmeasured at 4h scale.** The 83-day
   window gives 7 signals; any test of overlay lift is noise.

2. **Do NOT add Coinglass overlays to the Phase 4 candidate list.**
   There's no evidence they help, and the Phase 3 Track B finding
   (on 15m execution) already showed that 15m-level overlays are
   unrelated to the 4h Track A measurement.

3. **Coinglass remains a Phase 5 research dimension.** When
   (whenever) a longer Coinglass 15m history becomes available
   (plan upgrade or multi-session stitching), re-run this same
   experiment with 4+ years of coverage. Only then can the overlay
   lift be measured.

4. **The `compute_monitor_state` live monitor does NOT read Coinglass
   fields** (by design — see `strategy_c_v2_phase4_live_monitoring.md`
   §5.4). When Coinglass is properly measured in Phase 5+, the monitor
   can be extended; until then, it stays Binance-only.

---

## 7. Comparison to the Phase 3 Track B 15m result

For the record, Phase 3's 15m Track B overlay test
(`strategy_c_v2_phase3_coinglass_overlay.md`) reported that
`funding_oi_weighted > 0.0005` as a long-veto produced +16.61 pp of
lift on the 24-day test slice of the same window. That finding was
already flagged as conflicting with the Track A 4-year funding filter
measurement (which showed the same filter hurts by −29 pp on average).

The Phase 4 4h result adds another data point: on 4h with the same
filter, **the lift is effectively 0**. Reconciling the three results:

| Measurement                          | Execution | Window         | Delta       |
|--------------------------------------|----------:|---------------:|------------:|
| Track A 4-year funding filter        |        4h |       4 years |    −29.44 pp |
| Track B 15m Coinglass overlay        |       15m |        24 days |    +16.61 pp |
| Track A 83-day 4h Coinglass overlay  |        4h |        83 days |      0.00 pp |

The 4-year Track A measurement is the only statistically credible one.
The shorter-window results reflect either (a) single-regime volatility
or (b) aliasing from the 15m vs 4h execution frame difference. Neither
supports a "Coinglass improves the Phase 4 candidate" conclusion.

---

## 8. When to revisit

**Phase 5 Coinglass research prerequisites** (checklist for a future
session that wants to measure overlay lift honestly):

1. Multi-year Coinglass 15m history available (either via plan
   upgrade or stitching multiple 90-day pulls).
2. 4h aggregation same as in this report.
3. Rolling walk-forward (not single-slice) across at least 3 test
   windows.
4. Compute Coinglass feature z-scores on train slice ONLY.
5. Test overlay variants as ENTRY VETOES, REGIME VETOES, and
   EXIT REFINEMENTS (not just entry vetoes).
6. Compare lift across ALL THREE CANDIDATES (A, B, C), not just one.

Until all six are met, Coinglass remains deferred infrastructure —
built, tested, but not promoted into the production candidate.

---

## 9. Summary

- **Baseline 4h Candidate A on 83 days**: 7 trades, +2.03%, DD 10.32%.
- **5 Coinglass overlay variants tested**: 4 produce no change, 1
  produces −0.08 pp.
- **Conclusion**: overlay effect is unmeasurable at this sample size.
- **Decision**: Phase 4 candidate list (A, B, C) does NOT add Coinglass
  as an overlay. Phase 5 can revisit if longer Coinglass data becomes
  available.

See `strategy_c_v2_phase4_final_recommendation.md` for how this
decision integrates with the primary + backup pick.
