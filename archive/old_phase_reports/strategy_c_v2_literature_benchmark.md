# Strategy C v2 — Deliverable #3: Literature Benchmark Report

_Date: 2026-04-11_
_Status: Phase 2 — first trustworthy 5-year OOS run. Track A (Binance-only)._

This report runs the five F1 literature benchmark strategies (RSI-only,
MACD-only, RSI+MACD AND gate, buy-and-hold, and flat) through a proper
24m-train / 6m-test rolling walk-forward over 2020-04 → 2026-04 on three
execution frames: **15m, 1h, 4h**. Every cell goes through the cost +
funding + slippage aware v2 backtester. No Coinglass features, no
pair_cvd, no model.

Its purpose is **not** to make literature rules win. Its purpose is to:

1. Validate the walk-forward harness and backtester end-to-end.
2. Identify the least cost-dominated timeframe for rule-based trading.
3. Establish the number every subsequent family has to beat.

---

## 1. Method

| Parameter         | Value                          |
|-------------------|--------------------------------|
| Data window       | 2020-04-05 → 2026-04-05 (≈6y)  |
| Train window      | 24 months rolling              |
| Test window       | 6 months rolling, step 6 months|
| Splits produced   | **8** per timeframe (48m OOS)  |
| Fee per side      | 0.05%                          |
| Slippage per side | 0.01%                          |
| Round-trip cost   | **0.12%**                      |
| Funding           | Binance 8h fundingRate 5-year CSV, applied only when position is held through the settlement |
| Leverage          | 1x notional                    |
| Entry convention  | t+1 open after signal close    |
| Exits             | Time-stop OR opposite-signal flip |
| Hold horizons     | 4 / 8 / 16 / 32 execution bars |
| Min OOS trades    | 30 (cells below are flagged)   |

Features are computed causally on the full series and then sliced into
test windows — this is safe because every indicator (RSI, MACD, EMA, SMA,
Bollinger, Stochastic, ATR, returns) reads only past closes, so the
"global-compute + per-split-slice" path is leakage-free. No normalization
or z-scoring is used in F1, so no per-split stat fitting is required.

---

## 2. Key calibration finding: funding on 4-year perp long is −28%

Before comparing strategies, look at what straight buy-and-hold costs on
BTCUSDT perp over the 4-year OOS window. Per-split gross vs net, 15m
execution:

| Split | Window                | Gross return | Funding cost | Net    |
|-------|-----------------------|--------------|--------------|--------|
| 0     | 2022-04 → 2022-10    | −56.36%      | −2.09%       | −58.57% |
| 1     | 2022-10 → 2023-04    | +39.10%      | −2.75%       | +36.23% |
| 2     | 2023-04 → 2023-10    | −1.26%       | −2.74%       | −4.12%  |
| 3     | 2023-10 → 2024-04    | +146.89%     | −8.86%       | +137.92% |
| 4     | 2024-04 → 2024-10    | −9.15%       | −3.04%       | −12.31% |
| 5     | 2024-10 → 2025-04    | +35.13%      | −4.46%       | +30.56% |
| 6     | 2025-04 → 2025-10    | +46.13%      | −2.70%       | +43.31% |
| 7     | 2025-10 → 2026-04    | −44.95%      | −1.37%       | −46.44% |
| **Total compound** | | **+43.10%** | **−28.00%** | **+13.12%** |

**Gross spot-equivalent return was +43.1% over 48 months. Funding cost
alone was −28.0%.** That's what perp holders pay for 4 years of long
exposure. Net compounded B&H on the perp comes out to **+13.12%** —
essentially a draw.

This number is the honest benchmark. Anything that can't clear +13%
without taking on materially more drawdown is not adding value over
"just hold the perp."

---

## 3. Full results by timeframe

### 3.1 15m execution — cost-dominated

| Strategy          | Hold | Trades | OOS ret | Max DD | PF   | Pos% | Exposure |
|-------------------|------|--------|---------|--------|------|------|----------|
| rsi_only_14       | 4    |  3,841 | −98.66% | 98.66% | 0.66 |  0.0 | 11.0%    |
| rsi_only_14       | 8    |  2,885 | −96.58% | 96.68% | 0.73 |  0.0 | 16.4%    |
| rsi_only_14       | 16   |  2,257 | −85.81% | 87.98% | 0.84 | 12.5 | 25.6%    |
| rsi_only_14       | 32   |  1,813 | −78.25% | 82.48% | 0.89 | 25.0 | 40.0%    |
| rsi_only_30       | 4    |  1,028 | −77.41% | 77.83% | 0.62 |  0.0 |  2.9%    |
| rsi_only_30       | 8    |    759 | −62.50% | 65.47% | 0.73 | 12.5 |  4.3%    |
| rsi_only_30       | 16   |    590 | −33.30% | 46.29% | 0.89 | 25.0 |  6.7%    |
| **rsi_only_30**   | **32** |  **492** | **−2.57%** | **40.70%** | **1.02** | **50.0** |  **11.2%** |
| macd_only         | 4    | 30,829 | −100.00% | 100.00% | 0.49 |  0.0 | 78.0%  |
| macd_only         | 8    | 19,720 | −100.00% | 100.00% | 0.57 |  0.0 | 85.9%  |
| macd_only         | 16   | 13,495 | −100.00% | 100.00% | 0.64 |  0.0 | 90.4%  |
| macd_only         | 32   | 10,663 | −100.00% | 100.00% | 0.66 |  0.0 | 92.4%  |
| rsi_and_macd_14   | 4    |  3,664 | −98.56% | 98.56% | 0.66 |  0.0 | 10.4%  |
| rsi_and_macd_14   | 8    |  2,769 | −96.40% | 96.50% | 0.72 |  0.0 | 15.8%  |
| rsi_and_macd_14   | 16   |  2,192 | −86.72% | 88.81% | 0.84 | 12.5 | 24.8%  |
| rsi_and_macd_14   | 32   |  1,799 | −79.15% | 83.18% | 0.88 | 25.0 | 39.7%  |
| buy_and_hold      | full |      8 | +13.12% | 58.57% | 2.04 | 50.0 | 100.0% |

**Verdict:** every rule-based cell on 15m loses money. The best is
`rsi_only_30 hold=32` at **−2.57%** — essentially flat, but with a 40.7%
drawdown. `macd_only` is catastrophic at every hold length (30,000+
trades, cost annihilates every edge). B&H beats every rule-based cell,
and even B&H only clears +13% because of funding drag. **15m rule-based
trading with the literature family is not viable on a 0.12% round-trip.**

### 3.2 1h execution — viable

| Strategy          | Hold | Trades | OOS ret | Max DD | PF   | Pos% | Exposure |
|-------------------|------|--------|---------|--------|------|------|----------|
| rsi_only_14       | 4    |  1,229 | −64.91% | 72.68% | 0.84 | 12.5 | 14.0%    |
| rsi_only_14       | 8    |    886 | −38.87% | 56.34% | 0.94 | 25.0 | 20.2%    |
| rsi_only_14       | 16   |    676 |  −2.13% | 47.14% | 1.03 | 37.5 | 30.6%    |
| **rsi_only_14**   | **32** |  **516** | **+101.63%** | **41.61%** | **1.17** | **62.5** | **45.2%** |
| rsi_only_30       | 4    |    328 |  +3.73% | 20.66% | 1.05 | 62.5 |  3.7%    |
| **rsi_only_30**   | **8**  |  **230** |  **+71.01%** | **13.62%** | **1.42** | **75.0** |  **5.2%** |
| rsi_only_30       | 16   |    177 | +47.45% | 22.90% | 1.28 | 50.0 |  8.1%    |
| rsi_only_30       | 32   |    135 | +16.42% | 35.13% | 1.14 | 37.5 | 12.3%    |
| macd_only         | 4    |  7,703 | −99.99% | 99.99% | 0.70 |  0.0 | 78.0%    |
| macd_only         | 8    |  4,899 | −99.80% | 99.82% | 0.76 |  0.0 | 86.0%    |
| macd_only         | 16   |  3,332 | −98.68% | 98.90% | 0.81 |  0.0 | 90.5%    |
| macd_only         | 32   |  2,605 | −96.20% | 96.94% | 0.84 |  0.0 | 92.5%    |
| rsi_and_macd_14   | 4    |  1,166 | −69.55% | 73.85% | 0.81 | 12.5 | 13.3%    |
| rsi_and_macd_14   | 8    |    844 |  −8.59% | 49.36% | 1.01 | 50.0 | 19.2%    |
| rsi_and_macd_14   | 16   |    650 | +10.51% | 44.31% | 1.05 | 37.5 | 29.5%    |
| **rsi_and_macd_14** | **32** | **510** | **+106.11%** | **41.61%** | **1.17** | **87.5** | **44.7%** |
| buy_and_hold      | full |      8 | +10.72% | 58.48% | 2.00 | 50.0 | 100.0%   |

**Verdict:** three rule-based cells materially beat B&H at 1h:

- **`rsi_and_macd_14 hold=32`** — +106.11% OOS with 87.5% of test windows
  positive (7/8). Best window consistency. 510 trades → high sample size.
- **`rsi_only_14 hold=32`** — +101.63%, 62.5% positive windows.
- **`rsi_only_30 hold=8`** — +71.01% with the lowest drawdown (13.62%)
  and best profit factor (1.42). Only 230 trades, but spread across 8
  windows = ~28 per window which is marginal but passes the filter.

MACD-only is still toxic even at 1h — its signal fires too often.

### 3.3 4h execution — best risk-adjusted

| Strategy          | Hold | Trades | OOS ret | Max DD | PF   | Pos% | Exposure |
|-------------------|------|--------|---------|--------|------|------|----------|
| rsi_only_14       | 4    |    341 |  +74.43% | 44.10% | 1.23 | 75.0 | 15.5%    |
| rsi_only_14       | 8    |    245 |  +41.68% | 36.21% | 1.18 | 62.5 | 22.2%    |
| rsi_only_14       | 16   |    183 |  +32.25% | 39.21% | 1.17 | 50.0 | 33.0%    |
| rsi_only_14       | 32   |    152 |  −23.93% | 54.44% | 1.02 | 37.5 | 52.6%    |
| rsi_only_30       | 4    |    101 |  +39.19% | 20.57% | 1.41 | 62.5 |  4.6%    |
| rsi_only_30       | 8    |     72 |  +85.84% | 11.26% | 1.99 | 87.5 |  6.5%    |
| **rsi_only_30**   | **16** |  **52** | **+138.41%** | **13.92%** | **2.75** | **75.0** |  **9.4%** |
| rsi_only_30       | 32   |     39 |  +51.69% | 27.83% | 1.53 | 62.5 | 13.8%    |
| macd_only         | 4    |  1,925 |  −91.16% | 91.37% | 0.86 |  0.0 | 77.9%    |
| macd_only         | 8    |  1,223 |  −72.46% | 77.06% | 0.93 | 12.5 | 86.0%    |
| macd_only         | 16   |    831 |  −53.48% | 64.82% | 0.97 | 37.5 | 90.4%    |
| macd_only         | 32   |    647 |  −30.55% | 53.51% | 1.01 | 37.5 | 92.5%    |
| **rsi_and_macd_14** | **4**  |  **316** | **+136.20%** | **36.76%** | **1.37** | **75.0** | **14.4%** |
| rsi_and_macd_14   | 8    |    238 |   +6.33% | 42.14% | 1.08 | 37.5 | 21.6%    |
| rsi_and_macd_14   | 16   |    180 |   +5.87% | 43.65% | 1.09 | 50.0 | 32.5%    |
| rsi_and_macd_14   | 32   |    150 |  −38.96% | 57.18% | 0.96 | 25.0 | 51.9%    |
| buy_and_hold      | full |      8 |  +12.02% | 58.61% | 2.03 | 50.0 |  99.8%   |

**Verdict:** 4h is the clear winner for literature rules:

- **`rsi_only_30 hold=16`** is the best **risk-adjusted** cell in the
  entire sweep: **+138.41%** OOS with just **13.92%** drawdown and profit
  factor **2.75**. 75% of windows are positive. Only concern: **52 trades**
  over 8 windows = 6.5 trades/window. Passes the min-30 filter but sits
  right above it.
- **`rsi_and_macd_14 hold=4`** is the best **high-frequency** cell:
  **+136.20%** with 316 trades. Drawdown higher (36.76%) but the trade
  count is three times the guardrail — much more robust statistically.
- **`rsi_only_30 hold=8`** — +85.84% with the smallest DD (11.26%) and
  the highest window consistency (87.5% positive, 7/8).

MACD-only is still underwater at 4h but less catastrophic than on 15m/1h.

---

## 4. Cross-timeframe summary

Best non-flat, non-B&H cell per TF that passes the 30-trade guardrail:

| TF   | Winning cell                         | OOS ret  | Max DD | n_trades | Pos windows |
|------|--------------------------------------|----------|--------|----------|-------------|
| 15m  | rsi_only_30 hold=32                  | **−2.57%** (worse than flat!) | 40.70% | 492 | 4/8 |
| 1h   | rsi_and_macd_14 hold=32              | **+106.11%** | 41.61% | 510 | 7/8 |
| 4h   | rsi_only_30 hold=16                  | **+138.41%** | 13.92% | 52  | 6/8 |

Buy-and-hold reference (perp, including funding):

| TF   | B&H OOS ret | B&H DD  |
|------|-------------|---------|
| 15m  | +13.12%     | 58.57%  |
| 1h   | +10.72%     | 58.48%  |
| 4h   | +12.02%     | 58.61%  |

(B&H differs slightly across TFs because the "re-enter at each window"
convention means slightly different entry/exit bars. The underlying asset
path is identical.)

---

## 5. Findings

1. **15m rule-based literature strategies are cost-dominated.** No cell
   is profitable. The best cell (`rsi_only_30 hold=32`) breaks even net
   but still drawsdown 40.7%. Adding more signals (shorter hold, more
   frequent entries) multiplies the cost and pushes the cell deeper into
   negative territory. This confirms the Baseline A/B/C finding that
   short-horizon 15m composite-score rules are crushed by 0.12% per
   round-trip, and generalises it beyond the 47-day pair_cvd slice.

2. **1h is where rule-based trading starts working.** Three cells beat
   B&H on 1h by 60-90 percentage points. The winning configurations all
   use hold=32 (32 hours = 1.3 days) or hold=8 (8 hours) — long enough
   for the signal to resolve into a directional move bigger than 0.12%.

3. **4h gives the best risk-adjusted literature results.** `rsi_only_30
   hold=16` is the standout: +138% OOS with 13.9% DD and profit factor
   2.75 — a Sharpe-adjusted winner. But only 52 trades across 8 test
   windows, so the statistical confidence is weaker than the 1h
   equivalent. `rsi_and_macd_14 hold=4` on 4h delivers +136% with 316
   trades, at the cost of 36.7% DD.

4. **MACD-only is toxic on every frame.** It emits a signal at every
   bar where the histogram flips sign, which is far too often. At 15m it
   lands 30,000 trades and wipes out equity. Even at 4h it still
   underperforms buy-and-hold. The histogram sign alone is not a usable
   stand-alone signal — it must be combined with something.

5. **Funding cost is a first-class PnL line on perps.** 4 years of long
   BTC perp holding cost 28% in funding. Any strategy that stays long for
   most of the time absorbs the same drag. The `rsi_only_30` family spends
   only 5-11% of its time in the market (on 1h/4h), which is the main
   reason it beats B&H so decisively — it pays dramatically less funding.

6. **The AND gate doesn't universally help.** On 15m and 1h short-hold,
   `rsi_and_macd_14` gives similar or slightly worse results than
   `rsi_only_14`. On 4h hold=4 it delivers the best high-frequency cell.
   The combo is a tactical choice, not a free lunch.

---

## 6. Honest caveats

- **8 walk-forward windows is the minimum viable**, not a statistically
  robust sample. Window-level positive fraction numbers (50%, 62.5%,
  87.5%) are coarse-grained — a single unlucky window moves the number by
  12.5 percentage points.
- **OI features are NOT included** in Track A because Binance REST only
  serves 30 days of history. Many literature variants (Hafid 2024) rank
  OI-derived features highly; we will not know what they add to the
  benchmark until an OI archive is available or until we move to a
  higher Coinglass tier.
- **No normalisation yet.** Features are raw. Per-split z-scoring would
  add an additional leakage-free transform; it's deferred to Phase 3 when
  we build the cost-aware score model.
- **The `rsi_only_30 hold=16` 4h winner is on a thin sample** (52
  trades). Its +138% return is real on this OOS slice, but it should be
  treated as a candidate, not a discovery, until it is re-run under
  parameter perturbations and a longer hold sweep.
- **"Literature" here = Stefaniuk-style trend-following.** The mean-
  reversion interpretation of RSI (> 70 short, < 30 long) is an untested
  alternative we may sweep in a follow-up.
- **funding_cum_24h, bars_to_next_funding, and other Family B features
  are computed but not yet consumed by F1.** They will be used by F2/F4
  in Phase 3 and by the score model in Phase 4.

---

## 7. What this report does NOT claim

- It does not claim +138% is a production-ready edge.
- It does not claim RSI-based trend-following "works" in a universal sense.
- It does not claim 4h is the universal best timeframe — it is the best
  *for these specific literature rules under this specific cost model
  over this specific 4-year OOS window*.
- It does not rank strategies by win rate (which would have crowned
  several cells that actually lose money after cost).

See `strategy_c_v2_oos_leaderboard.md` for the cross-TF leaderboard and
`strategy_c_v2_next_cycle_recommendation.md` for the forward plan.
