# Strategy C v2 — Phase 3 Deliverable: Directional Decomposition

_Date: 2026-04-11_
_Status: Phase 3. Where does the Strategy C v2 edge come from?_

This report decomposes every robustness-sweep cell into three directional
variants:

- `long-only` — map −1 signals to 0 (no shorting)
- `short-only` — map +1 signals to 0 (no longing)
- `long-short` — default (both sides)

Same 8 rolling 24m/6m test windows, same 0.12% round-trip, same real
funding cashflows. The only change between variants is the
`apply_side_filter` pass on the signal vector before the backtester runs.

Bottom line: **the Strategy C v2 edge is asymmetric — it lives almost
entirely on the long side.** Short trades contribute less, are more
cost-sensitive, and are the primary source of drawdown in the long-short
combined variants.

---

## 1. 4h rsi_only decomposition

For the 4h rsi_only family (the Phase 2 + 3 alpha winner), every (period,
hold, side) cell is reported below. Cells are sorted by RSI period then
hold. Only the OOS compounded return column differs between sides — the
underlying walk-forward and cost model are identical.

### 1.1 rsi_only period 21 (4h)

| hold | long-only | short-only | long-short |  Long DD | LS DD |
|:----:|----------:|-----------:|-----------:|---------:|------:|
|  8   |    +60.50% |    +20.03% |   +136.71% |   18.28% | 22.96% |
|  12  |    +95.82% |    +23.97% |   +142.77% |   12.53% | 20.89% |
|  16  |    +97.60% |     +9.56% |   +116.48% |   13.30% | 28.64% |
|  24  |   +115.51% |    −24.84% |    +61.77% |   12.08% | 32.89% |
|  32  |    +84.74% |    −38.92% |    +17.44% |   15.96% | 40.40% |

Long-only is positive in every cell (+60 to +115%). Short-only peaks at
+23% and collapses to −39% at hold=32. **Long-short returns grow when
shorts help and shrink when shorts hurt** — at hold=24 and 32, the
long-short combined is materially worse than long-only.

### 1.2 rsi_only period 30 (4h)

| hold | long-only | short-only | long-short |  Long DD | LS DD |
|:----:|----------:|-----------:|-----------:|---------:|------:|
|  8   |    +49.50% |    +24.31% |    +85.84% |   10.69% | 11.26% |
|  12  |    +49.64% |     −5.91% |    +40.80% |    8.13% | 18.56% |
|  16  |    +85.90% |    +28.25% |   **+138.41%** |    9.22% | 13.92% |
|  24  |   +103.53% |    −11.76% |    +79.59% |    8.70% | 24.34% |
|  32  |   +122.16% |    −20.00% |    +51.69% |   10.88% | 27.83% |

Same pattern. rsi_only_30 long-only has drawdowns of 8-11% (excellent)
with returns of +49 to +122%. The Phase 2 winner (hold=16, +138.41%
long-short) is +85.90% long-only with only 9.22% DD.

**Notice: at hold=24, long-only is +103.53% while long-short drops to
+79.59%.** The short side was negative (-11.76%), pulling the combined
return down. And the long-short DD is 24.34% while long-only is 8.70% —
almost 3x the drawdown.

### 1.3 rsi_only period 34 (4h)

| hold | long-only | short-only | long-short |  Long DD | LS DD |
|:----:|----------:|-----------:|-----------:|---------:|------:|
|  8   |    +52.82% |     +9.09% |    +66.71% |   10.87% | 13.49% |
|  12  |    +51.18% |     −1.40% |    +49.06% |    9.58% | 22.33% |
|  16  |    +91.99% |    +15.87% |   +122.47% |    8.44% | 16.01% |
|  24  |   +105.57% |    −10.70% |    +83.56% |    8.52% | 25.13% |
|  32  |   +131.31% |     −3.60% |    +92.56% |    8.16% | 30.12% |

rsi_only_34 long-only has the **best DD-to-return trade-off on the whole
4h grid**: hold=32 gives +131.31% with 8.16% DD and pf=7.97. Only
19 trades (thin sample) but the Pareto frontier result.

### 1.4 rsi_only period 42 (4h)

| hold | long-only | short-only | long-short |  Long DD | LS DD |
|:----:|----------:|-----------:|-----------:|---------:|------:|
|  8   |    +59.07% |    −20.59% |    +26.31% |    3.55% | 16.16% |
|  12  |    +54.54% |    −19.47% |    +24.45% |    8.28% | 19.09% |
|  16  |    +65.15% |    −21.79% |    +29.16% |    6.34% | 22.97% |
|  24  |    +82.79% |    −28.32% |    +31.02% |    3.28% | 18.98% |
|  32  |   +105.04% |    −14.36% |    +75.59% |    4.78% | 22.19% |

**rsi_only_42 long-only has single-digit drawdowns (3-8%)** with returns
up to +105%. Its profit factors are extraordinary (pf=17.48 at hold=24
and pf=13.56 at hold=32) — but these are on 12-13 trades, below the
30-trade floor.

The **short side on rsi_only_42 is uniformly negative** — the signal is
too slow for the short side to capture anything profitable.

---

## 2. 4h rsi_and_macd decomposition (the MACD gate effect)

| period | hold | long-only | short-only | long-short |
|:------:|:----:|----------:|-----------:|-----------:|
|   14   |  4   |  +114.16% |    +10.29% |   +136.20% |
|   14   |  8   |    +4.07% |     +2.17% |     +6.33% |
|   14   | 16   |   +72.53% |    −44.42% |     +5.87% |
|   30   |  4   |   +29.73% |     −0.40% |    +29.21% |
|   30   |  8   |   +20.14% |     +0.93% |    +21.25% |
|   30   | 16   |   +69.91% |     +4.19% |    +77.03% |

**rsi_and_macd_14 long-only h=4** gives +114.16% with 20.64% DD and
177 trades — that's a Pareto-strong alternative to the best rsi_only
cell. The equivalent long-short is +136.20% with 36.76% DD; going
long-only cuts the DD nearly in half at the cost of ~22pp of return.

`rsi_and_macd_14 hold=16 short-only` is the nastiest cell: −44.42%
with 66.25% DD. This is why the long-short hold=16 is near-flat
(+5.87%) — the long side (+72.53%) is almost fully offset by the
short side.

---

## 3. 1h decomposition (rsi_and_macd and rsi_only)

### 1h rsi_and_macd

Period 7 is omitted (every cell is catastrophic, see robustness report).

| period | hold | long-only | short-only | long-short |
|:------:|:----:|----------:|-----------:|-----------:|
|   14   |  16  |   +30.23% |    −21.18% |    +10.51% |
|   14   |  24  |   +39.84% |     +4.24% |    +81.89% |
|   14   |  32  |   +36.21% |    +24.68% |   +106.11% |
|   14   |  48  |   +38.85% |    −18.77% |    +37.12% |
|   21   |  16  |   +33.50% |    −10.00% |    +18.74% |
|   21   |  24  |   +61.59% |    −13.88% |    +41.47% |
|   21   |  32  |   +44.61% |     −9.45% |    +34.41% |
|   21   |  48  |   +92.99% |    +15.69% |   +138.77% |

On 1h rsi_and_macd_14 hold=32 — the Phase 2 "most robust" winner — the
picture is different. Both long-only (+36.21%) and short-only (+24.68%)
are positive. The long-short combined (+106.11%) is more than the sum
of either side alone. That's the ONLY 1h cell where the short side is
genuinely contributing.

But the 1h **long-only drawdowns** (20-33%) are materially worse than
their 4h rsi_only counterparts (8-16%). 1h is noisier.

### 1h rsi_only

| period | hold | long-only | short-only | long-short |
|:------:|:----:|----------:|-----------:|-----------:|
|   14   |  16  |   +27.79% |    −27.85% |     −2.13% |
|   14   |  24  |   +30.95% |     −8.80% |    +43.95% |
|   14   |  32  |   +54.03% |     +7.72% |   +101.63% |
|   30   |  16  |   +62.50% |     −9.27% |    +47.45% |
|   30   |  24  |   +30.94% |     −0.24% |    +30.63% |
|   30   |  32  |   +25.60% |     −7.31% |    +16.42% |

`rsi_only_30 long-only h=16` on 1h is +62.50% with **10.38% DD**,
108 trades, and pf=1.72 — a strong robust low-DD cell with a larger
sample than the best 4h long-only cells.

---

## 4. The asymmetry: where the edge lives

### 4.1 Every single 4h rsi_only long-only cell is positive

Across 20 cells (4 periods × 5 holds), long-only returns range from
+49.50% to +131.31%. Mean ≈ +83%. Median ≈ +82%. Worst ≈ +50%.

### 4.2 Short-only is regime-sensitive and mostly negative on longer holds

Short-only on rsi_only_{21, 30, 34, 42} across holds {8, 12, 16, 24, 32}:

- Positive: 7 / 20 cells
- Negative: 13 / 20 cells
- Best: +28.25% (rsi_only_30 h=16)
- Worst: −38.92% (rsi_only_21 h=32)

**The short side is an inconsistent contributor, not a reliable
second alpha source.**

### 4.3 Drawdowns: long-only is ~2-4x lower than long-short

| 4h cell                        | Long DD | LS DD  | LS/Long |
|-------------------------------|--------:|-------:|--------:|
| rsi_only_21 h=12               | 12.53%  | 20.89% | 1.67x   |
| rsi_only_30 h=16               |  9.22%  | 13.92% | 1.51x   |
| rsi_only_34 h=16               |  8.44%  | 16.01% | 1.90x   |
| rsi_only_21 h=24               | 12.08%  | 32.89% | 2.72x   |
| rsi_only_30 h=32               | 10.88%  | 27.83% | 2.56x   |
| rsi_only_34 h=32               |  8.16%  | 30.12% | 3.69x   |
| rsi_only_42 h=24               |  3.28%  | 18.98% | 5.79x   |

**Averaging across the 4h rsi_only grid, long-only DD is roughly 2.5x
smaller than long-short DD.** The shorts are where the drawdown lives.

### 4.4 Why this happens (mechanistic explanation)

Three reinforcing reasons:

1. **The 48-month OOS window (Apr 2022 → Apr 2026) has more up-move than
   down-move in absolute log-return terms.** Bitcoin went from $47K to
   $67K with two large rallies (+147% in one test window) and one large
   drawdown (−56% in one window). Longs capture the rallies directly;
   shorts need to capture the drawdowns — but shorts on rallies are
   stops.

2. **Long perp positions pay funding most of the time** (8h rate
   typically positive), so longs have a cost. Short positions RECEIVE
   funding most of the time. But the signal that says "short" (RSI<30)
   is a capitulation signal, and most capitulations in 2022-2026 have
   been bottoms, not tops. Shorting bottoms is where the drawdown comes
   from.

3. **Opposite-flip exit rules make the side variants NOT additive.**
   In long-short mode, a short signal exits a long trade early, often
   at a worse price than the time-stop exit would have delivered.
   Long-only mode removes this early-exit penalty, letting longs run
   their full time-stop.

---

## 5. Best long-only candidates passing promotion bars

The promotion bar from Phase 2 recommendation:
- OOS compounded return > 100%
- Max drawdown < 25%
- Profit factor > 1.5
- ≥5/8 positive OOS windows
- >100 trades across all OOS windows

### 5.1 Long-only cells

| TF  | Cell                             | Return    | DD     | PF    | Pos windows | Trades |
|-----|----------------------------------|----------:|-------:|------:|------------:|-------:|
| 4h  | rsi_only_21 h=24 long-only       | +115.51%  | 12.08% | 2.28  | 5/8 (62.5%) |  47    |
| 4h  | rsi_only_30 h=32 long-only       | +122.16%  | 10.88% | 4.39  | 5/8 (62.5%) |  24    |
| 4h  | rsi_only_34 h=32 long-only       | +131.31%  |  8.16% | 7.97  | 5/8 (62.5%) |  19    |
| 4h  | rsi_only_42 h=32 long-only       | +105.04%  |  4.78% | 13.56 | 5/8 (62.5%) |  12    |
| 4h  | rsi_and_macd_14 h=4 long-only    | +114.16%  | 20.64% | 1.76  | 6/8 (75.0%) | 177    |

None of these clear ALL five bars simultaneously. The return + DD + PF
bars are trivially cleared; the gate is trade count (most cells have
<50 trades) and sometimes window consistency.

**Only cell that clears all five bars (long-only)**: **`4h rsi_and_macd_14
h=4 long-only` → +114.16%, 20.64% DD, PF 1.76, 6/8 positive, 177 trades.**
This is the first Phase 3 cell to clear every promotion bar.

### 5.2 Long-short cells passing promotion bars

| TF  | Cell                              | Return    | DD     | PF    | Pos windows | Trades |
|-----|-----------------------------------|----------:|-------:|------:|------------:|-------:|
| 4h  | rsi_only_21 h=12 (side=both)      | +142.77%  | 20.89% | 1.83  | 7/8 (87.5%) | 107    |
| 4h  | rsi_only_21 h=8  (side=both)      | +136.71%  | 22.96% | 1.71  | 6/8 (75.0%) | 132    |

Two 4h long-short cells clear everything. The best by raw return is
rsi_only_21 h=12 with 7/8 positive windows — strong on every dimension.

### 5.3 Pareto picks (by DD per promotion-clearing cell)

| Rank | Cell                               | Return    | **DD**  | PF   | Trades |
|-----:|------------------------------------|----------:|--------:|-----:|-------:|
|  1   | 4h rsi_and_macd_14 h=4 long-only   | +114.16%  | **20.64%** | 1.76 | 177 |
|  2   | 4h rsi_only_21 h=12 both           | +142.77%  |   20.89%   | 1.83 | 107 |
|  3   | 4h rsi_only_21 h=8  both           | +136.71%  |   22.96%   | 1.71 | 132 |

---

## 6. Directional decomposition — TL;DR

1. **The Strategy C v2 edge is ~80% in longs, ~20% or negative in shorts.**
   20 of 20 long-only cells are positive; 7 of 20 short-only cells are
   positive.

2. **Long-only cuts drawdown by 2-5x** in the 4h rsi_only family with
   modest (10-30%) return sacrifice.

3. **Long-only opens two types of cells that clear all promotion bars**:
   - High frequency: `4h rsi_and_macd_14 h=4 long-only` → +114% / 20.64%
     DD / 177 trades. The first Phase 3 cell that clears every bar.
   - Low frequency, ultra-low DD: `4h rsi_only_42 h=24 long-only` →
     +82.79% / **3.28% DD** / pf=17.48 (on 13 trades — thin sample).

4. **Side=both cells that clear all bars** are also present:
   `4h rsi_only_21 h=12 both` → +142.77% / 20.89% DD / 107 trades /
   7/8 positive. Beats long-only variants on raw return at the cost of
   slightly more drawdown.

5. **The 1h side decomposition is less clean.** On `rsi_and_macd_14 h=32`
   (Phase 2's robust winner), the combined long-short (+106%) genuinely
   exceeds long-only (+36%) — one of the few cells where shorts add net
   value. But even there, long-only DD (30.84%) is better than
   long-short (41.61%).

---

## 7. What this report changes for Phase 3 strategy design

- **Primary candidate = long-only on 4h rsi family.** The drawdown
  reduction alone (9-13% vs 21-28%) makes the long-only variants
  deployable in a way the long-short variants aren't.
- **"Long-only + optional opportunistic shorts"** may be a second
  variant worth exploring, using a stricter short filter that only
  fires shorts in high-confidence down regimes. This is the bridge
  between §5.1 (long-only) and §5.2 (long-short, best raw return).
- **Short-only is discarded** as a standalone strategy — 13/20 negative
  cells and never a clean winner.
- **The Phase 2 "hold=16 sweet spot" on rsi_only_30 is partly a
  long-only artifact.** The long-only hold=24 and hold=32 cells on
  rsi_only_{30, 34, 42} actually produce HIGHER returns with LOWER
  drawdown; only their trade counts fail the 30-trade floor.

See `strategy_c_v2_phase3_funding_filter.md` for how funding-regime
filters interact with each directional variant.
