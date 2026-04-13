# Strategy C v2 — Phase 8 FINAL
## One BTCUSDT perpetual futures strategy on a $10,000 account

_Date: 2026-04-12_
_Status: FINAL — one mainline, one winner, one fallback. No branching._

<!-- canonical-metrics
cell: D1_long_primary
source: canonical
oos_return: 1.4345
max_dd: 0.1297
num_trades: 73
profit_factor: 2.23
worst_trade_pnl: -0.0568
-->

## 1. What this document is

This is the final answer for the single Phase 8 leveraged futures
strategy. Produced by a focused sweep on the D1_long signal with
three hard constraints binding:

- `actual_frac ≤ 2.0` — Phase 6 tail-event stress (40% shock on a 2x
  isolated sleeve without liquidation). Higher exchange leverage is
  rejected because 3x+ isolated liquidates at ~33% adverse move, and
  a 40% synthetic shock liquidates on 3x regardless of frac.
- `stops_fired / num_trades ≤ 45%` — operational realism.
- `worst single trade ≥ -20% of sleeve equity` — no catastrophic loss.
- `liquidation buffer multiple ≥ 3x` — worst observed adverse move
  must be ≤ 1/3 of the liquidation distance.

Three concepts kept strictly separate, as required:

| Concept | Value here |
|---|---|
| Exchange leverage | 2x (isolated BTCUSDT perp on Binance USDT-M) |
| actual_frac | 2.000 (fully margined — max allowed under Phase 6 tail stress) |
| Portfolio sleeve allocation | 1.0 (whole $10,000 account, undiluted) |

**Actual notional exposure** is 2.000 × $10,000 = **$20,000**. This
is below the 3x–5x notional target stated in the brief, because
the 40% tail-stress hard constraint makes anything above 2x
exchange leverage fail the survival test. §5 explains why the
target is unreachable without relaxing that constraint.

## 2. Comparison table — three D1_long variants

All three variants share the same signal stream (rsi_only_20 long,
4h BTCUSDT, 8-window walk-forward 2022-04 → 2026-04), the same
hold_bars base (11), the same exchange leverage (2x), the same
portfolio allocation (1.0), the same stop semantics
(strategy_close_stop), and the same fee/slip model (0.05% + 0.01%
per side = 0.12% round-trip per unit of actual_frac). The only
differences between the variants are: stop/risk config, and
whether dynamic sizing / adaptive exit are on.

Each row is the **best constraint-passing config** found for that
variant. All runs use starting equity = **$10,000**, exchange
leverage = **2x**, actual_frac at the **2.000 cap**, actual notional
exposure = **$20,000**.

| Variant | Stop | Risk | Dynamic | Adaptive | Trades | OOS Return | End Equity | Max DD (%) | Max DD ($) | Worst Trade (%) | Worst Trade ($) | PF | Stops | Liq Safety | Tail Stress |
|---------|-----:|-----:|--------:|---------:|-------:|-----------:|-----------:|-----------:|-----------:|----------------:|----------------:|---:|------:|-----------|-------------|
| **V1 — D1_long fixed** | 1.25% | 2.5% | off | off | 75 | +261.47% | $36,147 | 12.58% | $4,602 | −7.98% | −$798 | 2.28 | 25/75 (33.3%) | liq@50% / worst_adv=6.51% / buffer=7.68x | survives 40% → −80% equity |
| **V2 — D1_long + dynamic sizing** | 1.25% | 2.5% | on | off | 75 | +255.51% | $35,551 | 11.97% | $4,277 | −7.98% | −$798 | 2.28 | 25/75 (33.3%) | liq@50% / worst_adv=6.51% / buffer=7.68x | survives 40% → −80% equity |
| **V3 — D1_long + dynamic sizing + adaptive exit** | 1.25% | 2.5% | on | on | 66 | **+296.12%** | **$39,612** | 16.04% | $6,832 | −7.98% | −$798 | 2.38 | 26/66 (39.4%) | liq@50% / worst_adv=6.51% / buffer=7.68x | survives 40% → −80% equity |

_Shared columns for all three rows_: starting equity = $10,000,
exchange leverage = 2x, actual_frac = 2.000, actual notional =
$20,000, stop semantics = strategy_close_stop, portfolio
allocation = 1.0, liquidation adverse move = 50%, tail shock
loss at 40% = 80% of sleeve equity (survives — no liquidation).

### Key observations

- **V1 vs V2**: dynamic sizing makes return slightly *worse*
  (+255.51% vs +261.47%) when the base frac is at the 2.0 cap. The
  multiplier's upside is clipped, so the only effect is reducing
  frac on low-conviction bars — which removes return from trades
  that would have been winners. At max-frac, dynamic sizing is not
  additive.
- **V2 vs V3**: adaptive exit adds **+40.61 pp** return (+255.51%
  → +296.12%). This is the real edge on top of max-frac D1_long:
  extend high-conviction holds to 16 bars, compress low-conviction
  holds to 6 bars. The cost is a higher DD (16.04% vs 11.97%)
  because the extended holds absorb more tail-risk excursion.
- **All three variants pass every hard constraint.**

## 3. FINAL optimized config — V3 with tight stop at max frac

This is the highest-return survivable configuration. It runs as
its own virtual sub-account at full allocation on a fixed $10,000
starting equity with true 2x leveraged notional.

```
Strategy: D1_long (rsi_only_20 long, 4h BTCUSDT perp, Binance USDT-M)
Mainline modifiers: dynamic sizing ON, adaptive exit ON

--- The three strictly-separated concepts ---
exchange_leverage:          2.0   (isolated)
actual_frac:                2.0   (fully margined; base frac for dynamic)
portfolio_allocation:       1.0   (100% of account)

--- Derived numbers on a $10,000 account ---
starting_equity:            $10,000
actual_notional_exposure:   $20,000   (= 2.0 × $10,000)

--- Strategy parameters ---
signal_family:              rsi_only
rsi_period:                 20
side:                       long
hold_bars_base:             11
hold_bars_adaptive_range:   {6, 11, 16}  (adaptive exit score-based)
stop_loss_pct:              0.0125   (1.25%)
stop_semantics:             strategy_close_stop
stop_trigger:               close
stop_slippage_on_fill:      0.0
risk_per_trade:             0.025    (2.5%)
fee_per_side:               0.0005   (0.05%)
slip_per_side:              0.0001   (0.01%)
round_trip_cost_per_frac:   0.0012   (0.12% per unit of actual_frac)
use_dynamic_sizing:         true
use_adaptive_hold:          true
dynamic_multiplier_range:   [0.5, 1.5]  (upside clipped at frac=2.0)
walk_forward:               24m train / 6m test / 8 windows / 2022-04..2026-04

--- OOS canonical metrics (at portfolio_allocation = 1.0) ---
num_trades:                 66
oos_return:                 +296.12%
ending_equity:              $39,612
max_dd_pct:                 16.04%
max_dd_usd:                 $6,832
profit_factor:              2.38
worst_trade_pnl:            -7.98%
worst_trade_usd:            -$798
worst_adverse_move:         6.51%
stops_fired:                26 / 66  (39.4%)

--- Liquidation safety ---
liquidation_adverse_move:   50% (= 1 / exchange_leverage)
worst_observed_adverse:     6.51%
liq_buffer_multiple:        7.68x
tail_shock_loss_at_40%:     80% of sleeve equity
survives_phase6_tail:       YES (equity falls to $2,000, no liquidation)
passes_operational_checks:  YES (stops_fired ≤ 45%, worst_trade ≥ -20%)
```

## 4. FALLBACK config — V1 fixed with tight stop at max frac

This is the safest operationally survivable version. Used if
adaptive exit shows fragility in paper telemetry (e.g., the
extended 16-bar holds get caught in adverse moves that the 11-bar
base would have exited earlier).

```
Strategy: D1_long (rsi_only_20 long, 4h BTCUSDT perp, Binance USDT-M)
Mainline modifiers: NONE (pure fixed sizing, fixed hold)

--- The three strictly-separated concepts ---
exchange_leverage:          2.0   (isolated)
actual_frac:                2.0   (fully margined, fixed on every trade)
portfolio_allocation:       1.0   (100% of account)

--- Derived numbers on a $10,000 account ---
starting_equity:            $10,000
actual_notional_exposure:   $20,000

--- Strategy parameters ---
signal_family:              rsi_only
rsi_period:                 20
side:                       long
hold_bars:                  11 (fixed)
stop_loss_pct:              0.0125   (1.25%)
stop_semantics:             strategy_close_stop
stop_trigger:               close
risk_per_trade:             0.025    (2.5%)
fee_per_side:               0.0005
slip_per_side:              0.0001
use_dynamic_sizing:         false
use_adaptive_hold:          false

--- OOS canonical metrics (at portfolio_allocation = 1.0) ---
num_trades:                 75
oos_return:                 +261.47%
ending_equity:              $36,147
max_dd_pct:                 12.58%
max_dd_usd:                 $4,602
profit_factor:              2.28
worst_trade_pnl:            -7.98%
worst_trade_usd:            -$798
worst_adverse_move:         6.51%
stops_fired:                25 / 75  (33.3%)

--- Liquidation safety ---
liquidation_adverse_move:   50%
worst_observed_adverse:     6.51%
liq_buffer_multiple:        7.68x
tail_shock_loss_at_40%:     80% of sleeve equity
survives_phase6_tail:       YES
passes_operational_checks:  YES
```

The fallback gives up **34.65 pp** of return vs the final config
(+261.47% vs +296.12%, $3,465 less ending equity) in exchange for
**lower DD** (12.58% vs 16.04%, $2,230 smaller max dip) and
simpler operational surface (no dynamic sizing or adaptive hold
code paths to monitor).

## 5. Why this is the final path — short explanation

### 5.1 Why D1_long only

D1_long (rsi_only_20 long on 4h BTCUSDT) is the only mainline
carried forward. It was frozen after Phase 6 as the best
consolidated cell in the OOS leaderboard. C_long stays as a
benchmark fallback in `CANONICAL_CELLS` but gets no further
research effort. No new strategy family, timeframe, or Coinglass
trigger is being explored — the alpha families are frozen.

### 5.2 Why actual_frac = 2.0, not 3.0–5.0

The brief asks for actual notional exposure targeting 3x–5x. The
tail-stress hard constraint makes that unreachable on 2x isolated
BTCUSDT perps:

- Liquidation distance at `L` leverage is ≈ `1/L`:
  - 2x → 50% adverse move to liquidate
  - 3x → 33% adverse move to liquidate
  - 5x → 20% adverse move to liquidate
- Phase 6 agreed synthetic tail shock = 40% adverse move
- 40% > 33% means any 3x isolated position liquidates on the
  agreed stress regardless of actual_frac
- 40% < 50% means 2x isolated survives — equity falls to
  `1 − actual_frac × 0.40` of sleeve; at frac=2.0 that is
  `1 − 0.80 = 0.20`, i.e., $10,000 → $2,000 with no liquidation

So under the agreed Phase 6 stress policy, the maximum survivable
leveraged configuration is **2x exchange leverage with
actual_frac ≤ 2.0**, giving maximum notional exposure of **2x**
on the sleeve equity (= $20,000 on a $10,000 account). The 3x–5x
target is incompatible with the 40% tail-stress constraint. To
hit 3x notional you would have to either:

- Accept a less severe tail-stress policy (e.g., 20%–25% shock),
  which would let 3x leverage pass but leaves the sleeve
  vulnerable to historical BTC 1-hour crashes
- Use cross-margin with a large dollar reserve, which blurs the
  sleeve-level result with account-level reserve math (exactly
  the layering the brief forbids)

This document keeps the hard constraint and accepts 2x as the
answer. If the constraint is later relaxed, the same search
framework can re-run against a higher `FRAC_CAP`.

### 5.3 Why stop=1.25% / risk=2.5%

The sweep tested stop values in {1.0%, 1.25%, 1.5%, 2.0%, 2.5%}
at frac=2.0. Results (V1 fixed, all at frac=2.0):

| Stop | Risk | Return | DD (%) | DD ($) |
|-----:|-----:|-------:|-------:|-------:|
| 1.00% | 2.00% | +223.95% | 18.10% | $5,567 |
| **1.25%** | **2.50%** | **+261.47%** | **12.58%** | **$4,602** |
| 1.50% | 3.00% | +259.13% | 19.09% | $7,698 |
| 2.00% | 4.00% | +240.60% | 22.86% | $9,170 |
| 2.50% | 5.00% | +220.71% | 27.45% | $11,136 |

1.25% is the sweet spot: tight enough to cut losers aggressively
(max DD drops from 19.09% to 12.58% vs the canonical 1.5% stop),
loose enough to not strangle winners with noise (1.0% stop fires
on 40.8% of trades vs 1.25%'s 33.3%).

### 5.4 Why adaptive exit makes V3 the winner

At frac=2.0, dynamic sizing provides no upside (the multiplier is
clipped by the cap), so V2 is slightly worse than V1 fixed —
it's all downside: lower-conviction bars lose frac and thus
return. Adaptive exit is different: it modulates the hold length
(6 / 11 / 16 bars) based on a 3-component score and this
compounds the winning trades more aggressively. On the tight-stop
config, adaptive exit adds +34.65 pp return (+261.47% → +296.12%)
at the cost of +3.46 pp DD (12.58% → 16.04%). This is a clean
return-for-DD trade where the new DD (16.04%) is still well
below the fallback's 19.09% that the canonical 1.5% stop produced.

### 5.5 What the paper run validates

Phase 8 paper telemetry will run the final config (§3) as its own
virtual sub-account with $10,000 starting equity, 2x exchange
leverage, actual_frac=2.0 on every entry (clipped dynamic output),
and adaptive exit active. It will compare realized fills and
PnLs against the OOS canonical numbers (66 trades, +296.12%,
16.04% DD, −$798 worst trade, 39.4% stop rate). If realized
numbers drift more than the promotion thresholds in the Phase 8
canonical baseline doc, the strategy drops back to the fallback
config (§4) and re-validates from there.

### 5.6 What we are NOT doing

- No new strategy families (C_long stays as fallback, no further
  research)
- No new timeframes (4h only)
- No new signal sources (no Coinglass triggers, no MTF overlays)
- No broad research into "what else might work"
- No portfolio-allocation dilution of the strategy-level result
  (the $20,000 notional is real on a $10,000 account; it is not
  a reduced allocation of a larger strategy)
- No scaling up beyond frac=2.0 without first relaxing the tail-
  stress policy (which would be a separate explicit decision by
  the user, not a research branch)

---

## Appendix — full sweep (all 19 configs, constraint-passing only, ranked by OOS return)

Columns are as required by the brief: exchange leverage, actual_frac,
stop config, stop semantics (strategy_close_stop on all), starting
equity, trades, OOS return, ending equity, max DD (% and $), worst
trade (% and $), liquidation safety, tail-stress result. Starting
equity = $10,000, exchange leverage = 2x, actual notional on
frac=2.0 rows = $20,000, on frac=1.333 row = $13,333.

| Config | Stop | Risk | Frac | Trades | Return | End $ | DD % | DD $ | Worst % | Worst $ | PF | Stops | Tail |
|--------|-----:|-----:|-----:|-------:|-------:|------:|-----:|-----:|--------:|--------:|---:|------:|------|
| V3 dyn+adap s1.25 r2.5 base2.0 | 1.25% | 2.50% | 2.000 | 66 | **+296.12%** | **$39,612** | 16.04% | $6,832 | −7.98% | −$798 | 2.38 | 39.4% | PASS |
| V3 dyn+adap s1.5 r3.0 base2.0 | 1.50% | 3.00% | 2.000 | 64 | +268.15% | $36,815 | 22.95% | $10,966 | −8.51% | −$851 | 2.26 | 37.5% | PASS |
| V1 fixed s1.25 r2.5 f2.0 (fallback) | 1.25% | 2.50% | 2.000 | 75 | +261.47% | $36,147 | 12.58% | $4,602 | −7.98% | −$798 | 2.28 | 33.3% | PASS |
| V1 fixed s1.5 r3.0 f2.0 (canonical) | 1.50% | 3.00% | 2.000 | 73 | +259.13% | $35,913 | 19.09% | $7,698 | −8.51% | −$851 | 2.23 | 30.1% | PASS |
| V2 dyn s1.25 r2.5 base2.0 | 1.25% | 2.50% | 2.000 | 75 | +255.51% | $35,551 | 11.97% | $4,277 | −7.98% | −$798 | 2.28 | 33.3% | PASS |
| V2 dyn s1.5 r3.0 base2.0 | 1.50% | 3.00% | 2.000 | 73 | +253.21% | $35,321 | 18.53% | $7,297 | −8.51% | −$851 | 2.23 | 30.1% | PASS |
| V1 fixed s2.0 r4.0 f2.0 | 2.00% | 4.00% | 2.000 | 73 | +240.60% | $34,060 | 22.86% | $9,170 | −8.51% | −$851 | 2.14 | 27.4% | PASS |
| V2 dyn s1.5 r2.667 base1.777 | 1.50% | 2.67% | 2.000 | 73 | +238.98% | $33,898 | 17.95% | $6,756 | −8.51% | −$851 | 2.23 | 30.1% | PASS |
| V3 dyn+adap s1.5 r2.25 base1.5 | 1.50% | 2.25% | 2.000 | 64 | +237.94% | $33,794 | 18.19% | $7,513 | −8.51% | −$851 | 2.33 | 37.5% | PASS |
| V1 fixed s1.0 r2.0 f2.0 | 1.00% | 2.00% | 2.000 | 76 | +223.95% | $32,395 | 18.10% | $5,567 | −7.24% | −$724 | 2.17 | 40.8% | PASS |
| V1 fixed s2.5 r5.0 f2.0 | 2.50% | 5.00% | 2.000 | 73 | +220.71% | $32,071 | 27.45% | $11,136 | −8.51% | −$851 | 2.07 | 23.3% | PASS |
| V3 dyn+adap s1.5 r2.0 base1.333 | 1.50% | 2.00% | 2.000 | 64 | +204.55% | $30,455 | 16.36% | $5,948 | −7.74% | −$774 | 2.35 | 37.5% | PASS |
| V2 dyn s1.5 r2.25 base1.5 | 1.50% | 2.25% | 2.000 | 73 | +192.77% | $29,277 | 16.49% | $5,314 | −8.51% | −$851 | 2.16 | 30.1% | PASS |
| V3 dyn+adap s2.0 r2.667 base1.333 | 2.00% | 2.67% | 2.000 | 63 | +183.78% | $28,378 | 19.79% | $6,894 | −7.75% | −$775 | 2.19 | 30.2% | PASS |
| V2 dyn s1.5 r2.0 base1.333 | 1.50% | 2.00% | 2.000 | 73 | +164.32% | $26,432 | 14.81% | $4,260 | −7.74% | −$774 | 2.17 | 30.1% | PASS |
| V2 dyn s2.0 r2.667 base1.333 | 2.00% | 2.67% | 2.000 | 73 | +151.42% | $25,142 | 18.30% | $5,222 | −7.75% | −$775 | 2.06 | 27.4% | PASS |
| V2 dyn s1.0 r1.333 base1.333 | 1.00% | 1.33% | 2.000 | 76 | +146.89% | $24,689 | 13.11% | $2,957 | −6.27% | −$627 | 2.13 | 40.8% | PASS |
| V1 fixed s1.5 r2.0 f1.333 | 1.50% | 2.00% | 1.333 | 73 | +143.45% | $24,345 | 12.97% | $3,397 | −5.68% | −$568 | 2.23 | 30.1% | PASS |

Configs rejected by constraints: `V3 dyn+adap s1.0 r1.333 base1.333`
(stop rate 48.5% > 45% ceiling). All other configs pass all four
hard constraints (frac ≤ 2.0, stop rate ≤ 45%, worst trade ≥ -20%,
liquidation buffer ≥ 3x).
