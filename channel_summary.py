#!/usr/bin/env python3
"""Final neutral summary — all indicators across all 6 channels."""
import sys
sys.stdout.reconfigure(encoding="utf-8")

print("=" * 100)
print("NEUTRAL SUMMARY — 6 ASCENDING CHANNELS x ALL INDICATORS")
print("=" * 100)

print("""
DATA AVAILABLE:
  C, A, B (2022): OI, Funding, L/S, CVD          (no Liq, no Basis, no Taker)
  D (2025):       OI, Funding, L/S, CVD, Basis    (no Liq, no Taker)
  E (Nov25-Jan26): ALL 7 indicators
  F (Feb-Mar 2026): ALL 7 indicators
""")

# ═══════════════════════════════════════════
print("=" * 100)
print("1. OI CHANGE: Last High -> Breakdown")
print("=" * 100)
print("""
  Channel   OI@High    OI@Break     Change    Pattern
  C         $19.9B     $17.2B       -13.8%    DROP
  A         $16.7B     $13.7B       -17.7%    DROP
  B         $13.7B     $12.9B        -5.8%    DROP
  D         $79.8B     $88.5B       +10.9%    RISE (!)
  E         $66.2B     $60.4B        -8.7%    DROP
  F         $51.3B     $49.7B        -3.1%    DROP

  5/6 DROP, 1/6 RISE (D is outlier: OI rose into breakdown)
  Avg drop (excl D): -9.8%
  Threshold candidates: -5% (5/6), -3% (5/6), any negative (5/6)
""")

print("=" * 100)
print("2. FUNDING: Pattern at Highs vs Breakdown")
print("=" * 100)
print("""
  Channel   Avg@Highs    @Breakdown   Ch.Peak    Brk/Peak   Direction
  C         +0.506%      +0.874%      +1.214%     72%       MIXED
  A         +0.658%      -0.689%      +1.092%    -63%       REVERSED
  B         +0.515%      +0.014%      +0.900%      2%       FADED
  D         +0.517%      +0.374%      +1.809%     21%       FADED
  E         +0.026%      +0.968%      +1.048%     92%       SURGED (!)
  F         -0.456%      +0.183%      +0.679%     27%       FADED

  No universal pattern! 3 faded, 1 reversed, 1 surged, 1 mixed
  Funding alone NOT a reliable breakdown detector
  BUT: |break - avg_high| is large in all cases -> DIVERGENCE exists
""")

print("=" * 100)
print("3. L/S RATIO")
print("=" * 100)
print("""
  Channel   Avg@Highs   @Breakdown   Trend(1H->2H)   >1.0 days%
  C         1.13        0.99         FALLING          93%
  A         0.97        1.07         RISING           88%
  B         1.14        1.18         RISING          100%
  D         1.71        1.60         RISING          100%
  E         2.07        2.20         FALLING         100%
  F         1.30        0.98         FALLING          78%

  Mixed patterns:
  - All channels except A had L/S > 1.0 for majority of time
  - No consistent direction at breakdown
  - Wide range: 0.97 to 2.20 at breakdown
  - F stands out: L/S fell below 1.0 (shorts dominant)
""")

print("=" * 100)
print("4. LIQUIDATION (only E, F have data)")
print("=" * 100)
print("""
  At Highs:  Short liq > Long liq  (shorts getting squeezed)
    E highs: avg LiqRatio 0.54 (shorts liquidated more)
    F highs: avg LiqRatio 0.53 (shorts liquidated more)

  At Lows:   Long liq > Short liq  (longs getting stopped)
    E lows:  avg LiqRatio 1.87 (longs liquidated more)
    F lows:  avg LiqRatio 2.94 (longs liquidated more)

  At Breakdown:
    E: LiqRatio = 12.04x  (MASSIVE long liquidation cascade)
    F: LiqRatio =  4.85x  (strong long liquidation)

  PATTERN: Breakdown = extreme long liquidation (ratio > 1.5x)
  Consistent in both samples. High->Break shift is dramatic.
  Limited to 2 channels (no 2022 liq data).
""")

print("=" * 100)
print("5. CVD (Cumulative Volume Delta)")
print("=" * 100)
print("""
  Channel   CVD@High     CVD@Break     Change
  C         -80.6B       -85.3B        -4.7B
  A         -85.9B       -87.4B        -1.5B
  B         -76.5B       -78.4B        -1.9B
  D         -210.5B      -212.5B       -2.0B
  E         -246.9B      -248.6B       -1.7B
  F         -252.7B      -255.0B       -2.3B

  6/6 DECLINE! CVD drops from high to breakdown in EVERY channel.
  THIS IS THE MOST UNIVERSAL SIGNAL.
  Sellers are accumulating dominance before breakdown.
""")

print("=" * 100)
print("6. TAKER BUY/SELL RATIO (only E, F)")
print("=" * 100)
print("""
  At Highs:  Taker B/S > 1.0 (buyers dominant)
    E highs: avg 1.018
    F highs: avg 1.116

  At Breakdown:  Taker B/S < 1.0 (sellers dominant!)
    E: 0.862
    F: 0.860

  PATTERN: Taker ratio flips from >1 at highs to <1 at breakdown
  Very consistent in both samples (0.86 exactly!)
  Shift: ~15-25% swing from buying to selling pressure
""")

print("=" * 100)
print("7. BASIS (Futures Premium)")
print("=" * 100)
print("""
  Channel   @High    @Break    Direction
  D         0.0454   0.0399    NARROWED (premium shrank)
  E         0.0453   0.0419    NARROWED (premium shrank)
  F         0.0511   0.0649    WIDENED (!!)

  D, E: Basis narrows at breakdown = less bullish conviction
  F: Basis WIDENED = market still pricing in upside? Or short squeeze premium?
  Only 3 samples, no clear universal pattern.
""")

print("=" * 100)
print("8. RSI AT KEY EVENTS")
print("=" * 100)
print("""
  RSI(3) — most sensitive:
  Channel   @Highs(avg)   @Lows(avg)   @Breakdown
  C         77.3          31.4         57.1
  A         46.3          17.2         14.1
  B         72.5          21.4          2.2
  D         46.6          44.8         93.3 (*)
  E         78.7          17.5          6.5
  F         75.5          13.4         18.1

  (*) D breakdown RSI anomaly: Binance close $120K vs user's $99K channel break

  RSI(14) — smoothed:
  Channel   @Highs(avg)   @Lows(avg)   @Breakdown
  C         62.4          33.6         44.8
  A         41.7          31.5         25.6
  B         50.3          34.8         32.9
  D         53.9          47.6         66.4 (*)
  E         52.3          33.9         39.6
  F         50.1          33.0         41.0

  Excluding D outlier:
    Avg RSI(3) at breakdown:  19.6  (deeply oversold)
    Avg RSI(14) at breakdown: 36.8  (moderately oversold)
    Avg RSI(3) at highs:      70.1  (overbought)
    Avg RSI(14) at highs:     51.4  (neutral-high)

  RSI(3) has the widest separation: 70 at highs vs 20 at breaks
""")

print("=" * 100)
print("RELIABILITY RANKING — Which indicators work across ALL channels?")
print("=" * 100)
print("""
  Rank  Indicator               Consistency  Samples  Notes
  ----  ----------------------  -----------  -------  -----
   1    CVD decline             6/6 = 100%   6        Most universal! Always declines high->break
   2    OI decline              5/6 =  83%   6        D is outlier (OI rose)
   3    Taker B/S < 1.0         2/2 = 100%   2*       Perfect but only 2 samples
   4    Long Liq dominance      2/2 = 100%   2*       Perfect but only 2 samples
   5    RSI(3) oversold (<30)   4/5 =  80%   5**      C exception (57), D excluded
   6    L/S > 1.0 at highs     5/6 =  83%   6        F exception (L/S declining)
   7    Funding fade            3/6 =  50%   6        No universal pattern!
   8    Basis narrowing         2/3 =  67%   3        F widened

  * Only E, F have liquidation + taker data
  ** D excluded due to price mismatch

  BEST COMBINATION for detection:
    CVD declining + OI dropping + Taker < 1 + RSI(3) < 30
    = Captures the common elements across all channel types
""")

print()
print("=" * 100)
print("CURRENT SITUATION — Channel F Retest (4/6, $69,600)")
print("=" * 100)
print("""
  Indicator         Value         Signal
  ─────────         ─────         ──────
  RSI(3)            50.5          Neutral (not oversold, not overbought)
  RSI(7)            44.0          Neutral
  RSI(14)           45.0          Neutral
  L/S               0.87          Shorts dominant
  Funding           -0.005%       Neutral
  OI                $46.7B        Declining (-6% from break)
  Taker B/S         ~1.0          Neutral
  Liq activity      Very low      No cascade

  Neither strongly bullish nor bearish.
  The retest is at a 'dead zone' — no extreme readings in any indicator.
  RSI at mid-range suggests the market could go either way.
""")
