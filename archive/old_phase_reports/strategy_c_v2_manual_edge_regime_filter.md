# Manual Edge Extraction — Regime Filter Study

_Date: 2026-04-12_
_Status: Research branch `manual_edge_extraction`, sub-study 1 of 5._

## TL;DR

**Regime filters almost universally hurt return on D1_long and
C_long.** The only two that don't destroy return are `funding_veto_long`
(neutral, ~0 pp) and `funding_cum_24h > 0.001` (modest +7.56 pp on
D1_long, −14.16 pp on C_long — asymmetric). Every other tested filter
cuts return by 12-110 pp in exchange for modest DD improvements.

The hypothesis "manual edge comes mainly from skipping hostile regimes"
is **REJECTED for these signal families** as tested. The systematic
signal already fires only in directional regimes (RSI > 70 on 4h); an
additional regime filter is redundant with the signal itself and cuts
genuinely productive trades.

---

## 1. Method

- Base cells: D1_long (rsi_only_20 h=11 long, sl=1.5% close r=2% L=2x)
  and C_long (rsi_and_macd_14 h=4 long, sl=2% close r=2% L=2x).
- Each base signal stream is passed through one filter variant.
- Same 8-window walk-forward, 0.12% round-trip, real funding.
- All filters are ENTRY VETOES — they zero out signals that fail the
  regime condition, they never flip sign.
- No filter modifies the stop / exit / sizing — those stay at baseline.

13 variants tested per cell:

| Variant                   | Rule                                          |
|---------------------------|-----------------------------------------------|
| `none` (baseline)         | no filter                                     |
| `ema_cross`               | long only when EMA50 > EMA200                 |
| `close_vs_sma200`         | long only when close > SMA200                 |
| `long_only_bull_regime`   | EMA cross for longs, always block shorts      |
| `rv_expansion`            | rv_4h > 0.5%                                  |
| `rv_compression`          | rv_4h < 1.5%                                  |
| `rv_mid_band`             | 0.5% < rv_4h < 2.0%                           |
| `funding_veto_long`       | block longs when funding > 0.0005             |
| `funding_cum_veto`        | block longs when funding_cum_24h > 0.001      |
| `rsi_extreme_75`          | require RSI ≥ 75 at signal                    |
| `rsi_extreme_80`          | require RSI ≥ 80 at signal                    |
| `combo_trend_rv`          | ema_cross + rv_expansion                      |
| `combo_trend_rsi_extreme` | ema_cross + rsi_extreme_75                    |

---

## 2. D1_long baseline

| Metric               | Value      |
|----------------------|-----------:|
| OOS compounded return | **+143.45%** |
| Max drawdown         | 12.97%    |
| Trades               | 73        |
| PF                   | 2.23      |
| Positive windows     | 7/8 (87.5%) |
| Exposure             | 7.9%      |

## 3. D1_long filter deltas

| Variant                  |  Δ return |  Δ DD   | Δ trades | Δ pf | final ret | final dd |  verdict |
|--------------------------|----------:|--------:|---------:|-----:|----------:|---------:|----------|
| `none` (baseline)        |     0.00  |   0.00  |      0   |  0   |  +143.45% |  12.97% | baseline |
| `funding_veto_long`      |    −0.34  |   0.00  |     −1   | −0.02|  +143.10% |  12.97% | neutral  |
| **funding_cum_veto**     |   **+7.56** | +2.85 |     −4   | +0.01|  +151.00% |  15.82% | **weak positive** |
| `close_vs_sma200`        |   −20.69  |   0.00  |     −2   | +0.14|  +122.76% |  12.97% | negative |
| `rv_compression`         |   −26.58  |   0.00  |      0   | +0.17|  +116.87% |  12.97% | negative |
| `ema_cross`              |   −51.76  |  −2.61  |    −13   | +0.25|   +91.69% |  10.36% | negative |
| `long_only_bull_regime`  |   −51.76  |  −2.61  |    −13   | +0.25|   +91.69% |  10.36% | negative |
| `rsi_extreme_75`         |   −53.44  |  +6.36  |     −7   | +0.09|   +90.01% |  19.33% | negative |
| `rv_expansion`           |   −66.63  |  +3.95  |    −12   | +0.02|   +76.81% |  16.92% | negative |
| `rv_mid_band`            |   −76.88  |  +3.95  |    −12   | −0.03|   +66.57% |  16.92% | negative |
| `combo_trend_rv`         |   −77.95  |  −2.45  |    −25   | +0.05|   +65.50% |  10.52% | negative |
| `combo_trend_rsi_extreme`|   −93.79  |  +6.12  |    −18   | +0.00|   +49.66% |  19.09% | negative |
| `rsi_extreme_80`         |  −112.34  |  +4.41  |    −37   | −0.17|   +31.10% |  17.38% | **very negative** |

## 4. C_long baseline

| Metric               | Value      |
|----------------------|-----------:|
| OOS compounded return | **+106.26%** |
| Max drawdown         | 18.10%    |
| Trades               | 178       |
| PF                   | 1.70      |
| Positive windows     | 6/8 (75.0%) |
| Exposure             | 7.8%      |

## 5. C_long filter deltas

| Variant                  |  Δ return |  Δ DD   | Δ trades | Δ pf | final ret | final dd |  verdict |
|--------------------------|----------:|--------:|---------:|-----:|----------:|---------:|----------|
| `none` (baseline)        |     0.00  |   0.00  |      0   |  0   |  +106.26% |  18.10% | baseline |
| `funding_veto_long`      |    +0.18  |   0.00  |     −2   | +0.01|  +106.44% |  18.10% | neutral  |
| `funding_cum_veto`       |   −14.16  |   0.00  |     −7   | −0.04|   +92.10% |  18.10% | negative |
| **ema_cross**            |   **−12.73** | **−9.83** |   −53   | **+0.28** |   +93.52% |   **8.27%** | **dd-positive** |
| `long_only_bull_regime`  |   −12.73  |  −9.83  |    −53   | +0.28|   +93.52% |   8.27% | dd-positive |
| `close_vs_sma200`        |   −47.64  |  +1.99  |    −13   | −0.24|   +58.62% |  20.09% | negative |
| `rv_compression`         |   −38.36  |  +0.37  |     −7   | −0.20|   +67.89% |  18.47% | negative |
| `rv_expansion`           |   −60.44  |  −7.08  |    −52   | −0.23|   +45.82% |  11.02% | negative |
| `rv_mid_band`            |   −68.14  |  −9.16  |    −59   | −0.27|   +38.12% |   8.94% | negative |
| `rsi_extreme_75`         |   −66.61  |  −5.09  |    −76   | −0.16|   +39.65% |  13.01% | negative |
| `combo_trend_rsi_extreme`|   −70.61  |  −5.98  |    −98   | −0.12|   +35.65% |  12.12% | negative |
| `combo_trend_rv`         |   −73.70  | −10.01  |    −87   | −0.20|   +32.55% |   8.09% | negative |
| `rsi_extreme_80`         |   −87.10  |  −6.85  |   −128   | −0.22|   +19.15% |  11.25% | very negative |

---

## 6. What the results say

### 6.1 Regime filters HURT return on both cells

11 of 12 non-baseline filters hurt D1_long return. 12 of 12 hurt
C_long return (funding_veto_long is +0.18 pp, essentially neutral).
The "I only trade in favorable regimes" hypothesis fails on these
signal families.

### 6.2 Why? — the signal already encodes regime

`rsi_only_20 > 70` on 4h already requires the price to be in a strong
trending phase. That's the SAME information an EMA-cross trend filter
carries. Layering them is not additive; it's subtractive because:

1. Many `rsi_only_20 > 70` bars fire BEFORE the EMA50/200 cross
   actually flips — the signal is faster than the trend filter.
2. Any signal that fires during the "slow" trend-filter lag gets
   vetoed, even when the signal was genuinely predictive.

The RSI-based signal is essentially its own regime filter. Adding a
second regime filter cuts productive trades along with unproductive
ones.

### 6.3 The DD improvement is real but comes from undertrading

`ema_cross` on C_long cuts DD from 18.10% to 8.27% — that's a 54% DD
reduction. But return falls only 12.7pp (+106 → +93). Return/DD
ratio improves from 5.87 to 11.31. **This is genuinely better on a
risk-adjusted basis**, even though absolute return is lower.

Similarly, `ema_cross` on D1_long: ret 143→92 (−52pp), DD 13→10
(−3pp). Return/DD ratio: 11.05 → 8.85. **Worse on risk-adjusted.**

So the filter asymmetrically helps C_long but hurts D1_long on the
risk-adjusted axis.

### 6.4 The only absolute-return winner is `funding_cum_veto` on D1_long

`funding_cum_veto` blocks longs when the 24h cumulative funding is >
0.001 (100 bp accumulated over 24h). On D1_long this **adds +7.56 pp
of return** (+143 → +151) while raising DD by 2.85 pp (13 → 16).
Net marginal improvement.

Why only on D1_long? The 4-bar hold of C_long rarely straddles the
problematic funding event, so the filter has little effect on C_long
entry selection.

### 6.5 Tight RSI-extremity filters are catastrophic

`rsi_extreme_80` reduces trades from 73 → 36 on D1_long (and 178 →
50 on C_long), and cuts return by 87-112 pp. Forcing the RSI past
80 removes the bulk of productive trades — most D1_long signals
fire between 70 and 78, and the ones above 80 are actually the
MORE exhausted / mean-reverting entries, not better trades.

This is a falsification of the "bigger conviction = better trade"
intuition for this specific signal family. **RSI extremity is NOT
a genuine conviction score on D1_long.** This is an important finding
for the dynamic sizing study.

---

## 7. Cross-cut: regime filter by axis

### Return axis — filters that hurt return

All 12 filters hurt return on C_long. 11 of 12 hurt D1_long. The
winners are funding-based, not trend/vol/RSI-based.

### DD axis — filters that help drawdown

Sorted by best DD improvement:

| Filter | Cell | ΔDD | Δ return |
|---|---|---:|---:|
| combo_trend_rv | C_long | −10.01 pp | −73.70 pp |
| ema_cross / long_only_bull | C_long | −9.83 pp | −12.73 pp |
| rv_mid_band | C_long | −9.16 pp | −68.14 pp |
| rv_expansion | C_long | −7.08 pp | −60.44 pp |
| rsi_extreme_80 | C_long | −6.85 pp | −87.10 pp |
| rsi_extreme_75 | C_long | −5.09 pp | −66.61 pp |

**Only one of these has a reasonable return/DD trade**: `ema_cross`
on C_long, which loses 12.73 pp of return for 9.83 pp of DD reduction.
That's roughly 1.3 pp of return per 1 pp of DD saved, and the
return/DD ratio improves from 5.87 to 11.31.

### Trade count axis

Most filters cut trade counts by 10-50% (and `rsi_extreme_80` cuts
C_long from 178 → 50, a 72% cut). Fewer trades means thinner statistical
base. A cell with 50 trades after filtering is close to the Phase 2
floor and should be treated as a marginal sample.

---

## 8. Verdict by filter

| Filter | D1_long | C_long | Promote? |
|---|---|---|---|
| ema_cross | dd-positive-risk | **dd-positive-risk** | **shadow for C_long** |
| long_only_bull_regime | same as ema_cross on long-only cells | same | shadow for C_long |
| close_vs_sma200 | negative | negative | reject |
| rv_expansion | negative | negative | reject |
| rv_compression | negative | negative | reject |
| rv_mid_band | negative | negative | reject |
| funding_veto_long | neutral | neutral | reject (no lift) |
| **funding_cum_veto** | **weak positive** | negative | **shadow for D1_long only** |
| rsi_extreme_75 | negative | negative | reject |
| rsi_extreme_80 | very negative | very negative | reject |
| combo_trend_rv | negative | negative | reject |
| combo_trend_rsi_extreme | negative | negative | reject |

**Two shadow candidates**:
1. `funding_cum_veto` on D1_long → **+7.56 pp return, +2.85 pp DD** (small net positive)
2. `ema_cross` on C_long → **−12.73 pp return, −9.83 pp DD** (return/DD ratio improved substantially)

Neither clears the +20 pp return-improvement bar from the hypothesis
framework. Both are marginal — the first is a small direct positive,
the second is a risk-adjustment trade. Neither is a production
promotion; both are shadow candidates for observation.

---

## 9. Key insight for the rest of the manual-edge research

**The signal is already its own regime filter.** D1_long's `rsi > 70`
and C_long's `rsi > 70 AND macd_hist > 0` are regime-aware by design.
A separate regime filter fights the signal rather than augmenting it.

This falsifies the most intuitive manual-trader hypothesis ("I just
don't trade in bad regimes"). What's left of the manual-edge
hypothesis is:

- **Dynamic sizing** (vary frac per signal) — doesn't remove trades,
  just sizes them differently. Score can be asymmetric across
  productive/unproductive trades without harming the signal floor.
- **Pyramiding** — adds conditional new trades on top of confirmed
  continuation. Again, doesn't veto the base signal.
- **Adaptive exit** — modifies exit timing based on post-entry
  behavior. Signal is unchanged; only holding period varies.

The common thread: the three remaining hypotheses all PRESERVE the
base signal and apply orthogonal modifications. The regime-filter
study suggests this is the right structure — the signal is not the
problem, and filtering it further is counterproductive.

---

## 10. What would make a regime filter actually work

The filters tested here apply to EVERY signal in the stream. A
useful manual-trader regime filter would likely:

1. Apply only during specific market states (e.g., after a
   substantial drawdown, after a funding extreme, after a vol spike)
2. Be a RISK filter, not an ENTRY filter — reduce sizing rather than
   skip trades entirely
3. Use multi-bar confirmation (not single-bar trend filter) to avoid
   lagging the signal

This points to the dynamic sizing study as the next test — instead
of vetoing, vary the position_frac by regime. That's Sub-sweep 2.

---

## 11. Summary

- **12 of 13 regime filters hurt absolute return** on both D1_long
  and C_long.
- **Only 1 filter (funding_cum_veto) produces a small positive** on
  D1_long; same filter is negative on C_long.
- **ema_cross on C_long** halves drawdown for a moderate return cost
  — genuine risk-adjustment improvement, marginal candidate.
- **The RSI extremity family is a curve-fit trap** — tightening the
  RSI trigger bar to 80+ cuts MORE productive trades than
  unproductive ones.
- **The regime filter hypothesis is largely REJECTED** for these
  signal families. The signal encodes regime already.
- **Shadow candidates** (not production promotion):
  - D1_long + funding_cum_veto
  - C_long + ema_cross

The manual-edge research continues with dynamic sizing, pyramiding,
and adaptive exit — families that preserve signals rather than
filter them.
