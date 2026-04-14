# BTCUSDT Research Archive

> **Production system has moved to [btcusdt-perp-live](https://github.com/denniskid2520/btcusdt-perp-live)**

This repository contains the full research history: 18 phases, 6,427 parameter sweeps, legacy strategies, phase reports, and experimental materials. For the active live trading system, see the production repo above.

---

# BTCUSDT D1 Perpetual Futures Strategy (Archive)

Quantitative BTCUSDT perpetual futures trading system. Live on Binance USDT-M.

## Strategy

**D1 Long** — 4h RSI(20) regime gate + 1h hybrid pullback/breakout execution.

- **Signal**: RSI(20) > 70 on 4h bars activates a long-only regime zone
- **Execution**: 1h pullback (0.75% dip) and breakout (0.25% new high) re-entries within the zone
- **Dual stop**: alpha 1.25% (client-side close-check) + catastrophe 2.5% (exchange STOP_MARKET)
- **Hold**: 24 hours per trade, max 6 entries per regime zone
- **Capital**: equity-linked, reads Binance availableBalance automatically

## Deployment Stack

| Candidate | Role | Leverage | Status |
|-----------|------|----------|--------|
| **B_balanced_3x** | primary live | 3x isolated | **LIVE** |
| B_balanced_4x | aggressive candidate | 4x isolated | paper |
| A_density_4x | high-sample shadow | 4x isolated | paper |
| B_balanced_5x | high-return shadow | 5x isolated | paper |

## Backtest Results (6-year OOS walk-forward, exec-aware cost model)

| Candidate | Trades | WR | PF | Simple Return | Max DD |
|-----------|-------:|---:|---:|-----------:|-------:|
| **B_balanced_3x** | 150 | 69.3% | 4.63 | +566% | 12.7% |
| B_balanced_4x | 150 | 69.3% | 4.63 | +848% | 18.6% |
| A_density_4x | 264 | 67.4% | 3.30 | +722% | 15.6% |
| B_balanced_5x | 150 | 69.3% | 4.63 | +942% | 20.5% |

## R&D Summary

- **18 phases** of research and validation
- **6,427 parameter combinations** tested
- **621 automated tests** (active suite)
- **6-year backtest** period (2020-04 to 2026-04)
- **8-window walk-forward** OOS validation (24m train / 6m test)
- **Stress tested**: 5 shock levels + 4 slippage levels + 15m intrabar replay
- **Deployed**: AWS Lightsail, real-time bar-close polling

## Architecture

```
src/
  strategies/       — signal generators, sizing, monitor, canonical baseline
  research/         — backtester, walk-forward, stress test, parity test
  execution/        — paper runner, live service, weekly reconciliation
  data/             — feature computation (RSI, EMA, MACD, RV)
  indicators/       — ATR, Bollinger, stochastic
  adapters/         — Binance API, MarketBar
  systems/
    btcusdt_d1_final/  — single namespace index

tests/              — 621 active tests
archive/            — legacy strategies, old research (preserved, not active)
```

## Key Documents

- `ACTIVE_STRATEGY.md` — source of truth for what's live
- `strategy_c_v2_FINAL.md` — strategy summary + backtest results
- `strategy_c_v2_PHASE11_DEPLOYMENT.md` — deployment spec + validation plan
- `strategy_c_v2_PHASE13_6_STOP_CORRECTION.md` — corrected stop semantics

## Run Backtest

```bash
cd src && python ../run_backtest_report.py
```

Compounded backtest:
```bash
cd src && python ../run_compound_backtest.py
```

## Run Tests

```bash
python -m pytest tests/
```

## Live Service

```bash
# Dry-run (no orders):
PYTHONPATH=src python3 -m execution.live_service --dry-run

# Live:
PYTHONPATH=src python3 -m execution.live_service

# With micro-live cap:
PYTHONPATH=src python3 -m execution.live_service --max-cap 5000
```

## Deployment (Lightsail)

```bash
bash deploy_lightsail.sh
```

Monitoring:
```bash
ssh -i btctrading.pem ubuntu@13.209.14.27 "tail -20 /home/ubuntu/btc-strategy-v2/data/live_state/B_balanced_3x/service.log"
```
