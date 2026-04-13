#!/usr/bin/env python3
"""Channel swing strategy design — based on 6-channel indicator data."""
import sys
sys.stdout.reconfigure(encoding="utf-8")

print("""
================================================================================
CHANNEL SWING STRATEGY — High SHORT -> Low LONG -> Repeat
================================================================================

Your question:
  "高點要在達到一定的條件才能做空
   那要怎麼樣才能延續利潤等到低點的條件都達到才能止盈然後接續做多"

= When HIGH conditions met -> SHORT
  Hold short until LOW conditions met -> Take profit + flip LONG
  Hold long until HIGH conditions met -> Take profit + flip SHORT
  Repeat until channel breaks

================================================================================
DATA-DRIVEN CONDITIONS (from 6 channels, all events)
================================================================================

---- SHORT ENTRY (at channel HIGH) ----

From ALL HIGHS data:
  RSI(3):  avg=67.1  range=22.8~97.6  (14/20 > 50)
  RSI(7):  avg=59.9  range=34.3~83.9  (17/20 > 45)
  RSI(14): avg=53.0  range=32.6~70.0  (15/20 > 45)
  Taker B/S: avg=1.05 (2 ch)  -> buyers slightly dominant
  Liq: Short liq > Long liq (LiqR < 1.0 in 5/7 data points)
  OI: Rising into highs (avg +8.6% from prev event)

  PROPOSED SHORT CONDITIONS:
    [MUST] RSI(3) > 65   (hit rate: 12/20 = 60%)
    [MUST] RSI(7) > 55   (hit rate: 12/20 = 60%)
    [HELP] Taker B/S > 1.0  (buyers exhausting)
    [HELP] Short Liq > Long Liq  (shorts being squeezed = top signal)
    [HELP] OI rising into this high

  COMBINED: RSI(3) > 65 AND RSI(7) > 55
    C: 2/10 HIGH hit, 3/28 HIGH hit, 3/9 MID -> would capture 2 of 3 highs
    B: 7/8 HIGH (90,66), 7/20 HIGH (82,73), 8/10 HIGH (69,62) -> 3 of 4
    E: 12/3 (73,60), 12/9 (77,59), 1/14 (94,82) -> 3 of 4
    F: 3/4 (85,69), 3/16 (96,76) -> 2 of 3
    TOTAL: ~13/20 highs captured (65%)

  TIGHTER: RSI(3) > 70 AND RSI(7) > 58
    Fewer false signals, captures peak highs better
    C: 3/2 (76,67) YES, 3/28 (97,83) YES -> 2/3
    B: 7/8 (90,66) YES, 7/20 (82,73) YES, 8/10 (69,62) NO -> 2/4
    E: 12/9 (77,59) YES, 1/14 (94,82) YES -> 2/4
    F: 3/4 (85,69) YES, 3/16 (96,76) YES -> 2/3
    TOTAL: ~10/20 (50%) but fewer false triggers


---- LONG ENTRY / SHORT EXIT (at channel LOW) ----

From ALL LOWS data:
  RSI(3):  avg=23.6  range=3.8~65.1  (14/20 < 30)
  RSI(7):  avg=31.2  range=8.9~52.6  (14/20 < 40)
  RSI(14): avg=35.7  range=15.8~50.4 (12/20 < 42)
  Taker B/S: avg=0.97 (6 pts) -> sellers slightly dominant
  Liq: Long liq > Short liq (LiqR > 1.0 in 7/8 data points)
  OI: Dropping into lows (avg -5.8% from prev event)

  PROPOSED LONG CONDITIONS:
    [MUST] RSI(3) < 25   (hit rate: 11/20 = 55%)
    [MUST] RSI(7) < 35   (hit rate: 10/20 = 50%)
    [HELP] Taker B/S < 1.0  (sellers exhausting)
    [HELP] Long Liq > Short Liq  (longs being washed = bottom signal)
    [HELP] OI dropping (weak hands flushed)

  COMBINED: RSI(3) < 25 AND RSI(7) < 35
    C: 1/24 (35,25) YES, 4/11 (8,20) YES -> 2/3
    A: 5/5 (29,35) borderline, 5/9 (4,15) YES -> 1~2/2
    B: 6/18 (5,11) YES, 6/30 (15,29) YES, 7/26 (15,39) NO -> 2/4
    E: 11/21 (5,14) YES, 12/1 (13,30) YES, 12/18 (20,30) YES -> 3/4
    F: 2/5 (3,8) YES, 2/24 (9,25) YES, 3/8 (24,40) NO, 3/22 (15,35) YES -> 3/4
    TOTAL: ~13/20 (65%)


================================================================================
THE PROBLEM: How to HOLD between HIGH and LOW?
================================================================================

The key challenge is NOT entry — it's HOLDING the position while price
oscillates within the channel.

Three approaches:

  APPROACH 1: TRAILING STOP (current system)
    Short entry at HIGH -> trail with ATR stop
    Problem: ATR stop may trigger mid-channel on normal volatility
    In channel B: ATR(14) ~ $1000-1500, 3.5x ATR ~ $3500-5000
    Channel width: ~$5000 -> stop too tight!

  APPROACH 2: INDICATOR-BASED EXIT (your question)
    Short entry at HIGH -> hold until LOW RSI conditions met
    Exit = RSI(3) < 25 AND RSI(7) < 35
    Advantage: exits exactly at channel low
    Risk: what if channel breaks? No safety net

  APPROACH 3: HYBRID (recommended)
    Short entry at HIGH -> hold with WIDE structural stop
    Primary exit: LOW indicator conditions met -> take profit + flip
    Safety exit: price breaks above channel high + buffer -> cut loss
    Time exit: if no LOW signal within N bars -> reduce position

================================================================================
APPROACH 3: HYBRID STRATEGY DETAIL
================================================================================

STATE MACHINE:
  [FLAT] -> detect channel -> [IN_CHANNEL]
  [IN_CHANNEL] -> HIGH conditions -> [SHORT]
  [SHORT] -> LOW conditions -> close short + [LONG]
  [LONG] -> HIGH conditions -> close long + [SHORT]
  [SHORT/LONG] -> channel break -> [FLAT] (emergency exit)

---- PHASE 1: Channel Detection ----
  Identify ascending channel structure (existing system)
  OR: detect 2+ swing highs + 2+ swing lows forming parallel trend

---- PHASE 2: HIGH -> SHORT ----
  Entry conditions (all must be true):
    1. Price near channel resistance (within 3% of upper trendline)
    2. RSI(3) > 65
    3. RSI(7) > 55
  Enhancement (need more data):
    4. Taker B/S > 1.0  (buyers dominant at top)
    5. Short liquidation > Long liquidation (shorts squeezed)

  Stop loss:
    Channel high + 2% buffer (structural)
    OR: ATR(14) * 5 above entry (wide enough for channel)

---- PHASE 3: HOLD SHORT -> Wait for LOW ----
  Exit conditions (take profit + flip to long):
    1. RSI(3) < 25
    2. RSI(7) < 35
  Enhancement:
    3. Taker B/S < 1.0 (sellers exhausting)
    4. Long liquidation spike (longs washed out)

  Safety exits:
    - Price closes above channel resistance + 2%: CUT (channel expanding)
    - 30 bars (4h) without LOW signal: reduce 50%
    - CVD rising strongly: wrong side, cut

---- PHASE 4: LOW -> LONG ----
  Same logic reversed

---- PHASE 5: Channel Breakdown Detection ----
  When in LONG and these fire, CLOSE + go SHORT (or FLAT):
    - CVD declining (6/6 universal)
    - OI dropping > 5% from recent high (5/6)
    - RSI(3) < 20 on breakdown candle (4/5)
    - Taker B/S < 0.90 (2/2)

================================================================================
EXPECTED PERFORMANCE (back-of-envelope)
================================================================================

Channel B example (Jun-Aug 2022):
  Channel: $17570 to $24900, width ~$6000
  6 swing legs = 3 long + 3 short
  Avg swing: ~$4000 (capture 70% of $6000 width)
  Per swing PnL: ~$4000/$22000 = ~18% x 3 leverage = ~54% per swing
  6 swings x 15% captured (after fees/slippage) = ~90% in 2 months

Channel E example (Nov25-Jan26):
  Channel: $80600 to $97879, width ~$17000
  ~5 swing legs
  Per swing: ~$12000/$90000 = ~13% x 3 = ~39%
  5 swings x 10% captured = ~50% in 2 months

vs Current (breakout only):
  1 trade per channel, catch the breakdown: ~10-20% per trade
  But higher win rate, fewer entries

TRADE-OFF:
  Swing: more trades, more profit potential, higher execution risk
  Breakout: fewer trades, more selective, lower execution risk

================================================================================
NEXT STEP
================================================================================

  Option A: Backtest this swing strategy on all 6 channels
            - Need to verify RSI conditions hit rate precisely
            - Need to measure actual vs theoretical PnL
            - Need to test safety exit effectiveness

  Option B: Add swing logic as OVERLAY to existing channel strategy
            - Existing: wait for breakout -> trade
            - New: while channel active, swing trade within it
            - On breakdown: existing strategy takes over

  Option C: Keep them separate
            - Strategy 1: Channel breakout (current, proven)
            - Strategy 2: Channel swing (new, needs validation)
            - Run with separate capital
""")
