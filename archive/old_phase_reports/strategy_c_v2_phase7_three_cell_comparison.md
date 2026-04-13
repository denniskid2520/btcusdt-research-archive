# Strategy C v2 — Phase 7 Deliverable: Three-Cell Comparison

_Date: 2026-04-12_
_Status: Phase 7 — D1_long primary vs C_long backup vs D1_long frac=2 shadow._

## TL;DR

On the **30-day retrospective window**, C_long had the best result
(−1.01%) and D1_long_primary had the worst (−3.58% / −2.16%
depending on semantics). On the **5-year walk-forward**, the ranking
flips — D1_long_frac2_shadow leads at +261-227%, D1_long_primary
next at +143-117%, C_long at +106-98%.

**The 30-day window is a noise sample, not a signal.** The 5-year
aggregate is the reliable guide. The three-cell deployment is
designed to extract different properties from each:

- D1_long_primary → maximum backtest-faithful return at frac 1.333
- C_long_backup → diversification + highest sample / slippage robustness
- D1_long_frac2_shadow → return-expansion candidate, shadow-only until
  survival is proven

---

## 1. Full 5-year aggregate comparison

| Cell                  | Semantics              | OOS Return | DD     | Trades | Worst | Stop% | PF   |
|-----------------------|------------------------|-----------:|-------:|-------:|------:|------:|-----:|
| D1_long_primary       | strategy_close_stop    | **+143.45%** | **12.97%** |   73  | −5.68% | 30.1% | **2.23** |
| D1_long_primary       | exchange_intrabar_stop |   +117.17% | 15.93% |   77  | −2.67% | 45.5% | 2.07 |
| C_long_backup         | strategy_close_stop    |   +106.26% | 18.10% | **178** | −6.62% | 9.6% | 1.70 |
| C_long_backup         | exchange_intrabar_stop |    +97.98% | 12.69% |  179  | **−2.25%** | 21.2% | 1.66 |
| D1_long_frac2_shadow  | strategy_close_stop    | **+261.47%** | 12.58% |  75  | −7.98% | 33.3% | **2.28** |
| D1_long_frac2_shadow  | exchange_intrabar_stop |   +227.12% | 22.38% |   80  | −3.40% | 50.0% | 2.18 |

### Best-in-cell per column

| Dimension            | Winner                                             |
|----------------------|----------------------------------------------------|
| Highest return       | D1_long_frac2_shadow @ strategy_close_stop (+261%) |
| Lowest DD (5-year)   | D1_long_frac2_shadow @ close_stop (12.58%)         |
| Most trades          | C_long @ intrabar_stop (179)                       |
| Lowest worst trade   | C_long @ intrabar_stop (−2.25%)                    |
| Highest profit factor| D1_long_frac2_shadow @ close_stop (2.28)           |

**Observation**: the shadow cell (frac=2.0) wins three of five
dimensions even though it's shadow-only. This is the "return
expansion" case the user's framing identifies — higher frac unlocks
higher return, but survival at frac=2.0 is on the edge per the Phase 6
tail-event report (survives 40% shock with −80% equity).

---

## 2. 30-day retrospective comparison

| Cell                  | Semantics              | Trades | 30d Net | Worst |
|-----------------------|------------------------|-------:|--------:|------:|
| C_long_backup         | strategy_close_stop    |   2    | −1.01%  | −1.41% |
| C_long_backup         | exchange_intrabar_stop |   2    | −1.01%  | −1.41% |
| D1_long_primary       | exchange_intrabar_stop |   1    | −2.16%  | −2.16% |
| D1_long_frac2_shadow  | exchange_intrabar_stop |   1    | −2.74%  | −2.74% |
| D1_long_frac2_shadow  | strategy_close_stop    |   1    | −2.83%  | −2.83% |
| D1_long_primary       | strategy_close_stop    |   1    | −3.58%  | −3.58% |

**30-day ranking (best to worst)**:

1. C_long (both semantics)        → −1.01%
2. D1_long_primary (intrabar)     → −2.16%
3. D1_long_frac2_shadow (intrabar)→ −2.74%
4. D1_long_frac2_shadow (close)   → −2.83%
5. D1_long_primary (close)        → −3.58%

### Small-sample warning

All three cells LOST money in this 30-day window. The sample is
1-2 trades per cell — an unlucky pair of drawdown trades on D1_long
determines the entire cell's PnL. Extrapolating a 30-day result to a
forward 30-day expectation is not statistically meaningful.

---

## 3. Role of each cell in the deployment ladder

### D1_long_primary → "maximum backtest-faithful return"

**Role**: the primary research-backed cell. Represents the Phase 6
winner after the stop-semantics split.

| Property | Value |
|---|---|
| 5-year OOS return (close_stop) | +143.45% |
| 5-year DD | 12.97% |
| Trade sample | 73 (marginal) |
| Worst trade | −5.68% |
| Semantics | strategy_close_stop — matches backtest path |

**Use case**: main capital allocation. The cell the user would deploy
if they had to pick ONE.

**Live deployment concerns**:
1. Trade sample is thin (73 across 4 years = 18/year)
2. Stop-semantics split: the backtest path is strategy_close_stop
   which is harder to implement live (requires the runner to fire
   market orders at bar close, no resting stop protection between)
3. Slippage sensitivity: 30% stop rate × frac 1.333 = ~40% of the
   trade count exposed to stop slippage

### C_long_backup → "diversification + robustness"

**Role**: uncorrelated signal family to D1 (rsi_and_macd instead of
rsi_only). Highest sample size and slippage resistance. Backup
allocation.

| Property | Value |
|---|---|
| 5-year OOS return | +106.26% (close_stop) |
| 5-year DD | 18.10% |
| Trade sample | 178 (strong) |
| Worst trade | −6.62% |
| Semantics | both produce near-identical results (9.6% → 21.2% stop%) |

**Use case**: paper deployment for diversification. If D1 breaks live,
C_long keeps running. If both run live, the combined portfolio is
signal-family-diversified.

**Live deployment concerns**:
1. Return is lower than D1 (~37 pp gap over 5 years)
2. Same DD as D1 (~18% vs 13%) — marginally worse risk profile
3. **Structurally slippage-robust** — only 9.6% of exits are stop-loss,
   so slippage drag is tightly bounded

### D1_long_frac2_shadow → "return expansion, prove survival first"

**Role**: shadow-only until live survival is proven. The highest-
return Phase 6 cell that stays within the tail-event safety ceiling
(frac = 2.0).

| Property | Value |
|---|---|
| 5-year OOS return | +261.47% (close_stop) |
| 5-year DD | 12.58% |
| Trade sample | 75 |
| Worst trade | −7.98% |
| Position fraction | **2.0** (at the hard safety ceiling) |

**Use case**: shadow monitoring. The runner executes the same
signals as D1_long_primary but at frac=2.0, logs the P&L, and
doesn't actually post real paper orders until survival is validated.

**Live deployment concerns**:
1. frac=2.0 is the HARD ceiling from Phase 6 tail-event analysis.
   A 40% shock delivers −80% equity loss (survivable but painful).
2. Shadow mode means the PnL is tracked but no real paper trades.
   If day-30 reconciliation shows the cell matches the retrospective,
   upgrade to real paper deployment.
3. The +261% is SEDUCTIVE but the sample is 75 trades — same thin
   sample risk as D1_long_primary.

---

## 4. Why not deploy all three at the same sizing

Because they serve different purposes:

| Purpose | Cell | Sizing |
|---|---|---|
| Core capital | D1_long_primary | 0.25× paper notional |
| Diversification | C_long_backup | 0.25× paper notional |
| Return expansion observation | D1_long_frac2_shadow | shadow-only (0× notional) |
| Unallocated reserve | — | 0.50× |

Total committed paper notional: 0.50× (with 0.25× reserve and 0.25×
unallocated for future cells).

If the shadow cell survives 30 days of real-data monitoring with
matching fills, it graduates to paper at day 30.

---

## 5. Correlation structure across the three cells

A concern when running multiple cells in parallel: **are they
correlated?** If all three cells take big losses on the same day, the
portfolio-level DD is worse than any single cell's DD.

In the 30-day retrospective, all cells opened positions on the SAME
DAY (2026-03-16). This is because:

- D1 uses rsi_only_20 h=11
- C uses rsi_and_macd_14 h=4

Both families fired on 2026-03-16 because BTC's RSI was in its
trigger zone at that timestamp for both periods. The signals are
**highly correlated** at the bar level.

**Implication**: the three cells will often enter and exit on the
same days. Portfolio DD is NOT significantly reduced by running them
in parallel on the same signal family. C_long's backup role is
structural (different signal family, different exit behavior), not
temporal (they still often trade the same day).

---

## 6. Decision framework for each cell at day 30

### D1_long_primary — "keep"

Criteria to keep:
- [ ] Live trades match retrospective within 2 bp
- [ ] No safety alerts fired
- [ ] Stop-loss fires as expected on stopped trades
- [ ] Monthly net PnL within ±5% of retrospective band (historically
      this cell can have −5% 30-day periods; don't over-react)

### D1_long_primary — "switch to C_long as primary"

Criteria to switch:
- [ ] Live D1_long PnL < retrospective by > 50 bp (plumbing bug)
- [ ] Safety alerts fired repeatedly (> 3 alerts in 30 days)
- [ ] Slippage consistently > tolerance band (structural problem)
- [ ] C_long outperforms D1_long live by > 100 bp (regime shift)

### D1_long_primary — "keep D1 only as shadow, halt live trades"

Criteria to de-promote:
- [ ] Live drawdown > 15% in 30 days (this is the session kill-switch
      threshold)
- [ ] Single-trade loss > −8% (outside tolerance)
- [ ] Three consecutive stopped-out trades with slippage > 30 bp each

### D1_long_frac2_shadow — "promote"

Criteria to promote out of shadow to paper:
- [ ] Shadow PnL matches retrospective within 5%
- [ ] No worst-trade larger than −10% (cell's tolerance at frac=2.0)
- [ ] Execution quality metrics all in tolerance
- [ ] At least 2 stopped-out events observed to validate stop-loss
      behavior at frac=2.0

### Halt-all criteria (portfolio level)

- [ ] Session DD > 15% across all cells combined
- [ ] Single day > −5% portfolio PnL
- [ ] 3 consecutive hard safety alerts
- [ ] Data source loss > 12 hours

---

## 7. Recommended allocation plan

### Day 0 — Deployment start

| Cell | Allocation | Semantics | Monitor |
|---|---|---|---|
| D1_long_primary | **0.25× paper** | strategy_close_stop | Daily |
| C_long_backup | **0.25× paper** | strategy_close_stop | Daily |
| D1_long_frac2_shadow | **0× (shadow)** | strategy_close_stop | Daily |
| Unallocated | 0.50× | — | — |

### Day 15 — mid-run checkpoint

- Confirm telemetry is flowing
- Confirm safety controls have been exercised (test-fire at least once)
- If reconciliation is Green: continue
- If reconciliation is Yellow: continue, flag for investigation
- If reconciliation is Amber or worse: halt and investigate

### Day 30 — Decision gate

See the day-30 recommendation report for the full classification.

### Day 30-60 — Graduation / shadow promotion

If Day 30 is all Green:
- Scale D1_long_primary to 0.5× paper
- Scale C_long_backup to 0.5× paper
- Promote D1_long_frac2_shadow to 0.1× paper
- Keep 0.1× reserve, 0.3× unallocated

If Day 30 has any Yellow flags:
- Stay at 0.25× each
- Extend to 60 days for additional validation

If Day 30 has any Amber or Red:
- De-promote or halt the affected cell
- Deploy only C_long (most robust) while D1 is investigated

---

## 8. Summary

- **Three cells cover three purposes**: primary return, diversification,
  return expansion.
- **5-year aggregate has D1_long_frac2_shadow on top** but frac=2.0
  is the tail-event ceiling — hence shadow-only.
- **30-day retrospective has C_long on top** but the sample is noise.
- **D1_long_primary is the "most backtest-faithful" cell** and should
  be the primary live allocation.
- **C_long_backup is structurally robust** and stays as the safety
  net even if D1 performs normally.
- **D1_long_frac2_shadow sits in shadow** until live data proves it
  matches the retrospective.
- **Portfolio-level decisions** need to account for signal correlation —
  these cells often trade the same day.

See `strategy_c_v2_phase7_day30_recommendation.md` for the detailed
classification framework and day-30 decision.
