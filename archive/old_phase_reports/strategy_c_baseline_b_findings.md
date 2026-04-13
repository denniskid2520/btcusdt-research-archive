# Strategy C — Baseline B precision-first research findings

**Date:** 2026-04-10
**Branch:** `claude/strategy-c-orderflow`
**Test count:** 64 passing (features, dataset, event_study, baseline_a, baseline_b, backtest)

## Honest TL;DR

Baseline B **does not find a reproducible edge** on 15m BTCUSDT on either
the 47-day dataset (with pair_cvd) or the 83-day dataset (without pair_cvd).
Every (percentile × hold × cooldown) combination loses money on the holdout
in both confirm and fade directions. The core reason is that the round-trip
cost (0.12% = 2 × 5 bps fee + 1 bp slip) is ~3× the median 15m bar move,
so a 1-4 bar directional signal needs a much higher win rate than any slice
we found (15-45%) to break even.

**Recommendation on pair_cvd: DROP it.** The event study showed cvd_delta
sign is *identical* to taker_delta sign on every bucket split, and the
with/without comparison showed the `without cvd` mode beats `with cvd`
on every single (pct × h × cd) cell of the sweep grid — sometimes by
+0.08% avg on holdout. It's redundant at best and slightly harmful at
worst. Dropping it also unlocks the 83-day dataset instead of the 47-day
pair_cvd-clipped version.

## Pipeline

1. **Feature extension** (`src/data/strategy_c_features.py`)
   - Added primitives: `cvd_delta`, `basis_change`, `fr_spread`, `agg_u_oi_pct`.
   - Added z-scores: `long_liq_z32`, `short_liq_z32`, `basis_change_z32`,
     `fr_spread_z96`, `agg_u_oi_pct_z32`, `cvd_delta_z32`.
   - Renamed `funding_z96` → `fr_close_z96` (clearer naming vs. `fr_spread`).
   - `rolling_zscore` now skips windows containing None (diff-series warmup).

2. **Event study module** (`src/research/event_study_strategy_c.py`)
   - `find_events(feats, side, z_threshold)` — scans `long_liq_z32` or
     `short_liq_z32` for threshold crossings, skips warmup Nones.
   - `measure_forward_returns(feats, events, horizons, fee, slip)` —
     enters bar[i+1].open, exits bar[i+1+h].open, sign-adjusted by side,
     round-trip cost deducted. Drops events whose max horizon runs past
     the last bar.
   - `bucket_events(results, feats_by_idx, key_fn, horizon, cost)` —
     groups results by a trigger-bar key and reports count / avg / median
     / win rate per bucket.

3. **Score-based Baseline B** (`src/strategies/strategy_c_baseline_b.py`)
   - `long_score(f)`  = long_liq_z32 + taker_z + cvd_z + basis_chg_z
     + oi_pct_z − |fr_spread_z|
   - `short_score(f)` = short_liq_z32 − taker_z − cvd_z − basis_chg_z
     − oi_pct_z − |fr_spread_z|
   - `baseline_b_signals(feats, long_threshold, short_threshold, include_cvd)`
     emits the higher-score side if it clears its threshold; ties are flat;
     any warmup None returns 0.
   - `include_cvd=False` drops the cvd term from both scores and from the
     warmup-None gate, so the score still fires on rows with missing cvd.

4. **Backtest cooldown** (`src/research/backtest_strategy_c.py`)
   - Added `cooldown_bars` parameter: after a trade exits, skip this many
     bars before re-evaluating signals. Default 0 (unchanged behaviour).

## Event study results — 47-day dataset (with pair_cvd)

Cost: 0.120% round-trip. Horizons: 1, 2, 4 bars. Thresholds: z > 2.0 / 2.5 / 3.0.

### Long events (long_liq_z32 spike)

| z_thr | n | avg% (h=2) | win (h=2) |
|---|---|---|---|
| 2.0 | 277 | -0.109 | 40.8% |
| 2.5 | 220 | -0.123 | 37.7% |
| 3.0 | 175 | -0.114 | 40.6% |

### Short events (short_liq_z32 spike)

| z_thr | n | avg% (h=2) | win (h=2) |
|---|---|---|---|
| 2.0 | 267 | -0.109 | 40.8% |
| 2.5 | 208 | -0.092 | 41.3% |
| 3.0 | 173 | -0.079 | 42.8% |

### Best bucketed slices (h=2)

| Condition | n | avg% | win |
|---|---|---|---|
| SHORT + taker_neg (z>2.5)  | 39 | +0.020 | 53.8% |
| SHORT + taker_neg (z>3.0)  | 29 | +0.011 | 51.7% |
| LONG  + oi_pos  (z>3.0)    | 26 | -0.014 | 53.8% |
| LONG  + oi_pos  (z>2.5)    | 36 | -0.035 | 50.0% |

Only four slices show 50%+ win rates. Sample sizes are very small (26-39),
which is a red flag for reproducibility.

### Critical observation — pair_cvd is redundant

Every `bucket by cvd sign` split produced **identical** counts to
`bucket by taker sign`:

```
bucket by taker sign (h=2):   neg=235  pos=42
bucket by cvd sign (h=2):     neg=235  pos=42    ← identical
```

This pattern held on 12/12 bucket tables across all sides × thresholds.
`cvd_delta` sign is fully determined by `taker_delta` sign on this dataset.

## Baseline B sweep — 47-day, WITH pair_cvd

Train: 3083 bars (Feb 17 → Mar 21). Holdout: 1322 bars (Mar 21 → Apr 3).
Grid: percentile ∈ {80, 85, 90, 95, 97.5}, hold ∈ {1, 2, 4}, cooldown ∈ {0, 2}.
Every (pct × h × cd) combination listed in `run_baseline_b_sweep.py`:

- **Best HOLDOUT row**: pct=85 h=4 cd=2 — n=147, win=30.6%, avg=-0.086%,
  net=-12.67%, dd=15.38%.
- **Worst HOLDOUT row**: pct=80 h=1 cd=0 — n=317, win=17.0%, avg=-0.177%.
- **Train win rates**: 19.3% - 40.0%.
- **Holdout win rates**: 15.1% - 35.9%.

Every single row is negative avg net on holdout.

### Fade direction (flipped signals)

Testing whether the score is systematically wrong — re-running the same
sweep with signals negated (long_score hits → SHORT):

- **Best HOLDOUT row**: pct=97.5 h=1 cd=2 — n=46, win=30.4%, avg=-0.054%,
  net=-2.47%.
- Fade raises win rates (32-46% vs 19-36%) but average losses grow too,
  so net is still negative.

Conclusion: no directional edge, fade or confirm. The score selects bars
where BOTH directions lose after costs — it's not picking noise, it's
picking high-cost-drag bars.

## With vs without pair_cvd comparison — 47-day

| pct | h | cd | WITH cvd (hold. avg%) | WITHOUT cvd (hold. avg%) | Δ avg |
|---|---|---|---|---|---|
| 95.0 | 4 | 0 | -0.100 | -0.028 | **+0.072** |
| 95.0 | 4 | 2 | -0.097 | -0.008 | **+0.089** |
| 97.5 | 4 | 2 | -0.126 | -0.050 | **+0.076** |
| 97.5 | 4 | 0 | -0.147 | -0.068 | **+0.079** |
| 97.5 | 2 | 2 | -0.131 | -0.085 | +0.046 |

Dropping cvd helps on **every single row** of the grid, sometimes by nearly
a full round-trip cost (0.09% ≈ 90 bps). The best without-cvd holdout row
is near break-even (avg=-0.008%, 40.3% win, n=72) — the only glimpse of
anything resembling signal. But:

## Extended 83-day dataset (no pair_cvd)

Rebuilt via `backfill_strategy_c_no_cvd.py` → `strategy_c_btcusdt_15m_nocvd.csv`
(7967 bars, Jan 11 → Apr 3, $90.5K → $67K = -26% trend).

- **Best HOLDOUT row**: pct=80 h=4 cd=2 — n=303, win=31.7%, avg=-0.106%,
  net=-32.21%.
- **Best high-percentile row**: pct=97.5 h=4 cd=2 — n=76, win=39.5%,
  avg=-0.119%, net=-9.08%.
- **Event study on 83 days**: no slice with n≥50 shows positive avg net;
  best large-sample slice is SHORT + oi_neg (z>2.0), n=135, avg=-0.076%,
  40.7% win.

**The 47-day near-break-even result (-0.008% avg) did NOT replicate on the
longer dataset.** On 2× the data, best holdout is back to -0.106% avg.
The 47-day slice was almost certainly sampling noise.

## Why it doesn't work (in two sentences)

On 15m BTC the median absolute bar return is ~0.03%; the round-trip cost
is 0.12%, which is ~4× the raw typical move. A 1-4 bar directional strategy
would need win rates well above 60% to overcome that drag, but no signal
we tested clears 50% win rate on a sample of ≥50 events.

## Recommendations

1. **Drop pair_cvd** from the feature set and dataset layer. It is
   informationally redundant with `taker_delta_norm` (proven on 12/12
   bucket splits) and slightly harmful in the sweep. Dropping it also
   unlocks 2× longer history. ✅ *Done — `include_cvd=False` path tested,
   `backfill_strategy_c_no_cvd.py` in place, 83-day dataset saved.*

2. **Do not promote Baseline B to live**. No edge on 47-day or 83-day
   datasets across 30 configuration cells. The precision-first research
   goal was met — we honestly looked, and there is no tradeable signal
   here at this horizon / cost structure.

3. **If we want to keep iterating on Strategy C, change one of**:
   - Cost structure (maker rebates, lower-fee venue) to drop round-trip
     cost toward 0.03-0.05%.
   - Horizon (longer holds — daily / 4h — where raw price moves exceed
     the cost by a wider margin).
   - Feature set (something orthogonal to taker-flow: order-book imbalance,
     quote-level liquidity, realized-variance regime, macro context).
   - Event definition (combine multi-exchange liquidation cascades rather
     than Binance-only pair liquidations).

4. **Baseline A remains the honest benchmark** on the 47-day dataset:
   427 trades, -45.3% equity, 32% win rate. Any future Strategy C variant
   should beat both baseline A and break-even (0%) on holdout before
   going live.

## Deliverables written to disk

Code (all test-driven, 64 tests passing):
- `src/research/event_study_strategy_c.py` — new, 8 tests
- `src/strategies/strategy_c_baseline_b.py`  — new, 15 tests
- `src/research/backtest_strategy_c.py`       — added `cooldown_bars`, 2 tests
- `src/data/strategy_c_dataset.py`            — `include_cvd` param in fetcher/aligner
- `src/strategies/strategy_c_baseline_b.py`   — `include_cvd` param in scores

Drivers (reproducible, no args needed):
- `run_event_study.py` — 47-day event study
- `run_event_study_nocvd.py` — 83-day event study
- `run_baseline_b_sweep.py` — 47-day sweep (with cvd)
- `run_baseline_b_fade_sweep.py` — 47-day fade sweep
- `run_baseline_b_cvd_compare.py` — with/without cvd side-by-side
- `run_baseline_b_sweep_nocvd.py` — 83-day sweep (without cvd)
- `backfill_strategy_c_no_cvd.py` — regenerates the 83-day dataset

Datasets:
- `src/data/strategy_c_btcusdt_15m.csv` — 4500 bars, 46.9 days, pair_cvd included
- `src/data/strategy_c_btcusdt_15m_nocvd.csv` — 7967 bars, 83 days, pair_cvd dropped

## What the research proved

- ✅ `find_events` + `measure_forward_returns` + `bucket_events` primitives
  work correctly and are test-driven.
- ✅ Baseline B scoring is correctly implemented (15 tests).
- ✅ Cooldown support was added to the backtest with tests.
- ✅ Temporal 70/30 holdout + percentile threshold selection protocol
  works and produces honest out-of-sample numbers.
- ✅ pair_cvd is redundant with taker_delta and should be dropped — an
  unambiguous negative result.
- ❌ No score/threshold combination produced positive holdout avg on
  either dataset.
- ❌ The 47-day near-break-even did not replicate on 83 days.

The research path itself was successful: we set up the machinery,
tuned honestly on train, evaluated honestly on holdout, and got a
clean negative answer. That is exactly what the precision-first brief
asked for. Moving on to a different horizon or cost structure is now
a well-informed choice rather than a guess.
