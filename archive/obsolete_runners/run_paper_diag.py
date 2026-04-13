#!/usr/bin/env python3
"""Paper Trading Diagnostic — shows WHY no signal fired."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from execution.live_engine import LiveConfig, LiveEngine
from data.mtf_bars import MultiTimeframeBars
from strategies.trend_breakout import TrendBreakoutStrategy, _detect_channel, _detect_impulse_state


def main():
    cfg = LiveConfig()
    engine = LiveEngine(state_path=Path("state/paper_state.json"), config=cfg)

    print("Fetching bars...")
    multi = engine.adapter.fetch_multi(
        cfg.symbol, {"4h": cfg.history_bars, "1h": 500, "15m": 500},
    )
    bars = multi.get("4h", [])
    if not bars:
        print("Failed to fetch bars")
        return

    current = bars[-1]
    print(f"\n{'='*60}")
    print(f"DIAGNOSTIC — {current.timestamp} — ${current.close:,.0f}")
    print(f"{'='*60}")

    # 1. Channel detection
    strat = engine.strategy
    scfg = strat.config
    recent = bars[-scfg.structure_lookback:]
    channel, failure = _detect_channel(recent, scfg)

    if channel:
        print(f"\n[CHANNEL DETECTED]")
        print(f"  Type:      {channel.channel_type}")
        print(f"  Direction: {channel.direction}")
        print(f"  Slope:     {channel.slope:.6f}")
        print(f"  R²:        {channel.r_squared:.3f}")
        print(f"  Width:     {channel.width_pct:.2f}%")
        print(f"  Support:   ${channel.support_price:,.0f}")
        print(f"  Resistance:${channel.resistance_price:,.0f}")
        pos_in_channel = (current.close - channel.support_price) / (channel.resistance_price - channel.support_price) if channel.resistance_price != channel.support_price else 0.5
        print(f"  Price pos: {pos_in_channel:.1%} (0%=support, 100%=resistance)")
    else:
        print(f"\n[NO CHANNEL] reason: {failure}")
        # Try secondary lookback
        if scfg.secondary_structure_lookback and len(bars) >= scfg.secondary_structure_lookback:
            recent2 = bars[-scfg.secondary_structure_lookback:]
            channel2, failure2 = _detect_channel(recent2, scfg)
            if channel2:
                print(f"  Secondary lookback found: {channel2.channel_type} {channel2.direction}")
            else:
                print(f"  Secondary also failed: {failure2}")

    # 2. RSI(3)
    closes = [b.close for b in bars[-20:]]
    if len(closes) >= 4:
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas[-3:]]
        losses = [-d if d < 0 else 0 for d in deltas[-3:]]
        avg_gain = sum(gains) / 3
        avg_loss = sum(losses) / 3
        if avg_loss == 0:
            rsi3 = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi3 = 100 - (100 / (1 + rs))
        print(f"\n[RSI(3)] = {rsi3:.1f}")
        if rsi3 < 20:
            print(f"  → Oversold — longs ALLOWED")
        elif rsi3 > 80:
            print(f"  → Overbought — shorts ALLOWED")
        else:
            print(f"  → Neutral — longs blocked (need <20), shorts blocked (need >80)")

    # 3. ADX
    try:
        import ta
        highs = [b.high for b in bars[-30:]]
        lows = [b.low for b in bars[-30:]]
        cls = [b.close for b in bars[-30:]]
        import pandas as pd
        df = pd.DataFrame({"high": highs, "low": lows, "close": cls})
        adx_ind = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=14)
        adx_val = adx_ind.adx().iloc[-1]
        print(f"\n[ADX(14)] = {adx_val:.1f}")
        if adx_val >= 25:
            print(f"  → Trending — breakouts allowed, bounces blocked")
        else:
            print(f"  → Ranging — bounces allowed, breakouts blocked")
    except Exception as e:
        print(f"\n[ADX] Error: {e}")

    # 4. MA200
    if len(bars) >= 200:
        ma200 = sum(b.close for b in bars[-200:]) / 200
        above = current.close > ma200
        print(f"\n[MA200] = ${ma200:,.0f} — price {'above' if above else 'below'}")
        print(f"  → Longs {'allowed' if above else 'blocked'}, Shorts {'blocked' if above else 'allowed'}")

    # 5. Weekly MACD (death cross gate)
    if len(bars) >= 250:
        # Approximate weekly from 4h bars (42 bars = 1 week)
        weekly_closes = []
        for i in range(0, len(bars) - 41, 42):
            weekly_closes.append(bars[i + 41].close)
        if len(weekly_closes) >= 26:
            import pandas as pd
            s = pd.Series(weekly_closes)
            ema12 = s.ewm(span=12).mean()
            ema26 = s.ewm(span=26).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9).mean()
            hist = macd_line - signal_line
            print(f"\n[Weekly MACD]")
            print(f"  MACD line:  {macd_line.iloc[-1]:,.0f}")
            print(f"  Signal:     {signal_line.iloc[-1]:,.0f}")
            print(f"  Histogram:  {hist.iloc[-1]:,.0f}")
            if hist.iloc[-1] <= 0:
                print(f"  → Death cross zone (hist ≤ 0)")

    # 6. Full strategy evaluation
    from adapters.base import Position as Pos
    mtf = MultiTimeframeBars(multi)
    evaluation = strat.evaluate(
        symbol=cfg.symbol, bars=bars, position=Pos(symbol=cfg.symbol),
        mtf_bars=mtf,
    )
    sig = evaluation.signal
    print(f"\n[STRATEGY SIGNAL]")
    print(f"  Action:     {sig.action}")
    print(f"  Reason:     {sig.reason}")
    print(f"  Confidence: {sig.confidence}")

    # Show which rules passed/failed
    if evaluation.rule_evaluations:
        print(f"\n[RULE EVALUATIONS]")
        if isinstance(evaluation.rule_evaluations, dict):
            for name, result in evaluation.rule_evaluations.items():
                status = "PASS" if result.get("passed") else "FAIL"
                reason = result.get("reason", "")
                print(f"  {status:4s} | {name}: {reason}")
        elif isinstance(evaluation.rule_evaluations, list):
            for r in evaluation.rule_evaluations:
                print(f"  {r}")

    print(f"\n{'='*60}")
    s = engine.status()
    print(f"Balance: {s['btc_balance']:.6f} BTC | Position: {s['position']}")
    print(f"Total trades: {s['total_trades']}")


if __name__ == "__main__":
    main()
