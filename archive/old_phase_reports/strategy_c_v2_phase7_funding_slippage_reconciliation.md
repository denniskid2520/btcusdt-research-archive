# Strategy C v2 — Phase 7 Deliverable: Funding / Slippage Reconciliation

_Date: 2026-04-12_
_Status: Phase 7 — 30-day retrospective reconciliation format + data._

## TL;DR

Over the 30-day retrospective window (2026-03-06 → 2026-04-05):

| Source of PnL divergence | Expected magnitude | Actual (retrospective) |
|--------------------------|-------------------:|-----------------------:|
| Entry slippage           |        ≤ 2 bp/trade |                 0 bp  |
| Exit/stop slippage       |      ≤ 10 bp/trade |                 0 bp  |
| Funding drag             | ≤ 0.05% per 24h hold |       ≤ 0.02% abs    |
| Fee / cost               | exact formula match |             exact     |
| Data timing              |        0 on match    | 0 (backtest = live)  |

**No deviations beyond the model.** The retrospective is the
baseline; any live run must reproduce these numbers. Divergence
in live → plumbing bug.

---

## 1. Reconciliation purpose

The Phase 7 brief requires **daily + weekly reconciliation** between
paper-path PnL and backtest-counterfactual PnL. The reconciliation
answers one question: *"Is the live run matching the model, and
where does it diverge?"*

Four divergence sources are tracked independently:

1. **Slippage** — difference between model fill and paper fill
2. **Funding** — difference between model funding and exchange funding
3. **Fee** — difference between model cost and exchange fee
4. **Data timing** — signal computed on a slightly different bar
   (e.g. live saw a partial bar, model saw a completed bar)

---

## 2. Per-trade reconciliation record

Every closed trade produces a reconciliation record:

```python
@dataclass
class TradeReconciliationRecord:
    trade_id: str
    cell_label: str
    stop_semantics: str
    date: datetime
    # Model (counterfactual backtest)
    model_entry: float
    model_exit: float
    model_gross: float
    model_funding: float
    model_cost: float
    model_net: float
    # Paper (live fill)
    paper_entry: float
    paper_exit: float
    paper_gross: float
    paper_funding: float
    paper_cost: float
    paper_net: float
    # Deltas
    slippage_entry_bp: float    # (paper_entry − model_entry) / model_entry × 10000
    slippage_exit_bp: float
    funding_delta_pp: float     # paper_funding − model_funding
    cost_delta_pp: float        # paper_cost − model_cost
    net_delta_pp: float         # paper_net − model_net (should ≈ sum of above)
    timing_drift_bars: int      # how many bars' worth the live signal came late
```

The reconciler sums these into daily and weekly totals.

---

## 3. 30-day retrospective reconciliation (model vs model — baseline)

Since the retrospective uses the same backtester for both "model" and
"paper" paths, all deltas are 0 by construction. This is the BASELINE
against which real live data is compared.

### D1_long_primary (strategy_close_stop)

| Date       | Trade | Model net | Paper net | Δnet | Entry slip bp | Exit slip bp |
|------------|-------|----------:|----------:|-----:|--------------:|-------------:|
| 2026-03-16 | L     |   −3.58%  |   −3.58%  |  0   |       0       |      0       |

### D1_long_primary (exchange_intrabar_stop)

| Date       | Trade | Model net | Paper net | Δnet | Entry slip bp | Exit slip bp |
|------------|-------|----------:|----------:|-----:|--------------:|-------------:|
| 2026-03-16 | L     |   −2.16%  |   −2.16%  |  0   |       0       |      0       |

### C_long_backup (both semantics identical)

| Date       | Trade | Model net | Paper net | Δnet |
|------------|-------|----------:|----------:|-----:|
| 2026-03-16 | L     |   +0.40%  |   +0.40%  |  0   |
| 2026-03-16 | L     |   −1.41%  |   −1.41%  |  0   |

### D1_long_frac2_shadow (strategy_close_stop)

| Date       | Trade | Model net | Paper net | Δnet |
|------------|-------|----------:|----------:|-----:|
| 2026-03-16 | L     |   −2.83%  |   −2.83%  |  0   |

### D1_long_frac2_shadow (exchange_intrabar_stop)

| Date       | Trade | Model net | Paper net | Δnet |
|------------|-------|----------:|----------:|-----:|
| 2026-03-16 | L     |   −2.74%  |   −2.74%  |  0   |

**All deltas are 0 bp.** The retrospective matches itself by construction.

---

## 4. 30-day reconciliation totals

| Cell                 | Semantics              | Trades | Σ net | Σ model net | Net Δ |
|----------------------|------------------------|-------:|------:|------------:|------:|
| D1_long_primary      | strategy_close_stop    |   1    | −3.58% |     −3.58% |  0 bp |
| D1_long_primary      | exchange_intrabar_stop |   1    | −2.16% |     −2.16% |  0 bp |
| C_long_backup        | strategy_close_stop    |   2    | −1.01% |     −1.01% |  0 bp |
| C_long_backup        | exchange_intrabar_stop |   2    | −1.01% |     −1.01% |  0 bp |
| D1_long_frac2_shadow | strategy_close_stop    |   1    | −2.83% |     −2.83% |  0 bp |
| D1_long_frac2_shadow | exchange_intrabar_stop |   1    | −2.74% |     −2.74% |  0 bp |

**0 bp across the board.** The model path is self-consistent.

---

## 5. Expected live divergence ranges

What a forward 30-day live run should look like, compared to the
retrospective above:

### Entry slippage (market order fills)

- Binance USDT-M BTCUSDT typical market order fill on 100-1000 USDT
  notional: 0-1 bp (very tight)
- On 1000-10000 USDT: 1-3 bp
- On 10000+ USDT: 2-5 bp (may need to split)

**Expected**: 0-2 bp per entry trade. Anything > 5 bp is an alert.

### Exit slippage

Same as entry for non-stop exits. For stop-loss exits:

- strategy_close_stop (market order at bar close): 0-2 bp typical
- exchange_intrabar_stop (stop-market order): 0-5 bp on normal fills,
  50-500 bp on gap events (bar opens through stop)

**Expected**: normal days ≤ 5 bp, gap days up to 100 bp. Anything
> 200 bp on a single fill is an alert.

### Funding accrual

Binance USDT-M funding every 8h at 00:00 / 08:00 / 16:00 UTC. The
rate is published a few minutes before settlement.

Expected difference from model funding: 0 bp if the rate source is
the same. Up to 1-2 bp if rate was mid-rounded in model vs exchange
exact.

**Expected**: ≤ 0.01% absolute difference per trade. Anything > 0.05%
is a flag.

### Fee accrual

Binance taker fee: 0.05% on USDT-M (VIP 0). May be lower with BNB
burn or VIP tiers.

Expected difference: 0 if fee rate matches config. 5-10 bp per trade
if config mismatch (e.g. we assume 0.05% but actual is 0.04% on BNB
burn).

**Expected**: 0 bp. Any non-zero is a config audit trigger.

### Data timing drift

The live runner should compute signals at the same timestamp the
retrospective used. Timing drift means:
- Live signal fired at bar T, retrospective at bar T+1 → signal
  missed by one bar
- Usually caused by: clock drift, data fetch lag, bar completion race

**Expected**: 0 bars. Any 1+ bar drift is an ALERT (affects trade
entry timing).

---

## 6. Per-cell tolerance recommendations

Different cells have different sensitivity to slippage:

### D1_long_primary (frac=1.333, 30% stop frequency)

- Cost per trade: 0.16% (model)
- Slippage sensitivity: **HIGH** — every stopped trade pays
  slippage × 1.333 of equity
- Tolerance: ≤ 5 bp live slippage per stopped trade
- Alert: > 20 bp on any single stopped trade

### C_long_backup (frac=1.000, 10% stop frequency)

- Cost per trade: 0.12% (model)
- Slippage sensitivity: **LOW** — only 10% of trades pay slippage,
  and position_frac is 1.0 (no amplification)
- Tolerance: ≤ 10 bp live slippage per stopped trade
- Alert: > 50 bp on any single stopped trade

### D1_long_frac2_shadow (frac=2.000, 33% stop frequency)

- Cost per trade: 0.24% (model)
- Slippage sensitivity: **VERY HIGH** — every stopped trade pays
  slippage × 2.0 of equity
- Tolerance: ≤ 3 bp live slippage per stopped trade
- Alert: > 15 bp on any single stopped trade

The per-cell tolerance scales inversely with stop frequency ×
position_frac.

---

## 7. Weekly reconciliation report format

Every Sunday, the reconciler produces:

```markdown
## Week ending 2026-MM-DD

### Aggregate PnL by cell

| Cell | Trades | Live net | Retrospective net | Δ |
|---|---|---|---|---|
| ... | ... | ... | ... | ... |

### Slippage accumulation

| Cell | Σ entry slip | Σ exit slip | Σ stop slip |
|---|---|---|---|
| ... | ... | ... | ... |

### Funding reconciliation

| Cell | Live funding | Model funding | Δ |
|---|---|---|---|
| ... | ... | ... | ... |

### Safety alerts fired this week

- (any entries from safety journal)

### Divergence assessment

- Green / Yellow / Red per cell
- Green: net Δ ≤ 10 bp
- Yellow: 10-50 bp
- Red: > 50 bp → escalate

### Week-over-week trend

- (cumulative live net vs retrospective net, plotted)
```

---

## 8. Divergence escalation ladder

| Severity | Condition                                        | Response                        |
|----------|--------------------------------------------------|---------------------------------|
| Green    | Net Δ ≤ 10 bp/day for all cells                  | Continue                        |
| Yellow   | Net Δ 10-50 bp/day or 1 cell > 50 bp             | Log, review, continue           |
| Amber    | Net Δ 50-100 bp/day or 2+ cells > 50 bp          | Review, consider halt          |
| Red      | Net Δ > 100 bp/day or any cell > 200 bp          | Halt, investigate plumbing bug |
| Black    | 3 consecutive days Red or abnormal single event  | Flat all, full audit            |

---

## 9. The critical insight for live deployment

**The retrospective produces 0 bp divergence because it's self-
consistent.** The live run's main job is to stay near 0 bp. Every bp
of divergence is either:

1. **Real execution cost** (slippage, fees) that we should measure
   and factor into future cost assumptions.
2. **Plumbing bug** (feature computation drift, clock skew, fee
   config mismatch, signal timing bug) that we should fix.

At day 30 of the live run, the reconciliation report should be the
PRIMARY evidence for whether to graduate the cells to higher sizing.
If live matches retrospective within tolerance → graduate. If not →
debug.

See `strategy_c_v2_phase7_day30_recommendation.md` for the graduation
criteria.
