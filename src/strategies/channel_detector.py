"""Daily channel detector with indicator-confirmed pivots.

Detects ascending/descending channels lasting 2-4 months on daily bars.
Uses Coinglass indicators (OI, Funding, L/S, Liquidation, CVD, Taker)
plus RSI to confirm genuine channel highs and lows before fitting trendlines.

Indicator confirmation based on 6-channel empirical analysis:

HIGH pivot ★★★ conditions (>= 75% hit rate across 20 samples):
  - L/S > 1.0      (95%)
  - LiqR < 1.0     (100%, 7 samples) — shorts squeezed
  - Taker B/S > 1.0 (86%, 7 samples)
  - OI rising       (84%)
  - Funding > 0     (80%)
  - L/S > 1.1       (80%)
  - CVD rising      (79%)

LOW pivot ★★★ conditions (>= 70% hit rate across 20 samples):
  - L/S > 1.0       (100%)
  - LiqR > 1.0      (88%, 8 samples) — longs washed
  - CVD declining    (87%)
  - R14 < 45        (85%)
  - OI declining     (80%)
  - R3 < 35         (75%)
  - Taker B/S < 1.0 (75%, 8 samples)
  - R3 < 30         (70%)
  - R7 < 40         (70%)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from adapters.base import MarketBar


# ── Data Structures ──

@dataclass
class DailyIndicators:
    """All Coinglass + RSI indicators for a single day."""
    oi: float = 0.0
    funding_pct: float = 0.0
    ls_ratio: float = 0.0
    long_liq_usd: float = 0.0
    short_liq_usd: float = 0.0
    cvd: float = 0.0
    taker_buy_usd: float = 0.0
    taker_sell_usd: float = 0.0
    rsi3: float = 50.0
    rsi7: float = 50.0
    rsi14: float = 50.0

    @property
    def liq_ratio(self) -> float:
        """Long / Short liquidation ratio. 0 if no short liq."""
        if self.short_liq_usd <= 0:
            return 0.0
        return self.long_liq_usd / self.short_liq_usd

    @property
    def taker_ratio(self) -> float:
        """Taker buy / sell ratio. 0 if no sells."""
        if self.taker_sell_usd <= 0:
            return 0.0
        return self.taker_buy_usd / self.taker_sell_usd


@dataclass
class ConfirmedPivot:
    """A pivot point confirmed by indicator conditions."""
    index: int          # bar index in the input array
    price: float        # high price for HIGH, low price for LOW
    kind: str           # "high" or "low"
    score: int          # how many ★★★ conditions matched
    date: str           # ISO date string


@dataclass
class DetectedChannel:
    """A detected channel with fitted trendlines."""
    kind: str                    # "ascending" or "descending"
    support_slope: float         # price change per day on support line
    support_intercept: float     # support price at index 0
    resistance_slope: float      # price change per day on resistance line
    resistance_intercept: float  # resistance price at index 0
    support_r2: float
    resistance_r2: float
    width: float                 # average channel width
    duration_days: int
    confirmed_highs: list[ConfirmedPivot] = field(default_factory=list)
    confirmed_lows: list[ConfirmedPivot] = field(default_factory=list)

    def support_at(self, day_index: int) -> float:
        return self.support_slope * day_index + self.support_intercept

    def resistance_at(self, day_index: int) -> float:
        return self.resistance_slope * day_index + self.resistance_intercept

    @property
    def avg_slope_per_day(self) -> float:
        return (self.support_slope + self.resistance_slope) / 2

    @property
    def slope_pct_per_day(self) -> float:
        """Slope as percentage of mid-channel price at midpoint."""
        mid_day = self.duration_days / 2
        mid_price = (self.support_at(mid_day) + self.resistance_at(mid_day)) / 2
        if mid_price <= 0:
            return 0.0
        return self.avg_slope_per_day / mid_price * 100

    def position_pct(self, price: float, day_index: int) -> float:
        """Where price sits in channel: 0.0 = support, 1.0 = resistance."""
        sup = self.support_at(day_index)
        res = self.resistance_at(day_index)
        width = res - sup
        if width <= 0:
            return 0.5
        return (price - sup) / width


# ── Configuration ──

@dataclass
class ChannelDetectorConfig:
    # Pivot detection
    pivot_window: int = 5              # days left/right to check for local max/min
    min_confirmed_highs: int = 2       # minimum confirmed HIGH pivots
    min_confirmed_lows: int = 2        # minimum confirmed LOW pivots
    min_bars: int = 30                 # minimum daily bars required

    # HIGH pivot scoring (each ★★★ condition = 1 point)
    min_high_score: int = 3            # minimum score to confirm a HIGH pivot

    # LOW pivot scoring
    min_low_score: int = 3             # minimum score to confirm a LOW pivot

    # Channel validation
    max_slope_divergence: float = 0.75  # max |sup_slope - res_slope| / max(|slopes|)
    min_r_squared: float = 0.0         # minimum R² for trendlines
    min_channel_width_pct: float = 0.03 # minimum width as % of price (3%)


# ── Channel Detector ──

class ChannelDetector:
    """Detect channels on daily bars using indicator-confirmed pivots."""

    def __init__(self, config: ChannelDetectorConfig | None = None) -> None:
        self.config = config or ChannelDetectorConfig()

    def detect(
        self,
        bars: list[MarketBar],
        indicators: dict[str, DailyIndicators],
    ) -> DetectedChannel | None:
        """Detect a channel from daily bars with indicator confirmation.

        Args:
            bars: Daily OHLCV bars (at least min_bars).
            indicators: Dict of date string -> DailyIndicators.

        Returns:
            DetectedChannel if found, None otherwise.
        """
        if len(bars) < self.config.min_bars:
            return None

        # Step 1: Find raw pivots
        raw_highs = self._find_pivot_highs(bars)
        raw_lows = self._find_pivot_lows(bars)

        if not raw_highs or not raw_lows:
            return None

        # Step 2: Confirm pivots with indicators
        confirmed_highs = self._confirm_highs(bars, raw_highs, indicators)
        confirmed_lows = self._confirm_lows(bars, raw_lows, indicators)

        if (len(confirmed_highs) < self.config.min_confirmed_highs or
                len(confirmed_lows) < self.config.min_confirmed_lows):
            return None

        # Step 3: Fit trendlines
        res_slope, res_intercept = self._linear_fit(
            [(p.index, p.price) for p in confirmed_highs]
        )
        sup_slope, sup_intercept = self._linear_fit(
            [(p.index, p.price) for p in confirmed_lows]
        )

        if res_slope is None or sup_slope is None:
            return None

        # Step 4: Compute R²
        res_r2 = self._r_squared(
            [(p.index, p.price) for p in confirmed_highs],
            res_slope, res_intercept,
        )
        sup_r2 = self._r_squared(
            [(p.index, p.price) for p in confirmed_lows],
            sup_slope, sup_intercept,
        )

        # Step 5: Validate
        # Both slopes same sign (or near zero)
        if res_slope > 0 and sup_slope < -abs(res_slope) * 0.3:
            return None
        if res_slope < 0 and sup_slope > abs(res_slope) * 0.3:
            return None

        # Slope divergence
        max_abs = max(abs(res_slope), abs(sup_slope))
        if max_abs > 0:
            divergence = abs(res_slope - sup_slope) / max_abs
            if divergence > self.config.max_slope_divergence:
                return None

        # R² check
        if res_r2 < self.config.min_r_squared or sup_r2 < self.config.min_r_squared:
            return None

        # Channel width
        mid_idx = len(bars) // 2
        width = (res_slope * mid_idx + res_intercept) - (sup_slope * mid_idx + sup_intercept)
        if width <= 0:
            return None

        mid_price = (res_slope * mid_idx + res_intercept + sup_slope * mid_idx + sup_intercept) / 2
        if mid_price > 0 and width / mid_price < self.config.min_channel_width_pct:
            return None

        # Step 6: Build result
        avg_slope = (res_slope + sup_slope) / 2
        kind = "ascending" if avg_slope > 0 else "descending"
        duration = (bars[-1].timestamp - bars[0].timestamp).days

        return DetectedChannel(
            kind=kind,
            support_slope=sup_slope,
            support_intercept=sup_intercept,
            resistance_slope=res_slope,
            resistance_intercept=res_intercept,
            support_r2=sup_r2,
            resistance_r2=res_r2,
            width=width,
            duration_days=duration,
            confirmed_highs=confirmed_highs,
            confirmed_lows=confirmed_lows,
        )

    # ── Pivot Finding ──

    def _find_pivot_highs(self, bars: list[MarketBar]) -> list[int]:
        """Find indices of local high pivots."""
        w = self.config.pivot_window
        pivots = []
        for i in range(w, len(bars) - w):
            is_highest = all(
                bars[i].high >= bars[j].high
                for j in range(i - w, i + w + 1)
                if j != i
            )
            if is_highest:
                pivots.append(i)
        return pivots

    def _find_pivot_lows(self, bars: list[MarketBar]) -> list[int]:
        """Find indices of local low pivots."""
        w = self.config.pivot_window
        pivots = []
        for i in range(w, len(bars) - w):
            is_lowest = all(
                bars[i].low <= bars[j].low
                for j in range(i - w, i + w + 1)
                if j != i
            )
            if is_lowest:
                pivots.append(i)
        return pivots

    # ── Pivot Confirmation ──

    def _confirm_highs(
        self,
        bars: list[MarketBar],
        pivot_indices: list[int],
        indicators: dict[str, DailyIndicators],
    ) -> list[ConfirmedPivot]:
        """Confirm high pivots using ★★★ indicator conditions."""
        confirmed = []
        for idx in pivot_indices:
            date_str = bars[idx].timestamp.strftime("%Y-%m-%d")
            ind = indicators.get(date_str)
            if ind is None:
                continue

            # Find previous pivot's indicators for CVD/OI change
            prev_ind = self._find_prev_indicators(bars, idx, indicators)
            score = self.score_high_pivot(ind, prev_ind)

            if score >= self.config.min_high_score:
                confirmed.append(ConfirmedPivot(
                    index=idx,
                    price=bars[idx].high,
                    kind="high",
                    score=score,
                    date=date_str,
                ))
        return confirmed

    def _confirm_lows(
        self,
        bars: list[MarketBar],
        pivot_indices: list[int],
        indicators: dict[str, DailyIndicators],
    ) -> list[ConfirmedPivot]:
        """Confirm low pivots using ★★★ indicator conditions."""
        confirmed = []
        for idx in pivot_indices:
            date_str = bars[idx].timestamp.strftime("%Y-%m-%d")
            ind = indicators.get(date_str)
            if ind is None:
                continue

            prev_ind = self._find_prev_indicators(bars, idx, indicators)
            score = self.score_low_pivot(ind, prev_ind)

            if score >= self.config.min_low_score:
                confirmed.append(ConfirmedPivot(
                    index=idx,
                    price=bars[idx].low,
                    kind="low",
                    score=score,
                    date=date_str,
                ))
        return confirmed

    def _find_prev_indicators(
        self,
        bars: list[MarketBar],
        current_idx: int,
        indicators: dict[str, DailyIndicators],
        lookback: int = 7,
    ) -> DailyIndicators | None:
        """Find indicators from ~lookback days before current index."""
        target = max(0, current_idx - lookback)
        date_str = bars[target].timestamp.strftime("%Y-%m-%d")
        return indicators.get(date_str)

    def score_high_pivot(
        self,
        ind: DailyIndicators,
        prev_ind: DailyIndicators | None,
    ) -> int:
        """Score a HIGH pivot against ★★★ conditions.

        Each matched condition = 1 point.
        Based on empirical analysis of 20 channel highs across 6 channels.
        """
        score = 0

        # L/S > 1.0 (95% hit rate)
        if ind.ls_ratio > 1.0:
            score += 1

        # L/S > 1.1 (80% hit rate)
        if ind.ls_ratio > 1.1:
            score += 1

        # Funding > 0 (80% hit rate)
        if ind.funding_pct > 0:
            score += 1

        # LiqR < 1.0 — shorts squeezed more (100% hit rate, 7 samples)
        if ind.liq_ratio > 0 and ind.liq_ratio < 1.0:
            score += 1

        # Taker B/S > 1.0 (86% hit rate, 7 samples)
        if ind.taker_ratio > 1.0:
            score += 1

        # OI rising from previous (84% hit rate)
        if prev_ind is not None and prev_ind.oi > 0 and ind.oi > prev_ind.oi:
            score += 1

        # CVD rising from previous (79% hit rate)
        if prev_ind is not None and prev_ind.cvd != 0 and ind.cvd > prev_ind.cvd:
            score += 1

        return score

    def score_low_pivot(
        self,
        ind: DailyIndicators,
        prev_ind: DailyIndicators | None,
    ) -> int:
        """Score a LOW pivot against ★★★ conditions.

        Each matched condition = 1 point.
        Based on empirical analysis of 20 channel lows across 6 channels.
        """
        score = 0

        # L/S > 1.0 (100% hit rate)
        if ind.ls_ratio > 1.0:
            score += 1

        # LiqR > 1.0 — longs washed (88% hit rate, 8 samples)
        if ind.liq_ratio > 1.0:
            score += 1

        # CVD declining from previous (87% hit rate)
        if prev_ind is not None and prev_ind.cvd != 0 and ind.cvd < prev_ind.cvd:
            score += 1

        # R14 < 45 (85% hit rate)
        if ind.rsi14 < 45:
            score += 1

        # OI declining from previous (80% hit rate)
        if prev_ind is not None and prev_ind.oi > 0 and ind.oi < prev_ind.oi:
            score += 1

        # R3 < 35 (75% hit rate)
        if ind.rsi3 < 35:
            score += 1

        # Taker B/S < 1.0 (75% hit rate, 8 samples)
        if ind.taker_ratio > 0 and ind.taker_ratio < 1.0:
            score += 1

        # R3 < 30 (70% hit rate)
        if ind.rsi3 < 30:
            score += 1

        # R7 < 40 (70% hit rate)
        if ind.rsi7 < 40:
            score += 1

        return score

    def score_crash_momentum(
        self,
        ind: DailyIndicators,
        prev_ind: DailyIndicators | None,
        oi_change_3d_pct: float = 0.0,
    ) -> int:
        """Score crash momentum using ★★★ validated indicators.

        Detects active crash conditions (liquidation cascade in progress).
        Uses the same indicator framework as HIGH/LOW scoring but with
        extreme thresholds that indicate panic selling.

        Each matched condition = 1 point. Score >= 3 = crash mode.

        Conditions (derived from historical crash analysis):
        1. OI 1-day drop (OI declining from previous) — cascade underway
        2. OI 3-day drop > 10% — sustained liquidation cascade
        3. Funding negative (< -0.1%) — panic, shorts paid to short
        4. LiqR > 2.0 — long liquidations >> short (cascade)
        5. Taker B/S < 0.8 — aggressive selling dominance
        6. CVD declining — net selling pressure
        7. RSI(3) < 15 — extreme oversold panic (not yet bounced)
        """
        score = 0

        # 1. OI declining from previous day (same as ★★★ LOW)
        if prev_ind is not None and prev_ind.oi > 0 and ind.oi < prev_ind.oi:
            score += 1

        # 2. OI 3-day drop > 10% — sustained cascade
        if oi_change_3d_pct < -10:
            score += 1

        # 3. Funding deeply negative — panic selling
        if ind.funding_pct < -0.001:
            score += 1

        # 4. LiqR > 2.0 — massive long liquidation cascade
        if ind.liq_ratio > 2.0:
            score += 1

        # 5. Taker sell dominance — aggressive dumping
        if ind.taker_ratio > 0 and ind.taker_ratio < 0.8:
            score += 1

        # 6. CVD declining (same as ★★★ LOW)
        if prev_ind is not None and prev_ind.cvd != 0 and ind.cvd < prev_ind.cvd:
            score += 1

        # 7. RSI(3) extreme oversold — panic, hasn't bounced yet
        if ind.rsi3 < 15:
            score += 1

        return score

    # ── Trendline Math ──

    @staticmethod
    def _linear_fit(points: list[tuple[int, float]]) -> tuple[float | None, float | None]:
        """OLS linear regression. Returns (slope, intercept) or (None, None)."""
        if len(points) < 2:
            return None, None

        n = len(points)
        x_vals = [p[0] for p in points]
        y_vals = [p[1] for p in points]
        x_mean = sum(x_vals) / n
        y_mean = sum(y_vals) / n

        denom = sum((x - x_mean) ** 2 for x in x_vals)
        if denom == 0:
            return None, None

        numer = sum((x - x_mean) * (y - y_mean) for x, y in points)
        slope = numer / denom
        intercept = y_mean - slope * x_mean
        return slope, intercept

    @staticmethod
    def _r_squared(
        points: list[tuple[int, float]],
        slope: float,
        intercept: float,
    ) -> float:
        """Compute R² for a fitted line."""
        if len(points) < 2:
            return 0.0

        y_vals = [p[1] for p in points]
        y_mean = sum(y_vals) / len(y_vals)

        ss_tot = sum((y - y_mean) ** 2 for y in y_vals)
        if ss_tot == 0:
            return 1.0

        ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in points)
        return 1.0 - ss_res / ss_tot
