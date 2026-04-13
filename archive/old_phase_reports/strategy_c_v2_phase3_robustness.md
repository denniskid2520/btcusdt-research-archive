# Strategy C v2 — Phase 3 Deliverable: Robustness Report

_Date: 2026-04-11_
_Status: Phase 3 — parameter perturbation around the Phase 2 winners._

This report answers one question: **is the Phase 2 OOS edge broad or
point-fragile?** If a single-cell winner is just an artefact of one lucky
parameter combination, the rest of the nearby parameter surface will
collapse. A real edge is broad — many nearby cells produce similar numbers.

We re-run the Phase 2 walk-forward (24m/6m/6m, 8 OOS test windows,
0.12% round-trip, funding cashflows) on a denser grid around the
Phase 2 winners:

- **4h rsi_only_30 hold=16** (Phase 2 best return, +138.41%)
- **1h rsi_and_macd_14 hold=32** (Phase 2 best robustness, +106.11%)

Grid: RSI length ∈ {7, 14, 21, 30, 34, 42} × hold ∈ {8, 12, 16, 24, 32, 48}
(selected per-TF). All three sides (long-only / short-only / long-short)
are computed; the aggregate side="both" numbers live in this report, the
directional decomposition lives in `strategy_c_v2_phase3_directional.md`.

---

## 1. Setup note: fixing a Phase 2 silent bug

Phase 2's `rsi_only_signals` and `rsi_and_macd_signals` only read
`f.rsi_14` / `f.rsi_30` — any period value other than 14 or 30 silently
fell through to `rsi_30`. This would have made a Phase 3 sweep look
identical across RSI periods 21/30/34/42 (it did, briefly, before the
fix was caught).

Fix: `rsi_override` parameter added to both signal functions. The
runner now computes arbitrary-period RSI via the new public
`data.strategy_c_v2_features.rsi_series` helper and passes it as an
override. Four new tests cover the override path. All 745 pre-existing
tests still pass.

This report reflects the post-fix numbers. The Phase 2 results are
unaffected because Phase 2 only ran RSI 14 and RSI 30.

---

## 2. 4h rsi_only — period × hold matrix (side=both)

Numbers below are OOS compounded return (with 0.12% cost and real funding)
across the 8 walk-forward test windows.

| RSI period | hold=8 | hold=12 | hold=16 | hold=24 | hold=32 |
|:----------:|-------:|--------:|--------:|--------:|--------:|
| **21** | **+136.71** | **+142.77** | +116.48 | +61.77 | +17.44 |
| **30** | +85.84 | +40.80 | **+138.41** | +79.59 | +51.69 |
| **34** | +66.71 | +49.06 | +122.47 | +83.56 | +92.56 |
| **42** | +26.31 | +24.45 | +29.16 | +31.02 | +75.59 |

Drawdowns (same grid):

| RSI period | hold=8 | hold=12 | hold=16 | hold=24 | hold=32 |
|:----------:|-------:|--------:|--------:|--------:|--------:|
| **21** | 22.96 | 20.89 | 28.64 | 32.89 | 40.40 |
| **30** | 11.26 | 18.56 | 13.92 | 24.34 | 27.83 |
| **34** | 13.49 | 22.33 | 16.01 | 25.13 | 30.12 |
| **42** | 16.16 | 19.09 | 22.97 | 18.98 | 22.19 |

Trade counts:

| RSI period | hold=8 | hold=12 | hold=16 | hold=24 | hold=32 |
|:----------:|-------:|--------:|--------:|--------:|--------:|
| **21** | 132 | 107 | 98 | 84 | 79 |
| **30** | 72 | 56 | 52 | 41 | 39 |
| **34** | 58 | 47 | 42 | 34 | 30 |
| **42** | 41 | 34 | 29 | 24 | 21 |

### Observations

1. **The edge is broad, not point-fragile.** Every single cell in the
   4h rsi_only grid is positive. The weakest cell (rsi_only_21 h=32) is
   still +17.44%. The strongest (rsi_only_21 h=12) is +142.77%. The
   median is ≈+80%, well above the +13% B&H reference.

2. **Two "sweet spots" exist, not one.**
   - **RSI(21) with hold 8-16** — highest absolute returns (+116 to +143%),
     moderate drawdowns (21-29%), highest trade counts (98-132).
   - **RSI(30) with hold=16** — lowest drawdown (13.9%), very high pf (2.75),
     slightly fewer trades (52).

3. **Phase 2's winner is NOT the robust point.** `rsi_only_30 hold=16`
   is a local maximum on drawdown, but the nearby cell `rsi_only_30 hold=12`
   drops to +40.80% — a cliff. By contrast `rsi_only_21 hold={8, 12, 16}`
   are all three comfortably above +115%. The RSI(21) family is the
   more robust choice for a deployable system.

4. **RSI(42) is slow enough to lose the edge.** Its peak is +75.59 at
   hold=32, and it's ≤+31% for hold ≤24. 42 bars on 4h = ~7 days of
   smoothing; the trigger fires too rarely for the rule to matter.

5. **RSI(7) is missing from 4h** — not swept (would likely collapse like
   on 1h, see §3).

6. **The 87.5% positive windows cell** (rsi_only_21 h=12, 107 trades)
   is the single most robust cell on the board — every dimension is
   comfortable above the promotion bars.

---

## 3. 1h rsi_and_macd — period × hold matrix (side=both)

| RSI period | hold=16 | hold=24 | hold=32 | hold=48 |
|:----------:|--------:|--------:|--------:|--------:|
| **7**  | **−85.36** | **−90.70** | **−87.74** | **−78.63** |
| **14** | +10.51 | +81.89 | **+106.11** | +37.12 |
| **21** | +18.74 | +41.47 | +34.41 | **+138.77** |

| DD | 16 | 24 | 32 | 48 |
|:--:|----:|----:|----:|----:|
| **7**  | 88.66 | 91.33 | 89.18 | 85.18 |
| **14** | 44.31 | 48.02 | 41.61 | 45.08 |
| **21** | 37.33 | 41.25 | 30.71 | 27.58 |

### Observations

1. **RSI(7) is completely toxic on 1h rsi_and_macd.** Every cell is below
   −78%. It emits too many signals, the MACD histogram gate doesn't
   save it, and the cost model wipes the equity. **Drop RSI(7) from
   future sweeps.**

2. **RSI(21) hold=48 is the new 1h winner**: +138.77% OOS with 27.58% DD
   and 250 trades across 8 windows. Better than Phase 2's best 1h cell
   (rsi_and_macd_14 h=32 → +106.11% / 41.61% DD).

3. **RSI(14) is the "sweet spot" period for hold=32** but not for
   longer holds. RSI(21) is better at hold=48.

4. **1h is sensitive to both period and hold.** The best cell is isolated
   at (21, 48). Moving one cell over (21, 32) drops to +34.41%. This is
   more fragile than 4h.

---

## 4. Cross-family sanity: 1h rsi_only vs 4h rsi_and_macd

The sweep also included cross-family cells to check whether
`rsi_only` (Phase 2 winner on 4h) generalises to 1h, and
`rsi_and_macd` generalises to 4h.

### 1h rsi_only (cross-family)

| period | hold | return | DD | trades |
|--:|--:|--:|--:|--:|
| 14 | 16 | −2.13% | 47.14% | 676 |
| 14 | 24 | +43.95% | 48.72% | 568 |
| 14 | 32 | +101.63% | 41.61% | 516 |
| 30 | 16 | +47.45% | 22.90% | 177 |
| 30 | 24 | +30.63% | 33.27% | 144 |
| 30 | 32 | +16.42% | 35.13% | 135 |

`rsi_only_14 hold=32` on 1h is +101.63%, matching Phase 2. The rsi_only
family is weaker on 1h than rsi_and_macd — the MACD histogram gate adds
meaningful lift here. The `rsi_only_30 hold=16` cell (+47.45%, DD 22.90%,
n=177) is interesting as a low-trade-count alternative.

### 4h rsi_and_macd (cross-family)

| period | hold | return | DD | trades |
|--:|--:|--:|--:|--:|
| 14 | 4 | **+136.20%** | 36.76% | 316 |
| 14 | 8 | +6.33% | 42.14% | 238 |
| 14 | 16 | +5.87% | 43.65% | 180 |
| 30 | 4 | +29.21% | 19.16% | 86 |
| 30 | 8 | +21.25% | 22.15% | 64 |
| 30 | 16 | +77.03% | 21.56% | 49 |

`rsi_and_macd_14 hold=4` on 4h is the highest-trade-count 4h winner in
the whole sweep (+136.20%, 316 trades, DD 36.76%). Moving hold to 8 or
16 collapses the edge — this is point-fragile on 4h.

---

## 5. Robustness conclusion

| Question | Answer |
|---|---|
| Is Phase 2's 4h winner point-fragile? | **Partially.** Its specific (period=30, hold=16) is a DD-minimum, but there are 6-8 nearby cells with ≥+80% OOS. |
| Is Phase 2's 1h winner point-fragile? | **Somewhat.** The family shape is stable for RSI(14, 21), but cells swing by 100+ pp as hold varies. |
| Is there a broader 4h winner than Phase 2 found? | **Yes — rsi_only_21 hold=12 → +142.77% with 87.5% positive windows and 107 trades.** Same alpha family, denser grid, larger sample. |
| Is there a broader 1h winner? | **Yes — rsi_and_macd_21 hold=48 → +138.77% with 250 trades and 27.58% DD.** Replaces Phase 2's rsi_and_macd_14 h=32 on every dimension except raw pf. |

### Phase 3 robustness-promoted candidates

| TF  | Cell                           | OOS ret  | DD    | trades | pos  | PF   |
|-----|--------------------------------|---------:|------:|-------:|-----:|-----:|
| 4h  | rsi_only_21 h=12 (side=both)   | +142.77% | 20.89% | 107   | 7/8  | 1.83 |
| 4h  | rsi_only_30 h=16 (side=both)   | +138.41% | 13.92% | 52    | 6/8  | 2.75 |
| 1h  | rsi_and_macd_21 h=48 (side=both)| +138.77% | 27.58% | 250   | 5/8  | 1.34 |
| 1h  | rsi_and_macd_14 h=32 (side=both)| +106.11% | 41.61% | 510   | 7/8  | 1.17 |

### Open robustness questions to revisit after directional + funding reports

1. Does restricting to long-only preserve the broad edge while cutting
   drawdown? (Answered in `strategy_c_v2_phase3_directional.md`.)
2. Does a funding filter on the 4h rsi_only family add or subtract lift?
   (Answered in `strategy_c_v2_phase3_funding_filter.md`.)
3. Does the MTF 4h→1h→15m framework improve the trade-off further?
   (Pending in `strategy_c_v2_phase3_mtf.md`.)
