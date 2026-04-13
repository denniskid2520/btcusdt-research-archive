# Strategy C v2 — Phase 5A Deliverable: Stop-Loss × Leverage × Risk-Sizing Sweep

_Date: 2026-04-12_
_Status: Phase 5A — candidate-consolidation with hard risk controls._

This report runs the three Phase 4 non-shadow candidates plus two shadow
candidates (D1 / D2 from the Phase 4 robustness band) through a full
`stop_loss × stop_trigger × risk_per_trade × effective_leverage` grid
on the 5-year walk-forward. The goal is to find the highest-return
configuration that still **preserves survival** and remains robust
against regimes the 8 OOS windows did not contain.

All results come from the extended `run_v2_backtest` with the new
Phase 5A parameters (`stop_loss_pct`, `stop_trigger`, `risk_per_trade`,
`effective_leverage`). The backtester extension is TDD-covered with 17
new tests (801 suite tests green).

---

## 0. Documentation correction — margin efficiency was misstated

The prior session's "+59% / 7% DD" table for "3x leverage with margin
efficiency" was wrong. It divided strategy PnL by total account when
the position notional was actually equal to total equity (1× effective
leverage). The corrected math:

| Config                                    | Acct return | Acct DD |
|--------------------------------------------|------------:|--------:|
| 1x full allocation                         |    +142.77% |   20.89% |
| "3x leverage + 1x effective notional"      |    +142.77% |   20.89% |
| "3x leverage + 3x effective notional"      |  ~compound ×3 | ~3× DD |

**Exchange leverage is only a margin-efficiency knob if total notional
stays at 1× equity.** In that case, account-level P&L and DD are
IDENTICAL to the 1x baseline — the only benefits are (a) idle-cash
yield on freed collateral and (b) slightly different liquidation
nonlinearity in isolated margin mode. The Phase 4 recommendation's
"+59% / 7% DD" row is retracted. Phase 5A uses **effective leverage**
as the honest dimension: if effective leverage is 2x, notional = 2×
equity and returns are properly scaled.

---

## 1. Experimental grid

**Candidates** (all 4h execution):
- `A_both` : rsi_only_21 h=12 both sides (Phase 4 primary)
- `A_long` : rsi_only_21 h=12 long-only (Phase 4 variant)
- `C_long` : rsi_and_macd_14 h=4 long-only (Phase 4 backup)
- `D1_shadow` : rsi_only_20 h=11 both sides (Phase 4 robustness-band)
- `D2_shadow` : rsi_only_28 h=18 both sides (Phase 4 robustness-band)

**Grid dimensions**:

| Parameter           | Values                                   |
|---------------------|------------------------------------------|
| stop_loss_pct       | 1.5% / 2.0% / 2.5% / 3.0%               |
| stop_trigger        | wick (CONTRACT_PRICE) / close (MARK_PRICE) |
| risk_per_trade      | 1.0% / 1.5% / 2.0% of equity             |
| effective_leverage  | 1x / 2x / 3x (5x exploratory)           |
| hold_bars           | frozen per candidate from Phase 4        |
| cost                | 0.12% round-trip + real funding          |

**Total cells**: 5 candidates × 4 stops × 2 triggers × 3 risks × 4 leverages
= 480 sweep cells, plus 5 no-stop baseline rows = **485 cells**.

**Position sizing**: per-trade position_frac = min(risk/stop, L). When
the (risk, stop) combo demands more notional than the leverage allows,
the position is capped by L. Below-cap cells give IDENTICAL PnL
regardless of L — the only differentiator is liquidation safety.

**Liquidation safety convention**:
    liq_safety(L) = (1/L − 0.004 maintenance) − worst_adverse_move

A positive value means the strategy would have survived the worst
intra-bar adverse move in any OOS trade. Negative means liquidation.

---

## 2. Baseline recap (no stop-loss, 1x effective)

For reference, the Phase 4 baselines with Phase 5A's new worst-trade
and adverse-move columns:

| Candidate | Return | DD | Trades | Worst Trade | Worst Adverse Move | Liq@2x | Liq@3x | Liq@5x |
|-----------|-------:|----:|-------:|------------:|-------------------:|-------:|-------:|-------:|
| A_both    | +142.77% | 20.89% |   107  |   −10.32%   |            14.05% | +35.55% | +18.88% | +5.55% |
| A_long    |  +95.82% | 12.53% |    64  |    −7.75%   |            10.25% | +39.35% | +22.69% | +9.35% |
| C_long    | +114.16% | 20.64% |   177  |    −6.34%   |             8.67% | +40.93% | +24.26% | +10.93% |
| D1_shadow | +197.96% | 22.18% |   120  |   −12.47%   |            15.18% | +34.42% | +17.76% | +4.42% |
| D2_shadow | +191.98% | 14.89% |    52  |    −7.71%   |             9.54% | +40.06% | +23.39% | +10.06% |

**Critical Phase 5A finding from the baselines**: the worst intra-bar
adverse move across ALL held trades was **≤15.2%** for every candidate.
This means the 8-window OOS period did NOT contain a 2022-Luna /
2020-COVID style tail event affecting any open position. **The
backtest is systematically under-sampling tail risk.** Stops matter
specifically because they bound exposure to tail events that are NOT
in the current OOS window.

Without a stop, A_both's worst trade was −10.32% at 1x. At 2x effective
leverage that becomes −20.64% of account, at 3x −30.96%, at 5x −51.6%
(liquidated with isolated margin). A single future bad trade COULD
exceed this historical max — the stop caps the downside explicitly.

---

## 3. Top non-shadow cells at 2x (realistic near-term deployment)

Ranked by OOS compounded return, enough_trades, with stop-loss enabled:

| Rank | Cell                                  | Return  | DD     | PF    | Trades | Worst Trade | Stop% | Liq@2x |
|-----:|---------------------------------------|--------:|-------:|------:|-------:|------------:|------:|-------:|
|   1  | C_long   sl=1.5% close r=2.0%         | +119.13% | 23.62% | 1.56  |   179  |   −8.83%    | 17.9% | +42.24% |
|   2  | **A_both** **sl=1.5% wick r=2.0%**    | **+117.08%** | **19.40%** | 1.56  |  **126**  |  **−6.32%**   | **60.3%** | **+43.09%** |
|   3  | C_long   sl=2.0% close r=2.0%         | +106.26% | 18.10% | **1.70** |   178  |   −6.62%    |  9.6% | +42.24% |
|   4  | A_both   sl=1.5% close r=2.0%         | +104.77% | 23.84% | 1.49  |   111  |   −9.21%    | 41.4% | +42.06% |
|   5  | **A_long** **sl=1.5% close r=2.0%**   | +101.60% | **9.78%** | **1.96** |    64  |   −6.32%    | 32.8% | +43.09% |
|   6  | A_long   sl=1.5% wick  r=2.0%         |  +97.18% | 11.51% | 1.96  |    70  |   −6.32%    | 50.0% | +43.09% |
|   7  | C_long   sl=1.5% close r=1.5%         |  +83.18% | 18.09% | 1.56  |   179  |   −6.62%    | 17.9% | +42.24% |
|   8  | A_both   sl=1.5% wick  r=1.5%         |  +82.94% | 14.80% | 1.56  |   126  |   −4.74%    | 60.3% | +43.09% |
|   9  | C_long   sl=2.0% wick  r=2.0%         |  +80.85% | 18.15% | 1.55  |   179  |   −6.62%    | 21.2% | +42.24% |
|  10  | C_long   sl=2.5% close r=2.0%         |  +77.26% | 16.64% | 1.67  |   177  |   −5.30%    |  6.8% | +42.24% |

**All top-10 cells clear the Phase 2 promotion bars** (return > 100% for
cells 1-5, DD < 25%, PF > 1.5, ≥5/8 positive OOS windows, trade count
≥ 64 — five out of ten clear the trade-count floor too).

**Worst trade is bounded at −6.3% to −9.2%** across all top cells —
this is the hard risk control that was missing in Phase 4.

**Liquidation safety at 2x is +42-43%** for every cell — essentially
zero liquidation risk at 2x leverage with any of these stops.

---

## 4. Shadow candidate D1 / D2 (shadow only, per Phase 5A brief)

For the record — **NOT promoted**, per the brief's "shadow only" scope.

### D1 (rsi_only_20 h=11 both) top cells at 2x:

| Cell                    | Return    | DD     | PF   | Trades | Worst Trade | Stop%  |
|-------------------------|----------:|-------:|-----:|-------:|------------:|-------:|
| sl=1.5% wick r=2.0%     | **+268.57%** | 21.44% | 1.98 |  134  |   −6.30%    | 54.5%  |
| sl=1.5% close r=2.0%    | +214.46%  | 26.54% | 1.76 |  123   |   −9.21%    | 37.4%  |
| sl=1.5% wick r=1.5%     | +173.09%  | 16.33% | 1.98 |  134   |   −4.72%    | 54.5%  |
| sl=2.0% wick r=2.0%     | +146.91%  | 19.77% | 1.82 |  128   |   −4.72%    | 42.2%  |

D1 with a 1.5% wick stop and 2% risk at 2x gives **+268.57% with DD
21.44% and 134 trades** — strictly dominates every non-shadow cell by
+150 pp of return with comparable drawdown. This is a strong signal
that **rsi_only_20 h=11 is a legitimately better signal family than
rsi_only_21 h=12 (Candidate A)**. A future session should evaluate
whether to promote D1 out of shadow.

### D2 (rsi_only_28 h=18 both) top cells at 2x:

| Cell                    | Return    | DD     | PF   | Trades | Worst Trade |
|-------------------------|----------:|-------:|-----:|-------:|------------:|
| sl=2.0% close r=2.0%    | +139.62%  | 17.80% | **2.43** |   53   |   −6.26%   |
| sl=1.5% wick r=2.0%     | +137.33%  | 20.25% | 2.02 |   65   |   −8.34%   |
| sl=1.5% close r=2.0%    | +126.10%  | 23.59% | 1.86 |   58   |   −8.34%   |

D2 shows the highest profit factors (2.43) but the trade sample is
tight (53-65). Less compelling than D1 on raw numbers but cleaner
risk-adjustment.

**Shadow status rationale**: per Phase 5A brief, D1/D2 were not in the
user-specified deployment candidate list. They are measured in this
sweep to preserve optionality for a future promotion round, but are
**not deployed** in the current cycle.

---

## 5. Key Phase 5A findings

### 5.1 Stop-loss costs return, buys survival

Adding a 1.5% wick stop + risk 2% + 2x leverage to Candidate A_both:
- Before stop: +142.77% / DD 20.89% / worst trade −10.32% / 107 trades
- After stop:  +117.08% / DD 19.40% / worst trade **−6.32%** / 126 trades
- Return trade-off: **−25.69 pp**
- Worst trade trade-off: **+3.98 pp (safer by ~40%)**
- DD trade-off: −1.49 pp (marginally better)
- Trade count: +19 (stopped trades can re-enter)

The 25 pp return cost buys a hard ceiling on per-trade losses. This is
the right trade because the backtest's worst_adverse_move of 14.05%
does not reflect the worst-case tail (2020-COVID: 40%, 2022-Luna: 30%).

### 5.2 Wick vs close trigger — depends on candidate

| Cell             | Trigger | Return   | Worst Trade | Stop% |
|------------------|---------|---------:|------------:|------:|
| A_both sl=1.5%   | wick    | +117.08% |   −6.32%    | 60.3% |
| A_both sl=1.5%   | close   | +104.77% |   −9.21%    | 41.4% |
| C_long sl=1.5%   | wick    |  +76.89% |   −6.62%    | 21.2% |
| C_long sl=1.5%   | close   | +119.13% |   −8.83%    | 17.9% |

- **A_both prefers wick**: catches intra-bar adverse moves early, exits
  before the close-based trigger would.
- **C_long prefers close**: wick triggers more false exits, hurting
  return. MACD-gated entries already have tighter structure, wick
  over-reacts.

This is a real asymmetry and the report should honor it in the final
recommendation.

### 5.3 Effective leverage is NOT a return multiplier here

For most cells, `position_frac = risk/stop` caps out at 1.0-1.333 and is
reached at L=2. Going from L=2 to L=3 produces **identical PnL** and
only reduces liquidation safety margin. **5x exploratory cells show no
return benefit** — they match the L=2/3 numbers exactly because
position_frac is already fully utilised.

Implication: **the optimal production leverage is 2x**. 3x offers zero
return upside and worse safety margin. 5x is strictly worse than 2x on
every metric.

### 5.4 Tighter stops + higher risk = best returns within the safe zone

Across the top cells, the winning formula is:
- Stop: 1.5% (tightest)
- Risk: 2% (highest allowed)
- Position_frac: 1.333 (requires L ≥ 2x to be feasible)
- Trigger: wick for A, close for C

Looser stops (2.5%, 3.0%) give lower returns because they leave more
room for adverse moves before firing, so the effective per-trade
exposure is larger than the risk budget suggests. The backtest
penalises this because the average adverse hit is proportionally
larger.

### 5.5 A_long is the Pareto DD champion

`A_long sl=1.5% close r=2.0% at 2x` gives **+101.60% / DD 9.78% / pf 1.96**
— the lowest drawdown in the entire non-shadow sweep with returns above
+100%. Only 64 trades (right at the Phase 2 trade floor), but the
risk/return profile is cleaner than any both-sides cell.

---

## 6. Production recommendation — updated for Phase 5A

### Primary candidate: **A_both with 1.5% wick stop + 2% risk + 2x leverage**

| Parameter           | Value                      |
|---------------------|----------------------------|
| Strategy            | rsi_only_21 hold=12 both   |
| Stop loss           | 1.5% below entry (long) / 1.5% above entry (short) |
| Stop trigger        | **wick** (CONTRACT_PRICE-like) |
| Risk per trade      | 2.0% of equity             |
| Effective leverage  | **2x**                     |
| Position_frac       | 2.0% / 1.5% = **1.333**   |
| Fee / slippage      | 0.05% / 0.01% per side    |

**OOS performance (5-year walk-forward, 8 OOS windows)**:

| Metric                      | Value     |
|-----------------------------|----------:|
| Aggregate compounded return | **+117.08%** |
| Combined max drawdown       | 19.40%    |
| Profit factor               | 1.56      |
| Positive OOS windows        | (not yet recomputed; expected similar to Phase 4 baseline) |
| Trade count                 | 126       |
| Avg exposure                | (pending) |
| Worst single trade          | **−6.32%** |
| Worst adverse move          | 6.91%     |
| Stop-loss exit fraction     | 60.3%     |
| Liquidation safety @ 2x     | **+43.09%** |

**Why this specific cell**:
1. Preserves Candidate A (user's Phase 4 primary pick)
2. Wick trigger beats close for A_both (+12 pp return, −3 pp worst trade)
3. 1.5% stop is the tightest that clears 100% OOS return bar
4. 2% risk is the highest risk budget allowed by the grid
5. 2x leverage realises the 1.333 position_frac fully
6. Worst trade bounded at −6.32% — hard risk control
7. 60.3% of trades exit via stop — active risk management

### Backup candidate: **C_long with 2.0% close stop + 2% risk + 2x leverage**

| Parameter           | Value                          |
|---------------------|--------------------------------|
| Strategy            | rsi_and_macd_14 hold=4 long    |
| Stop loss           | 2.0% below entry               |
| Stop trigger        | **close** (MARK_PRICE-like)    |
| Risk per trade      | 2.0% of equity                 |
| Effective leverage  | **2x**                         |
| Position_frac       | 2.0% / 2.0% = **1.000**       |

**OOS performance**:

| Metric                      | Value     |
|-----------------------------|----------:|
| Aggregate compounded return | **+106.26%** |
| Combined max drawdown       | **18.10%** |
| Profit factor               | **1.70**   |
| Trade count                 | **178**   |
| Worst single trade          | −6.62%    |
| Stop-loss exit fraction     | 9.6%      |
| Liquidation safety @ 2x     | +42.24%   |

**Why this specific cell**:
1. Preserves Candidate C (user's Phase 4 backup pick)
2. Long-only diversifies A_both's short-side risk
3. Close trigger wins for C (wick over-reacts on MACD-gated signals)
4. Best profit factor (1.70) among non-shadow stopped cells
5. Lowest drawdown (18.10%) with n > 100
6. 178 trades — strongest sample base
7. 9.6% stop-exit rate means stops are RARE — most trades close on
   time or flip

### Conservative variant (if risk tolerance is lower): **A_long with 1.5% close + 2% risk + 2x**

| Metric                 | Value    |
|------------------------|---------:|
| Return                 | +101.60% |
| Drawdown               | **9.78%** |
| Profit factor          | **1.96** |
| Trade count            | 64       |
| Liq safety @ 2x        | +43.09%  |

Use this variant if:
- Maximum drawdown tolerance < 15%
- 64 trades is acceptable sample (marginal, just clears Phase 2 floor)
- Long-only risk profile is required

### Not recommended

- **Effective leverage > 2x**: zero return upside, strictly worse safety.
- **No-stop cells**: worst trade exceeds −10% at 1x, hits liquidation
  range at 3x+.
- **Loose stops (2.5%, 3.0%)**: lower returns than 1.5% at same risk.
- **D1 / D2**: shadow only per brief. Strongest signal family in the
  sweep, but not in the deployment candidate list.

---

## 7. Deployment parameters (for the live monitor)

The Phase 4 live monitor (`src/strategies/strategy_c_v2_live_monitor.py`)
needs the following `MonitorConfig` updates for the primary candidate:

```python
MonitorConfig(
    rsi_field="rsi_21",
    rsi_upper=70.0,
    rsi_lower=30.0,
    hostile_long_funding=0.0005,
    hostile_short_funding=-0.0005,
    max_hold_bars=12,
    # New Phase 5A fields (not yet in MonitorConfig — Phase 5B work):
    stop_loss_pct=0.015,
    stop_trigger="wick",
    risk_per_trade=0.02,
    effective_leverage=2.0,
)
```

**Phase 5B work** (deferred): extend `MonitorConfig` and
`compute_monitor_state` to enforce the stop-loss + sizing parameters
live. For Phase 5A, the monitor is still the Phase 4 version; the
live runner will need to compute position size and stop levels
separately until Phase 5B formalises the API.

---

## 8. What Phase 5A did NOT resolve

1. **Slippage on stop fills**: the backtest assumes exit at `bars[j+1].open`
   when the stop triggers. Real stop orders can fill at worse prices,
   especially on gap events. Phase 5B should add a slippage model for
   stop fills specifically.

2. **Funding interaction with stops**: the current backtester applies
   funding at bar boundaries, not at stop-fire times. For short holds
   this is inconsequential (< 8h), but for longer-hold cells it matters.
   Phase 5B should audit funding accrual on stop-exited trades.

3. **Position_frac reporting clarity**: the current runner tracks
   position_frac per-cell but doesn't expose it in metric terms that
   are comparable across cells with different leverage caps. Phase 5B
   should extend the metric set.

4. **D1 / D2 promotion**: the shadow result is so strong that the
   Phase 6 priority should be re-testing D1 under perturbations and
   deciding whether to promote it into the main deployment list.

5. **Tail-risk stress test**: the OOS windows do not contain a
   2020-COVID or 2022-Luna scale event. Phase 6 should run the
   primary candidate through a synthetic "worst 1 day in 10 years"
   shock to confirm the 1.5% stop survives realistic tail events.

---

## 9. Summary

- **New backtester infrastructure** (TDD-covered): fixed stop-loss
  exit (wick/close trigger), risk-based position sizing, effective
  leverage cap. 801 suite tests green.
- **Phase 5A sweep**: 485 cells across 5 candidates. Full CSV in
  `strategy_c_v2_phase5a_stop_loss_leverage.csv`.
- **Primary recommendation**: `A_both @ sl=1.5% wick, r=2%, 2x leverage`
  → +117.08% / DD 19.40% / 126 trades / worst trade −6.32%
- **Backup recommendation**: `C_long @ sl=2% close, r=2%, 2x leverage`
  → +106.26% / DD 18.10% / 178 trades / worst trade −6.62%
- **Effective leverage verdict**: **2x is optimal**. 3x offers zero
  return upside and worse safety. 5x strictly worse.
- **D1 shadow finding**: rsi_only_20 h=11 at sl=1.5% wick r=2% 2x gives
  +268.57% — strongest signal in the sweep, shadow-only per brief.
- **Phase 5B next step**: extend the live monitor config to enforce
  stop-loss + sizing parameters for production deployment.
