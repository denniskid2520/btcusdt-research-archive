# Strategy C v2 — Deliverable #2: Feature Matrix

_Date: 2026-04-11_
_Status: Phase 1 complete. This is the per-feature inventory for the
Strategy C v2 walk-forward program._

This file is the source of truth for which features live in the v2 feature
vector, which track they belong to, which primitive implements them, and
when in the phase plan they get wired up.

Read this alongside:
- `strategy_c_v2_plan.md` — architectural plan and phase decomposition
- `strategy_c_v2_data_coverage.md` — the data-source inventory that drives
  the Track A / Track B split

---

## 1. Family taxonomy

| Family | Description                               | Source                         | Tracks |
|--------|-------------------------------------------|--------------------------------|--------|
| A      | Binance price / technical (OHLCV-derived)| Binance klines 15m/1h/4h/1d    | A, B   |
| B      | Binance perp structure                    | Binance fundingRate + spot     | A, B   |
| C      | Coinglass supplemental                    | Coinglass 8 endpoints, ~90d 15m| B only |

Track A runs on Family A + Family B only. Track B runs on all three
families. Every feature listed below is tagged with its track membership.

---

## 2. Family A — Binance price/technical (full 6-year history)

All Family A features are derived from the already-on-disk Binance klines
(15m base + 1h/4h/1d derived lookback). Warmup column shows the number of
bars before the feature becomes non-None on the 15m timeline.

### 2.1 Returns

| Feature | Definition                              | Primitive              | Warmup (15m bars) | Phase | Track |
|---------|-----------------------------------------|------------------------|-------------------|-------|-------|
| ret_1   | `close[t] / close[t-1] - 1`             | inline                 | 1                 | P2    | A, B  |
| ret_4   | `close[t] / close[t-4] - 1`             | inline                 | 4                 | P2    | A, B  |
| ret_8   | `close[t] / close[t-8] - 1`             | inline                 | 8                 | P2    | A, B  |
| ret_16  | `close[t] / close[t-16] - 1`            | inline                 | 16                | P2    | A, B  |
| ret_32  | `close[t] / close[t-32] - 1`            | inline                 | 32                | P2    | A, B  |

### 2.2 Realized volatility

Rolling standard deviation of log returns on the base 15m series.

| Feature | Definition                                          | Primitive | Warmup (15m bars) | Phase | Track |
|---------|------------------------------------------------------|-----------|-------------------|-------|-------|
| rv_1h   | `std(log_ret[t-4..t], ddof=0)`                       | inline    | 4                 | P2    | A, B  |
| rv_4h   | `std(log_ret[t-16..t], ddof=0)`                      | inline    | 16                | P2    | A, B  |
| rv_1d   | `std(log_ret[t-96..t], ddof=0)`                      | inline    | 96                | P2    | A, B  |
| rv_7d   | `std(log_ret[t-672..t], ddof=0)`                     | inline    | 672               | P2    | A, B  |

### 2.3 Momentum

| Feature | Definition                              | Primitive | Warmup | Phase | Track |
|---------|-----------------------------------------|-----------|--------|-------|-------|
| mom_30  | `close[t] - close[t-30]`                | inline    | 30     | P2    | A, B  |

### 2.4 RSI (Wilder)

| Feature | Primitive                                  | Warmup | Phase | Track |
|---------|--------------------------------------------|--------|-------|-------|
| rsi_14  | `_rsi_from_closes` (existing)              | 14     | P2    | A, B  |
| rsi_30  | `_rsi_from_closes` (existing)              | 30     | P2    | A, B  |

### 2.5 MACD (12, 26, 9)

| Feature     | Primitive                                | Warmup | Phase | Track |
|-------------|------------------------------------------|--------|-------|-------|
| macd        | `compute_macd` (existing in macro_cycle) | 26     | P2    | A, B  |
| macd_signal | `compute_macd` → signal_line             | 34     | P2    | A, B  |
| macd_hist   | `compute_macd` → histogram               | 34     | P2    | A, B  |

### 2.6 Stochastic — two periods

Full Stochastic, `smooth_k=3`, `smooth_d=3`.

| Feature       | Primitive (new Phase 1)    | Warmup (15m)           | Phase | Track |
|---------------|----------------------------|------------------------|-------|-------|
| stoch_k_30    | `stochastic(k_period=30)`  | 30 + 3 + 3 - 2 = 34    | P2    | A, B  |
| stoch_d_30    | `stochastic(k_period=30)`  | 30 + 3 + 3 - 2 = 34    | P2    | A, B  |
| stoch_k_200   | `stochastic(k_period=200)` | 200 + 3 + 3 - 2 = 204  | P2    | A, B  |
| stoch_d_200   | `stochastic(k_period=200)` | 200 + 3 + 3 - 2 = 204  | P2    | A, B  |

### 2.7 Moving averages and MA ratios

| Feature    | Primitive                   | Warmup | Phase | Track |
|------------|-----------------------------|--------|-------|-------|
| sma_20     | rolling mean                | 20     | P2    | A, B  |
| sma_50     | rolling mean                | 50     | P2    | A, B  |
| sma_200    | rolling mean                | 200    | P2    | A, B  |
| ema_20     | `_ema` (existing)           | 20     | P2    | A, B  |
| ema_50     | `_ema` (existing)           | 50     | P2    | A, B  |
| ema_200    | `_ema` (existing)           | 200    | P2    | A, B  |

Derived ratios (close/SMA, EMA crosses) are computed inline in the feature
module from the above; not separate fields.

### 2.8 Bollinger Bands (20, 2.0)

| Feature      | Primitive (new Phase 1)   | Warmup | Phase | Track |
|--------------|---------------------------|--------|-------|-------|
| bb_mid_20    | `bollinger_bands`         | 20     | P2    | A, B  |
| bb_upper_20  | `bollinger_bands`         | 20     | P2    | A, B  |
| bb_lower_20  | `bollinger_bands`         | 20     | P2    | A, B  |
| bb_width_20  | `bollinger_bands` (upper − lower) | 20 | P2  | A, B  |
| bb_pctb_20   | `bollinger_bands` (%B)    | 20     | P2    | A, B  |

### 2.9 ATR (Wilder)

| Feature | Primitive (new Phase 1) | Warmup | Phase | Track |
|---------|--------------------------|--------|-------|-------|
| atr_14  | `atr(period=14)`         | 14     | P2    | A, B  |
| atr_30  | `atr(period=30)`         | 30     | P2    | A, B  |

### 2.10 Calendar features (always populated, no warmup)

| Feature        | Definition                          | Primitive | Track |
|----------------|-------------------------------------|-----------|-------|
| hour_of_day    | `timestamp.hour` (0..23)            | inline    | A, B  |
| day_of_week    | `timestamp.weekday()` (0=Mon..6=Sun)| inline    | A, B  |
| is_weekend     | `day_of_week >= 5`                  | inline    | A, B  |

---

## 3. Family B — Binance perp structure

### 3.1 Funding rate (8h settlements, forward-filled to 15m)

| Feature                | Definition                                     | Source / Primitive                | Phase | Track |
|------------------------|------------------------------------------------|-----------------------------------|-------|-------|
| funding_rate           | Most-recent settled funding rate, ffill to 15m | `btcusdt_funding_5year.csv`       | P2    | A, B  |
| bars_to_next_funding   | 15m bars until next 8h settlement (0..31)      | derived from 8h schedule          | P2    | A, B  |
| funding_cum_24h        | Sum of funding_rate over last 96 bars (24h)    | rolling sum inline                | P2    | A, B  |

### 3.2 Basis perp vs spot (requires spot fetch)

| Feature              | Definition                                      | Source                                   | Phase | Track |
|----------------------|--------------------------------------------------|------------------------------------------|-------|-------|
| basis_perp_vs_spot   | `perp_close - spot_close` per 15m bar            | `/api/v3/klines` (spot BTCUSDT, to fetch)| P2    | A, B  |

### 3.3 Features deferred due to coverage gaps (see data_coverage §4)

| Feature            | Gap reason                                | Current decision                  |
|--------------------|-------------------------------------------|-----------------------------------|
| open_interest      | Binance REST gives only ~30 days          | Dropped from Track A; included in Track B via Coinglass OI |
| mark_vs_last       | Binance premiumIndex is snapshot-only     | Dropped from Track A; included in Track B via Coinglass OI OHLC |

---

## 4. Family C — Coinglass supplemental (**Track B only, ~90-day window**)

These features are Track B only per `strategy_c_v2_data_coverage.md` §3.
They are included here for completeness of the feature matrix. Implementation
lands in Phase 4 when Track B comes online.

### 4.1 Flow and microstructure

| Feature                | Definition                                                  | Endpoint                                          | Phase | Track |
|------------------------|-------------------------------------------------------------|---------------------------------------------------|-------|-------|
| taker_delta_norm_z32   | (taker_buy − taker_sell) / (taker_buy + taker_sell), z-scored over 32 bars | `/api/futures/taker-buy-sell-volume/history` | P4 | B |
| cvd_delta_z32          | Δ(cumulative volume delta) z-scored 32 bars                 | derived from taker_buy/sell                       | P4    | B     |

### 4.2 Liquidations (F3 reversal strategy inputs)

| Feature           | Definition                                | Endpoint                                     | Phase | Track |
|-------------------|-------------------------------------------|----------------------------------------------|-------|-------|
| long_liq_z32      | Long liquidation USD z-score over 32 bars | `/api/futures/liquidation/aggregated-history`| P4    | B     |
| short_liq_z32     | Short liquidation USD z-score over 32 bars| same                                         | P4    | B     |
| liq_imbalance     | `(short_liq - long_liq) / (short_liq + long_liq)` | derived                              | P4    | B     |

### 4.3 Funding stress (aggregated across exchanges)

| Feature             | Definition                                                     | Endpoint                                    | Phase | Track |
|---------------------|----------------------------------------------------------------|---------------------------------------------|-------|-------|
| fr_close_z96        | Aggregated funding close z-scored over 96 bars                 | `/api/futures/funding-rate/history`         | P4    | B     |
| fr_spread_z96       | OI-weighted funding − vanilla funding, z-scored 96 bars        | `/api/futures/funding-rate/ohlc-history`    | P4    | B     |
| oi_weighted_funding | Raw OI-weighted funding rate                                   | `/api/futures/funding-rate/ohlc-history`    | P4    | B     |

### 4.4 Open interest dynamics

| Feature                | Definition                             | Endpoint                                     | Phase | Track |
|------------------------|----------------------------------------|----------------------------------------------|-------|-------|
| oi_pct_change_z32      | Δ% OI over 15m, z-scored 32 bars       | `/api/futures/openInterest/ohlc-history`     | P4    | B     |
| agg_u_oi_pct_z32       | Δ% aggregated (USD) OI, z-scored 32 bars | same                                       | P4    | B     |

### 4.5 Long/short ratio and positioning

| Feature            | Endpoint                                               | Phase | Track |
|--------------------|---------------------------------------------------------|-------|-------|
| long_short_ratio   | `/api/futures/long-short-ratio/history`                 | P4    | B     |
| top_trader_ls      | `/api/futures/top-long-short-account-ratio/history`     | P4    | B     |

### 4.6 Dropped Coinglass features

| Feature   | Reason                                                                 |
|-----------|------------------------------------------------------------------------|
| pair_cvd  | Baseline C verdict: redundant with `taker_delta_norm_z32`. Not fetched in v2. |

---

## 5. Feature counts by track

Family A breakdown (35 fields):
- Returns: 5 (ret_1/4/8/16/32)
- Realized vol: 4 (rv_1h/4h/1d/7d)
- Momentum: 1 (mom_30)
- RSI: 2 (rsi_14/30)
- MACD: 3 (macd, signal, hist)
- Stochastic: 4 (k_30, d_30, k_200, d_200)
- SMA: 3 (20/50/200)
- EMA: 3 (20/50/200)
- Bollinger: 5 (mid, upper, lower, width, pctb — all at 20/2.0)
- ATR: 2 (14, 30)
- Calendar: 3 (hour_of_day, day_of_week, is_weekend)

Family B breakdown (4 core + 2 Track-B-only augmentations):
- Track A + B: funding_rate, bars_to_next_funding, funding_cum_24h, basis_perp_vs_spot
- Track B extra: open_interest (via Coinglass), mark_vs_last (via Coinglass)

Family C breakdown (12 fields, Track B only):
- Flow: taker_delta_norm_z32, cvd_delta_z32
- Liquidations: long_liq_z32, short_liq_z32, liq_imbalance
- Funding stress: fr_close_z96, fr_spread_z96, oi_weighted_funding
- OI dynamics: oi_pct_change_z32, agg_u_oi_pct_z32
- Positioning: long_short_ratio, top_trader_ls

| Track | Family A | Family B | Family C | Total features |
|-------|----------|----------|----------|----------------|
| A     | 35       | 4        | 0        | **39**         |
| B     | 35       | 6        | 12       | **53**         |

(Counts exclude derived inline ratios like `close/sma_200` — those are
computed on demand inside strategies.)

---

## 6. Warmup horizon per track

- **Track A (15m base):** the slowest feature is `rv_7d` with 672 bars of
  warmup (7 × 24 × 4 = 672). At 15m cadence this is 7 days. All other
  Family A warmups are smaller. The first fully-populated Track A feature
  vector lands **672 bars after the 15m series begins** — trivial compared
  to the 6-year history.
- **Track B (15m base):** the slowest features are the z-score rollings on
  Coinglass streams (32 or 96 bars). Track B has ~90 days of history, so
  these warmups consume the first ~1 day (for z32) or ~1 day (for z96) of
  the window — still leaves >88 days of usable signal.

---

## 7. Feature-to-strategy mapping (Phase 3+)

For orientation, which features each strategy family *primarily* relies on.
This is a guide, not a hard constraint — the cost-aware score model (Phase 4)
will see every feature in Family A + B (Track A) or A + B + C (Track B).

| Strategy family | Primary features                                                                 | Track(s) |
|-----------------|-----------------------------------------------------------------------------------|----------|
| F1 literature   | rsi_14, macd, macd_hist                                                           | A, B     |
| F2 continuation | ema_20/50/200, rsi_14, atr_14, rv_1h/4h, bb_pctb_20, stoch_k_30                  | A, B     |
| F3 reversal     | long_liq_z32, short_liq_z32, taker_delta_norm_z32, rv_1h, atr_14                 | **B only** |
| F4 hybrid       | |fr_close_z96|, rv_4h percentile → switches between F2 and F3 (A: F2+lite reversal; B: full) | A, B |

---

## 8. Phase-wise feature availability

| Phase | What lands                                                                                           |
|-------|-------------------------------------------------------------------------------------------------------|
| P1    | Primitive infrastructure (Bollinger, Stochastic, ATR); fundingRate 5y CSV; dataset + features scaffolds |
| P2    | Walk-forward harness; feature module implementation for Family A + Family B (Track A)                |
| P3    | Literature benchmark (F1); continuation (F2); hybrid-lite (F4 Track A) — all running on Family A + B  |
| P4    | Track B comes online — Family C Coinglass features + F3 reversal + full F4 hybrid + score model       |
| P5    | Final leaderboard aggregation and recommendation                                                     |

---

## 9. Open questions (to revisit in Phase 2)

1. **Does `close/sma_200` add value over `ret_32 + macd`?** The feature set
   is already moderately redundant. The cost-aware score model (Phase 4)
   will handle collinearity, but for rule-based F2 continuation in Phase 3
   we should be explicit about which ratios the rule reads.
2. **Should `rv_7d` survive?** A 7-day rolling std on 15m bars is almost
   a constant over short windows. It may be better expressed as a
   4h-resampled std and then forward-filled to 15m. Decision deferred to
   Phase 2 implementation — whichever is cheaper is fine.
3. **Literature benchmark — 15m or 1h?** Stefaniuk 2025 publishes on 1h;
   our execution is 15m. We plan to run F1 on *both* 1h and 15m in
   Phase 3 so the benchmark is honest against the published paper.
