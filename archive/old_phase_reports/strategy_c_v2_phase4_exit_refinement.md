# Strategy C v2 — Phase 4 Deliverable: Exit Refinement Report (ATR Trailing Stops)

_Date: 2026-04-12_
_Status: Phase 4 — does ATR trailing exit improve compounded return, DD, PF, or exposure?_

Phase 3 robustness + directional decomposition found that the edge is
broad on 4h RSI-only but that drawdowns on long-short variants are in
the 13-21% range. The Phase 4 brief asked whether **ATR trailing stops**
can reduce those drawdowns without destroying the return.

This report runs each of the three Phase 4 candidates through 8 ATR
variants: atr_field ∈ {atr_14, atr_30} × atr_trail_k ∈ {1.5, 2.0, 2.5,
3.0}, under the same 5-year walk-forward / 0.12% cost / funding-
aware backtest.

**Bottom line: ATR trailing stops HURT compounded return by 30-60
percentage points while reducing drawdown by only 3-7 pp. This is not a
favourable trade — the ATR exit family is dropped from the production
candidate list.**

---

## 1. Implementation summary (for context)

The Phase 4 backtester extension adds two new parameters:

```python
run_v2_backtest(
    ...,
    atr_values=atr_series,      # list[float | None]
    atr_trail_k=2.0,            # multiplier
)
```

Semantics (pinned by 12 new unit tests):

- **Long position**: initial stop = entry_price − k × ATR[entry_idx];
  high_water_mark updates intra-bar as `max(high_water, bar.high)`;
  stop ratchets up monotonically via
  `stop = max(stop, high_water − k × ATR[j])`; exit fires at
  `bar[j+1].open` when `bar[j].low ≤ stop` with reason `atr_trail_long`.
- **Short position**: mirror image; stop = entry + k × ATR; low_water
  tracks the favorable move downward; exit fires when
  `bar[j].high ≥ stop`.
- **Check ordering**: the stop on entry to bar j is checked against
  bar j's extremes BEFORE updating for bar j's high/low. This models
  "the stop was set at the end of bar j-1; during bar j it either
  gets hit or doesn't." Updating first would create a same-bar
  short-circuit (entry → high → new stop → low hit).
- None ATR values at any bar disable the check for that bar (stop
  holds its last known level).

All 12 new tests pass alongside the existing 29 backtester tests
(41/41 backtester total).

---

## 2. Results — full table

Each cell is (Candidate × atr_field × k × hold). Baselines are the
time-stop + opposite-flip variants from the candidate consolidation
report.

### 2.1 Candidate A (rsi_only_21 hold=12 both)

Baseline: **+142.77% / DD 20.89% / n=107**

| ATR field | k    | Return    | DD     | Trades | ΔRet      | ΔDD        |
|-----------|-----:|----------:|-------:|-------:|----------:|-----------:|
| none      |  —   | +142.77%  | 20.89% |    107 |      0.00 |       0.00 |
| atr_14    | 1.5  |  +89.89%  | 13.95% |    155 |    −52.88 |      −6.94 |
| atr_14    | 2.0  |  +97.66%  | 19.17% |    127 |    −45.11 |      −1.72 |
| atr_14    | 2.5  |  +72.08%  | 21.22% |    116 |    −70.69 |      +0.33 |
| atr_14    | 3.0  |  +90.77%  | 22.63% |    112 |    −52.00 |      +1.74 |
| atr_30    | 1.5  |  +54.40%  | 22.88% |    169 |    −88.37 |      +1.99 |
| atr_30    | 2.0  |  +66.34%  | 14.18% |    147 |    −76.43 |      −6.71 |
| atr_30    | 2.5  |  +71.31%  | 22.98% |    122 |    −71.46 |      +2.09 |
| atr_30    | 3.0  |  +71.81%  | 21.89% |    115 |    −70.96 |      +1.00 |

**Best ATR cell for A: `atr_14 k=1.5`** — cuts DD from 20.89% to 13.95%
(−6.94 pp) at the cost of −52.88 pp of return (142.77 → 89.89).
Trade count RISES from 107 to 155 because the ATR stop triggers
early exits, freeing the strategy to re-enter sooner.

**Return / DD ratio**: baseline = 6.83; atr_14 k=1.5 = 6.44. **Worse
risk-adjusted, not better.**

### 2.2 Candidate B (rsi_only_30 hold=16 both)

Baseline: **+138.41% / DD 13.92% / n=52**

| ATR field | k    | Return    | DD     | Trades | ΔRet      | ΔDD        |
|-----------|-----:|----------:|-------:|-------:|----------:|-----------:|
| none      |  —   | +138.41%  | 13.92% |     52 |      0.00 |       0.00 |
| atr_14    | 1.5  |  +43.18%  | 13.19% |     89 |    −95.23 |      −0.73 |
| atr_14    | 2.0  |  +73.00%  | 13.47% |     67 |    −65.41 |      −0.45 |
| atr_14    | 2.5  |  +70.41%  | 15.46% |     57 |    −68.00 |      +1.54 |
| atr_14    | 3.0  |  +99.19%  | 18.35% |     55 |    −39.22 |      +4.43 |
| atr_30    | 1.5  |  +35.77%  | 13.68% |     98 |   −102.64 |      −0.24 |
| atr_30    | 2.0  |  +51.92%  | 11.57% |     85 |    −86.49 |      −2.35 |
| atr_30    | 2.5  |  +66.79%  | 13.47% |     65 |    −71.62 |      −0.45 |
| atr_30    | 3.0  |  +50.89%  | 17.18% |     59 |    −87.52 |      +3.26 |

**Best ATR cell for B: `atr_30 k=2.0`** — cuts DD from 13.92% to 11.57%
(−2.35 pp) at the cost of −86.49 pp of return (138 → 52). Return/DD
goes from 9.94 to 4.49 — the ratio **collapses** because return falls
much faster than DD.

Candidate B already has a low drawdown; there's very little room to
improve it before the return cost starts dominating.

### 2.3 Candidate C (rsi_and_macd_14 hold=4 long-only)

Baseline: **+114.16% / DD 20.64% / n=177**

| ATR field | k    | Return    | DD     | Trades | ΔRet      | ΔDD        |
|-----------|-----:|----------:|-------:|-------:|----------:|-----------:|
| none      |  —   | +114.16%  | 20.64% |    177 |      0.00 |       0.00 |
| atr_14    | 1.5  |  +32.87%  | 21.41% |    187 |    −81.29 |      +0.77 |
| atr_14    | 2.0  |  +57.34%  | 21.96% |    183 |    −56.82 |      +1.32 |
| atr_14    | 2.5  |  +93.38%  | 20.70% |    179 |    −20.78 |      +0.06 |
| atr_14    | 3.0  | +109.78%  | 20.70% |    177 |     −4.38 |      +0.06 |
| atr_30    | 1.5  |  +15.76%  | 21.57% |    191 |    −98.40 |      +0.93 |
| atr_30    | 2.0  |  +32.70%  | 20.80% |    185 |    −81.46 |      +0.16 |
| atr_30    | 2.5  |  +88.55%  | 21.22% |    181 |    −25.61 |      +0.58 |
| atr_30    | 3.0  |  +91.29%  | 20.70% |    179 |    −22.87 |      +0.06 |

**Best ATR cell for C: `atr_14 k=3.0`** — preserves return (−4.38 pp)
but provides ZERO drawdown improvement (+0.06 pp — worse by a rounding).

Candidate C is the only candidate where the ATR stop has a minimal
return impact, but it also has a minimal DD impact. The stop simply
doesn't do anything for a hold=4 strategy where trades are already
short-lived.

---

## 3. Aggregate picture

Across all 24 ATR sweep cells, the sign pattern is consistent:

- ΔReturn: **always negative**, ranging from −4 pp to −103 pp
- ΔDD:     **mixed**, ranging from −7 pp (helpful) to +4 pp (worse)

Best return/DD trade-offs across the whole sweep:

| Rank | Cell                              | Return    | DD     | Return/DD |
|-----:|-----------------------------------|----------:|-------:|----------:|
|  1   | C baseline                         | +114.16% | 20.64% |      5.53 |
|  2   | C atr_14 k=3.0                     | +109.78% | 20.70% |      5.30 |
|  3   | B baseline                         | +138.41% | 13.92% | **9.94**  |
|  4   | B atr_14 k=3.0                     |  +99.19% | 18.35% |      5.41 |
|  5   | A baseline                         | +142.77% | 20.89% |      6.83 |
|  6   | A atr_14 k=2.0                     |  +97.66% | 19.17% |      5.09 |

**Every baseline strictly dominates its best ATR variant** on
return/DD. The one cell that comes close is `C atr_14 k=3.0` — its
ratio (5.30) is within 4% of C's baseline (5.53), but the absolute
return is also 4 pp lower.

---

## 4. Why the ATR trailing stop fails here

Three reinforcing mechanisms:

### 4.1 The RSI trend-following signal already stops on reversals

When RSI drops below 70 (or above 30 for shorts) the persistent signal
goes to 0, but the backtester exits only on the opposite signal fire
(−1 or +1). In the 4h rsi_only family, opposite fires typically happen
early enough that the adverse move is already underway — the ATR stop
usually fires in the same bar or one before.

The PROBLEM is that the ATR stop fires on intra-bar noise. A small
drawdown during a bigger favorable trend triggers the stop, closes
the position, pays the round-trip cost, and then the signal re-enters
on the next bar. Net effect: more trades (155 vs 107 for A at k=1.5),
more cost, less retained upside.

### 4.2 ATR_14 is noisy on 4h bars

A 14-bar ATR on 4h = 56 hours of lookback. BTC volatility over 2-3
days is large enough that a 2× ATR stop (2 × ~$1200 = $2400 on a $60K
price) triggers on minor pullbacks that reverse within 1-2 bars. The
stop fires, the cost is paid, the signal re-enters — churn.

### 4.3 The compounded return is fragile to trade count

Doubling trade count (e.g., 107 → 155 for A) roughly doubles the cost
drag (12.84% → 18.60%). But the *winners* are the same — the ATR stop
mostly cuts winning trades short. The net effect: similar gross, more
cost, less net.

Candidate C is somewhat protected because its hold=4 is already so
short that the ATR stop rarely fires before time-stop. That's why
`C atr_14 k=3.0` has nearly the same trade count (177 vs 177) and
only −4 pp of return.

---

## 5. Is there a narrow win?

Across 24 cells there are a handful with MEANINGFUL drawdown reduction:

| Cell                   | ΔReturn | ΔDD    | Notes                     |
|------------------------|--------:|-------:|---------------------------|
| A atr_14 k=1.5         | −52.88  | −6.94  | Biggest DD cut, biggest ret loss |
| A atr_30 k=2.0         | −76.43  | −6.71  | Similar DD cut, worse ret loss   |
| B atr_30 k=2.0         | −86.49  | −2.35  | Minimal DD cut, heavy ret loss   |

**None of these are usable.** All trade DD-reduction 1:7 or worse for
return-loss. A 7:1 adverse ratio is definitionally a bad risk-adjusted
move.

---

## 6. Recommendation for the production candidates

**Do NOT ship any candidate with an ATR trailing stop.**

Specifically:
- Candidate A ships as `rsi_only_21 h=12 both + time-stop + opposite_flip`
- Candidate B ships as `rsi_only_30 h=16 both + time-stop + opposite_flip`
- Candidate C ships as `rsi_and_macd_14 h=4 long-only + time-stop + opposite_flip`

The existing time-stop exit is the best exit for this signal family
under this cost model. Time is the dominant dimension: hold to the
planned bar count and exit cleanly.

---

## 7. When an ATR stop MIGHT help (deferred to future work)

The Phase 4 ATR sweep fails because the signal already has a stop-
like property (RSI regime flip). An ATR stop COULD help in families
where the signal stays "on" through adverse moves — for example:

1. **A pure trend-following strategy using EMA crossovers** (no RSI
   gate) — the signal stays long through big drawdowns until the
   cross reverses. There, an ATR stop would definitionally clip the
   drawdown.
2. **A liquidation-reversal family (Track B, Phase 3 F3 variant)**
   where the entry is a contrarian signal and the stop is the
   risk-control dimension.
3. **A multi-timeframe MTF variant** where the higher-TF signal
   outlasts the lower-TF move. The MTF framework explicitly defers
   ATR stops to a Phase 5 test.

None of those are in the Phase 4 scope. The current candidates A, B, C
all use a signal family where ATR stops are dominated by time-stops.

---

## 8. Summary

- **ATR trailing stops dropped.** Every variant tested is dominated by
  the time-stop baseline on return/DD ratio.
- **The backtester infrastructure remains.** 12 unit tests pin the
  semantics. Phase 5 or a future exit-refinement cycle can reuse it
  without reimplementation.
- **Exit refinement for the Phase 4 candidates** means exactly what
  the Phase 2 and Phase 3 backtester already does: time-stop + opposite
  signal flip. No new exit logic is promoted.

See `strategy_c_v2_phase4_final_recommendation.md` for how this feeds
into the primary + backup selection.
