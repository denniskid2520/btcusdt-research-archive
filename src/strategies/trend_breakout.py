from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any

from adapters.base import MarketBar, Position
from strategies.base import Strategy, StrategySignal


RULE_NAMES: tuple[str, ...] = (
    "ascending_channel_support_bounce",
    "ascending_channel_breakout",
    "descending_channel_rejection",
    "descending_channel_breakdown",
    "rising_channel_breakdown_retest_short",
    "rising_channel_breakdown_continuation_short",
    "descending_channel_support_bounce",
    "ascending_channel_resistance_rejection",
    "descending_channel_breakout_long",
    "ascending_channel_breakdown_short",
)


@dataclass(frozen=True)
class TrendBreakoutConfig:
    """Channel breakout strategy configuration.

    Validated filters (backtest-proven):
        - rsi_filter + adx_filter(smart): +32.7%, 50% WR, 19.3% DD
        - Channel direction override: 25% -> 62.5% direction accuracy

    Optional/experimental filters (disabled by default, 0 overhead):
        - ma_regime_filter: reduces DD but also reduces profit
        - crowded_long/short_threshold: needs real OI data (Coinglass)
        - use_parent_boundary_targets: tested, hurts return (-13%)
        - use_narrative_regime: legacy, system works better without it
    """

    # ── Channel detection ─────────────────────────────────────────
    impulse_lookback: int = 12
    structure_lookback: int = 24
    pivot_window: int = 2
    min_pivot_highs: int = 2
    min_pivot_lows: int = 2
    impulse_threshold_pct: float = 0.04
    impulse_atr_expansion_min: float | None = None
    impulse_volume_expansion_min: float | None = None
    min_channel_width_abs: float = 0.0
    min_channel_width_pct: float | None = None
    max_slope_divergence_ratio: float = 0.75
    min_r_squared: float = 0.0
    secondary_structure_lookback: int | None = None

    # ── Entry / exit / stop ───────────────────────────────────────
    entry_buffer_pct: float = 0.15
    continuation_buffer_pct: float = 0.2
    stop_buffer_pct: float = 0.08
    min_stop_atr_multiplier: float = 0.0
    trailing_stop_atr: float = 0.0
    time_stop_bars: int | None = None
    max_atr_price_ratio: float = 0.0
    atr_lookback: int = 14

    # ── Rule toggles ─────────────────────────────────────────────
    allow_longs: bool = True
    allow_shorts: bool = True
    enable_rising_channel_breakdown_retest_short: bool = True
    enable_rising_channel_breakdown_continuation_short: bool = True
    enable_descending_channel_support_bounce: bool = True
    enable_ascending_channel_resistance_rejection: bool = True
    enable_descending_channel_breakout_long: bool = True
    enable_ascending_channel_breakdown_short: bool = True

    # ── Parent context (multi-scale detection) ────────────────────
    parent_structure_lookback: int = 90
    parent_pivot_window: int = 2
    parent_min_pivot_highs: int = 2
    parent_min_pivot_lows: int = 2
    parent_timeframe_factor: int = 6
    parent_boundary_zone_pct: float = 0.2
    require_parent_confirmation: bool = True
    shock_reclaim_window_bars: int = 2
    shock_cooldown_bars: int = 8
    breakdown_confirm_bars: int = 2

    # ── Validated filters (recommended) ───────────────────────────
    rsi_filter: bool = False  # RSI(3) oversold/overbought confirmation
    rsi_period: int = 3
    rsi_oversold: float = 20.0
    rsi_overbought: float = 80.0
    adx_filter: bool = False  # ADX trend strength gating
    adx_period: int = 14
    adx_threshold: float = 25.0
    adx_mode: str = "simple"  # "simple" or "smart" (bounce/breakout aware)

    # ── Optional filters (disabled by default) ────────────────────
    ma_regime_filter: bool = False  # +MA200: DD 19.3%->9.6%, WR 50%->61.5%
    ma_regime_period: int = 200
    crowded_long_threshold: float = 0.0  # OI filter, needs futures_provider
    crowded_short_threshold: float = 0.0
    oi_divergence_lookback: int = 0  # 0=disabled. Bars to check OI-price alignment.
    oi_divergence_threshold: float = -0.03  # OI change% below this = "falling" (e.g., -3%)
    use_parent_boundary_targets: bool = False  # tested: hurts return (-13%)
    use_narrative_regime: bool = False  # legacy: system works without it


@dataclass(frozen=True)
class RuleEvaluation:
    rule_name: str
    eligible: bool
    triggered: bool
    first_failed_condition: str | None
    context: dict[str, Any] | None = None


@dataclass(frozen=True)
class StrategyEvaluation:
    signal: StrategySignal
    rule_evaluations: list[RuleEvaluation]
    parent_context: dict[str, float | str | None] | None = None


@dataclass(frozen=True)
class _Pivot:
    index: int
    price: float
    kind: str


@dataclass(frozen=True)
class _Channel:
    kind: str
    support_slope: float
    support_intercept: float
    resistance_slope: float
    resistance_intercept: float
    width: float

    def support_at(self, index: int) -> float:
        return (self.support_slope * index) + self.support_intercept

    def resistance_at(self, index: int) -> float:
        return (self.resistance_slope * index) + self.resistance_intercept


@dataclass(frozen=True)
class _ParentEvent:
    event_type: str
    bars_since_event: int | None = None


class TrendBreakoutStrategy(Strategy):
    """Parameterized channel trend breakout strategy with evaluation funnel."""

    def __init__(self, config: TrendBreakoutConfig | None = None) -> None:
        self.config = config or TrendBreakoutConfig()

    def generate_signal(self, symbol: str, bars: list[MarketBar], position: Position) -> StrategySignal:
        return self.evaluate(symbol=symbol, bars=bars, position=position).signal

    def evaluate(
        self,
        symbol: str,
        bars: list[MarketBar],
        position: Position,
        futures_provider: Any | None = None,
    ) -> StrategyEvaluation:
        required_bars = max(self.config.impulse_lookback, self.config.structure_lookback)
        if len(bars) < required_bars:
            return StrategyEvaluation(
                signal=StrategySignal(action="hold", confidence=0.0, reason="insufficient_bars"),
                rule_evaluations=_all_failed("insufficient_bars"),
                parent_context=None,
            )

        if position.is_open:
            return StrategyEvaluation(
                signal=self._manage_open_position(position, bars[-1].close),
                rule_evaluations=_all_failed("position_open"),
                parent_context=None,
            )

        # Narrative regime: look up once and reuse below
        narrative_parent_context = None
        if self.config.use_narrative_regime:
            regime = _lookup_narrative_regime_for_bar(bars[-1])
            if regime is not None:
                narrative_parent_context = regime.parent_context

        recent = bars[-self.config.structure_lookback :]
        channel, channel_failure = _detect_channel(recent, self.config)

        # Dual lookback: if primary fails, try wider window
        if channel is None and self.config.secondary_structure_lookback is not None:
            sec_lookback = self.config.secondary_structure_lookback
            if len(bars) >= sec_lookback:
                recent = bars[-sec_lookback:]
                channel, channel_failure = _detect_channel(recent, self.config)

        generic_impulse = _detect_impulse_state(
            recent[-self.config.impulse_lookback :],
            self.config.impulse_threshold_pct,
            self.config.impulse_atr_expansion_min,
            self.config.impulse_volume_expansion_min,
        )
        front_impulse = _detect_impulse_state(
            recent[: self.config.impulse_lookback],
            self.config.impulse_threshold_pct,
            self.config.impulse_atr_expansion_min,
            self.config.impulse_volume_expansion_min,
        )

        parent_context = _build_parent_context(bars, self.config)

        # Override parent context with narrative regime if enabled
        if narrative_parent_context is not None:
            parent_context = narrative_parent_context

        # Volatility gate: skip when market is too chaotic for structural trades
        if self.config.max_atr_price_ratio > 0:
            atr = _compute_atr(recent, self.config.atr_lookback)
            if atr > 0 and recent[-1].close > 0:
                ratio = atr / recent[-1].close
                if ratio > self.config.max_atr_price_ratio:
                    return StrategyEvaluation(
                        signal=StrategySignal(action="hold", confidence=0.0, reason="volatility_too_high"),
                        rule_evaluations=_all_failed("volatility_too_high"),
                        parent_context=parent_context,
                    )

        context = _build_context(recent, channel, self.config, parent_context)
        rule_evals: list[RuleEvaluation] = []
        winning_signal = StrategySignal(action="hold", confidence=0.0, reason="no_trade_setup")

        rule_checks = (
            self._check_ascending_channel_support_bounce(context, generic_impulse, channel_failure),
            self._check_ascending_channel_breakout(context, generic_impulse, channel_failure),
            self._check_descending_channel_rejection(context, generic_impulse, channel_failure),
            self._check_descending_channel_breakdown(context, generic_impulse, channel_failure),
            self._check_rising_channel_breakdown_retest_short(context, front_impulse, channel_failure),
            self._check_rising_channel_breakdown_continuation_short(context, front_impulse, channel_failure),
            self._check_descending_channel_support_bounce(context, channel_failure),
            self._check_ascending_channel_resistance_rejection(context, channel_failure),
            self._check_descending_channel_breakout_long(context, generic_impulse, channel_failure),
            self._check_ascending_channel_breakdown_short(context, generic_impulse, channel_failure),
        )

        for rule_eval, candidate_signal in rule_checks:
            rule_evals.append(rule_eval)
            if candidate_signal is not None and winning_signal.action == "hold":
                winning_signal = candidate_signal

        # MA regime filter: block longs below SMA, block shorts above SMA
        if winning_signal.action != "hold" and self.config.ma_regime_filter:
            sma_val = _compute_sma(bars, self.config.ma_regime_period)
            if sma_val is not None:
                current_close = bars[-1].close
                if winning_signal.action in ("buy",) and current_close < sma_val:
                    winning_signal = StrategySignal(action="hold", confidence=0.0, reason="ma_regime_blocked_long")
                elif winning_signal.action in ("short",) and current_close > sma_val:
                    winning_signal = StrategySignal(action="hold", confidence=0.0, reason="ma_regime_blocked_short")

        # OI / crowded-trade filter: block longs when crowd is too long, shorts when too short
        if winning_signal.action != "hold" and futures_provider is not None:
            snapshot = futures_provider.get_snapshot(symbol, bars[-1].timestamp)
            if snapshot is not None:
                if winning_signal.action == "buy" and self.config.crowded_long_threshold > 0:
                    if snapshot.long_pct >= self.config.crowded_long_threshold * 100:
                        winning_signal = StrategySignal(
                            action="hold", confidence=0.0, reason="oi_crowded_long_blocked",
                        )
                elif winning_signal.action == "short" and self.config.crowded_short_threshold > 0:
                    if snapshot.short_pct >= self.config.crowded_short_threshold * 100:
                        winning_signal = StrategySignal(
                            action="hold", confidence=0.0, reason="oi_crowded_short_blocked",
                        )

        # OI-price divergence filter: rising price + falling OI = weak trend
        if (
            winning_signal.action != "hold"
            and futures_provider is not None
            and self.config.oi_divergence_lookback > 0
            and len(bars) > self.config.oi_divergence_lookback
        ):
            lookback = self.config.oi_divergence_lookback
            current_snap = futures_provider.get_snapshot(symbol, bars[-1].timestamp)
            past_snap = futures_provider.get_snapshot(symbol, bars[-1 - lookback].timestamp)
            if (
                current_snap is not None
                and past_snap is not None
                and current_snap.oi_close is not None
                and past_snap.oi_close is not None
                and past_snap.oi_close > 0
            ):
                oi_change_pct = (current_snap.oi_close - past_snap.oi_close) / past_snap.oi_close
                price_change = bars[-1].close - bars[-1 - lookback].close
                if (
                    winning_signal.action == "buy"
                    and price_change > 0
                    and oi_change_pct < self.config.oi_divergence_threshold
                ):
                    winning_signal = StrategySignal(
                        action="hold", confidence=0.0, reason="oi_price_divergence_blocked",
                    )
                elif (
                    winning_signal.action == "short"
                    and price_change < 0
                    and oi_change_pct < self.config.oi_divergence_threshold
                ):
                    winning_signal = StrategySignal(
                        action="hold", confidence=0.0, reason="oi_price_divergence_blocked",
                    )

        # ADX trend strength filter
        if winning_signal.action != "hold" and self.config.adx_filter:
            adx_val = _compute_adx(bars, self.config.adx_period)
            if adx_val is not None:
                if self.config.adx_mode == "smart":
                    # Smart mode: low ADX → allow bounces block breakouts,
                    #              high ADX → allow breakouts block bounces
                    is_bounce = winning_signal.reason in _BOUNCE_RULES
                    is_breakout = winning_signal.reason in _BREAKOUT_RULES
                    if adx_val >= self.config.adx_threshold and is_bounce:
                        winning_signal = StrategySignal(
                            action="hold", confidence=0.0, reason="adx_strong_trend_bounce_blocked",
                        )
                    elif adx_val < self.config.adx_threshold and is_breakout:
                        winning_signal = StrategySignal(
                            action="hold", confidence=0.0, reason="adx_weak_trend_breakout_blocked",
                        )
                else:
                    # Simple mode (original): block all when ADX < threshold
                    if adx_val < self.config.adx_threshold:
                        winning_signal = StrategySignal(
                            action="hold", confidence=0.0, reason="adx_weak_trend_blocked",
                        )

        # RSI confirmation filter: bounce needs oversold/overbought confirmation
        if winning_signal.action != "hold" and self.config.rsi_filter:
            rsi_val = _compute_rsi(bars, self.config.rsi_period)
            if rsi_val is not None:
                if winning_signal.action == "buy" and rsi_val > self.config.rsi_oversold:
                    winning_signal = StrategySignal(
                        action="hold", confidence=0.0, reason="rsi_not_oversold_blocked",
                    )
                elif winning_signal.action == "short" and rsi_val < self.config.rsi_overbought:
                    winning_signal = StrategySignal(
                        action="hold", confidence=0.0, reason="rsi_not_overbought_blocked",
                    )

        if winning_signal.action != "hold" and self.config.use_parent_boundary_targets:
            winning_signal = _extend_target_to_parent_boundary(winning_signal, parent_context)

        if winning_signal.action != "hold" and self.config.min_stop_atr_multiplier > 0:
            winning_signal = _apply_atr_stop_floor(
                winning_signal, recent, self.config.atr_lookback, self.config.min_stop_atr_multiplier,
            )

        if winning_signal.action != "hold" and self.config.trailing_stop_atr > 0:
            meta = dict(winning_signal.metadata) if winning_signal.metadata else {}
            meta["trailing_stop_atr"] = self.config.trailing_stop_atr
            winning_signal = StrategySignal(
                action=winning_signal.action,
                confidence=winning_signal.confidence,
                reason=winning_signal.reason,
                stop_price=winning_signal.stop_price,
                target_price=winning_signal.target_price,
                metadata=meta,
            )

        return StrategyEvaluation(signal=winning_signal, rule_evaluations=rule_evals, parent_context=parent_context)

    def _check_ascending_channel_support_bounce(
        self,
        context: dict[str, float | str | None],
        generic_impulse: str,
        channel_failure: str,
    ) -> tuple[RuleEvaluation, StrategySignal | None]:
        rule_name = "ascending_channel_support_bounce"
        if not self.config.allow_longs:
            return _failed(rule_name, "rule_disabled"), None
        if channel_failure != "ok":
            return _failed(rule_name, channel_failure), None
        if context["channel_kind"] != "ascending_channel":
            return _failed(rule_name, "channel_kind_mismatch"), None
        if generic_impulse != "bullish":
            return _failed(rule_name, "impulse_mismatch"), None
        parent_gate_reason = _parent_long_gate_reason(context, self.config.require_parent_confirmation)
        if parent_gate_reason is not None:
            return _failed(rule_name, parent_gate_reason, context), None
        if context["close"] > context["support"] + context["entry_buffer"]:
            return _failed(rule_name, "price_out_of_entry_zone"), None
        signal = StrategySignal(
            action="buy",
            confidence=0.75,
            reason=rule_name,
            stop_price=context["support"] - context["stop_buffer"],
            target_price=context["resistance"],
            metadata={**context, "second_target_price": context["resistance"] + context["width"]},
        )
        return _triggered(rule_name), signal

    def _check_ascending_channel_breakout(
        self,
        context: dict[str, float | str | None],
        generic_impulse: str,
        channel_failure: str,
    ) -> tuple[RuleEvaluation, StrategySignal | None]:
        rule_name = "ascending_channel_breakout"
        if not self.config.allow_longs:
            return _failed(rule_name, "rule_disabled"), None
        if channel_failure != "ok":
            return _failed(rule_name, channel_failure), None
        if context["channel_kind"] != "ascending_channel":
            return _failed(rule_name, "channel_kind_mismatch"), None
        if generic_impulse != "bullish":
            return _failed(rule_name, "impulse_mismatch"), None
        parent_gate_reason = _parent_long_gate_reason(context, self.config.require_parent_confirmation)
        if parent_gate_reason is not None:
            return _failed(rule_name, parent_gate_reason, context), None
        if context["close"] <= context["resistance"]:
            return _failed(rule_name, "price_out_of_entry_zone"), None
        signal = StrategySignal(
            action="buy",
            confidence=0.85,
            reason=rule_name,
            stop_price=context["resistance"] - context["stop_buffer"],
            target_price=context["resistance"] + context["width"],
            metadata={**context, "second_target_price": context["close"] + context["width"]},
        )
        return _triggered(rule_name), signal

    def _check_descending_channel_rejection(
        self,
        context: dict[str, float | str | None],
        generic_impulse: str,
        channel_failure: str,
    ) -> tuple[RuleEvaluation, StrategySignal | None]:
        rule_name = "descending_channel_rejection"
        if not self.config.allow_shorts:
            return _failed(rule_name, "rule_disabled"), None
        if channel_failure != "ok":
            return _failed(rule_name, channel_failure), None
        if context["channel_kind"] != "descending_channel":
            return _failed(rule_name, "channel_kind_mismatch"), None
        if generic_impulse != "bearish":
            return _failed(rule_name, "impulse_mismatch"), None
        parent_gate_reason = _parent_short_gate_reason(context, self.config.require_parent_confirmation)
        if parent_gate_reason is not None:
            return _failed(rule_name, parent_gate_reason, context), None
        if context["close"] < context["resistance"] - context["entry_buffer"]:
            return _failed(rule_name, "price_out_of_entry_zone"), None
        signal = StrategySignal(
            action="short",
            confidence=0.75,
            reason=rule_name,
            stop_price=context["resistance"] + context["stop_buffer"],
            target_price=context["support"],
            metadata={**context, "second_target_price": context["support"] - context["width"]},
        )
        return _triggered(rule_name), signal

    def _check_descending_channel_breakdown(
        self,
        context: dict[str, float | str | None],
        generic_impulse: str,
        channel_failure: str,
    ) -> tuple[RuleEvaluation, StrategySignal | None]:
        rule_name = "descending_channel_breakdown"
        if not self.config.allow_shorts:
            return _failed(rule_name, "rule_disabled"), None
        if channel_failure != "ok":
            return _failed(rule_name, channel_failure), None
        if context["channel_kind"] != "descending_channel":
            return _failed(rule_name, "channel_kind_mismatch"), None
        if generic_impulse != "bearish":
            return _failed(rule_name, "impulse_mismatch"), None
        parent_gate_reason = _parent_short_gate_reason(context, self.config.require_parent_confirmation)
        if parent_gate_reason is not None:
            return _failed(rule_name, parent_gate_reason, context), None
        if context["close"] >= context["support"]:
            return _failed(rule_name, "price_out_of_entry_zone"), None
        signal = StrategySignal(
            action="short",
            confidence=0.85,
            reason=rule_name,
            stop_price=context["support"] + context["stop_buffer"],
            target_price=context["support"] - context["width"],
            metadata={**context, "second_target_price": context["close"] - context["width"]},
        )
        return _triggered(rule_name), signal

    def _check_rising_channel_breakdown_retest_short(
        self,
        context: dict[str, float | str | None],
        front_impulse: str,
        channel_failure: str,
    ) -> tuple[RuleEvaluation, StrategySignal | None]:
        rule_name = "rising_channel_breakdown_retest_short"
        if not self.config.allow_shorts or not self.config.enable_rising_channel_breakdown_retest_short:
            return _failed(rule_name, "rule_disabled"), None
        if channel_failure != "ok":
            return _failed(rule_name, channel_failure), None
        if context["channel_kind"] != "ascending_channel":
            return _failed(rule_name, "channel_kind_mismatch"), None
        if front_impulse != "bearish":
            return _failed(rule_name, "impulse_mismatch"), None
        parent_gate_reason = _parent_short_gate_reason(context, self.config.require_parent_confirmation)
        if parent_gate_reason is not None:
            return _failed(rule_name, parent_gate_reason, context), None
        if not (context["support"] <= context["close"] <= context["support"] + context["entry_buffer"]):
            return _failed(rule_name, "price_out_of_entry_zone"), None

        # Single frozen structural invalidation formula used everywhere.
        retest_invalidation = max(context["support"], context["high"])
        signal = StrategySignal(
            action="short",
            confidence=0.8,
            reason=rule_name,
            stop_price=retest_invalidation + context["stop_buffer"],
            target_price=context["support"] - context["width"],
            metadata={**context, "second_target_price": context["close"] - context["width"]},
        )
        return _triggered(rule_name), signal

    def _check_rising_channel_breakdown_continuation_short(
        self,
        context: dict[str, float | str | None],
        front_impulse: str,
        channel_failure: str,
    ) -> tuple[RuleEvaluation, StrategySignal | None]:
        rule_name = "rising_channel_breakdown_continuation_short"
        if not self.config.allow_shorts or not self.config.enable_rising_channel_breakdown_continuation_short:
            return _failed(rule_name, "rule_disabled"), None
        if channel_failure != "ok":
            return _failed(rule_name, channel_failure), None
        if context["channel_kind"] != "ascending_channel":
            return _failed(rule_name, "channel_kind_mismatch"), None
        if front_impulse != "bearish":
            return _failed(rule_name, "impulse_mismatch"), None
        parent_gate_reason = _parent_short_gate_reason(context, self.config.require_parent_confirmation)
        if parent_gate_reason is not None:
            return _failed(rule_name, parent_gate_reason, context), None
        if not (
            context["close"] < context["support"]
            and context["close"] >= context["support"] - context["continuation_buffer"]
        ):
            return _failed(rule_name, "price_out_of_entry_zone"), None
        signal = StrategySignal(
            action="short",
            confidence=0.72,
            reason=rule_name,
            stop_price=context["support"] + context["stop_buffer"],
            target_price=context["support"] - context["width"],
            metadata={**context, "second_target_price": context["close"] - context["width"]},
        )
        return _triggered(rule_name), signal

    def _check_descending_channel_support_bounce(
        self,
        context: dict[str, float | str | None],
        channel_failure: str,
    ) -> tuple[RuleEvaluation, StrategySignal | None]:
        rule_name = "descending_channel_support_bounce"
        if not self.config.allow_longs or not self.config.enable_descending_channel_support_bounce:
            return _failed(rule_name, "rule_disabled"), None
        if channel_failure != "ok":
            return _failed(rule_name, channel_failure), None
        if context["channel_kind"] != "descending_channel":
            return _failed(rule_name, "channel_kind_mismatch"), None
        # Oscillation trade: no impulse required — channel structure + position is the signal
        gate_reason = _oscillation_long_gate_reason(context, self.config.require_parent_confirmation)
        if gate_reason is not None:
            return _failed(rule_name, gate_reason, context), None
        if context["close"] > context["support"] + context["entry_buffer"]:
            return _failed(rule_name, "price_out_of_entry_zone"), None
        signal = StrategySignal(
            action="buy",
            confidence=0.70,
            reason=rule_name,
            stop_price=context["support"] - context["stop_buffer"],
            target_price=context["resistance"],
            metadata={**context},
        )
        return _triggered(rule_name), signal

    def _check_ascending_channel_resistance_rejection(
        self,
        context: dict[str, float | str | None],
        channel_failure: str,
    ) -> tuple[RuleEvaluation, StrategySignal | None]:
        rule_name = "ascending_channel_resistance_rejection"
        if not self.config.allow_shorts or not self.config.enable_ascending_channel_resistance_rejection:
            return _failed(rule_name, "rule_disabled"), None
        if channel_failure != "ok":
            return _failed(rule_name, channel_failure), None
        if context["channel_kind"] != "ascending_channel":
            return _failed(rule_name, "channel_kind_mismatch"), None
        # Oscillation trade: no impulse required
        gate_reason = _oscillation_short_gate_reason(context, self.config.require_parent_confirmation)
        if gate_reason is not None:
            return _failed(rule_name, gate_reason, context), None
        if context["close"] < context["resistance"] - context["entry_buffer"]:
            return _failed(rule_name, "price_out_of_entry_zone"), None
        signal = StrategySignal(
            action="short",
            confidence=0.70,
            reason=rule_name,
            stop_price=context["resistance"] + context["stop_buffer"],
            target_price=context["support"],
            metadata={**context},
        )
        return _triggered(rule_name), signal

    def _check_descending_channel_breakout_long(
        self,
        context: dict[str, float | str | None],
        generic_impulse: str,
        channel_failure: str,
    ) -> tuple[RuleEvaluation, StrategySignal | None]:
        rule_name = "descending_channel_breakout_long"
        if not self.config.allow_longs or not self.config.enable_descending_channel_breakout_long:
            return _failed(rule_name, "rule_disabled"), None
        if channel_failure != "ok":
            return _failed(rule_name, channel_failure), None
        if context["channel_kind"] != "descending_channel":
            return _failed(rule_name, "channel_kind_mismatch"), None
        if generic_impulse != "bullish":
            return _failed(rule_name, "impulse_mismatch"), None
        parent_gate_reason = _parent_long_gate_reason(context, self.config.require_parent_confirmation)
        if parent_gate_reason is not None:
            return _failed(rule_name, parent_gate_reason, context), None
        if context["close"] <= context["resistance"]:
            return _failed(rule_name, "price_out_of_entry_zone"), None
        signal = StrategySignal(
            action="buy",
            confidence=0.85,
            reason=rule_name,
            stop_price=context["resistance"] - context["stop_buffer"],
            target_price=context["resistance"] + context["width"],
            metadata={**context},
        )
        return _triggered(rule_name), signal

    def _check_ascending_channel_breakdown_short(
        self,
        context: dict[str, float | str | None],
        generic_impulse: str,
        channel_failure: str,
    ) -> tuple[RuleEvaluation, StrategySignal | None]:
        rule_name = "ascending_channel_breakdown_short"
        if not self.config.allow_shorts or not self.config.enable_ascending_channel_breakdown_short:
            return _failed(rule_name, "rule_disabled"), None
        if channel_failure != "ok":
            return _failed(rule_name, channel_failure), None
        if context["channel_kind"] != "ascending_channel":
            return _failed(rule_name, "channel_kind_mismatch"), None
        if generic_impulse != "bearish":
            return _failed(rule_name, "impulse_mismatch"), None
        parent_gate_reason = _parent_short_gate_reason(context, self.config.require_parent_confirmation)
        if parent_gate_reason is not None:
            return _failed(rule_name, parent_gate_reason, context), None
        # Require close to be meaningfully below support (confirmation buffer)
        if not (
            context["close"] < context["support"]
            and context["close"] <= context["support"] - context["continuation_buffer"]
        ):
            return _failed(rule_name, "price_out_of_entry_zone"), None
        signal = StrategySignal(
            action="short",
            confidence=0.85,
            reason=rule_name,
            stop_price=context["support"] + context["stop_buffer"],
            target_price=context["support"] - context["width"],
            metadata={**context},
        )
        return _triggered(rule_name), signal

    @staticmethod
    def _manage_open_position(position: Position, current_price: float) -> StrategySignal:
        stop_price = getattr(position, "stop_price", None)
        target_price = getattr(position, "target_price", None)
        if position.side == "long":
            if stop_price is not None and current_price <= stop_price:
                return StrategySignal(action="sell", confidence=1.0, reason="long_structure_stop")
            if target_price is not None and current_price >= target_price:
                return StrategySignal(action="sell", confidence=1.0, reason="long_target_hit")
        if position.side == "short":
            if stop_price is not None and current_price >= stop_price:
                return StrategySignal(action="cover", confidence=1.0, reason="short_structure_stop")
            if target_price is not None and current_price <= target_price:
                return StrategySignal(action="cover", confidence=1.0, reason="short_target_hit")
        return StrategySignal(action="hold", confidence=0.0, reason="position_open")


def _all_failed(reason: str) -> list[RuleEvaluation]:
    return [RuleEvaluation(rule_name=name, eligible=False, triggered=False, first_failed_condition=reason) for name in RULE_NAMES]


def _failed(rule_name: str, reason: str, context: dict[str, Any] | None = None) -> RuleEvaluation:
    return RuleEvaluation(
        rule_name=rule_name,
        eligible=False,
        triggered=False,
        first_failed_condition=reason,
        context=context,
    )


def _triggered(rule_name: str) -> RuleEvaluation:
    return RuleEvaluation(rule_name=rule_name, eligible=True, triggered=True, first_failed_condition=None)


def _build_context(
    recent: list[MarketBar],
    channel: _Channel | None,
    config: TrendBreakoutConfig,
    parent_context: dict[str, float | str | None] | None,
) -> dict[str, float | str | None]:
    current = recent[-1]
    parent_context = parent_context or _empty_parent_context()
    if channel is None:
        return {
            "channel_kind": None,
            "close": current.close,
            "high": current.high,
            "support": 0.0,
            "resistance": 0.0,
            "width": 0.0,
            "entry_buffer": 0.0,
            "continuation_buffer": 0.0,
            "stop_buffer": 0.0,
            **parent_context,
        }

    index = len(recent) - 1
    support = channel.support_at(index)
    resistance = channel.resistance_at(index)
    width = resistance - support
    return {
        "channel_kind": channel.kind,
        "close": current.close,
        "high": current.high,
        "support": support,
        "resistance": resistance,
        "width": width,
        "entry_buffer": width * config.entry_buffer_pct,
        "continuation_buffer": width * config.continuation_buffer_pct,
        "stop_buffer": width * config.stop_buffer_pct,
        **parent_context,
    }


def _empty_parent_context() -> dict[str, float | str | None]:
    return {
        "parent_structure_type": "unknown",
        "parent_upper_boundary": None,
        "parent_lower_boundary": None,
        "parent_position_in_channel": "unknown",
        "parent_event_type": "none",
    }


def _resample_bars_for_parent(bars: list[MarketBar], factor: int) -> list[MarketBar]:
    if factor <= 1:
        return bars
    resampled: list[MarketBar] = []
    for index in range(0, len(bars), factor):
        chunk = bars[index : index + factor]
        if len(chunk) < factor:
            continue
        resampled.append(
            MarketBar(
                timestamp=chunk[-1].timestamp,
                open=chunk[0].open,
                high=max(item.high for item in chunk),
                low=min(item.low for item in chunk),
                close=chunk[-1].close,
                volume=sum(item.volume for item in chunk),
            )
        )
    return resampled


def _maybe_override_channel_direction(
    channel: _Channel,
    parent_bars: list[MarketBar],
) -> _Channel:
    """Override channel direction based on recent price regression.

    The channel geometry (support/resistance lines) was fitted from a wide window
    that may span multiple market regimes.  The direction (ascending/descending)
    should reflect the CURRENT regime, not the historical average.

    Uses the most recent 30 parent bars (~30 days at 24H) to capture the
    current market regime.  Shorter is better — longer windows get confused
    by intra-channel oscillations.
    """
    recent_n = min(30, len(parent_bars))
    if recent_n < 10:
        return channel

    recent_closes = [b.close for b in parent_bars[-recent_n:]]
    recent_x = list(range(len(recent_closes)))
    fit = _linear_fit(recent_x, recent_closes)
    if fit is None:
        return channel

    recent_slope = fit[0]
    channel_ascending = channel.kind == "ascending_channel"
    recent_ascending = recent_slope > 0

    if channel_ascending == recent_ascending:
        return channel  # Direction agrees, no override needed

    # Direction disagrees: flip the channel kind while keeping geometry
    new_kind = "ascending_channel" if recent_ascending else "descending_channel"
    return _Channel(
        kind=new_kind,
        support_slope=channel.support_slope,
        support_intercept=channel.support_intercept,
        resistance_slope=channel.resistance_slope,
        resistance_intercept=channel.resistance_intercept,
        width=channel.width,
    )


def _score_parent_channel(
    window: list[MarketBar],
    channel: _Channel,
    config: TrendBreakoutConfig,
) -> tuple[float, bool]:
    """Score a parent channel candidate. Returns (score, direction_consistent).

    Score = touches * (1 + mean_R²). Direction consistency checks whether
    the recent third of the window slope agrees with the channel direction.
    """
    last_idx = len(window) - 1
    width = max(channel.resistance_at(last_idx) - channel.support_at(last_idx), 1e-9)
    pivots = _find_pivots(window, config.parent_pivot_window)
    tolerance = width * 0.12
    touches = 0
    for p in pivots:
        if p.kind == "high":
            fitted = channel.resistance_slope * p.index + channel.resistance_intercept
        else:
            fitted = channel.support_slope * p.index + channel.support_intercept
        if abs(p.price - fitted) <= tolerance:
            touches += 1

    # R² for channel quality
    highs = [p for p in pivots if p.kind == "high"]
    lows = [p for p in pivots if p.kind == "low"]
    r2_res = _r_squared(
        [p.index for p in highs], [p.price for p in highs],
        channel.resistance_slope, channel.resistance_intercept,
    ) if len(highs) >= 2 else 0.5
    r2_sup = _r_squared(
        [p.index for p in lows], [p.price for p in lows],
        channel.support_slope, channel.support_intercept,
    ) if len(lows) >= 2 else 0.5
    mean_r2 = (r2_res + r2_sup) / 2

    # Recent-direction consistency: recent third of window slope should
    # agree with overall channel direction.
    recent_third = window[len(window) * 2 // 3:]
    direction_consistent = True
    if len(recent_third) >= 4:
        recent_closes = [b.close for b in recent_third]
        recent_x = list(range(len(recent_closes)))
        recent_fit = _linear_fit(recent_x, recent_closes)
        if recent_fit is not None:
            channel_ascending = channel.support_slope > 0
            recent_ascending = recent_fit[0] > 0
            direction_consistent = (channel_ascending == recent_ascending)

    score = max(touches, 1) * (1 + mean_r2)
    return score, direction_consistent


def _build_parent_context(
    bars: list[MarketBar],
    config: TrendBreakoutConfig,
) -> dict[str, float | str | None]:
    parent_bars = _resample_bars_for_parent(bars, config.parent_timeframe_factor)
    min_bars = max(config.parent_pivot_window * 2 + 1, config.parent_min_pivot_highs + config.parent_min_pivot_lows)

    # Multi-scale detection: try multiple lookback windows, pick best channel.
    # Shorter windows capture recent structure; longer windows capture macro trends.
    max_lookback = min(config.parent_structure_lookback, len(parent_bars))
    lookback_candidates = [lb for lb in [60, 90, 120, 180, 240, 360] if min_bars <= lb <= max_lookback]
    if not lookback_candidates:
        lookback_candidates = [max_lookback] if max_lookback >= min_bars else []

    detect_cfg = TrendBreakoutConfig(
        pivot_window=config.parent_pivot_window,
        min_pivot_highs=config.parent_min_pivot_highs,
        min_pivot_lows=config.parent_min_pivot_lows,
        max_slope_divergence_ratio=config.max_slope_divergence_ratio,
        min_channel_width_abs=config.min_channel_width_abs,
        min_channel_width_pct=config.min_channel_width_pct,
    )
    # Also try with relaxed pivot requirements for shorter windows
    relaxed_cfg = TrendBreakoutConfig(
        pivot_window=2,
        min_pivot_highs=2,
        min_pivot_lows=2,
        max_slope_divergence_ratio=config.max_slope_divergence_ratio,
        min_channel_width_abs=config.min_channel_width_abs,
        min_channel_width_pct=config.min_channel_width_pct,
    )

    best_channel: _Channel | None = None
    best_window: list[MarketBar] = []
    best_score = -1.0
    consistent_candidates: list[tuple[float, _Channel, list[MarketBar]]] = []
    all_candidates: list[tuple[float, _Channel, list[MarketBar]]] = []

    for lookback in sorted(lookback_candidates):
        window = parent_bars[-lookback:]
        channel, failure = _detect_channel(window, detect_cfg)
        if failure != "ok" or channel is None:
            continue
        score, is_consistent = _score_parent_channel(window, channel, config)
        entry = (score, channel, window)
        all_candidates.append(entry)
        if is_consistent:
            consistent_candidates.append(entry)

    # Phase 2: if no direction-consistent channels found, try re-detecting
    # on recent sub-windows of each candidate to capture recent structure.
    if not consistent_candidates:
        for lookback in sorted(lookback_candidates):
            window = parent_bars[-lookback:]
            # Try the recent half and recent third with relaxed pivot settings
            for frac in (2, 3):
                sub_start = len(window) * (frac - 1) // frac
                sub_window = window[sub_start:]
                if len(sub_window) < min_bars:
                    continue
                ch2, fail2 = _detect_channel(sub_window, relaxed_cfg)
                if fail2 != "ok" or ch2 is None:
                    continue
                score2, is_consistent2 = _score_parent_channel(sub_window, ch2, config)
                entry2 = (score2, ch2, sub_window)
                all_candidates.append(entry2)
                if is_consistent2:
                    consistent_candidates.append(entry2)

    # Prefer direction-consistent channels; among those, prefer highest score
    if consistent_candidates:
        best_score, best_channel, best_window = max(consistent_candidates, key=lambda c: c[0])
    elif all_candidates:
        best_score, best_channel, best_window = max(all_candidates, key=lambda c: c[0])

    parent_channel = best_channel
    window = best_window if best_window else []
    if parent_channel is None:
        return _empty_parent_context()

    # Direction override: use RECENT price slope to determine the true market
    # direction.  The channel geometry (boundaries) is still from the best-fit
    # channel, but its kind is overridden if recent prices clearly trend the
    # other way.  This fixes macro-trend domination in long lookback windows.
    parent_channel = _maybe_override_channel_direction(parent_channel, parent_bars)

    last_index = len(window) - 1
    upper = parent_channel.resistance_at(last_index)
    lower = parent_channel.support_at(last_index)
    width = max(upper - lower, 1e-9)
    close = window[-1].close
    zone = width * config.parent_boundary_zone_pct
    if close < lower:
        position = "below_lower_boundary"
    elif close > upper:
        position = "above_upper_boundary"
    elif close <= lower + zone:
        position = "near_lower_boundary"
    elif close >= upper - zone:
        position = "near_upper_boundary"
    else:
        position = "mid_channel"

    event = _detect_parent_event_type(window, parent_channel, config)
    return {
        "parent_structure_type": parent_channel.kind,
        "parent_upper_boundary": upper,
        "parent_lower_boundary": lower,
        "parent_position_in_channel": position,
        "parent_event_type": event.event_type,
    }


def _detect_parent_event_type(
    bars: list[MarketBar],
    channel: _Channel,
    config: TrendBreakoutConfig,
) -> _ParentEvent:
    if len(bars) < 3:
        return _ParentEvent(event_type="normal")

    last_index = len(bars) - 1
    lower = channel.support_at(last_index)
    close = bars[-1].close

    if _is_confirmed_breakdown(bars, channel, config.breakdown_confirm_bars):
        return _ParentEvent(event_type="confirmed_breakdown", bars_since_event=0)

    shock_index = _find_recent_shock_reclaim_index(bars, channel)
    if shock_index is None:
        return _ParentEvent(event_type="normal")

    bars_since = (len(bars) - 1) - shock_index
    if bars_since <= config.shock_reclaim_window_bars:
        return _ParentEvent(event_type="shock_break_reclaim", bars_since_event=bars_since)
    if bars_since <= config.shock_cooldown_bars:
        return _ParentEvent(event_type="post_shock_stabilization", bars_since_event=bars_since)
    if close < lower:
        return _ParentEvent(event_type="confirmed_breakdown", bars_since_event=bars_since)
    return _ParentEvent(event_type="normal", bars_since_event=bars_since)


def _find_recent_shock_reclaim_index(bars: list[MarketBar], channel: _Channel) -> int | None:
    for index in range(len(bars) - 2, 0, -1):
        lower = channel.support_at(index)
        bar = bars[index]
        if bar.low < lower and bar.close >= lower:
            return index
    return None


def _is_confirmed_breakdown(bars: list[MarketBar], channel: _Channel, confirm_bars: int) -> bool:
    if confirm_bars <= 0 or len(bars) < confirm_bars:
        return False
    for offset in range(confirm_bars):
        idx = len(bars) - 1 - offset
        lower = channel.support_at(idx)
        if bars[idx].close >= lower:
            return False
    return True


def _parent_short_gate_reason(context: dict[str, float | str | None], require_confirmation: bool = True) -> str | None:
    """Block shorts when parent structure doesn't support bearish thesis."""
    parent_event = context.get("parent_event_type")
    parent_type = context.get("parent_structure_type")
    position = context.get("parent_position_in_channel")

    if parent_event in {"shock_break_reclaim", "post_shock_stabilization"}:
        return "shock_override_active"
    # Don't short when parent structure is unknown — can't confirm regime
    if require_confirmation and parent_type in {"unknown", None}:
        return "parent_regime_unknown"
    # Don't short when parent is ascending and hasn't broken down
    if parent_type == "ascending_channel" and parent_event != "confirmed_breakdown":
        return "parent_context_conflict"
    # Don't short near any lower boundary (support zone, regardless of channel type)
    if position in {"near_lower_boundary", "below_lower_boundary"}:
        return "parent_context_conflict"
    return None


def _oscillation_short_gate_reason(context: dict[str, float | str | None], require_confirmation: bool = True) -> str | None:
    """Lighter gate for counter-trend oscillation shorts (e.g. resistance rejection in ascending channel).

    Only blocks at shock events — does NOT filter on parent trend direction,
    because oscillation trades rely on channel structure + price position, not momentum.
    """
    parent_event = context.get("parent_event_type")
    if parent_event in {"shock_break_reclaim", "post_shock_stabilization"}:
        return "shock_override_active"
    if require_confirmation and context.get("parent_structure_type") in {"unknown", None}:
        return "parent_regime_unknown"
    return None


def _oscillation_long_gate_reason(context: dict[str, float | str | None], require_confirmation: bool = True) -> str | None:
    """Lighter gate for counter-trend oscillation longs (e.g. support bounce in descending channel).

    Only blocks at shock events — does NOT filter on parent trend direction.
    """
    parent_event = context.get("parent_event_type")
    if parent_event in {"shock_break_reclaim", "post_shock_stabilization"}:
        return "shock_override_active"
    if require_confirmation and context.get("parent_structure_type") in {"unknown", None}:
        return "parent_regime_unknown"
    return None


def _parent_long_gate_reason(context: dict[str, float | str | None], require_confirmation: bool = True) -> str | None:
    """Block longs when parent structure doesn't support bullish thesis."""
    parent_event = context.get("parent_event_type")
    parent_type = context.get("parent_structure_type")
    position = context.get("parent_position_in_channel")

    if parent_event in {"shock_break_reclaim", "post_shock_stabilization"}:
        return "shock_override_active"
    # Don't buy when parent structure is unknown — can't confirm regime
    if require_confirmation and parent_type in {"unknown", None}:
        return "parent_regime_unknown"
    # Don't buy when parent is descending and hasn't broken out
    if parent_type == "descending_channel" and parent_event != "confirmed_breakdown":
        return "parent_context_conflict"
    # Don't buy when ascending channel has confirmed breakdown (structure failed)
    if parent_type == "ascending_channel" and parent_event == "confirmed_breakdown":
        return "parent_context_conflict"
    # Don't buy near resistance of ascending channel (reversal zone)
    if parent_type == "ascending_channel" and position in {"near_upper_boundary", "above_upper_boundary"}:
        return "parent_context_conflict"
    return None


def _detect_impulse_state(
    bars: list[MarketBar],
    threshold_pct: float,
    atr_expansion_min: float | None,
    volume_expansion_min: float | None,
) -> str:
    if len(bars) < 2:
        return "neutral"

    change_pct = (bars[-1].close - bars[0].close) / bars[0].close
    if abs(change_pct) < threshold_pct:
        return "neutral"

    if atr_expansion_min is not None and _atr_expansion_ratio(bars) < atr_expansion_min:
        return "neutral"
    if volume_expansion_min is not None and _volume_expansion_ratio(bars) < volume_expansion_min:
        return "neutral"
    return "bullish" if change_pct > 0 else "bearish"


def _detect_channel(
    bars: list[MarketBar],
    config: TrendBreakoutConfig,
) -> tuple[_Channel | None, str]:
    pivots = _find_pivots(bars, config.pivot_window)
    highs = [pivot for pivot in pivots if pivot.kind == "high"]
    lows = [pivot for pivot in pivots if pivot.kind == "low"]
    if len(highs) < config.min_pivot_highs or len(lows) < config.min_pivot_lows:
        return None, "pivot_count_insufficient"

    resistance = _linear_fit([pivot.index for pivot in highs], [pivot.price for pivot in highs])
    support = _linear_fit([pivot.index for pivot in lows], [pivot.price for pivot in lows])
    if resistance is None or support is None:
        return None, "channel_not_detected"

    resistance_slope, resistance_intercept = resistance
    support_slope, support_intercept = support
    if resistance_slope > 0 and support_slope > 0:
        kind = "ascending_channel"
    elif resistance_slope < 0 and support_slope < 0:
        kind = "descending_channel"
    else:
        return None, "channel_not_detected"

    scale = max(abs(resistance_slope), abs(support_slope), 1e-9)
    if abs(resistance_slope - support_slope) / scale > config.max_slope_divergence_ratio:
        return None, "slope_divergence_too_large"

    if config.min_r_squared > 0:
        r2_res = _r_squared([pivot.index for pivot in highs], [pivot.price for pivot in highs], resistance_slope, resistance_intercept)
        r2_sup = _r_squared([pivot.index for pivot in lows], [pivot.price for pivot in lows], support_slope, support_intercept)
        if min(r2_res, r2_sup) < config.min_r_squared:
            return None, "r_squared_too_low"

    last_index = len(bars) - 1
    width = ((resistance_slope * last_index) + resistance_intercept) - ((support_slope * last_index) + support_intercept)
    if width <= config.min_channel_width_abs:
        return None, "below_min_channel_width"
    if config.min_channel_width_pct is not None and (width / bars[-1].close) < config.min_channel_width_pct:
        return None, "below_min_channel_width"

    tolerance = width * 0.12
    support_touches = sum(
        1 for pivot in lows if abs(pivot.price - ((support_slope * pivot.index) + support_intercept)) <= tolerance
    )
    resistance_touches = sum(
        1 for pivot in highs if abs(pivot.price - ((resistance_slope * pivot.index) + resistance_intercept)) <= tolerance
    )
    if support_touches < config.min_pivot_lows or resistance_touches < config.min_pivot_highs:
        return None, "pivot_count_insufficient"

    return (
        _Channel(
            kind=kind,
            support_slope=support_slope,
            support_intercept=support_intercept,
            resistance_slope=resistance_slope,
            resistance_intercept=resistance_intercept,
            width=width,
        ),
        "ok",
    )


def _find_pivots(bars: list[MarketBar], window: int) -> list[_Pivot]:
    pivots: list[_Pivot] = []
    for index in range(window, len(bars) - window):
        segment = bars[index - window : index + window + 1]
        if bars[index].high == max(item.high for item in segment):
            pivots.append(_Pivot(index=index, price=bars[index].high, kind="high"))
        if bars[index].low == min(item.low for item in segment):
            pivots.append(_Pivot(index=index, price=bars[index].low, kind="low"))
    return pivots


def _linear_fit(x_values: list[int], y_values: list[float]) -> tuple[float, float] | None:
    if len(x_values) != len(y_values) or len(x_values) < 2:
        return None
    x_mean = mean(x_values)
    y_mean = mean(y_values)
    denominator = sum((value - x_mean) ** 2 for value in x_values)
    if denominator == 0:
        return None
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))
    slope = numerator / denominator
    intercept = y_mean - (slope * x_mean)
    return slope, intercept


def _r_squared(x_values: list[int], y_values: list[float], slope: float, intercept: float) -> float:
    """Coefficient of determination (R²) for a linear fit."""
    y_mean = mean(y_values)
    ss_tot = sum((y - y_mean) ** 2 for y in y_values)
    if ss_tot == 0:
        return 1.0
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(x_values, y_values))
    return 1.0 - (ss_res / ss_tot)


def _compute_sma(bars: list[MarketBar], period: int) -> float | None:
    """Simple Moving Average of close prices over the last `period` bars."""
    if len(bars) < period:
        return None
    return mean(bar.close for bar in bars[-period:])


def _compute_atr(bars: list[MarketBar], lookback: int) -> float:
    """Average True Range over the last `lookback` bars."""
    window = bars[-lookback:] if len(bars) >= lookback else bars
    if len(window) < 2:
        return 0.0
    true_ranges: list[float] = []
    prev_close = window[0].close
    for bar in window[1:]:
        true_ranges.append(max(bar.high - bar.low, abs(bar.high - prev_close), abs(bar.low - prev_close)))
        prev_close = bar.close
    return mean(true_ranges) if true_ranges else 0.0


def _compute_adx(bars: list[MarketBar], period: int) -> float | None:
    """Average Directional Index — measures trend strength regardless of direction.

    Returns value 0-100.  ADX > 25 → trending, ADX < 20 → ranging.
    Requires at least ``2 * period`` bars.
    """
    needed = 2 * period + 1
    if len(bars) < needed:
        return None

    window = bars[-needed:]

    # Step 1: compute +DM, -DM, TR for each bar
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    tr_list: list[float] = []
    for i in range(1, len(window)):
        high_diff = window[i].high - window[i - 1].high
        low_diff = window[i - 1].low - window[i].low
        pdm = high_diff if high_diff > low_diff and high_diff > 0 else 0.0
        mdm = low_diff if low_diff > high_diff and low_diff > 0 else 0.0
        plus_dm.append(pdm)
        minus_dm.append(mdm)
        tr = max(
            window[i].high - window[i].low,
            abs(window[i].high - window[i - 1].close),
            abs(window[i].low - window[i - 1].close),
        )
        tr_list.append(tr)

    # Step 2: Wilder's smoothing for ATR, +DM, -DM
    atr_smooth = sum(tr_list[:period])
    pdm_smooth = sum(plus_dm[:period])
    mdm_smooth = sum(minus_dm[:period])

    dx_values: list[float] = []
    for i in range(period, len(tr_list)):
        atr_smooth = atr_smooth - atr_smooth / period + tr_list[i]
        pdm_smooth = pdm_smooth - pdm_smooth / period + plus_dm[i]
        mdm_smooth = mdm_smooth - mdm_smooth / period + minus_dm[i]

        if atr_smooth == 0:
            continue
        plus_di = 100 * pdm_smooth / atr_smooth
        minus_di = 100 * mdm_smooth / atr_smooth
        di_sum = plus_di + minus_di
        if di_sum == 0:
            continue
        dx_values.append(100 * abs(plus_di - minus_di) / di_sum)

    if not dx_values:
        return None

    # Step 3: Smooth DX into ADX (first ADX = mean of first period DX values)
    if len(dx_values) < period:
        return mean(dx_values)

    adx = mean(dx_values[:period])
    for dx in dx_values[period:]:
        adx = (adx * (period - 1) + dx) / period
    return adx


def _compute_rsi(bars: list[MarketBar], period: int) -> float | None:
    """Relative Strength Index using Wilder's smoothing.

    Returns 0-100.  RSI < oversold → oversold, RSI > overbought → overbought.
    Short periods (2-6) are recommended for structural confirmation per research.
    """
    needed = period + 1
    if len(bars) < needed:
        return None

    window = bars[-needed:]
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(window)):
        delta = window[i].close - window[i - 1].close
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    if not gains:
        return None

    avg_gain = mean(gains[:period])
    avg_loss = mean(losses[:period])

    # Wilder's smoothing for remaining values
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# Bounce rules: trades that expect price to reverse at channel boundary
_BOUNCE_RULES: set[str] = {
    "ascending_channel_support_bounce",
    "descending_channel_rejection",
    "descending_channel_support_bounce",
    "ascending_channel_resistance_rejection",
}

# Breakout rules: trades that expect price to continue through channel boundary
_BREAKOUT_RULES: set[str] = {
    "ascending_channel_breakout",
    "descending_channel_breakdown",
    "rising_channel_breakdown_retest_short",
    "rising_channel_breakdown_continuation_short",
    "descending_channel_breakout_long",
    "ascending_channel_breakdown_short",
}


def _extend_target_to_parent_boundary(
    signal: StrategySignal,
    parent_context: dict[str, float | str | None] | None,
) -> StrategySignal:
    """Extend the target price to the parent channel boundary when it's further
    in the profitable direction than the local channel target."""
    if parent_context is None or signal.target_price is None:
        return signal
    if signal.action == "short":
        parent_lower = parent_context.get("parent_lower_boundary")
        if parent_lower is not None and isinstance(parent_lower, (int, float)) and parent_lower < signal.target_price:
            return StrategySignal(
                action=signal.action,
                confidence=signal.confidence,
                reason=signal.reason,
                stop_price=signal.stop_price,
                target_price=parent_lower,
                metadata=signal.metadata,
            )
    elif signal.action == "buy":
        parent_upper = parent_context.get("parent_upper_boundary")
        if parent_upper is not None and isinstance(parent_upper, (int, float)) and parent_upper > signal.target_price:
            return StrategySignal(
                action=signal.action,
                confidence=signal.confidence,
                reason=signal.reason,
                stop_price=signal.stop_price,
                target_price=parent_upper,
                metadata=signal.metadata,
            )
    return signal


def _apply_atr_stop_floor(
    signal: StrategySignal,
    bars: list[MarketBar],
    atr_lookback: int,
    atr_multiplier: float,
) -> StrategySignal:
    """Widen the stop to at least atr_multiplier * ATR from entry price."""
    if signal.stop_price is None:
        return signal
    atr = _compute_atr(bars, atr_lookback)
    if atr == 0:
        return signal
    min_distance = atr * atr_multiplier
    entry_price = signal.metadata.get("close", bars[-1].close) if signal.metadata else bars[-1].close

    if signal.action in ("short",):
        # Short: stop is above entry
        min_stop = entry_price + min_distance
        if signal.stop_price < min_stop:
            return StrategySignal(
                action=signal.action,
                confidence=signal.confidence,
                reason=signal.reason,
                stop_price=min_stop,
                target_price=signal.target_price,
                metadata=signal.metadata,
            )
    elif signal.action in ("buy",):
        # Long: stop is below entry
        min_stop = entry_price - min_distance
        if signal.stop_price > min_stop:
            return StrategySignal(
                action=signal.action,
                confidence=signal.confidence,
                reason=signal.reason,
                stop_price=min_stop,
                target_price=signal.target_price,
                metadata=signal.metadata,
            )
    return signal


def _atr_expansion_ratio(bars: list[MarketBar]) -> float:
    if len(bars) < 2:
        return 0.0
    true_ranges: list[float] = []
    previous_close = bars[0].close
    for bar in bars:
        true_ranges.append(max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close)))
        previous_close = bar.close
    midpoint = max(len(true_ranges) // 2, 1)
    baseline = mean(true_ranges[:midpoint])
    latest = mean(true_ranges[midpoint:])
    if baseline == 0:
        return 0.0
    return latest / baseline


def _volume_expansion_ratio(bars: list[MarketBar]) -> float:
    if len(bars) < 2:
        return 0.0
    midpoint = max(len(bars) // 2, 1)
    baseline = mean(bar.volume for bar in bars[:midpoint])
    latest = mean(bar.volume for bar in bars[midpoint:])
    if baseline == 0:
        return 0.0
    return latest / baseline


# ── Narrative regime integration ────────────────────────────────────


def _lookup_narrative_regime_for_bar(bar: MarketBar):
    """Look up the narrative regime for a bar's date.  Returns None on import failure."""
    try:
        from research.narrative_regime import lookup_narrative_regime
    except ImportError:
        return None
    return lookup_narrative_regime(bar.timestamp.date(), current_price=bar.close)
