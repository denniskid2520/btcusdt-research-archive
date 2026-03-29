# Crypto Quant Research

Research-first crypto trading project focused on backtesting and paper trading only. No live trading, no real API keys, and all exchange interaction remains stubbed.

## Project Focus

- Python 3.11 target runtime
- `src` layout
- parameterized `TrendBreakoutStrategy`
- deterministic `PaperBroker`
- per-rule backtest observability
- per-rule rejection funnel observability
- synthetic fixtures for rules that do not naturally appear in the stub dataset

## Strategy Logic

`TrendBreakoutStrategy` implements six entry rules:

- `ascending_channel_support_bounce`
- `ascending_channel_breakout`
- `descending_channel_rejection`
- `descending_channel_breakdown`
- `rising_channel_breakdown_retest_short`
- `rising_channel_breakdown_continuation_short`

### Regime Detection

- Generic long/short regime uses the latest `impulse_lookback` bars.
- Bullish or bearish impulse requires absolute return above `impulse_threshold_pct`.
- Optional ATR expansion filter: `impulse_atr_expansion_min`
- Optional volume expansion filter: `impulse_volume_expansion_min`
- For the two rising-channel short rules, impulse is evaluated on the front segment of the structure window (`前段脈衝`) rather than the latest bars.

### Structure Detection

- Fits pivot highs and pivot lows over `structure_lookback`
- Requires at least `min_pivot_highs` pivot highs and `min_pivot_lows` pivot lows
- Requires channel width greater than `min_channel_width_abs`
- Optionally requires width percentage greater than `min_channel_width_pct`
- Requires slope divergence ratio less than or equal to `max_slope_divergence_ratio`

### Stops And Targets

- Long stop = structural support minus `stop_buffer_pct * channel_width`
- Short stop = structural resistance plus `stop_buffer_pct * channel_width`
- `rising_channel_breakdown_retest_short` stop uses one exact formula everywhere:
  - `stop = max(recovered_support, retest_bar_high) + stop_buffer`
- First target = opposite channel boundary or boundary-derived objective
- Second target = channel height projection
- Optional time stop:
  - if `time_stop_bars` is enabled, exit at the close of the T-th bar after entry
  - `exit_reason = time_stop`

## Key Parameters

- `impulse_lookback`
- `structure_lookback`
- `pivot_window`
- `min_pivot_highs`
- `min_pivot_lows`
- `impulse_threshold_pct`
- `impulse_atr_expansion_min`
- `impulse_volume_expansion_min`
- `min_channel_width_abs`
- `min_channel_width_pct`
- `max_slope_divergence_ratio`
- `entry_buffer_pct`
- `continuation_buffer_pct`
- `stop_buffer_pct`
- `time_stop_bars`
- `enable_rising_channel_breakdown_retest_short`
- `enable_rising_channel_breakdown_continuation_short`

## Baseline vs Enhanced

Baseline comparison disables only:

- `rising_channel_breakdown_retest_short`
- `rising_channel_breakdown_continuation_short`

All other parameters and rules remain identical.

## Backtest Outputs

Each closed trade records:

- `entry_rule`
- `exit_reason`
- side
- entry / exit timestamps
- entry / exit prices
- quantity
- entry / exit fees
- pnl
- return percentage

Backtest summary includes per-rule stats:

- `signal_name`
- `trigger_count`
- `filled_entries`
- `win_rate_pct`
- `pnl`
- `contribution_pct`

Backtest summary also includes condition funnel stats:

- `rule_eval_counts`: how many bars each rule was evaluated
- `rejection_stats`: `{rule: {first_failed_condition: count}}`
- failure taxonomy includes:
  - `rule_disabled`
  - `position_open`
  - `insufficient_bars`
  - `channel_not_detected`
  - `channel_kind_mismatch`
  - `impulse_mismatch`
  - `price_out_of_entry_zone`
  - `below_min_channel_width`
  - `slope_divergence_too_large`
  - `pivot_count_insufficient`

Contribution is defined as:

- `rule_realized_pnl / total_realized_pnl`
- if total realized pnl is `0`, contribution is `0.0`

## Install

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .[dev]
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]
```

## Run Backtest

Enhanced strategy:

```bash
python -m research.backtest --symbol BTCUSDT --timeframe 1h --limit 180 --variant enhanced
```

Baseline strategy:

```bash
python -m research.backtest --symbol BTCUSDT --timeframe 1h --limit 180 --variant baseline
```

Before/after comparison on the same dataset:

```bash
python -m research.backtest --symbol BTCUSDT --timeframe 1h --limit 180 --compare
```

Backfill stub bars to CSV:

```bash
python -m data.backfill --symbol BTCUSDT --timeframe 1h --limit 180 --output data/sample_bars.csv
```

Run from CSV:

```bash
python -m research.backtest --csv data/sample_bars.csv --symbol BTCUSDT --timeframe 1h --variant enhanced
```

## Run Tests

```bash
pytest
```

## Relevant Files

- `src/strategies/trend_breakout.py`
- `src/research/backtest.py`
- `src/execution/paper_broker.py`
- `tests/test_strategy.py`
- `tests/test_backtest.py`
- `tests/fixtures_synthetic_bars.py`
