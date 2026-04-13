"""BTCUSDT D1 Final Strategy — namespace index.

This package is the single entry point for the production strategy.
All modules are re-exported from their canonical locations in src/.
No strategy logic lives here — only imports.

Production-critical modules:
    .config         — canonical cell configs + deployment configs
    .signals        — rsi_only_signals, rsi_and_macd_signals
    .filters        — side_filter, funding_filter
    .sizing         — dynamic sizing + adaptive hold
    .backtest       — V2 backtester
    .execution      — execution layer (4h regime + 1h pullback)
    .monitor        — live monitor state machine
    .runner         — paper runner + live service
    .stress         — stress test suite
    .reconciliation — weekly reconciliation
"""

# Config / canonical baseline
from strategies.strategy_c_v2_canonical_baseline import (
    CANONICAL_CELLS,
    CanonicalCell,
    CanonicalCellConfig,
    CanonicalMetrics,
    D1_LONG_PRIMARY,
    get_canonical_cell,
    get_primary_cell,
    get_backup_cell,
    list_shadow_cells,
)

# Signals
from strategies.strategy_c_v2_literature import (
    rsi_only_signals,
    rsi_and_macd_signals,
)

# Filters
from strategies.strategy_c_v2_filters import (
    apply_side_filter,
    apply_funding_filter,
)

# Sizing
from strategies.strategy_c_v2_dynamic_sizing import (
    DynamicSizingConfig,
    AdaptiveHoldConfig,
    compute_sizing_multiplier,
    compute_hold_override,
    compute_position_frac_override,
    compute_hold_bars_override_vector,
)

# Live monitor
from strategies.strategy_c_v2_live_monitor import (
    MonitorConfig,
    MonitorState,
    LivePositionState,
    compute_monitor_state,
)

# Deployment configs
from execution.live_executor import (
    DEPLOYMENT_CONFIGS,
    LiveDeploymentConfig,
    CapitalConfig,
)
