# ACTIVE_STRATEGY.md — Source of Truth

_Last updated: 2026-04-13_

## Current live strategy

**BTCUSDT D1 Long — 4h RSI Regime + 1h Hybrid Execution**

## Candidate stack (FROZEN)

| Candidate | Role | Mode | Leverage |
|-----------|------|------|----------|
| **B_balanced_3x** | first live | LIVE (micro-live pending) | 3x isolated |
| B_balanced_4x | primary aggressive | paper only | 4x isolated |
| A_density_4x | high-sample shadow | paper only | 4x isolated |
| B_balanced_5x | high-return shadow | paper only | 5x isolated |

## Active runner

| Runner | Purpose | Location |
|--------|---------|----------|
| `live_service.py` | real-time bar-close polling (live + dry-run) | `src/execution/live_service.py` |
| `live_paper_cron.py` | hourly cron for paper candidates | `src/execution/live_paper_cron.py` |
| `weekly_reconciliation.py` | weekly report | `src/execution/weekly_reconciliation.py` |

## Production-critical files

These files must NOT be modified without explicit approval.

### Core strategy logic
```
src/strategies/strategy_c_v2_literature.py      — signal generators (rsi_only, rsi_and_macd)
src/strategies/strategy_c_v2_filters.py         — side filter, funding filter
src/strategies/strategy_c_v2_dynamic_sizing.py   — conviction score sizing + adaptive hold
src/strategies/strategy_c_v2_live_monitor.py     — live monitor state machine
src/strategies/strategy_c_v2_regime_filter.py    — trend/vol/rsi regime filters
src/strategies/strategy_c_v2_canonical_baseline.py — SSoT for all canonical cells
src/strategies/strategy_c_v2_paper_log.py        — paper trade telemetry schema
```

### Backtester + research
```
src/research/strategy_c_v2_backtest.py           — V2 backtester (dual-stop)
src/research/strategy_c_v2_runner.py             — walk-forward helpers
src/research/strategy_c_v2_walk_forward.py       — split generation
src/research/strategy_c_v2_execution_layer.py    — 4h regime + 1h pullback exec layer
src/research/strategy_c_v2_circuit_breaker.py    — breaker study + intrabar replay
src/research/strategy_c_v2_stress_test.py        — stress test suite
src/research/strategy_c_v2_report_consistency.py — report guard
src/research/strategy_c_v2_retrospective_paper.py — retrospective paper runner
```

### Execution + deployment
```
src/execution/paper_runner_v2.py                 — paper runner state machine
src/execution/live_paper_cron.py                 — hardened cron-based paper runner
src/execution/live_executor.py                   — live executor config + Binance API
src/execution/live_service.py                    — real-time bar-close polling service
src/execution/weekly_reconciliation.py           — weekly reconciliation report
```

### Features + data
```
src/data/strategy_c_v2_features.py               — feature computation (RSI, EMA, MACD, RV)
src/data/strategy_c_v2_dataset.py                — dataset schema + alignment
src/indicators/atr.py                             — ATR indicator
src/indicators/bollinger.py                       — Bollinger Bands
src/indicators/stochastic.py                      — Stochastic oscillator
```

### Shared infrastructure
```
src/adapters/base.py                              — MarketBar dataclass
src/adapters/binance_futures.py                   — FundingRateRecord + Binance helpers
src/adapters/coinglass_client.py                  — Coinglass API (not used in final)
```

### Namespace index
```
src/systems/btcusdt_d1_final/__init__.py          — single import entry point
```

### Deployment documents
```
strategy_c_v2_FINAL.md                            — strategy summary + backtest results
strategy_c_v2_PHASE11_DEPLOYMENT.md               — deployment spec + validation plan
strategy_c_v2_PHASE13_5_DEPLOYMENT.md             — live execution semantics
strategy_c_v2_PHASE13_6_STOP_CORRECTION.md        — corrected stop model
strategy_c_v2_phase8_canonical_baseline.md        — canonical baseline reconciliation
strategy_c_v2_plan.md                             — original research plan
deploy_lightsail.sh                               — Lightsail deployment script
```

### Active tests (611 tests)
```
tests/test_strategy_c_v2_*.py                     — all v2 strategy tests
tests/test_strategy_c_*.py                        — strategy C baseline tests
tests/test_paper_runner_v2.py                     — paper runner tests
tests/test_indicators_*.py                        — indicator tests
tests/test_binance_futures.py                     — Binance adapter tests
tests/test_coinglass_client.py                    — Coinglass adapter tests
```

### Active report generators
```
run_backtest_report.py                            — full backtest report (all 4 candidates)
run_compound_backtest.py                          — true compounded backtest
run_report_b4x.py                                — B_balanced_4x formatted report
run_full_report_zh.py                             — Chinese format report
run_phase10_final_lock.py                         — Phase 10 final lock validation
run_phase12_paper_30day.py                        — retrospective 30-day paper run
generate_report_xlsx.py                           — Excel report generator
```

## Archived areas — DO NOT TOUCH

```
archive/legacy_strategies/    — Strategy A/D, channel, BB, trend_breakout
archive/legacy_tests/         — tests for legacy strategies
archive/old_phase_reports/    — Phase 3-8 research reports (historical)
archive/obsolete_runners/     — old sweep/backfill/analysis scripts
```

These are preserved for historical reference only. They have no
bearing on the current production strategy and should not be
modified, imported, or referenced by active code.

## Runtime / state / log files (not in git)

```
data/paper_state/             — paper runner state per candidate
data/live_state/              — live executor state
logs/                         — cron.log, alerts.log, alerts.jsonl
reports/                      — weekly reconciliation reports
.env                          — API keys (NEVER commit)
```

## .gitignore rules

```
.env
data/
logs/
reports/
*.csv (large sweep outputs)
_report_data.json
Strategy_C_v2_Report.xlsx
__pycache__/
```
