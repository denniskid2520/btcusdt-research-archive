# Strategy C v2 — Phase 7 Deliverable: Day-30 Decision Framework

_Date: 2026-04-12_
_Status: Phase 7 — the rulebook for the day-30 decision and the
retrospective outcome._

## TL;DR

**Phase 7 in this session is deliberately infrastructure + retrospective.**
The "real" day-30 decision requires a forward 30-day live run on actual
paper fills, which is Phase 8 work. What Phase 7 delivers:

1. The decision rulebook (§3 below) — 5 classification outcomes
2. The retrospective simulation outcome (§4) — what the retrospective
   would recommend if it were the live run
3. The live deployment parameters (§5) — exactly what a Phase 8 runner
   should spin up
4. The day-30 check list (§6) — what to verify before scaling

**On the retrospective window**, the outcome is: **continue with
D1_long_primary and C_long_backup at 0.25× paper each; keep
D1_long_frac2_shadow in shadow mode; re-evaluate at the next 30-day
gate.**

---

## 1. The five day-30 classifications

Per the Phase 7 brief, each cell gets classified into one of five
outcomes at day 30:

| # | Classification                         | Meaning                                               |
|--:|----------------------------------------|-------------------------------------------------------|
| 1 | **keep D1_long primary**               | Live matches backtest → continue; consider scaling    |
| 2 | **switch to C_long primary**           | D1_long diverged → demote; promote C_long to primary |
| 3 | **keep D1_long only as shadow**        | D1_long flagged but not failed → keep monitoring only |
| 4 | **promote frac=2.0 shadow**            | Shadow matched the model → graduate to paper         |
| 5 | **halt**                               | Any catastrophic failure → stop all, investigate      |

---

## 2. Classification criteria — detailed

### Criterion table

| Criterion                                 | Keep | Switch | Shadow | Promote | Halt |
|-------------------------------------------|:----:|:------:|:------:|:-------:|:----:|
| Live net PnL matches retrospective ± 50 bp | ✓    |        |        |    ✓    |      |
| Live net PnL matches retrospective ± 100 bp |     | ✓      |        |         |      |
| Live net PnL divergence > 100 bp for 3+ days |   |        | ✓      |         |      |
| Live net PnL divergence > 200 bp ever     |      |        |        |         |  ✓   |
| Stop-loss fired as expected on stopped trades | ✓ | ✓      |        |    ✓    |      |
| Stop-loss fire mismatch > 2 times         |      |        | ✓      |         |      |
| Worst single trade ≤ backtest worst + 3 pp | ✓    | ✓      |        |    ✓    |      |
| Worst single trade > backtest worst + 10 pp |    |        |        |         |  ✓   |
| Any hard safety alert fired               |      |        | ✓      |         |      |
| Multiple hard safety alerts               |      |        |        |         |  ✓   |
| Session DD > 15%                          |      |        |        |         |  ✓   |
| Signal feature drift vs retrospective > 1%|      |        | ✓      |         |      |
| D1_long_frac2_shadow matches model        |      |        |        |    ✓    |      |
| D1_long_frac2_shadow worst trade > −10%   |      |        |        |         |  ✓   |

Reading the table: **any single Halt condition triggers a halt**,
regardless of other criteria. Keep/Switch/Shadow/Promote are
AND-conditions within a column.

### Simplified decision tree

```
if any_halt_condition_triggered:
    → HALT (classification 5)
elif D1_long_primary.live_matches_retro_within_50bp
     and no_hard_safety_alerts
     and D1_long_primary.worst_trade_within_tolerance:
    → KEEP D1_long (classification 1)
    if D1_long_frac2_shadow.matches_retro_within_50bp
       and D1_long_frac2_shadow.worst_trade_within_-10pct:
        → also PROMOTE shadow (classification 4)
elif D1_long_primary.live_diverged_more_than_100bp
     and C_long_backup.live_ok:
    → SWITCH to C_long primary (classification 2)
elif D1_long_primary.diverged_but_not_catastrophic
     or any_soft_flag_persistent:
    → KEEP D1_long as SHADOW only (classification 3)
    → also deploy C_long as primary in its place
else:
    → default to KEEP D1_long at current sizing (classification 1 conservative)
```

---

## 3. The rulebook — explicit go/no-go numbers

For each cell, the day-30 evaluation needs these concrete numbers:

### D1_long_primary

| Number                          | Expected (retro) | Green band       | Yellow band       | Red band          |
|---------------------------------|-----------------:|------------------|-------------------|-------------------|
| 30-day net PnL                  | −3.58% to −2.16% | within ± 5 pp   | within ± 10 pp    | outside ± 10 pp   |
| Trade count                     | 1                | 0-3              | 4-5               | 6+                |
| Stop fire count                 | 1                | 0-2              | 3                 | 4+                |
| Per-trade entry slippage        | 0 bp             | ≤ 5 bp          | 5-20 bp           | > 20 bp           |
| Per-stop slippage               | 0 bp             | ≤ 10 bp         | 10-50 bp          | > 50 bp           |
| Worst single trade              | −3.58%           | ≥ −5%           | −5 to −8%         | < −8%             |
| Hard safety alerts              | 0                | 0                 | 1                 | 2+                |

### C_long_backup

| Number                          | Expected (retro) | Green band       | Yellow band       | Red band          |
|---------------------------------|-----------------:|------------------|-------------------|-------------------|
| 30-day net PnL                  | −1.01%           | within ± 3 pp   | within ± 6 pp     | outside ± 6 pp    |
| Trade count                     | 2                | 1-4              | 5                 | 6+                |
| Stop fire count                 | 0                | 0-1              | 2                 | 3+                |
| Per-trade entry slippage        | 0 bp             | ≤ 5 bp          | 5-20 bp           | > 20 bp           |
| Worst single trade              | −1.41%           | ≥ −3%           | −3 to −6%         | < −6%             |

### D1_long_frac2_shadow

| Number                          | Expected (retro) | Green band       | Yellow band       | Red band          |
|---------------------------------|-----------------:|------------------|-------------------|-------------------|
| 30-day net PnL                  | −2.74% to −2.83% | within ± 5 pp   | within ± 10 pp    | outside ± 10 pp   |
| Trade count                     | 1                | 0-3              | 4-5               | 6+                |
| Worst single trade              | −2.83%           | ≥ −6%           | −6 to −10%        | < −10%            |
| Position fraction tracking       | 2.000           | exact            | ± 0.02            | ± 0.05            |

Any cell with all Green → eligible for promotion.
Any cell with Yellow → conservative: keep at current sizing.
Any cell with Red → down-class or halt.

---

## 4. Retrospective outcome (as if the retrospective were the live run)

Running the retrospective data through the day-30 rulebook:

### D1_long_primary (strategy_close_stop)

| Criterion | Expected | Retro | Band |
|---|---|---|---|
| 30-day net PnL | −3.58% | −3.58% | **Green** (exact match) |
| Trade count | 1 | 1 | **Green** |
| Stop fires | 1 | 1 | **Green** |
| Worst trade | −3.58% | −3.58% | **Green** (≥ −5%) |
| Slippage | 0 bp | 0 bp | **Green** |
| Safety alerts | 0 | 0 | **Green** |

**Verdict**: All Green → **KEEP D1_long_primary**.

### C_long_backup (strategy_close_stop)

| Criterion | Expected | Retro | Band |
|---|---|---|---|
| 30-day net PnL | −1.01% | −1.01% | **Green** (exact) |
| Trade count | 2 | 2 | **Green** |
| Stop fires | 0 | 0 | **Green** |
| Worst trade | −1.41% | −1.41% | **Green** (≥ −3%) |
| Slippage | 0 bp | 0 bp | **Green** |

**Verdict**: All Green → **KEEP C_long_backup**.

### D1_long_frac2_shadow (strategy_close_stop)

| Criterion | Expected | Retro | Band |
|---|---|---|---|
| 30-day net PnL | −2.83% | −2.83% | **Green** |
| Trade count | 1 | 1 | **Green** |
| Worst trade | −2.83% | −2.83% | **Green** (≥ −6%) |

**Verdict**: All Green → **PROMOTE frac=2.0 shadow to 0.1× paper**.

### Combined retrospective classification

| Cell | Classification |
|---|---|
| D1_long_primary | **Keep** |
| C_long_backup | **Keep** |
| D1_long_frac2_shadow | **Promote (0 → 0.1× paper)** |

**Note**: this is the retrospective outcome. A live run cannot produce
"exact match" because live data will have real slippage and timing
differences. The retrospective outcome is a sanity check that the
rulebook is internally consistent, not a guarantee of the live result.

---

## 5. Live deployment parameters (for Phase 8 hand-off)

Exactly what a Phase 8 runner should instantiate:

### Monitor config for D1_long_primary

```python
MonitorConfig(
    rsi_field="rsi_20",   # NOTE: Phase 4 live_monitor defaulted to rsi_21
    rsi_upper=70.0,
    rsi_lower=30.0,
    hostile_long_funding=0.0005,
    hostile_short_funding=-0.0005,
    max_hold_bars=11,     # Phase 6 hold
)
# + new Phase 5A/6/7 fields (not yet in MonitorConfig — Phase 8 extension):
deployment_params = {
    "cell_label": "D1_long_primary",
    "signal_family": "rsi_only",
    "period": 20,
    "hold_bars": 11,
    "side": "long",
    "stop_loss_pct": 0.015,
    "stop_trigger": "close",  # i.e. strategy_close_stop semantics
    "stop_slip_pct": 0.001,   # budget for slippage on stop fills
    "risk_per_trade": 0.020,
    "effective_leverage": 2.0,
    "paper_notional_fraction": 0.25,
}
```

### Monitor config for C_long_backup

```python
deployment_params = {
    "cell_label": "C_long_backup",
    "signal_family": "rsi_and_macd",
    "period": 14,
    "hold_bars": 4,
    "side": "long",
    "stop_loss_pct": 0.020,
    "stop_trigger": "close",
    "stop_slip_pct": 0.001,
    "risk_per_trade": 0.020,
    "effective_leverage": 2.0,
    "paper_notional_fraction": 0.25,
}
```

### Monitor config for D1_long_frac2_shadow

```python
deployment_params = {
    "cell_label": "D1_long_frac2_shadow",
    "signal_family": "rsi_only",
    "period": 20,
    "hold_bars": 11,
    "side": "long",
    "stop_loss_pct": 0.0125,
    "stop_trigger": "close",
    "stop_slip_pct": 0.001,
    "risk_per_trade": 0.025,
    "effective_leverage": 2.0,
    "paper_notional_fraction": 0.0,  # SHADOW — log but don't place
    "shadow_mode": True,
}
```

---

## 6. Day-30 audit checklist

To execute at day 30 of the live run:

**Data quality**
- [ ] All 4h bars received without gaps during the 30 days
- [ ] No stale-data hard alerts fired
- [ ] Live RSI(20) matches retrospective RSI(20) within 0.1 at all
      shared timestamps
- [ ] Live MACD(12,26,9) matches retrospective within 0.1

**Trade execution**
- [ ] Live trade count per cell within Green band
- [ ] Live trade entry timestamps match retrospective entries within
      ±1 bar
- [ ] Live entry prices match retrospective entries within 5 bp
- [ ] Live exit reasons match retrospective exit reasons exactly

**Stop-loss execution**
- [ ] Live stop levels match entry × (1 ± stop_pct) exactly
- [ ] Stop fires triggered on the expected bar (within ±1 bar)
- [ ] Stop fill prices within tolerance of retrospective (5 bp)
- [ ] No stop-trigger-fill mismatch alerts

**PnL reconciliation**
- [ ] Daily net PnL delta ≤ 10 bp (Green)
- [ ] Cumulative 30-day net PnL delta ≤ 50 bp (Green)
- [ ] Funding accrual matches model (± 2 bp)
- [ ] Cost per trade matches formula (± 2 bp)

**Safety**
- [ ] Zero hard safety alerts
- [ ] Fewer than 3 soft flags per cell
- [ ] Session DD < 15% at all times
- [ ] No abnormal slippage events

**Recommendation**
- [ ] All three cells Green → follow the retrospective outcome
      (keep + promote shadow)
- [ ] Any cell Yellow → hold at current sizing, extend monitoring
- [ ] Any cell Red → de-promote or halt per rulebook

---

## 7. Kill-switch conditions (always active)

Regardless of day-30 audit status, the live runner must halt
immediately on any of:

| Condition | Action |
|---|---|
| Session DD > 15% | flat all, investigate |
| Single trade loss > 10% | flat all, audit fill |
| 3 consecutive hard alerts | flat all |
| Data source unreachable > 6 hours | flat all |
| Single fill slippage > 2% | flat all |
| Abnormal price data (5 bp tick) | flat all |

These are independent of the classification rulebook. They are the
last line of defense against catastrophic failure modes the
classification doesn't anticipate.

---

## 8. What day-30 DOES NOT decide

Phase 7's day-30 decision is a FIRST checkpoint, not a final verdict.
Specifically, day-30 does NOT decide:

1. **Scaling to full (1×) allocation**: that's day-60 or day-90,
   after more trade samples are collected.
2. **Shifting to real (non-paper) capital**: that's Phase 9+.
3. **Changing the signal family**: that would restart Phase 6
   research.
4. **Adjusting stop / risk parameters**: those are frozen until a
   new research cycle changes them (never tune from live data).
5. **Adding Coinglass overlay**: Phase 4's negative finding stands.

Day-30 is ONLY about confirming that the live path matches the
retrospective path within tolerance, and graduating cells that did.

---

## 9. Summary

**Retrospective outcome (this session)**:
- D1_long_primary: KEEP at 0.25× paper
- C_long_backup: KEEP at 0.25× paper
- D1_long_frac2_shadow: PROMOTE from 0× to 0.1× paper
- Portfolio remains under 0.60× total paper notional
- All three cells Green by the Phase 7 rulebook

**Live day-30 outcome (Phase 8)**: apply the same rulebook to real
live data. Expected: same classification if plumbing is clean.

**What Phase 7 leaves behind**:
1. Stop-semantics split in the backtester (TDD-covered)
2. PaperTradeLogEntry telemetry schema
3. Retrospective simulation runner (reusable for ongoing
   reconciliation)
4. Parity study runner (reusable for any future semantic test)
5. Six deliverables including this rulebook
6. Live deployment configs for all three cells

**What Phase 8 must build**:
1. The actual live runner loop (4h scheduler)
2. Exchange connectivity (Binance USDT-M testnet or live)
3. State journal persistence
4. Real-time alert dispatch (email/webhook/SMS)
5. Automatic daily reconciliation job
6. Dashboard for operator-in-the-loop review

Phase 7 provides the pure-function brain; Phase 8 provides the
arms and legs.
