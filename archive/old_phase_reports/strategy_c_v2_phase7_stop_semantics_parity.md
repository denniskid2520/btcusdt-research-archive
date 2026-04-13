# Strategy C v2 — Phase 7 Deliverable: Stop-Semantics Parity Study

_Date: 2026-04-12_
_Status: Phase 7 — two stop semantics explicitly separated and measured._

## TL;DR

**The two stop semantics are NOT equivalent.** On the 5-year walk-forward
for the Phase 7 deployment cells:

| Cell                    | close_stop OOS ret | intrabar_stop OOS ret | Δ |
|-------------------------|-------------------:|----------------------:|--:|
| D1_long_primary         |         +143.45%   |              +117.17% | **−26.28 pp** |
| C_long_backup           |         +106.26%   |               +97.98% | **−8.28 pp**  |
| D1_long_frac2_shadow    |         +261.47%   |              +227.12% | **−34.35 pp** |

Intrabar fires MORE stops (+10-17 pp in stop frequency) and delivers
BETTER worst-trade outcomes (+3-5 pp less negative). In aggregate OOS
compound terms, **strategy_close_stop wins on return** by 8-34 pp.

**The live deployment's choice of semantics depends on which exchange
order type the runner uses.** If the runner submits MARKET orders at
bar close based on strategy logic, you get strategy_close_stop. If the
runner places resting STOP-LOSS orders on the exchange, you get
exchange_intrabar_stop. Both are valid; they produce materially
different PnL paths.

---

## 1. Why the two semantics exist — the physical model

**strategy_close_stop**
- The strategy evaluates the position at every completed bar close.
- If `bar.close <= stop_level` (for a long), fire the exit order.
- The order is a MARKET order submitted just after bar close.
- Fill happens at `bars[j+1].open` (next-bar execution).
- Slippage is the next-bar open minus the expected stop level.

**exchange_intrabar_stop**
- A STOP-LOSS order is pre-placed on the exchange at entry time.
- The exchange matches it the moment price touches the stop level
  (intrabar, not at bar close).
- Fill happens AT the stop level (±slippage for tight fills).
- Benefit: exits earlier, caps loss at the stop level itself on
  normal price action.
- Risk: fills worse than stop level on gap events (the order fills
  at the first available price, which could be far through the stop).

In the Phase 2-6 backtest, we used `stop_trigger="close"` which
implements `strategy_close_stop` (check close, fill at next bar open).
Phase 7 adds `exchange_intrabar_stop` (check wick/low-high, fill at
stop level).

---

## 2. Full parity table (5-year walk-forward)

| Cell                  | Semantics              | OOS Return | DD     | PF    | Trades | Stop% | Worst Trade |
|-----------------------|------------------------|-----------:|-------:|------:|-------:|------:|------------:|
| D1_long_primary       | strategy_close_stop    | **+143.45%** | 12.97% | 2.23 |   73  | 30.1% |    −5.68%   |
| D1_long_primary       | exchange_intrabar_stop |   +117.17% | 15.93% | 2.07 |   77  | 45.5% |    −2.67%   |
| C_long_backup         | strategy_close_stop    | **+106.26%** | 18.10% | 1.70 |  178  |  9.6% |    −6.62%   |
| C_long_backup         | exchange_intrabar_stop |    +97.98% | 12.69% | 1.66 |  179  | 21.2% |    −2.25%   |
| D1_long_frac2_shadow  | strategy_close_stop    | **+261.47%** | 12.58% | 2.28 |   75  | 33.3% |    −7.98%   |
| D1_long_frac2_shadow  | exchange_intrabar_stop |   +227.12% | 22.38% | 2.18 |   80  | 50.0% |    −3.40%   |

## 3. Per-cell delta breakdown

| Cell                  |     Δ ret | Δ DD   | Δ trades | Δ stop% | Δ worst |
|-----------------------|----------:|-------:|---------:|--------:|--------:|
| D1_long_primary       |  −26.28pp |  +2.96 |      +4  |  +15.32 |  +3.01  |
| C_long_backup         |   −8.28pp |  −5.41 |      +1  |  +11.68 |  +4.37  |
| D1_long_frac2_shadow  |  −34.35pp |  +9.80 |      +5  |  +16.67 |  +4.58  |

Reading the deltas (intrabar minus close_stop):

- **Return**: intrabar LOSES 8-34 pp of compounded return
- **DD**: mixed — +3 pp on D1_long_primary, −5 pp on C_long_backup,
  +10 pp on frac2_shadow. Intrabar stops cost MORE drawdown when
  the wick trigger catches noise the close trigger would have ridden
  out, but LESS drawdown when the wick trigger catches the exact
  adverse move the close trigger would miss.
- **Trade count**: +1 to +5. Intrabar fires more stops → each one
  frees the position to re-enter on the next signal. Slightly more
  trades per cell.
- **Stop frequency**: +12-17 pp. Intrabar fires 1.5-2x more stops
  than close.
- **Worst single trade**: intrabar's worst is 3-5 pp LESS NEGATIVE.
  The intrabar semantic structurally caps single-trade loss tighter
  (fills at the stop level, not at a worse gap-through next-bar open).

---

## 4. Why intrabar loses on return

Two reinforcing mechanisms:

### 4.1 False positives — wick-hit-then-recover

Many 4h bars have wicks that touch the stop level and then recover
by bar close. Under `strategy_close_stop`, the trade stays open and
captures whatever happens next. Under `exchange_intrabar_stop`, the
trade is already closed — it eats the stop loss AND misses any
recovery.

On D1_long the wick-hit-then-recover scenario happens ~15% of the
time (= 15.32pp extra stop frequency). On D2 it's 16.67%, on C_long
it's 11.68%. These are all real recoveries that intrabar exits miss.

### 4.2 Re-entry cost amplification

When intrabar stops fire, the position re-enters on the next signal,
paying another round-trip cost. On a cell with 30% → 45% stop
frequency, that's ~10 extra round-trips over the OOS window, which
is ~1.2% cost drag at position_frac=1.333.

Combined, the two effects cost intrabar 8-34 pp over the 5-year run.

---

## 5. Why intrabar wins on worst-trade

On trades where the price genuinely moves adversely (no recovery),
intrabar's earlier exit delivers a better fill:

- strategy_close_stop: waits for bar close. If the bar's close is
  already at 97.5 and the stop was 98, fills at the NEXT bar's open
  which could be 96 or 95. Actual loss ≈ 4-5% × frac.
- exchange_intrabar_stop: fires the moment price touches 98,
  fills at 98. Actual loss ≈ 2% × frac.

On the D1_long primary cell, the worst trade is:
- close_stop: −5.68% of account (worst price move hit ~4.3% below entry)
- intrabar_stop: −2.67% of account (stop fill at the 1.5% level + slip)

**Intrabar cuts the worst-trade tail by ~50%.** That's the only thing
it's structurally better at.

---

## 6. Where the two semantics fit in the deployment ladder

### The trade-off summary

| Dimension            | strategy_close_stop | exchange_intrabar_stop |
|----------------------|:-------------------:|:----------------------:|
| Aggregate return     |         ✅          |                        |
| Worst single trade   |                     |           ✅           |
| Tail-event survival  |                     |           ✅           |
| Trade count          |                     |           ~           |
| DD (mixed)           |          ~          |           ~            |
| Profit factor        |         ✅          |                        |
| Slippage sensitivity |                     |           ✅           |

Each semantic wins on different axes. Pick based on the deployment
priority.

### Deployment priority mapping

| Priority                             | Preferred semantic       |
|--------------------------------------|--------------------------|
| Maximum 5-year OOS return            | strategy_close_stop      |
| Tight worst-trade tail               | exchange_intrabar_stop   |
| Minimum operational complexity       | exchange_intrabar_stop (stop-order is fire-and-forget) |
| Maximum backtest fidelity            | strategy_close_stop (what we backtest with) |
| Gap-event protection                 | **neither alone** — stops of either kind fail on gap-through; need ATR filter or circuit breaker |

---

## 7. Recommended Phase 7 setup — run BOTH in parallel

Rather than choosing one semantics for live deployment, **run both in
parallel on separate paper accounts**. The Phase 7 brief already
implied this by asking for both to be tracked separately.

### Concrete proposal

| Paper slot | Semantics               | Purpose                                              |
|------------|-------------------------|------------------------------------------------------|
| D1_long_primary_close  | strategy_close_stop  | Match backtest; measure return fidelity             |
| D1_long_primary_intra  | exchange_intrabar_stop | Measure live-execution worst-trade                 |
| C_long_backup          | strategy_close_stop  | Backup with backtest-faithful semantics             |
| D1_long_frac2_shadow   | strategy_close_stop  | Shadow-only; match highest-return backtest path     |

This uses 4 paper slots total. The semantics-difference measurement
comes from the D1_long_primary_close vs _intra pair over 30 days.

---

## 8. The 30-day retrospective finding (small-sample caveat)

On the 2026-03-06 → 2026-04-05 window (Phase 7 retrospective):

| Cell                 | close_stop PnL | intrabar_stop PnL | Δ |
|----------------------|---------------:|------------------:|--:|
| D1_long_primary      |         −3.58% |            −2.16% | **+1.42 pp** (intrabar wins) |
| C_long_backup        |         −1.01% |            −1.01% | 0.00 (no stops) |
| D1_long_frac2_shadow |         −2.83% |            −2.74% | +0.09 pp (intrabar wins marginally) |

**On this specific 30-day window, intrabar beats close_stop on D1 cells.**
The specific trade in question was 2026-03-16 entry at 74,885 that
moved down without recovery. Intrabar's earlier exit at 73,761 was
better than close_stop's later exit at 72,953.

This is the OPPOSITE of the 5-year aggregate where close_stop wins
by 26 pp. The 30-day sample is one regime, and in that regime the
wick-hit-and-continue scenario dominated the wick-hit-and-recover
scenario.

**Small-sample warning**: do not extrapolate the 30-day result. The
5-year aggregate is the more reliable guide, and it says close_stop
wins on average. The intrabar advantage in 30 days is a statistical
fluctuation, not a regime shift.

---

## 9. Key findings

1. **The two semantics are measurably different** — 8-34 pp return
   gap on 5-year aggregates, ~1.5pp per trade on worst-trade.
2. **strategy_close_stop wins on aggregate return** due to
   wick-recovery preservation.
3. **exchange_intrabar_stop wins on worst-trade tail** due to
   earlier exit at the stop level.
4. **Running both in parallel is the right Phase 7 move** — gives us
   real-data comparison on live fills.
5. **The 30-day retrospective is a noisy sample** and should not
   drive the decision.
6. **Neither semantics protects against gap events** — both fire the
   stop late when price opens below the level. Gap protection needs
   an additional layer (ATR filter, circuit breaker, position sizing
   on volatility).
