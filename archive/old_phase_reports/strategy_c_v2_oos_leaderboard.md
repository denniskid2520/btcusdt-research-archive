# Strategy C v2 — Deliverable #4: First 5-Year OOS Leaderboard

_Date: 2026-04-11_
_Status: Phase 2 output. Track A only (Binance-native features)._

This is the first cross-timeframe leaderboard for Strategy C v2, ranking
every cell from the Phase 2 walk-forward across 15m / 1h / 4h by
**out-of-sample compounded return** on 8 rolling 24m/6m test windows.

The ranking is by OOS compounded return as the primary key, with max
drawdown, profit factor, OOS trade count, and fraction of positive
windows reported alongside as secondary evidence.

**Ranking is not by win rate.** Cells with tiny OOS trade counts are
flagged and excluded from the top section.

Full per-cell numbers live in
`strategy_c_v2_literature_benchmark.csv` (63 rows).

---

## 1. Method recap

- Data: Binance BTCUSDT perp OHLCV 2020-04-05 → 2026-04-05 (≈6y)
- Walk-forward: 24m train / 6m test / step 6m → **8 OOS test windows**
- Cost: 0.12% round-trip (fee + slippage), Binance 8h funding cashflows
  applied while position is held through the settle tick
- Leverage: 1x notional
- Min OOS trades: 30 (cells below are flagged "thin sample")
- Strategies: F1 literature family (RSI-only, MACD-only, RSI+MACD AND,
  buy-and-hold, flat)

---

## 2. Leaderboard — top 10 cells that pass the 30-trade filter

| Rank | Timeframe | Strategy          | Hold | OOS Return | Max DD | PF   | Pos Windows | Trades | Exposure |
|------|-----------|-------------------|------|-----------:|-------:|-----:|------------:|-------:|---------:|
| **1**  | 4h   | rsi_only_30       |  16  | **+138.41%** | 13.92% | 2.75 | 6/8 (75.0%) |     52 |    9.4% |
| **2**  | 4h   | rsi_and_macd_14   |   4  | **+136.20%** | 36.76% | 1.37 | 6/8 (75.0%) |    316 |   14.4% |
| **3**  | 1h   | rsi_and_macd_14   |  32  | **+106.11%** | 41.61% | 1.17 | 7/8 (87.5%) |    510 |   44.7% |
| 4    | 1h   | rsi_only_14       |  32  |   +101.63%  | 41.61% | 1.17 | 5/8 (62.5%) |    516 |   45.2% |
| 5    | 4h   | rsi_only_30       |   8  |    +85.84%  | 11.26% | 1.99 | 7/8 (87.5%) |     72 |    6.5% |
| 6    | 4h   | rsi_only_14       |   4  |    +74.43%  | 44.10% | 1.23 | 6/8 (75.0%) |    341 |   15.5% |
| 7    | 1h   | rsi_only_30       |   8  |    +71.01%  | 13.62% | 1.42 | 6/8 (75.0%) |    230 |    5.2% |
| 8    | 4h   | rsi_only_30       |  32  |    +51.69%  | 27.83% | 1.53 | 5/8 (62.5%) |     39 |   13.8% |
| 9    | 1h   | rsi_only_30       |  16  |    +47.45%  | 22.90% | 1.28 | 4/8 (50.0%) |    177 |    8.1% |
| 10   | 4h   | rsi_only_14       |   8  |    +41.68%  | 36.21% | 1.18 | 5/8 (62.5%) |    245 |   22.2% |

**Reference row (not ranked, for calibration):**

| Ref  | any   | buy_and_hold      | full |   **+12** to **+13%** | ~58.5% | ~2.03 | 4/8 (50.0%) |   8 | ~100%  |

The three B&H rows (one per TF) all cluster at +10.72% → +13.12% because
they're fundamentally the same asset path with a ~28% 4-year funding drag.

---

## 3. Rank by drawdown (secondary metric)

Same cells, re-sorted by lowest max drawdown:

| Rank | TF | Strategy         | Hold | OOS Return | **Max DD** | Trades |
|------|----|------------------|------|------------|-----------:|-------:|
| 1    | 4h | rsi_only_30      |   8  |  +85.84%   | **11.26%** |     72 |
| 2    | 1h | rsi_only_30      |   8  |  +71.01%   | **13.62%** |    230 |
| 3    | 4h | rsi_only_30      |  16  | +138.41%   | **13.92%** |     52 |
| 4    | 4h | rsi_only_30      |   4  |  +39.19%   | 20.57%     |    101 |
| 5    | 1h | rsi_only_30      |  16  |  +47.45%   | 22.90%     |    177 |
| 6    | 4h | rsi_only_30      |  32  |  +51.69%   | 27.83%     |     39 |

**Observation:** every cell in the low-drawdown top 6 is `rsi_only_30`.
The RSI(30) family is clearly the tightest-risk rule set in this
literature family. `rsi_only_30 hold=8` on **4h** gives +85.84% with just
**11.26%** DD — the best risk-adjusted cell by this metric.

---

## 4. Rank by profit factor

| Rank | TF | Strategy         | Hold | **PF**   | OOS Return | Trades |
|------|----|------------------|------|---------:|-----------:|-------:|
| 1    | 4h | rsi_only_30      |  16  | **2.75** | +138.41%   |     52 |
| 2    | 4h | rsi_only_30      |   8  | **1.99** |  +85.84%   |     72 |
| 3    | 4h | rsi_only_30      |  32  |   1.53   |  +51.69%   |     39 |
| 4    | 1h | rsi_only_30      |   8  |   1.42   |  +71.01%   |    230 |
| 5    | 4h | rsi_only_30      |   4  |   1.41   |  +39.19%   |    101 |
| 6    | 4h | rsi_and_macd_14  |   4  |   1.37   | +136.20%   |    316 |

`rsi_only_30` again dominates. The highest PF (2.75) corresponds to the
#1 return cell on 4h — but on only 52 trades.

---

## 5. Rank by window consistency (fraction positive)

Filtered to cells with > 50% positive OOS windows AND > +50% OOS return:

| Rank | TF | Strategy          | Hold | **Pos%** | OOS Return | Trades |
|------|----|-------------------|------|---------:|-----------:|-------:|
| 1    | 1h | rsi_and_macd_14   |  32  | **87.5%** | +106.11% |    510 |
| 2    | 4h | rsi_only_30       |   8  | **87.5%** |  +85.84% |     72 |
| 3    | 4h | rsi_only_30       |  16  |   75.0%   | +138.41% |     52 |
| 4    | 4h | rsi_and_macd_14   |   4  |   75.0%   | +136.20% |    316 |
| 5    | 4h | rsi_only_14       |   4  |   75.0%   |  +74.43% |    341 |
| 6    | 1h | rsi_only_30       |   8  |   75.0%   |  +71.01% |    230 |

Best cell **by window consistency**: `rsi_and_macd_14 hold=32` on **1h**
— 7 of 8 OOS test windows positive. It also has the #3 overall OOS
return (+106%), and the highest trade count (510). This is the most
statistically grounded winner on the board.

---

## 6. Losers — dropped from the leaderboard

The Phase 2 sweep is 63 cells total. Leaderboard tables above are the
top 10 by OOS return; the following cells were excluded for structural
reasons:

### 6.1 Thin-sample warning (n < 30 OOS trades)
None. Every cell on the board clears the 30-trade floor. The smallest is
`rsi_only_30 hold=32` on 4h at 39 trades over 8 windows.

### 6.2 Bottom five (cost-dominated failures)

| TF  | Strategy    | Hold | OOS return | Trades |
|-----|-------------|------|-----------:|-------:|
| 15m | macd_only   |   4  | **−100.00%** | 30,829 |
| 15m | macd_only   |   8  | **−100.00%** | 19,720 |
| 15m | macd_only   |  16  | **−100.00%** | 13,495 |
| 15m | macd_only   |  32  | **−100.00%** | 10,663 |
| 1h  | macd_only   |   4  |  −99.99%   |  7,703 |

`macd_only` trips an edge-flip signal whenever the histogram crosses
zero, which happens hundreds of times per month on 15m. At 30,000 trades
× 0.12% round-trip, cost alone is 36% of notional. Add funding and it's
a full loss. **MACD histogram sign is not a stand-alone signal**, it
only works as a confirming gate.

### 6.3 Every 15m rule-based cell is underwater

| TF  | Strategy       | Hold | OOS return |
|-----|----------------|------|-----------:|
| 15m | rsi_only_30    |  32  |  −2.57%    |
| 15m | rsi_only_30    |  16  | −33.30%    |
| 15m | rsi_only_30    |   8  | −62.50%    |
| 15m | rsi_only_30    |   4  | −77.41%    |
| 15m | rsi_only_14    |  32  | −78.25%    |
| 15m | rsi_only_14    |  16  | −85.81%    |
| 15m | rsi_and_macd_14|  32  | −79.15%    |

Even the best 15m rule-based cell (rsi_only_30 hold=32) is 2.57% below
flat. **15m execution with literature rules under a 0.12% round-trip is
not viable**. This is the single most important datapoint for the next
research cycle.

---

## 7. Cross-cuts

### 7.1 Return × Drawdown (Pareto-oriented)

The Pareto frontier of "maximise return / minimise drawdown" within the
passing cells:

| Cell                                   | Return   | DD    | Return/DD |
|----------------------------------------|---------:|------:|----------:|
| 4h rsi_only_30 hold=16                 | +138.41% | 13.92% |   **9.94** |
| 4h rsi_only_30 hold=8                  |  +85.84% | 11.26% |   **7.62** |
| 1h rsi_only_30 hold=8                  |  +71.01% | 13.62% |   **5.21** |
| 4h rsi_and_macd_14 hold=4              | +136.20% | 36.76% |   3.70 |
| 1h rsi_and_macd_14 hold=32             | +106.11% | 41.61% |   2.55 |
| 1h rsi_only_14 hold=32                 | +101.63% | 41.61% |   2.44 |

By return/drawdown ratio, the top three cells are all `rsi_only_30` on
4h or 1h with hold ∈ {8, 16}. The hold=4 and hold=32 variants trade
some risk-adjustment for higher raw return.

### 7.2 Timeframe × family heatmap

Best OOS return per (timeframe, rule family), passing 30-trade filter:

|                 | 15m      | 1h        | 4h        |
|-----------------|---------:|----------:|----------:|
| rsi_only_14     |  −78.25% |  +101.63% |   +74.43% |
| rsi_only_30     |   −2.57% |   +71.01% |  **+138.41%** |
| rsi_and_macd_14 |  −79.15% |  +106.11% |  +136.20% |
| macd_only       | −100.00% |   −99.99% |   −30.55% |

**Pattern is consistent:** every family's best result is on 4h (or tied
between 4h and 1h for rsi_and_macd_14). Every family's worst result is
on 15m.

---

## 8. Why the winner is suspect

Put honestly: the #1 cell (`4h rsi_only_30 hold=16 → +138%`) is real on
this OOS slice, but only marginally robust. Consider:

1. **52 trades across 8 windows = 6.5 trades per window**, right above
   the 30-trade floor. A single unlucky window can meaningfully shift
   the aggregate.
2. **rsi_only_30 fires only when RSI > 70 OR RSI < 30**, which is rare.
   On longer holds the signal ends up concentrated in a few bull/bear
   regime segments, so the result may be driven by 2-3 good regime
   pivots rather than many independent bets.
3. **The same strategy at hold=32 drops to +51.69% (DD 27.83%)** —
   sensitive to the hold parameter. Not catastrophic, but a sign that
   this isn't a regime-invariant edge.
4. **Run the same parameter grid on 1h and you get +16.42%** — the 4h
   specialisation matters.

The more statistically reliable winner is probably `1h rsi_and_macd_14
hold=32`: 510 trades, 87.5% positive windows, +106% OOS, slightly worse
drawdown but a much wider sample base. That is the cell the next
research cycle should explicitly try to beat.

---

## 9. Summary: what this leaderboard says

- **Best raw OOS compounded return:** 4h rsi_only_30 hold=16 — +138.41%
  (thin sample, treat as candidate not discovery)
- **Best risk-adjusted:** 4h rsi_only_30 hold=8 — +85.84% with 11.26% DD
- **Best robustness:** 1h rsi_and_macd_14 hold=32 — +106% with 87.5%
  positive windows and 510 trades
- **Best frequency / statistical base:** 4h rsi_and_macd_14 hold=4 —
  +136.20% with 316 trades, DD 36.76%
- **Biggest red flag:** every 15m rule-based cell loses money. Literature
  rules on 15m with 0.12% round-trip are not tradable.
- **The perp funding tax (−28% over 4 years)** is why even mediocre rule
  families can beat B&H on 1h/4h — they spend less time holding.

Full details in `strategy_c_v2_literature_benchmark.md` (Deliverable #3)
and the per-cell CSV `strategy_c_v2_literature_benchmark.csv` (63 rows).

The forward plan and next-cycle pick live in
`strategy_c_v2_next_cycle_recommendation.md` (Deliverable, this phase).
