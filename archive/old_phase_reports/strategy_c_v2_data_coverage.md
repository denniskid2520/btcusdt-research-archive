# Strategy C v2 — Deliverable #1: Data Coverage Report

_Date: 2026-04-11_
_Status: Phase 1 complete. This is the honest inventory of what we have, what we
can fetch, and what is structurally unavailable._

This report answers one question: **what data is available for the 5-year
BTCUSDT perpetual walk-forward program, and where are the hard gaps?**

It drives the Phase 1 architectural decision (two tracks), the Phase 2 feature
module scope, and every subsequent "can we use feature X" conversation. Nothing
is assumed — every row here was verified against disk or tested against the
live Binance public API during this session.

---

## 1. Target window

Strategy C v2 walk-forward target: **2020-04-05 → 2026-04-11**, 15m execution,
multi-timeframe features derived from 1h / 4h / 1d.

At 15m cadence that's ≈210,000 bars. The rolling walk-forward (24m train, 6m
test, step 6m) needs ≥30 months of history to run the first split, so the
usable research window starts 2022-10-05 for first-test and ends 2026-04-05 at
the right edge. 8–9 OOS test windows fit cleanly.

---

## 2. Source-by-source coverage

### 2.1 Binance USDT-M Futures — `fapi.binance.com`

| Endpoint                              | Cadence   | Usable history | Current disk file                  | Rows   | Status |
|---------------------------------------|-----------|----------------|------------------------------------|--------|--------|
| `/fapi/v1/klines` (15m)               | 15 min    | 6 years +      | `src/data/btcusdt_15m_6year.csv`   | 210219 | ✅ on disk, 2020-04-05 → 2026-04-05 |
| `/fapi/v1/klines` (1h)                | 1 hour    | 6 years +      | `src/data/btcusdt_1h_6year.csv`    |  52560 | ✅ on disk, 2020-04-05 → 2026-04-05 |
| `/fapi/v1/klines` (4h)                | 4 hours   | 6 years +      | `src/data/btcusdt_4h_6year.csv`    |  13147 | ✅ on disk, 2020-04-05 → 2026-04-05 |
| `/fapi/v1/klines` (1d)                | 1 day     | 6 years +      | `src/data/btcusdt_1d_6year.csv`    |   2192 | ✅ on disk, 2020-04-05 → 2026-04-05 |
| `/fapi/v1/klines` (1w)                | 1 week    | 6 years +      | `src/data/btcusdt_1w_6year.csv`    |    313 | ✅ on disk, 2020-04-06 → 2026-03-30 |
| `/fapi/v1/fundingRate`                | 8 hours   | 6 years +      | `src/data/btcusdt_funding_5year.csv` | 6603 | ✅ **backfilled Phase 1**, 2020-04-01 → 2026-04-10 |
| `/futures/data/openInterestHist` (5m-1d) | up to 1d | **~30 days**   | not on disk                        |    -   | ⚠️ hard limit — only last ~30 days, not usable for 5y walk-forward |
| `/fapi/v1/premiumIndex` (mark price)  | live only | **none**       | not on disk                        |    -   | ⚠️ snapshot only, no history |
| `/fapi/v1/indexPriceKlines`           | kline     | multi-year     | not on disk                        |    -   | 🔜 optional for Phase 2 cross-index basis |
| `/api/v3/klines` (spot BTCUSDT)       | 15m-1d    | multi-year     | not on disk                        |    -   | 🔜 optional Phase 2 perp-vs-spot basis feature |

**Key facts about Binance coverage**
- 15m/1h/4h/1d OHLCV covers our full target window with no gaps.
- Funding rate covers the full target window with 100.0% cadence coverage
  (6,603 / 6,602 expected at 8h interval). 3,925 early records (~2020-04
  through ~2024) return `markPrice=""` — we parse those as `None` and keep
  the funding_rate, which is the field we actually need for PnL.
- **Open interest history is a hard structural gap.** Binance's
  `openInterestHist` REST endpoint only returns ≈30 days back. A 5-year OI
  feature is not buildable from Binance REST alone.
- Spot klines are multi-year but not fetched yet. They would enable
  `basis_perp_vs_spot` on Track A.

### 2.2 Coinglass STANDARD plan — `open-api-v4.coinglass.com`

Coinglass STANDARD plan limits 15m interval history to **~90 days**. This is
a hard constraint from the API key tier, not a workaround. Daily-cadence
endpoints reach back further (years), but the 15m walk-forward cannot rely
on Coinglass data at execution frequency.

| Endpoint                                         | Cadence | 15m history | Daily history | On-disk file                    | Used by      |
|--------------------------------------------------|---------|-------------|---------------|----------------------------------|--------------|
| `/api/futures/funding-rate/history`              | 15m/1h/4h/1d | ~90 days | years | `coinglass_funding_1d.csv`, `coinglass_funding_4h.csv` | Track B (15m), macro research (1d) |
| `/api/futures/funding-rate/ohlc-history`         | 15m/1h/4h/1d | ~90 days | years | not on disk | Track B (OI-weighted funding) |
| `/api/futures/openInterest/ohlc-history`         | 15m/1h/4h/1d | ~90 days | years | `coinglass_oi_4h.csv`, `coinglass_oi_1d.csv` | Track B; also 1d for macro |
| `/api/futures/long-short-ratio/history`          | 15m/1h/4h/1d | ~90 days | years | not on disk | Track B |
| `/api/futures/top-long-short-account-ratio/history` | 15m/1h/4h/1d | ~90 days | years | `coinglass_top_ls_1d.csv` | Track B |
| `/api/futures/liquidation/aggregated-history`    | 15m/1h/4h/1d | ~90 days | years | `coinglass_liquidation_4h.csv` | Track B (F3 reversal strategy core) |
| `/api/futures/taker-buy-sell-volume/history`     | 15m/1h/4h/1d | ~90 days | years | `coinglass_taker_volume_4h.csv` | Track B |
| `/api/futures/pair-markets` (pair_cvd)           | 15m only | **~47 days** | n/a           | not separately on disk | **dropped** per Baseline C verdict |

**Key facts about Coinglass coverage**
- 15m pair-level history stops at ~90 days. `pair_cvd` is even tighter
  (~47 days). Neither can support a 5-year walk-forward.
- 1d-cadence Coinglass data reaches back multiple years and is already on
  disk for basis, CVD, funding, OI, and long/short ratio. This data is not
  useful at 15m execution speed, but it is viable for macro features or
  for daily-bar strategy variants later.
- Track B (90-day overlap) uses Coinglass at its native 15m cadence and is
  the only honest way to include these features in the research.

### 2.3 Strategy C dataset (Baselines A/B/C artefacts)

| File                                         | Rows | Range                          | Use in v2 |
|----------------------------------------------|------|--------------------------------|-----------|
| `src/data/strategy_c_btcusdt_15m.csv`        | 4500 | 2026-02-16 → 2026-04-03 (47 d) | v2 Track B (with Coinglass pair-level) |
| `src/data/strategy_c_btcusdt_15m_nocvd.csv`  | 7967 | 2026-01-11 → 2026-04-03 (83 d) | v2 Track B (without pair_cvd) |

These are the frozen Baseline A/B/C datasets. They remain useful in v2 only
for Track B comparison against the new Binance-only pipeline.

---

## 3. Two-track decomposition driven by the coverage gaps

The coverage table above forces exactly one architectural decision:

> A unified 5-year, 15m, Binance + Coinglass feature matrix **does not exist
> and cannot be built** on STANDARD tier. We have to choose one: either
> 5-year Binance-only, or 90-day Binance+Coinglass.

v2 refuses to choose. Instead it runs both tracks in parallel:

| Track | Window | Sources | Feature families | Strategies | Validation |
|-------|--------|---------|------------------|------------|------------|
| **A** | 2020-04 → 2026-04 (≈6y) | Binance klines 15m/1h/4h/1d + fundingRate | Family A + Family B | F1 literature, F2 continuation, F4 hybrid (reversal-lite without Coinglass liquidations) | Rolling walk-forward 24m/6m |
| **B** | last 90 days | A's sources + Coinglass 15m endpoints | A + B + C | F1 + F2 + F3 reversal + F4 hybrid with full stress features | Single temporal 70/30 split (same as Baseline C), min-trade guardrails |

Track A produces the v2 leaderboard and the final OOS equity curve
(Deliverable #9). Track B answers the "does Coinglass add lift when
available?" question (Deliverable #8).

---

## 4. Hard gaps — explicit list

These are the gaps the user should be aware of. Each is called out so
future phases don't trip over them:

1. **Binance open-interest 5-year history is not available via REST.**
   `openInterestHist` returns only ~30 days. Options to fill it later:
   - Subscribe to a higher Coinglass plan (PRO or above) and resample their
     multi-year 1h OI stream down to 15m via forward-fill.
   - Purchase a third-party archive (Kaiko, Amberdata, Glassnode historical).
   - Accept the gap and drop all OI features from Track A features.
   - **Phase 1 decision:** drop OI from Track A v2 features. Document it.
     Revisit in Phase 3 if a strategy shows promise and OI features plausibly
     help.

2. **Binance mark-vs-last has no history.** `/fapi/v1/premiumIndex` is a
   snapshot endpoint. We cannot reconstruct a historical mark-vs-last
   stream. This is Coinglass-only (and therefore Track B only).

3. **`pair_cvd` from Coinglass stays dropped.** Baseline C already tested
   this: the pair-level CVD stream does not add information over
   `taker_delta_norm_z32` from the taker-buy-sell-volume endpoint.

4. **Funding rate early records carry empty `markPrice`.** 3,925 of 6,603
   records (~2020-04 to ~2024) have `markPrice=""`. This is a real Binance
   API quirk, not a fetch bug. Our parser stores `None` in that case. It
   does not affect the actual funding rate value, which is what the
   backtest and strategy logic consume.

5. **1-week klines stop 2026-03-30.** The weekly file is 6 days short of
   the daily file's right edge (2026-04-05). Not blocking — weekly is an
   optional derived feature only.

6. **Literature benchmarks (Stefaniuk 2025) are published on 1h bars, not
   15m.** We should run F1 on both 1h and 15m to validate the walk-forward
   harness against published results before trusting 15m-native numbers.

---

## 5. Phase 1 deliverable status

| Item                                       | Status |
|--------------------------------------------|--------|
| 5-year OHLCV (15m/1h/4h/1d/1w)             | ✅ already on disk |
| Binance fundingRate 5y                     | ✅ backfilled Phase 1 |
| Binance fundingRate parser (with empty-markPrice handling) | ✅ TDD-covered |
| Bollinger Bands primitive                  | ✅ TDD-covered |
| Stochastic primitive                       | ✅ TDD-covered |
| ATR primitive                              | ✅ TDD-covered |
| StrategyCV2Bar dataclass + loader stub     | ✅ skeleton |
| StrategyCV2Features dataclass + compute stub | ✅ skeleton |
| This report (Deliverable #1)               | ✅ (this file) |
| Feature matrix (Deliverable #2)            | ⏳ next in Phase 1 |

All other deliverables (#3 literature benchmark, #4 walk-forward leaderboard,
#5–#7 best-of-family, #8 Binance vs Coinglass, #9 final recommendation)
belong to Phases 2–5 per `strategy_c_v2_plan.md` section 8.
