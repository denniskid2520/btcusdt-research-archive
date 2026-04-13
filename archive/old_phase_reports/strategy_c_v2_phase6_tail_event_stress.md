# Strategy C v2 — Phase 6 Deliverable: Tail-Event Stress Report

_Date: 2026-04-12_
_Status: Phase 6 — synthetic shock survivability._

## TL;DR

**Position fraction ≤ 2.0 is the hard safety ceiling.** Every cell
with `actual_position_frac` ≤ 2.0 survives a synthetic 40% single-day
adverse shock with account losses between −40% and −80%. Above
frac = 2.0, survival is not guaranteed:

| frac | 20% shock | 30% shock | 40% shock |
|-----:|----------:|----------:|----------:|
| 1.00 |    −20.0% |    −30.0% |    −40.0% |
| 1.33 |    −26.7% |    −40.0% |    −53.3% |
| 2.00 |    −40.0% |    −60.0% |    −80.0% |
| 2.40 |    −48.0% |    −72.0% |    −96.0% (margin 4%) |
| 2.67 |    −53.3% |    −80.0% | **LIQUIDATED** |
| 3.00 |    −60.0% |    −90.0% | **LIQUIDATED** |
| 3.20 |    −64.0% |    −96.0% | **LIQUIDATED** |
| 4.00 |    −80.0% | **LIQUIDATED** | **LIQUIDATED** |

**Phase 5A primary (frac=1.333) survives all three shocks.**
**Phase 6 return-expansion cells (frac=3-4) get liquidated on a 30-40% shock.**

---

## 1. Method

Post-processing analysis on the expanded Phase 6 sweep CSV. For each
cell, compute the worst-case per-trade loss under three synthetic
shock scenarios:

| Scenario | Adverse move  | Historical reference               |
|----------|---------------|------------------------------------|
| Mild     | 20% / 1 day   | Mid-2021 selloff                   |
| Moderate | 30% / 2 days  | 2022 Luna collapse                 |
| Severe   | 40% / 1 day   | 2020 COVID crash peak-to-trough    |

### Shock-impact model

For a shock of magnitude X% and position_frac P:

```
if X <= stop_loss_pct:
    per_trade_loss ≈ stop_loss_pct × P    (stop catches intra-bar)
else:
    per_trade_loss ≈ X × P                (gap-through; stop fires at gap open ≈ shock price)
```

Liquidation occurs when `per_trade_loss ≥ 1.0` (100% of equity).

**Conservative assumption**: the shock is delivered as a single adverse
bar. The stop fires at that bar's opening price (approximating a
gap-through). Slippage on stop fills is NOT included in this table —
real slippage would make the numbers worse by `slippage × frac`.

---

## 2. Per-cell survivability table (representative)

### Phase 5A primaries (frac ≤ 1.333)

| Cell                              | frac  | 20%   | 30%   | 40%   | verdict |
|-----------------------------------|------:|------:|------:|------:|---------|
| A_both sl=1.5% wick r=2% L=2x     | 1.333 | −26.7%| −40.0%| −53.3%| SURVIVE |
| A_long sl=1.5% close r=2% L=2x    | 1.333 | −26.7%| −40.0%| −53.3%| SURVIVE |
| C_long sl=2.0% close r=2% L=2x    | 1.000 | −20.0%| −30.0%| −40.0%| SURVIVE |

All three Phase 5A cells survive every shock with manageable loss.

### Phase 6 D1 cells at different frac levels

| Cell                                  | frac  | 20%   | 30%   | 40%   | verdict |
|---------------------------------------|------:|------:|------:|------:|---------|
| D1_both sl=1.5% wick r=2% L=2x         | 1.333 | −26.7%| −40.0%| −53.3%| SURVIVE |
| D1_both sl=1.25% wick r=2% L=2x        | 1.600 | −32.0%| −48.0%| −64.0%| SURVIVE |
| D1_both sl=1.25% wick r=2.5% L=2x      | 2.000 | −40.0%| −60.0%| −80.0%| SURVIVE |
| D1_both sl=1.25% wick r=3% L=3x        | 2.400 | −48.0%| −72.0%| −96.0%| SURVIVE (tight) |
| D1_both sl=1.5% wick r=4% L=3x         | 2.667 | −53.3%| −80.0%|**LIQ**| LIQ on 40% |
| D1_both sl=1.25% wick r=4% L=3x        | 3.000 | −60.0%| −90.0%|**LIQ**| LIQ on 40% |
| D1_both sl=1.25% wick r=4% L=5x        | 3.200 | −64.0%| −96.0%|**LIQ**| LIQ on 40% |
| D1_both sl=1.00% wick r=4% L=5x        | 4.000 | −80.0%|**LIQ**|**LIQ**| LIQ on 30% |

### D1_long cells (long-only cleaner risk)

Same per-frac impact as D1_both (the shock model doesn't distinguish
side — a 30% drop is a 30% drop whether you're long 1× or long 3×).
D1_long at frac = 3.0 gets liquidated on 40% shock just like D1_both.

**But directional impact matters**: shorts get hit on UP-moves. If the
synthetic shock is an UP-move (e.g. short squeeze), D1_long is
unaffected while D1_both takes the hit. In the long run with both
sides active, you take the tail from both directions.

---

## 3. The position_frac safety tiers

Clean tiering from the data:

| Tier    | frac range  | Liquidation on |
|---------|-------------|----------------|
| **Safe** | ≤ 2.00      | None of the three shocks |
| Tight   | 2.00 − 2.40 | Survives 40% but margin < 5% |
| At-risk | 2.40 − 3.20 | LIQ on 40% shock only |
| Danger  | 3.20 − 4.00 | LIQ on 30% AND 40% shocks |
| Ruin    | > 4.00      | LIQ on 20% shock |

The Phase 6 "safety ceiling" is **frac = 2.0**. Above it, you are
betting that the 4-year OOS window's actual tail (~15% max adverse)
continues to be the worst realistic future tail. History suggests
that bet is loose.

### What the backtest did NOT contain

The 8 OOS windows (2022-04 to 2026-04) had these max adverse moves
per candidate:

| Candidate | Worst adverse move in OOS |
|-----------|---------------------------:|
| A_both    | 14.05% |
| A_long    | 10.25% |
| C_long    |  8.67% |
| D1_both   | 15.18% |
| D2_shadow |  9.54% |

**None exceeded 16%.** The synthetic 20% shock is already outside
the OOS sample. The 30% and 40% shocks are events the OOS backtest
simply has no data for. Phase 6's tail analysis is a pure
forward-looking sanity check, not a backtest-derived probability.

Real-world 20%+ BTC moves in recent history:
- 2020-03-12 COVID: −40% in 24h
- 2021-05-19 China ban: −30% in 24h
- 2022-06-13 post-Luna: −15% in 24h (smaller, drawn out)
- 2022-11-08 FTX: −25% in 48h
- These ALL happened within the past 5 years — they are not theoretical.

**Any cell at frac > 2.0 would have been damaged or liquidated** in
at least one of these events if the strategy had been live.

---

## 4. Tail-event interaction with stops

### Does the stop-loss help against a 40% shock?

**Only partially.** The stop is designed for intra-bar moves. For a
gap-through shock (open below the stop level), the fill price is at
the gap open, not at the stop level:

- Stop set at 1.25% below entry (price 98.75)
- Shock: next bar opens at 70 (30% down)
- Stop "fires" but fill is at 70, not 98.75
- Per-trade loss = (70 − 100) / 100 × position_frac = 30% × frac

In the analysis table above, this gap-through scenario is what drives
the "shock × frac" loss column.

### When does the stop genuinely help?

When the shock is smaller than the stop distance, i.e., when X ≤ S:
- 20% shock + 2% stop: stop fires intra-bar at −2% (not −20%)
- Per-trade loss = 2% × frac (bounded)

In this regime, the stop is doing its job. But X ≤ S only matters for
**mild** shocks. For the 20/30/40% scenarios we're testing, the stop
is effectively bypassed.

### What about ATR-trailing?

Phase 4 already tested ATR trailing stops: uniformly dominated by
time-stop on return/DD. Phase 6 does not revisit this — the primary
exit continues to be time-stop + opposite-flip. A volatility-aware
stop COULD in theory reduce gap-through exposure by exiting positions
earlier in rising-volatility regimes, but Phase 4's empirical result
says the cost of the stop's false exits exceeds the tail benefit
within the OOS window.

---

## 5. Combined with slippage stress

The tail-event table assumes zero slippage. In practice, a gap-through
stop would fill worse than the gap open due to liquidity draining.
Adding realistic 1% slippage:

| frac | 40% shock, no slip | 40% shock, 1% slip on stop |
|------|:------------------:|:--------------------------:|
| 2.00 |      −80.0%        |         −82.0%             |
| 2.40 |      −96.0%        |      **LIQUIDATED**        |
| 2.67 |    LIQUIDATED      |      LIQUIDATED            |

The **frac = 2.4 tier** moves from "SURVIVE (tight)" to "LIQUIDATED"
when slippage is considered. The **hard ceiling therefore drops to
frac = 2.0** once slippage is included.

---

## 6. Recommendations

### 6.1 Hard deployment rule

**Do NOT deploy any cell with `actual_position_frac > 2.0`** for
capital at risk. No matter how high the baseline OOS return, the
tail-event math says a 40% shock delivers account-ending loss.

### 6.2 Soft deployment rule

Prefer `actual_position_frac ≤ 1.5` for extra margin of safety against
multi-bar drawdowns and slippage-amplified losses.

### 6.3 Return-expansion beyond frac=2.0 requires real tail hedges

If the user wants to run frac=3 or higher in production, the backtest
numbers are not sufficient evidence. Real hedging would need:
1. **Out-of-the-money put options** on BTC perp (or equivalent VIP
   protection) to cap per-trade tail loss
2. **Portfolio-level stop** that closes all positions when the account
   draws down more than X%
3. **Funding-rate regime filter** that reduces exposure when funding
   is hot (signalling crowded positioning)
4. **Cross-margin with substantial free collateral** to absorb
   gap-through events without getting liquidated

None of these are in the current Phase 6 scope. They are Phase 7+.

### 6.4 Frac-2.0 sweet spot cells

The cells at the exact frac = 2.0 safety ceiling with highest return:

| Cell                                    | Return | DD     | Trades | Worst Trade |
|-----------------------------------------|-------:|-------:|-------:|------------:|
| D1_both sl=1.25% wick r=2.5% L=2x       | +643.45%| 37.08% |  141  |   −9.45%   |
| D1_both sl=1.0% wick  r=2.0% L=2x       | +517.59%| 42.70% |  150  |   −9.45%   |
| D1_both sl=1.25% close r=2.5% L=2x      | +500.39%| 34.76% |  127  |   −9.45%   |
| D1_long sl=1.25% wick r=2.5% L=2x       | +345.18%| 22.60% |   79  |   −9.25%   |
| C_long  sl=1.0%  close r=2.0% L=2x      | +338.37%| 33.90% |  179  |   −9.27%   |
| A_both  sl=1.0%  wick  r=2.0% L=2x      | +231.15%| 40.63% |  126  |   −9.32%   |

D1_both at frac = 2.0 with a 1.25% wick stop gives **+643%** — the
highest cell that passes the tail-event safety ceiling. Worst trade
is −9.45% (manageable).

But this needs to also survive the slippage stress. The slippage
report showed 1.25% wick cells degrade substantially at 0.3%+ slip.
The best slippage-resistant cell at frac = 2.0 is:

**D1_both sl=1.25% close r=2.5% L=2x frac = 2.0** → +500.39% / DD 34.76%
- Close trigger → better slippage resistance
- frac = 2.0 → at the tail safety ceiling
- Survives 40% shock at −80% equity (recoverable, not ruined)

---

## 7. The "safest deployable + highest-return survivable" picks

Based on tail-event analysis alone (before combining with the final
recommendation):

### Safest (most conservative)

**C_long @ sl=2% close r=2% L=2x frac = 1.0** → +106% / DD 18%
- Survives 40% shock at −40% (no liquidation, recoverable)
- Best slippage resistance
- Highest trade count

### Highest-return survivable

**D1_both @ sl=1.25% close r=2.5% L=2x frac = 2.0** → +500% / DD 35%
- Survives 40% shock at −80% (near-ruin but no liquidation)
- Close trigger → reasonable slippage resistance
- Above the trade count floor
- **Candidate for paper-shadow, not paper-deploy** — frac = 2 is at
  the hard ceiling, so a single tail event still wipes most of the
  account

### Do NOT deploy

- Any cell with frac > 2.0: liquidation risk on 30-40% shocks
- A_both 1.5% wick anything: slippage-fragile, stopped-exit rate 60%
- D1_both/long sl = 1.0% wick anything: wick+tight+high-frac = cascade failure

See `strategy_c_v2_phase6_final_recommendation.md` for the combined
tail + slippage + trade-count ranking.
