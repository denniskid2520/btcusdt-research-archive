from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from adapters.base import MarketBar, Position
from strategies.base import Strategy, StrategySignal


RULE_NAMES: tuple[str, ...] = (
    "ascending_channel_support_bounce",
    "ascending_channel_breakout",
    "descending_channel_rejection",
    "descending_channel_breakdown",
    "rising_channel_breakdown_retest_short",
    "rising_channel_breakdown_continuation_short",
)


@dataclass(frozen=True)
class TrendBreakoutConfig:
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
    entry_buffer_pct: float = 0.15
    continuation_buffer_pct: float = 0.2
    stop_buffer_pct: float = 0.08
    time_stop_bars: int | None = None
    allow_longs: bool = True
    allow_shorts: bool = True
    enable_rising_channel_breakdown_retest_short: bool = True
    enable_rising_channel_breakdown_continuation_short: bool = True


@dataclass(frozen=True)
class RuleEvaluation:
    rule_name: str
    eligible: bool
    triggered: bool
    first_failed_condition: str | None


@dataclass(frozen=True)
class StrategyEvaluation:
    signal: StrategySignal
    rule_evaluations: list[RuleEvaluation]


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


class TrendBreakoutStrategy(Strategy):
    """Parameterized channel trend breakout strategy with evaluation funnel."""

    def __init__(self, config: TrendBreakoutConfig | None = None) -> None:
        self.config = config or TrendBreakoutConfig()

    def generate_signal(self, symbol: str, bars: list[MarketBar], position: Position) -> StrategySignal:
        return self.evaluate(symbol=symbol, bars=bars, position=position).signal

    def evaluate(self, symbol: str, bars: list[MarketBar], position: Position) -> StrategyEvaluation:
        del symbol
        required_bars = max(self.config.impulse_lookback, self.config.structure_lookback)
        if len(bars) < required_bars:
            return StrategyEvaluation(
                signal=StrategySignal(action="hold", confidence=0.0, reason="insufficient_bars"),
                rule_evaluations=_all_failed("insufficient_bars"),
            )

        if position.is_open:
            return StrategyEvaluation(
                signal=self._manage_open_position(position, bars[-1].close),
                rule_evaluations=_all_failed("position_open"),
            )

        recent = bars[-self.config.structure_lookback :]
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

        context = _build_context(recent, channel, self.config)
        rule_evals: list[RuleEvaluation] = []
        winning_signal = StrategySignal(action="hold", confidence=0.0, reason="no_trade_setup")

        rule_checks = (
            self._check_ascending_channel_support_bounce(context, generic_impulse, channel_failure),
            self._check_ascending_channel_breakout(context, generic_impulse, channel_failure),
            self._check_descending_channel_rejection(context, generic_impulse, channel_failure),
            self._check_descending_channel_breakdown(context, generic_impulse, channel_failure),
            self._check_rising_channel_breakdown_retest_short(context, front_impulse, channel_failure),
            self._check_rising_channel_breakdown_continuation_short(context, front_impulse, channel_failure),
        )

        for rule_eval, candidate_signal in rule_checks:
            rule_evals.append(rule_eval)
            if candidate_signal is not None and winning_signal.action == "hold":
                winning_signal = candidate_signal

        return StrategyEvaluation(signal=winning_signal, rule_evaluations=rule_evals)

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


def _failed(rule_name: str, reason: str) -> RuleEvaluation:
    return RuleEvaluation(rule_name=rule_name, eligible=False, triggered=False, first_failed_condition=reason)


def _triggered(rule_name: str) -> RuleEvaluation:
    return RuleEvaluation(rule_name=rule_name, eligible=True, triggered=True, first_failed_condition=None)


def _build_context(
    recent: list[MarketBar],
    channel: _Channel | None,
    config: TrendBreakoutConfig,
) -> dict[str, float | str | None]:
    current = recent[-1]
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
    }


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
