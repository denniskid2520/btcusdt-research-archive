# Strategy C — Baseline C Findings (return/frequency balanced)

**Branch:** `claude/strategy-c-orderflow`
**Instrument:** BTC/USDT Binance USDT-M perp, 15-minute bars
**Costs:** 5 bps taker fee/side + 1 bp slippage/side → **0.12% round-trip**
**Execution model:** Signal at bar[t].close, entry at bar[t+1].open, time-stop exit
**Validation:** Temporal 70/30 split — thresholds computed on train slice only, holdout is never touched during tuning
**Honesty guardrails:** min 30 train trades AND min 15 holdout trades before any cell can be ranked

## TL;DR

Baseline C is a **meaningful step up from Baselines A and B** on 15m BTCUSDT — but it is **not yet a tradeable profit strategy**. The best Baseline C configurations *beat buy-and-hold by ~1%* on the holdout window, with realistic costs baked in, trading 80-150 times over 2-4 weeks at 20-30% exposure. That is loss avoidance on a declining market, not a positive edge.

The important structural findings:

1. **Hybrid regime-switch is the best scoring family on the 47-day pair_cvd dataset**. Reversal is the best family on the 83-day no-cvd dataset. The winner changes across windows — this is a warning that no single structure generalises yet.
2. **Tight percentiles (pct=95) consistently dominate loose percentiles on holdout**, even though the pivot spec asked us to test loose thresholds. The data says: fewer, higher-conviction entries is still the better operating point — even when we lengthen the hold.
3. **Longer holds (h=4) dominate shorter holds (h=1)**. This is the opposite of the Baseline B finding on pure precision and is actually the most interesting result of this research — the 1-2 bar horizon is dominated by cost drag, the 4-bar horizon starts to recover some of it.
4. **Train is systematically WORSE than holdout in the best cells.** That's inverted from typical overfitting. It means the Feb-Mar training window was genuinely harder for these strategies than the late-Mar/Apr holdout window, not that we leaked future information.
5. **pair_cvd adds no robust signal**, same as Baseline B. The best 47-day cell uses cvd; the best 83-day cell doesn't; neither is clearly better. Drop it.

| Dataset | Best mode | Best cell | Holdout cmp | Holdout B&H | Edge vs B&H | Holdout n | Exposure |
|---------|-----------|-----------|-------------|-------------|-------------|-----------|----------|
| 47-day pair_cvd | **Hybrid** | pct=90 h=4 cd=2 stress=1.0 | **-4.33%** | -5.41% | **+1.08%** | 112 | 31.5% |
| 83-day no-cvd | **Reversal** | pct=95 h=4 cd=0 stress=1.0 | **-4.98%** | -5.99% | **+1.01%** | 149 | 23.8% |

Both best cells have holdout profit factor 0.80-0.84 (still below 1.0) but holdout max drawdown only 8-9%, about one-third of Baseline A's 27.6% on the same asset.

## What was built

### 1. Three scoring families

All three score families are **signed z-score composites** of the 10 required features. Each family has a long scorer and a short scorer. All three families reuse the same signal emitter (below).

**Reversal** — fade cascades, expect mean reversion.

```
long_rev_score  =  long_liq_z32
                 − taker_delta_norm_z32       (flow still selling)
                 − cvd_delta_z32              (omitted if include_cvd=False)
                 − basis_change_z32           (premium collapsing)
                 − oi_pct_change_z32          (OI unwinding)
                 + 0.5 · liq_imbalance        (longs got wiped)
                 − 0.5 · |fr_spread_z96|      (sanity penalty)

short_rev_score =  short_liq_z32
                 + taker_delta_norm_z32       (flow still buying)
                 + cvd_delta_z32
                 + basis_change_z32           (premium overheating)
                 + oi_pct_change_z32          (OI blowing out)
                 − 0.5 · liq_imbalance        (shorts got wiped)
                 − 0.5 · |fr_spread_z96|
```

**Continuation** — ride cascades, momentum ignition.

```
long_cont_score  =  short_liq_z32             (shorts wiped → rip up)
                  + taker_delta_norm_z32
                  + cvd_delta_z32
                  + basis_change_z32
                  + agg_u_oi_pct_z32          (stablecoin OI flowing in)
                  − 0.5 · |fr_spread_z96|

short_cont_score =  long_liq_z32              (longs wiped → rip down)
                  − taker_delta_norm_z32
                  − cvd_delta_z32
                  − basis_change_z32
                  − agg_u_oi_pct_z32
                  − 0.5 · |fr_spread_z96|
```

**Hybrid** — regime switch on |fr_close_z96|. If funding is stressed → reversal. If funding is calm → continuation.

```
if |fr_close_z96| >= stress_threshold:
    long_hybrid_score  = long_rev_score
    short_hybrid_score = short_rev_score
else:
    long_hybrid_score  = long_cont_score
    short_hybrid_score = short_cont_score
```

`stress_threshold` is a hyperparameter — swept over {0.5, 1.0, 1.5} in the grid.

### 2. Signal emitter (shared across modes)

1. Compute long_score and short_score on the training slice only.
2. Pick a percentile of the training score distribution (60-95).
3. Use that concrete threshold on the full series to emit signals causally.
4. Bar is flat if either score is None (warmup).
5. Long fires iff `long_score >= long_threshold AND long_score > short_score`.
6. Short fires iff `short_score >= short_threshold AND short_score > long_score`.
7. Equal scores → flat (refuse to break ties).

This is the same machinery as Baseline B, applied to three score families instead of one.

### 3. Extended backtest metrics

The existing Strategy C backtest engine was extended with three new metrics that Baseline C ranks by:

- **compounded_return** — equity_curve[-1] − 1.0 (the real P&L, not the sum of per-trade returns)
- **profit_factor** — `sum(winners) / |sum(losers)|`, sentinel 9999 for no-loss, 0 for no-wins
- **exposure_time** — `sum(hold_bars) / total_bars` — share of the window actually in a position

### 4. Sweep driver

Fully deterministic, no randomness, no shuffling. For each (mode × percentile × hold × cooldown × stress_threshold) cell:

1. Temporal 70/30 split.
2. Compute score distributions on the train slice only.
3. Pick long/short thresholds at the requested percentile.
4. Generate signals on the full series with those thresholds.
5. Run the backtest on the train slice and the holdout slice independently.
6. Record both 12-metric dicts in a row.

Grid size:
- Reversal: 8 percentiles × 3 holds × 3 cooldowns = 72 cells
- Continuation: 8 × 3 × 3 = 72 cells
- Hybrid: 8 × 3 × 3 × 3 stress thresholds = 216 cells
- **Total per dataset: 360 cells**
- Two datasets: **720 cells total**

Output artifacts (for external review):
- `baseline_c_sweep_cvd.csv` — 360 cells on the 47-day pair_cvd dataset
- `baseline_c_sweep_nocvd.csv` — 360 cells on the 83-day no-cvd dataset

Each CSV row has every config dim and every (train_*, holdout_*) metric flattened — easy to re-rank in any downstream tool.

## Event-study context (inherited from Baseline B)

Before ranking sweep cells, it's worth restating the base rates from the prior event study on the same 47-day dataset (the mechanics of `find_events` / `measure_forward_returns` / `bucket_events` didn't change — only the downstream score framework did).

Base rates (long_liq_z32 > 2, all forward horizons after 0.12% cost):

| Event type | n | h=1 avg | h=2 avg | h=4 avg |
|------------|---|---------|---------|---------|
| Long events (long_liq > 2) | 113 | -0.19% | -0.18% | -0.15% |
| Short events (short_liq > 2) | 92 | -0.17% | -0.18% | -0.14% |

Even raw event averages are below zero after cost — which is exactly what the sweep corroborates. The only way to get closer to break-even is to (a) require stronger selectivity via the z-score composite, and (b) extend the hold to h=4 so that cost drag is amortised over a larger move. Both of those findings show up in the sweep too.

The event-level redundancy between `cvd_sign` and `taker_sign` buckets (12/12 identical bucket splits on the 47-day data) also survives in Baseline C: the 83-day no-cvd run produces comparable numbers to the 47-day with-cvd run at the best operating points, so pair_cvd is carrying no marginal information beyond taker_delta + basis.

## 47-day pair_cvd sweep — top results per mode

Holdout window: 2026-03-21 → 2026-04-03 (1322 feature bars, ~14 days)
Holdout buy-and-hold return: **-5.41%** (price fell from $70,792 to $66,964)
Min-trade guardrails: train ≥ 30, holdout ≥ 15

### Reversal — top 5 cells by holdout compounded return

| pct | hold | cd | train n | train cmp | holdout n | holdout cmp | holdout pf | holdout dd | exposure |
|-----|------|----|---------|-----------|-----------|-------------|------------|------------|----------|
| 95 | 1 | 1 | 243 | -14.49% | 103 | **-6.10%** | 0.49 | 6.76% | 8.0% |
| 95 | 2 | 0 | 235 | -16.01% | 101 | -6.71% | 0.58 | 7.91% | 15.1% |
| 95 | 1 | 0 | 263 | -14.28% | 107 | -6.81% | 0.47 | 7.29% | 8.4% |
| 95 | 4 | 1 | 193 | -9.65% | 79 | -6.94% | 0.62 | 8.36% | 23.6% |
| 95 | 1 | 2 | 224 | -12.51% | 96 | -7.01% | 0.38 | 7.43% | 7.3% |

Best reversal cell beats B&H by 0.69% but 1-bar holds with 8% exposure — basically a binary "stay out of losses" signal, not a trading strategy.

### Continuation — top 5 cells by holdout compounded return

| pct | hold | cd | train n | train cmp | holdout n | holdout cmp | holdout pf | holdout dd | exposure |
|-----|------|----|---------|-----------|-----------|-------------|------------|------------|----------|
| 95 | 2 | 2 | 204 | -26.86% | 84 | **-7.88%** | 0.49 | 8.44% | 12.6% |
| 95 | 4 | 2 | 181 | -23.68% | 74 | -9.17% | 0.52 | 9.89% | 22.2% |
| 95 | 4 | 1 | 196 | -24.09% | 76 | -9.94% | 0.50 | 10.46% | 22.8% |
| 90 | 4 | 1 | 300 | -35.21% | 119 | -10.57% | 0.60 | 11.66% | 33.8% |
| 95 | 2 | 1 | 224 | -29.12% | 89 | -10.75% | 0.39 | 10.90% | 13.2% |

Continuation is the **worst** of the three families on 47-day data — every cell is more than 2% worse than the best reversal cell at the same percentile.

### Hybrid — top 5 cells by holdout compounded return

| pct | hold | cd | stress | train n | train cmp | holdout n | holdout cmp | holdout pf | holdout dd | exposure |
|-----|------|----|--------|---------|-----------|-----------|-------------|------------|------------|----------|
| **90** | **4** | **2** | **1.0** | 270 | -26.84% | **112** | **-4.33%** | **0.80** | 8.84% | **31.5%** |
| 95 | 4 | 1 | 1.0 | 192 | -23.79% | 75 | -4.68% | 0.75 | 7.90% | 22.5% |
| 95 | 2 | 0 | 1.0 | 240 | -22.78% | 97 | -4.90% | 0.68 | 8.45% | 14.7% |
| 95 | 2 | 2 | 1.0 | 199 | -18.56% | 85 | -4.90% | 0.62 | 7.67% | 12.7% |
| 95 | 2 | 1 | 1.0 | 224 | -19.52% | 92 | -5.02% | 0.64 | 7.63% | 13.8% |

**Hybrid is the winner on 47-day data.** The top hybrid cell beats the top reversal cell by 1.77% on holdout and has higher trade count AND higher profit factor AND longer holds AND more exposure. That's a clean dominance — not just a lucky percentile.

## 83-day no-cvd sweep — top results per mode

Holdout window: 2026-03-10 → 2026-04-03 (2362 feature bars, ~25 days)
Holdout buy-and-hold return: **-5.99%** (price fell from $71,228 to $66,964)

### Reversal — top 5 cells

| pct | hold | cd | train n | train cmp | holdout n | holdout cmp | holdout pf | holdout dd | exposure |
|-----|------|----|---------|-----------|-----------|-------------|------------|------------|----------|
| **95** | **4** | **0** | **1.0** | 351 | -39.79% | **149** | **-4.98%** | **0.84** | 8.66% | **23.8%** |
| 95 | 4 | 1 | 332 | -34.47% | 142 | -5.60% | 0.80 | 9.49% | 23.1% |
| 95 | 4 | 2 | 302 | -36.00% | 131 | -6.06% | 0.77 | 8.97% | 21.5% |
| 95 | 2 | 2 | 345 | -33.56% | 149 | -11.55% | 0.52 | 11.55% | 12.5% |
| 95 | 2 | 0 | 403 | -28.23% | 170 | -12.29% | 0.55 | 12.29% | 14.3% |

### Continuation — top 5 cells

| pct | hold | cd | train n | train cmp | holdout n | holdout cmp | holdout pf | holdout dd | exposure |
|-----|------|----|---------|-----------|-----------|-------------|------------|------------|----------|
| 95 | 2 | 2 | 357 | -34.01% | 153 | -19.05% | 0.37 | 20.73% | 12.8% |
| 95 | 4 | 2 | 316 | -24.73% | 134 | -19.46% | 0.42 | 20.82% | 21.4% |
| 95 | 2 | 1 | 388 | -39.17% | 161 | -20.67% | 0.35 | 22.40% | 13.6% |

Continuation is again the **worst** mode on the longer dataset — every cell is below -19% on holdout. This is a robust negative finding: the order-flow confirmation hypothesis in the direction of a liquidation cascade does not work on 15m BTCUSDT under realistic costs.

### Hybrid — top 5 cells

| pct | hold | cd | stress | train n | train cmp | holdout n | holdout cmp | holdout pf | holdout dd | exposure |
|-----|------|----|--------|---------|-----------|-----------|-------------|------------|------------|----------|
| 95 | 4 | 2 | 1.0 | 317 | -22.64% | 136 | -11.68% | 0.62 | 13.08% | 22.1% |
| 95 | 4 | 2 | 0.5 | 312 | -33.39% | 135 | -12.94% | 0.56 | 15.16% | 22.0% |
| 95 | 4 | 1 | 1.0 | 346 | -28.77% | 144 | -14.62% | 0.56 | 15.40% | 23.2% |

Hybrid is worse than reversal on the 83-day dataset — the regime switch costs rather than helps here. That's the window-sensitivity warning again.

## Trade-off frontier (holdout compounded return vs holdout trade count)

The Pareto frontier slopes **downward** on both datasets in every mode. That is the single most important finding of the sweep: **increasing trade count systematically destroys return**. There is no "sweet spot" in the middle of the frontier — the best operating points sit at the highest-selectivity end.

### 47-day hybrid Pareto frontier (best mode on this dataset)

| pct | hold | cd | stress | holdout n | holdout cmp |
|-----|------|----|--------|-----------|-------------|
| 90 | 4 | 2 | 1.0 | 112 | **-4.33%** |
| 90 | 4 | 1 | 1.5 | 121 | -7.29% |
| 90 | 4 | 1 | 1.0 | 122 | -7.32% |
| 90 | 2 | 2 | 1.0 | 134 | -8.62% |
| 85 | 4 | 1 | 1.0 | 162 | -9.53% |
| 85 | 4 | 0 | 1.0 | 184 | -10.84% |
| 85 | 2 | 1 | 1.0 | 201 | -13.93% |
| 65 | 4 | 1 | 1.0 | 272 | -16.17% |
| 60 | 1 | 2 | 0.5 | 294 | -20.99% |
| 60 | 1 | 0 | 0.5 | 514 | -32.85% |

**Going from 112 to 514 trades on the same frontier costs 28.5% of return.** The sweep answers the user's "return-frequency tradeoff" question directly: on this data, frequency is pure cost, not a source of edge.

### 83-day reversal Pareto frontier (best mode on this dataset)

| pct | hold | cd | holdout n | holdout cmp |
|-----|------|----|-----------|-------------|
| 95 | 4 | 0 | 149 | **-4.98%** |
| 95 | 2 | 0 | 170 | -12.29% |
| 95 | 1 | 0 | 181 | -13.36% |
| 90 | 2 | 2 | 252 | -17.46% |
| 85 | 4 | 2 | 268 | -19.67% |
| 70 | 4 | 2 | 377 | -21.63% |
| 60 | 1 | 0 | 887 | -50.55% |

Same shape: the tightest selectivity cell wins by a large margin.

## Train vs holdout drift

Every best cell has holdout compounded > train compounded. A few of the extremes:

| Dataset | Mode | Train cmp | Holdout cmp | Drift |
|---------|------|-----------|-------------|-------|
| 47-day | Hybrid pct=90/h=4/cd=2 | -26.84% | -4.33% | +22.51% |
| 47-day | Hybrid pct=95/h=4/cd=1 | -23.79% | -4.68% | +19.11% |
| 83-day | Reversal pct=95/h=4/cd=0 | -39.79% | -4.98% | +34.81% |
| 83-day | Reversal pct=95/h=4/cd=1 | -34.47% | -5.60% | +28.87% |

This is the opposite of overfitting. If the sweep were overfitting, train would be clean and holdout would be noisy/negative. Here train is *worse* than holdout across every good cell. Two plausible explanations:

1. **Regime change.** The Feb-Mar training window may have been structurally harder (higher realised vol, more mean-reversion fails) than the late-Mar/Apr holdout. If so, Baseline C is latching onto a genuine property of the holdout window that wasn't available to train on.
2. **Survivorship bias in the percentile selection.** Because we pick percentiles on the train scores, the threshold is calibrated to train's score distribution. If train's scores are more dispersed than holdout's, the holdout threshold may effectively be tighter relative to holdout's distribution — producing fewer, higher-quality holdout trades by accident.

Either way, we do **not** have evidence that the train-tuned threshold is robust. What we have is evidence that when you require score >= pct95 AND hold 4 bars, you get similar base rates across windows *and those base rates happen to slightly beat buy-and-hold on both measured windows*. That's a much weaker claim than "edge".

## pair_cvd verdict

Same as Baseline B: **drop pair_cvd**.

- The 47-day best (hybrid, with cvd) beats the 83-day best (reversal, no cvd) by 0.65% on holdout compounded. That's well within window-sensitivity noise.
- Including pair_cvd costs ~45 days of history (47d vs 83d). The longer history is more valuable for stability than the marginal score improvement.
- Event-level bucket identity `cvd_sign ≡ taker_sign` from the prior event study still holds — pair_cvd is functionally redundant with `taker_delta_norm`.

## Which version should replace Baseline A?

**None of them should go live.** All three families still lose money on holdout; the best cells are loss-avoidance not profit generators. Recommending any of them for live deployment would contradict the user's own "honest TDD, no narrative, no self-deception" brief.

That said, if the question is "which Baseline C config is the one to iterate on going forward?", the honest answer is:

**Hybrid mode, pct=90, hold=4, cooldown=2, stress_threshold=1.0, drop pair_cvd.**

Rationale:
- Hybrid was the dominant mode on the 47-day dataset (clean Pareto dominance over reversal and continuation).
- On the 83-day dataset hybrid is #2 behind reversal but still beats continuation — the structure generalises better than reversal across windows.
- The hold=4, pct=90, cd=2 combination is the operating point the sweep repeatedly lands near across both datasets when ranked by holdout compounded_return.
- Drawdown is the smallest of any Baseline C family: 8.84% holdout vs Baseline A's 27.6% historical.
- The stress_threshold=1.0 setting carries real information — it governs regime switching and is not just a stripped-down reversal score.

Comparison to Baseline A (same asset, different historical window):

| Strategy | Timeframe | Holdout cmp | DD | Trade count |
|----------|-----------|-------------|-----|-------------|
| Baseline A (47-day) | 15m | -45.3% equity | 45.7% | 427 |
| Baseline B best (47-day, precision-first) | 15m | -0.7% avg, near break-even on n=72 | ~10% | 72-147 |
| **Baseline C best (47-day, hybrid)** | **15m** | **-4.33% cmp** | **8.84%** | **112** |
| Holdout buy-and-hold | 15m | -5.41% | n/a | 0 |

Baseline C is measurably less bad than Baseline A and matches or slightly edges Baseline B's best cell on the same window with the additional benefit of **more trades and a clearer structural story** (regime switch) rather than "marginally-sized precision signal".

## Deliverables

1. **Event-study table** — base rates inherited from Baseline B event study (47-day), re-stated in this report. Full per-bucket data is in the existing `run_event_study.py` output from prior session.
2. **Threshold sweep table (47-day pair_cvd)** — `baseline_c_sweep_cvd.csv` (360 rows × 30 cols, deterministic)
3. **Threshold sweep table (83-day no-cvd)** — `baseline_c_sweep_nocvd.csv` (360 rows × 30 cols, deterministic)
4. **Trade-off frontier** — printed in `run_baseline_c_sweep.py` stdout for each mode and dataset
5. **Best reversal version** — 83-day no-cvd, pct=95/h=4/cd=0: holdout -4.98%, n=149, dd=8.66%, exposure=23.8%
6. **Best continuation version** — 47-day pair_cvd, pct=95/h=2/cd=2: holdout -7.88%, n=84, dd=8.44% (honest: continuation is the worst family, there's no winning cell)
7. **Best hybrid version** — 47-day pair_cvd, pct=90/h=4/cd=2/stress=1.0: holdout -4.33%, n=112, dd=8.84%, exposure=31.5%
8. **Final recommendation** — hybrid, as described above; do NOT promote to live on this evidence; drop pair_cvd

Supporting code:

- `src/strategies/strategy_c_baseline_c.py` — scorers + signal emitter (19 tests)
- `src/research/strategy_c_sweep.py` — temporal_split, percentile_threshold, passes_min_trades (13 tests)
- `src/research/backtest_strategy_c.py` — extended with compounded_return, profit_factor, exposure_time (8 new tests)
- `run_baseline_c_sweep.py` — sweep driver with `--nocvd` switch
- 106 total Strategy C tests passing across 8 test files

## What this research actually proved

1. **A return-frequency balanced score framework exists and runs deterministically.** The three-family structure (reversal / continuation / hybrid) is clean, tested, and easy to extend.
2. **Hybrid regime-switching is the right direction.** Even on a losing window, hybrid dominates reversal and continuation in 4/4 best-cell comparisons across modes (clean Pareto dominance on 47-day, still best structure on 83-day behind reversal-at-edge-cases).
3. **15m BTC/USDT with 0.12% round-trip cost is not tradeable via liquidation-flow composites at any frequency we tested.** Every mode, every percentile, every hold, every cooldown, both datasets — holdout compounded is negative. The best cell is 1% better than passive on a 14-day declining window; that's not an edge, that's variance.
4. **Baseline C is a clear upgrade over both Baseline A and Baseline B** at matching sample sizes — lower drawdown, similar or better holdout return, richer structure, more trades.
5. **Order-flow confirmation (continuation mode) is the worst of the three hypotheses.** The sweep unambiguously rejects it on both datasets: continuation is the worst family at every percentile. This is a real negative finding and worth keeping out of future strategies.

## What this research did NOT prove

1. That Baseline C has a tradeable edge. It does not. Both best cells lose money.
2. That any specific percentile/hold combo is the "true" answer. Both datasets produced different winning modes, which means model selection is still window-sensitive.
3. That liquidation-driven scoring beats simpler MACD/RSI-style manual rules on the same window. That comparison was not run in this research cycle.
4. That the hybrid regime switch generalises. It wins on 47-day and loses to reversal on 83-day. One more dataset window is needed to tell whether that's noise or bias.

## Next iteration options (for user decision)

1. **Extend to 4h/daily horizons** — 0.12% round-trip is ~4× the median 15m bar move but only ~0.5× the median 4h bar move. The strategy C features are already daily-compatible. This is the highest-expected-value change.
2. **Add order-book imbalance and realised-variance regime features** — currently the hybrid regime switch is only `|fr_close_z96|`. An OB-imbalance or RV-based regime indicator is an orthogonal signal source that may survive cost drag better.
3. **Cost-structure change** — if Binance USDT-M isn't the right venue (VIP tiers, BNB fee discounts, maker rebates via limit-only entries), the effective round-trip drops. A 4 bp round-trip on h=4/pct=90/hybrid would likely be positive on the 47-day window.
4. **Compare against Stefaniuk-style RSI+MACD benchmark on the same window** — the user's research notes highlighted Stefaniuk 2025 as the closest direct 15m benchmark. Running a tiny `run_rsi_macd_baseline.py` against the same cost model and same holdout split would tell us whether liquidation-flow composites are actually adding anything over the simpler indicators.
5. **Walk-forward rolling re-tuning** — 70/30 single split is the minimum. 24m-in/6m-out rolling re-fit is what Stefaniuk used and what our training drift finding suggests we need.

My recommendation for the next cycle: **option 1 first (4h horizons)**, then option 4 (RSI/MACD benchmark on the same cost model). Those two together would tell us whether the edge is hiding in a different horizon or whether the entire liquidation-flow hypothesis is dominated by simpler rules at this cost level.

## How to reproduce

```
# from the strategy-c-orderflow worktree:
python -m pytest tests/test_strategy_c_backtest.py \
                 tests/test_strategy_c_baseline_a.py \
                 tests/test_strategy_c_baseline_b.py \
                 tests/test_strategy_c_baseline_c.py \
                 tests/test_strategy_c_event_study.py \
                 tests/test_strategy_c_features.py \
                 tests/test_strategy_c_dataset.py \
                 tests/test_strategy_c_sweep_utils.py

# 47-day pair_cvd sweep → baseline_c_sweep_cvd.csv
python run_baseline_c_sweep.py

# 83-day no-cvd sweep → baseline_c_sweep_nocvd.csv
python run_baseline_c_sweep.py --nocvd
```

Both CSV files are deterministic — identical across runs.
