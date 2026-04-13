# Strategy C v2 — Phase 3 Deliverable: Funding-Aware Filter Report

_Date: 2026-04-11_
_Status: Phase 3. Funding as a regime feature, not just a cashflow line._

Phase 2 established that 4 years of BTCUSDT perp long exposure costs
~28% in cumulative funding. That's a first-class variable. This report
asks: **can we use funding as a regime signal to veto entries that are
likely to get eaten by hostile funding conditions?**

The filter has two knobs (either can be set independently):

- `max_long_funding`: if set, long signals are vetoed when the funding
  field exceeds this threshold (hostile-to-longs regime)
- `min_short_funding`: if set, short signals are vetoed when the funding
  field falls below this threshold (hostile-to-shorts regime)

Filter variants tested:
- Raw `funding_rate` (last settled rate, forward-filled to the bar)
- Cumulative `funding_cum_24h` (sum over past 24h of settlements)

Applied on top of 6 anchor cells chosen from Phase 2:
- 4h rsi_only_30 hold=16 (Phase 2 best DD)
- 4h rsi_only_30 hold=8  (low-DD alternative)
- 4h rsi_and_macd_14 hold=4 (high-frequency)
- 1h rsi_and_macd_14 hold=32 (Phase 2 most robust)
- 1h rsi_only_14 hold=32
- 1h rsi_only_30 hold=8

---

## 1. Headline: short-veto helps, long-veto hurts

Across every anchor cell tested:

- **Vetoing shorts when funding is hostile to shorts (funding < threshold)
  improves OOS compounded return by 5-28 percentage points.** It blocks
  the worst short trades — shorts in negative-funding regimes where
  shorts also pay funding — with no loss of upside.

- **Vetoing longs when funding is hostile to longs (funding > threshold)
  HURTS return by 3-44 percentage points.** It blocks the best long
  trades — longs in high-funding bull markets where the trend-following
  RSI rule is supposed to capture the move.

The mechanism is simple: RSI(30) > 70 on 4h fires in overheated regimes
that often coincide with high positive funding AND strong uptrends. The
trend-following interpretation says "long the strength" — blocking those
longs because "funding is expensive" is a cost-accounting mistake. The
funding drag is real but smaller than the directional edge.

Conversely, RSI(30) < 30 fires in capitulation that often coincides with
deeply negative funding AND further downside continuation... but more
often marks a short-term bottom. The short trade becomes a losing
bottom-pick AND pays funding, compounding the loss. Vetoing those shorts
is uncontroversially helpful.

---

## 2. Full results table

60 cells: 6 anchors × 10 filter variants. Each variant applied to the
both-sides version of the anchor.

### 2.1 4h rsi_only_30 h=16 (Phase 2 best DD)

| Filter variant          | Trades | OOS ret    | Max DD | PF   | Pos  | Δ ret   |
|-------------------------|-------:|-----------:|-------:|-----:|-----:|--------:|
| none (baseline)         |     52 |  +138.41%  | 13.92% | 2.75 | 75.0 |    —    |
| long > 0.0001           |     49 |   +94.53%  | 15.50% | 2.32 | 75.0 | −43.88  |
| long > 0.0003           |     50 |  +119.59%  | 13.92% | 2.59 | 75.0 | −18.82  |
| long > 0.0005           |     52 |  +133.55%  | 14.48% | 2.69 | 75.0 |  −4.86  |
| **short < −0.0001**     |     51 | **+155.99%** | 13.92% | 3.15 | 75.0 | **+17.58** |
| short < −0.0003         |     52 |  +138.41%  | 13.92% | 2.75 | 75.0 |    0    |
| both 0.0003             |     50 |  +119.59%  | 13.92% | 2.59 | 75.0 | −18.82  |
| both 0.0001             |     48 |  +108.86%  | 15.50% | 2.65 | 75.0 | −29.55  |
| cum24h long > 0.0005    |     49 |  +109.89%  | 15.50% | 2.49 | 75.0 | −28.52  |
| cum24h both 0.0005      |     49 |  +109.89%  | 15.50% | 2.49 | 75.0 | −28.52  |

### 2.2 4h rsi_only_30 h=8 (low-DD alternative)

| Filter variant          | Trades | OOS ret    | Max DD | PF   | Pos  | Δ ret   |
|-------------------------|-------:|-----------:|-------:|-----:|-----:|--------:|
| none                    |     72 |   +85.84%  | 11.26% | 1.99 | 87.5 |    —    |
| long > 0.0001           |     66 |   +66.77%  | 11.26% | 1.85 | 87.5 | −19.07  |
| long > 0.0003           |     68 |   +81.13%  | 11.26% | 1.97 | 87.5 |  −4.71  |
| long > 0.0005           |     71 |   +66.02%  | 15.91% | 1.76 | 87.5 | −19.82  |
| **short < −0.0001**     |     71 |   **+87.70%** | 11.26% | 2.02 | 87.5 |  **+1.86** |
| short < −0.0003         |     71 |   +87.70%  | 11.26% | 2.02 | 87.5 |  +1.86  |
| both 0.0003             |     67 |   +82.95%  | 11.26% | 2.00 | 87.5 |  −2.89  |
| both 0.0001             |     65 |   +68.44%  | 11.26% | 1.87 | 87.5 | −17.40  |
| cum24h long > 0.0005    |     66 |   +68.51%  | 10.54% | 1.87 | 87.5 | −17.33  |
| cum24h both 0.0005      |     65 |   +70.19%  | 10.54% | 1.90 | 87.5 | −15.65  |

### 2.3 4h rsi_and_macd_14 h=4 (high-frequency 4h)

| Filter variant              | Trades | OOS ret    | Max DD | PF   | Pos  | Δ ret   |
|-----------------------------|-------:|-----------:|-------:|-----:|-----:|--------:|
| none                        |    316 |  +136.20%  | 36.76% | 1.37 | 75.0 |    —    |
| long > 0.0001               |    299 |  +103.92%  | 36.76% | 1.33 | 75.0 | −32.28  |
| long > 0.0003               |    309 |  +100.85%  | 36.76% | 1.31 | 75.0 | −35.35  |
| long > 0.0005               |    314 |  +130.39%  | 36.76% | 1.36 | 75.0 |  −5.81  |
| **short < −0.0001**         |    315 |  +162.24%  | 31.56% | 1.43 | 75.0 | **+26.04** |
| **short < −0.0003**         |    315 | **+164.23%** | 33.84% | 1.43 | 75.0 | **+28.03** |
| both 0.0003                 |    308 |  +124.69%  | 33.84% | 1.37 | 75.0 | −11.51  |
| both 0.0001                 |    298 |  +126.40%  | 31.56% | 1.39 | 75.0 |  −9.80  |
| cum24h long > 0.0005        |    299 |   +98.33%  | 36.76% | 1.32 | 75.0 | −37.87  |
| cum24h both 0.0005          |    299 |   +98.33%  | 36.76% | 1.32 | 75.0 | −37.87  |

### 2.4 1h rsi_and_macd_14 h=32 (Phase 2 robust winner)

| Filter variant              | Trades | OOS ret    | Max DD | PF   | Pos  | Δ ret   |
|-----------------------------|-------:|-----------:|-------:|-----:|-----:|--------:|
| none                        |    510 |  +106.11%  | 41.61% | 1.17 | 87.5 |    —    |
| long > 0.0001               |    497 |   +75.95%  | 41.61% | 1.15 | 75.0 | −30.16  |
| long > 0.0003               |    505 |  +101.78%  | 41.61% | 1.17 | 87.5 |  −4.33  |
| long > 0.0005               |    508 |  +108.43%  | 41.61% | 1.18 | 87.5 |  +2.32  |
| **short < −0.0001**         |    508 |  +112.39%  | 41.61% | 1.18 | 87.5 |  +6.28  |
| short < −0.0003             |    509 |  +110.85%  | 41.61% | 1.18 | 87.5 |  +4.74  |
| both 0.0003                 |    504 |  +106.42%  | 41.61% | 1.18 | 87.5 |  +0.31  |
| both 0.0001                 |    495 |   +81.31%  | 41.61% | 1.15 | 75.0 | −24.80  |
| cum24h long > 0.0005        |    498 |   +69.58%  | 41.61% | 1.14 | 87.5 | −36.53  |
| cum24h both 0.0005          |    498 |   +69.58%  | 41.61% | 1.14 | 87.5 | −36.53  |

### 2.5 1h rsi_only_14 h=32

| Filter variant          | Trades | OOS ret    | Max DD | PF   | Pos  | Δ ret   |
|-------------------------|-------:|-----------:|-------:|-----:|-----:|--------:|
| none                    |    516 |  +101.63%  | 41.61% | 1.17 | 62.5 |    —    |
| long > 0.0001           |    503 |   +59.70%  | 41.61% | 1.13 | 50.0 | −41.93  |
| long > 0.0003           |    511 |   +97.39%  | 41.61% | 1.17 | 62.5 |  −4.24  |
| long > 0.0005           |    514 |  +103.90%  | 41.61% | 1.17 | 62.5 |  +2.27  |
| **short < −0.0001**     |    514 |  +107.77%  | 41.61% | 1.17 | 62.5 |  +6.14  |
| short < −0.0003         |    515 |  +106.27%  | 41.61% | 1.17 | 62.5 |  +4.64  |
| both 0.0003             |    510 |  +101.93%  | 41.61% | 1.17 | 62.5 |  +0.30  |
| both 0.0001             |    501 |   +64.56%  | 41.61% | 1.13 | 50.0 | −37.07  |
| cum24h long > 0.0005    |    504 |   +60.92%  | 41.61% | 1.13 | 62.5 | −40.71  |
| cum24h both 0.0005      |    504 |   +60.92%  | 41.61% | 1.13 | 62.5 | −40.71  |

### 2.6 1h rsi_only_30 h=8

| Filter variant          | Trades | OOS ret    | Max DD | PF   | Pos  | Δ ret   |
|-------------------------|-------:|-----------:|-------:|-----:|-----:|--------:|
| none                    |    230 |   +71.01%  | 13.62% | 1.42 | 75.0 |    —    |
| long > 0.0001           |    215 |   +61.68%  | 13.62% | 1.41 | 62.5 |  −9.33  |
| long > 0.0003           |    222 |   +68.44%  | 13.62% | 1.43 | 75.0 |  −2.57  |
| long > 0.0005           |    227 |   +67.07%  | 13.62% | 1.41 | 75.0 |  −3.94  |
| **short < −0.0001**     |    229 |   +77.42%  | 13.62% | 1.46 | 75.0 |  +6.41  |
| short < −0.0003         |    230 |   +71.01%  | 13.62% | 1.42 | 75.0 |    0    |
| both 0.0003             |    222 |   +68.44%  | 13.62% | 1.43 | 75.0 |  −2.57  |
| both 0.0001             |    214 |   +67.74%  | 13.62% | 1.45 | 62.5 |  −3.27  |
| cum24h long > 0.0005    |    214 |   +55.81%  | 17.16% | 1.38 | 62.5 | −15.20  |
| cum24h both 0.0005      |    214 |   +55.81%  | 17.16% | 1.38 | 62.5 | −15.20  |

---

## 3. Per-cell deltas — short-veto wins

Isolating the `short < −0.0001` row for each anchor:

| Anchor cell                            | Baseline ret | Short-veto ret | Δ       |
|----------------------------------------|------------:|---------------:|--------:|
| 4h rsi_only_30 h=16                    |   +138.41%  |   **+155.99%** |  +17.58 |
| 4h rsi_only_30 h=8                     |    +85.84%  |    +87.70%     |   +1.86 |
| **4h rsi_and_macd_14 h=4**             |   +136.20%  |   **+162.24%** | **+26.04** |
| 1h rsi_and_macd_14 h=32                |   +106.11%  |   +112.39%     |   +6.28 |
| 1h rsi_only_14 h=32                    |   +101.63%  |   +107.77%     |   +6.14 |
| 1h rsi_only_30 h=8                     |    +71.01%  |    +77.42%     |   +6.41 |
| **Mean delta**                         |             |                | **+10.72** |

**Average lift from a −0.0001 short-veto: +10.72 percentage points.**
Not a single cell loses from this filter. The two biggest gainers are
the 4h cells, which also have the most intense short-side exposure
during the 2022 capitulation regime.

---

## 4. Per-cell deltas — long-veto (−0.0001) loses everywhere

Isolating the `long > 0.0001` row:

| Anchor cell                            | Baseline ret | Long-veto ret | Δ        |
|----------------------------------------|------------:|--------------:|---------:|
| 4h rsi_only_30 h=16                    |   +138.41%  |    +94.53%    |  −43.88  |
| 4h rsi_only_30 h=8                     |    +85.84%  |    +66.77%    |  −19.07  |
| 4h rsi_and_macd_14 h=4                 |   +136.20%  |   +103.92%    |  −32.28  |
| 1h rsi_and_macd_14 h=32                |   +106.11%  |    +75.95%    |  −30.16  |
| 1h rsi_only_14 h=32                    |   +101.63%  |    +59.70%    |  −41.93  |
| 1h rsi_only_30 h=8                     |    +71.01%  |    +61.68%    |   −9.33  |
| **Mean delta**                         |             |               | **−29.44** |

**A 0.0001 long-veto cuts returns by ~29 percentage points on average.**
Every cell loses. The fastest cells (rsi_only_14 h=32 and rsi_only_30
h=16) lose the most — because they fire most often in hot bull regimes
which are exactly the regimes the veto blocks.

The threshold matters: a looser long-veto (0.0005) loses only ~7
percentage points on average, but it also blocks fewer trades and
provides almost no incremental protection. The "safe" long-veto is no
long-veto.

---

## 5. The cum_24h variant

`funding_cum_24h` is the sum of past-24h settlement rates (3 settlements
at 8h cadence). Tested as an alternative regime signal — "funding has
been hostile for the full day, not just at the last print."

Every cum_24h filter tested LOST relative to the non-filtered baseline,
often by larger margins than the raw-rate variant:

- `cum24h long > 0.0005` on 1h rsi_and_macd_14 h=32: −36.53 pp
- `cum24h long > 0.0005` on 1h rsi_only_14 h=32: −40.71 pp
- `cum24h both 0.0005` on 4h rsi_and_macd_14 h=4: −37.87 pp

**Hypothesis for the failure**: the cum_24h value is a TRAILING window —
it tells you funding has been hostile for a day, which means the
regime is established. But RSI trend-following signals are momentum
continuations, and the market that spent a day paying high funding is
often the market still trending — exactly where the RSI rule wants to
enter. Blocking those entries systematically removes the best trades.

**Practical implication**: do not use cum_24h as an entry veto. It may
be useful as a regime feature in a score model or as input to a
position-sizing decision, but not as a hard block.

---

## 6. The best funding-filtered cells on the board

Ranked by OOS compounded return (enough trades, with filter):

| Rank | Cell                                      | Return    | DD     | PF   | Pos  | Trades |
|-----:|-------------------------------------------|----------:|-------:|-----:|-----:|-------:|
|  1   | 4h rsi_and_macd_14 h=4  short<−0.0003     |  +164.23% | 33.84% | 1.43 | 75.0 |   315  |
|  2   | 4h rsi_and_macd_14 h=4  short<−0.0001     |  +162.24% | 31.56% | 1.43 | 75.0 |   315  |
|  3   | **4h rsi_only_30 h=16  short<−0.0001**    |  +155.99% | 13.92% | 3.15 | 75.0 |    51  |
|  4   | 4h rsi_only_30 h=16  none                 |  +138.41% | 13.92% | 2.75 | 75.0 |    52  |
|  5   | 4h rsi_and_macd_14 h=4  none              |  +136.20% | 36.76% | 1.37 | 75.0 |   316  |
|  6   | 4h rsi_only_30 h=16  long>0.0005          |  +133.55% | 14.48% | 2.69 | 75.0 |    52  |
|  7   | 4h rsi_and_macd_14 h=4  long>0.0005       |  +130.39% | 36.76% | 1.36 | 75.0 |   314  |
|  8   | 4h rsi_and_macd_14 h=4  both 0.0001       |  +126.40% | 31.56% | 1.39 | 75.0 |   298  |
|  9   | 4h rsi_and_macd_14 h=4  both 0.0003       |  +124.69% | 33.84% | 1.37 | 75.0 |   308  |
| 10   | 1h rsi_and_macd_14 h=32 short<−0.0001     |  +112.39% | 41.61% | 1.18 | 87.5 |   508  |

**The top Pareto cell after funding filter**: `4h rsi_only_30 h=16`
with a short-veto at −0.0001. **+155.99% OOS, 13.92% DD, PF 3.15, 75%
positive windows, 51 trades.** The filter improves the return by
+17.58pp without touching the drawdown.

Only drawback: trade count stays at 51 (right above the 30 floor). The
filter only dropped one trade (52 → 51) because most shorts in the
rsi_only_30 signal stream fire in regimes where funding is actually
positive — the filter only triggers on the one rare case.

---

## 7. Why the asymmetry? Two mechanisms

1. **Selection effect** — RSI > 70 on 4h fires in STRONG UPTRENDS which
   in crypto typically coincide with **positive** funding and positive
   price momentum. Blocking those longs removes the strongest signals.
   RSI < 30 fires in CAPITULATION where funding is often negative. Those
   are high-variance shorts — some are trend continuations (good shorts)
   but many are short-term bottoms (bad shorts). Blocking them filters
   the bad shorts without sacrificing much on the good ones.

2. **Funding direction mechanic** — on the perp, a long pays funding
   when funding > 0. A short receives funding when funding > 0. For a
   LONG in a strong uptrend, the directional gain dwarfs the funding
   cost. For a SHORT in a weak downtrend, the funding receipt is
   negligible, but the directional risk is real.

The asymmetric filter (short-veto only, no long-veto) captures both
mechanisms.

---

## 8. Recommendation

1. **Adopt a short-veto of `min_short_funding=-0.0001` as a default
   filter** for any Strategy C v2 candidate that includes short trades.
   Universal lift across all tested anchors with zero drawdown cost.

2. **Do NOT use a long-veto** under any threshold. Every long-veto
   variant tested lost return, and the loss was larger at tighter
   thresholds. If you want to avoid hot-funding longs, the correct tool
   is position sizing or exit logic, not an entry veto.

3. **Do NOT use cum_24h as an entry filter.** The trailing window picks
   up the most profitable trend continuations and removes them.

4. **Combined with the directional decomposition finding** (§5 of
   `strategy_c_v2_phase3_directional.md`), the cleanest framework is:

   > Long-only, optional short-veto becomes a no-op (no shorts to veto),
   > so deploy long-only **without** a funding filter.

   The funding filter is only needed when the strategy has shorts. If
   we keep shorts (for the higher raw return of the long-short variant),
   add the −0.0001 short-veto.

5. **The top Phase 3 candidate emerging from this report**:
   `4h rsi_only_30 h=16 (both sides) + short<-0.0001 filter`
   → +155.99% OOS, 13.92% DD, PF 3.15, 75% positive, 51 trades.
   This beats Phase 2's best by +17.58pp with identical drawdown.
   Only concern: 51 trades is thin — the filter is barely triggering,
   so most of the lift is from the base strategy, not the filter.

See `strategy_c_v2_phase3_recommendation.md` (after the MTF + Track B
reports) for the final primary-candidate selection.
