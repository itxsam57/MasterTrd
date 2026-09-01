from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EvidenceGrade(StrEnum):
    ACADEMIC = "ACADEMIC"
    VENUE_REFERENCE = "VENUE_REFERENCE"
    OPEN_SOURCE_REFERENCE = "OPEN_SOURCE_REFERENCE"
    EXPERIMENTAL = "EXPERIMENTAL"


class RecipeReadiness(StrEnum):
    EXECUTABLE = "EXECUTABLE"
    SPECIALIST_DATA_REQUIRED = "SPECIALIST_DATA_REQUIRED"
    PRIMITIVE_REQUIRED = "PRIMITIVE_REQUIRED"
    PROVIDER_REQUIRED = "PROVIDER_REQUIRED"
    EXPERIMENTAL = "EXPERIMENTAL"


class AssetClass(StrEnum):
    CRYPTO = "CRYPTO"
    EQUITY = "EQUITY"
    FX = "FX"
    FUTURES = "FUTURES"
    COMMODITY = "COMMODITY"
    RATES = "RATES"
    OPTIONS = "OPTIONS"
    PREDICTION = "PREDICTION"
    BETTING = "BETTING"
    MULTI_ASSET = "MULTI_ASSET"


class TradingHorizon(StrEnum):
    SCALP = "SCALP"
    INTRADAY = "INTRADAY"
    SWING = "SWING"
    POSITION = "POSITION"


@dataclass(frozen=True, slots=True)
class StrategySource:
    source_id: str
    title: str
    evidence_grade: EvidenceGrade
    url: str
    note: str


@dataclass(frozen=True, slots=True)
class StrategyRecipe:
    recipe_id: str
    name: str
    family: str
    asset_classes: tuple[AssetClass, ...]
    horizons: tuple[TradingHorizon, ...]
    readiness: RecipeReadiness
    source_ids: tuple[str, ...]
    entry_kind: str | None = None
    exit_kind: str | None = None
    blocker: str | None = None
    tags: tuple[str, ...] = ()


STRATEGY_SOURCES: tuple[StrategySource, ...] = (
    StrategySource(
        "moskowitz-tsmom",
        "Time Series Momentum",
        EvidenceGrade.ACADEMIC,
        "https://doi.org/10.1016/j.jfineco.2011.11.003",
        "Cross-asset time-series momentum evidence; concept source only.",
    ),
    StrategySource(
        "asness-value-momentum",
        "Value and Momentum Everywhere",
        EvidenceGrade.ACADEMIC,
        "https://doi.org/10.1111/jofi.12021",
        "Cross-asset value and momentum evidence; concept source only.",
    ),
    StrategySource(
        "jegadeesh-titman-momentum",
        "Returns to Buying Winners and Selling Losers",
        EvidenceGrade.ACADEMIC,
        "https://doi.org/10.1111/j.1540-6261.1993.tb04702.x",
        "Cross-sectional momentum evidence; concept source only.",
    ),
    StrategySource(
        "gatev-pairs",
        "Pairs Trading: Performance of a Relative-Value Arbitrage Rule",
        EvidenceGrade.ACADEMIC,
        "https://www.nber.org/papers/w7032",
        "Pairs/statistical-arbitrage evidence; concept source only.",
    ),
    StrategySource(
        "koijen-carry",
        "Carry",
        EvidenceGrade.ACADEMIC,
        "https://doi.org/10.1016/j.jfineco.2017.11.002",
        "Cross-asset carry evidence; concept source only.",
    ),
    StrategySource(
        "frazzini-pedersen-bab",
        "Betting Against Beta",
        EvidenceGrade.ACADEMIC,
        "https://doi.org/10.1016/j.jfineco.2013.10.005",
        "Low-beta/BAB factor evidence; concept source only.",
    ),
    StrategySource(
        "novy-marx-profitability",
        "The Other Side of Value: The Gross Profitability Premium",
        EvidenceGrade.ACADEMIC,
        "https://doi.org/10.1016/j.jfineco.2013.01.003",
        "Profitability/quality factor evidence; concept source only.",
    ),
    StrategySource(
        "moreira-muir-vol-managed",
        "Volatility-Managed Portfolios",
        EvidenceGrade.ACADEMIC,
        "https://doi.org/10.1111/jofi.12513",
        "Volatility-managed allocation evidence; concept source only.",
    ),
    StrategySource(
        "avellaneda-stoikov",
        "High-frequency trading in a limit order book",
        EvidenceGrade.ACADEMIC,
        "https://doi.org/10.1080/14697680701381228",
        "Inventory-aware market-making model; specialist evidence still required.",
    ),
    StrategySource(
        "crypto-common-factors",
        "Common Risk Factors in Cryptocurrency",
        EvidenceGrade.ACADEMIC,
        "https://doi.org/10.1111/jofi.13119",
        "Crypto factor and momentum research; concept source only.",
    ),
    StrategySource(
        "aqr-data-library",
        "AQR Data Sets",
        EvidenceGrade.ACADEMIC,
        "https://www.aqr.com/Insights/Datasets",
        "Public factor datasets and research references.",
    ),
    StrategySource(
        "kenneth-french-library",
        "Kenneth R. French Data Library",
        EvidenceGrade.ACADEMIC,
        "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html",
        "Public equity factor and portfolio research data.",
    ),
    StrategySource(
        "quantconnect-strategy-library",
        "QuantConnect Strategy Library",
        EvidenceGrade.OPEN_SOURCE_REFERENCE,
        "https://www.quantconnect.com/docs/v2/writing-algorithms/strategy-library",
        "Implementation/reference taxonomy; not profitability evidence.",
    ),
    StrategySource(
        "hummingbot-strategies",
        "Hummingbot Strategy Examples",
        EvidenceGrade.OPEN_SOURCE_REFERENCE,
        "https://hummingbot.org/strategies/scripts/examples/",
        "Market-making/arbitrage mechanics reference; not profitability evidence.",
    ),
    StrategySource(
        "freqtrade-strategies",
        "Freqtrade Strategy Examples",
        EvidenceGrade.OPEN_SOURCE_REFERENCE,
        "https://github.com/freqtrade/freqtrade-strategies",
        "Idea source only; examples are not treated as proven profitability.",
    ),
    StrategySource(
        "nautilus-integrations",
        "NautilusTrader Integrations",
        EvidenceGrade.VENUE_REFERENCE,
        "https://nautilustrader.io/docs/latest/integrations/",
        "Venue/data-provider capabilities, not strategy profitability evidence.",
    ),
    StrategySource(
        "nautilus-polymarket",
        "NautilusTrader Polymarket Integration",
        EvidenceGrade.VENUE_REFERENCE,
        "https://nautilustrader.io/docs/latest/integrations/polymarket/",
        "Prediction-market mechanics and adapter capability reference.",
    ),
    StrategySource(
        "nautilus-betfair",
        "NautilusTrader Betfair Integration",
        EvidenceGrade.VENUE_REFERENCE,
        "https://nautilustrader.io/docs/latest/integrations/betfair/",
        "Betting-exchange mechanics and adapter capability reference.",
    ),
    StrategySource(
        "nautilus-okx",
        "NautilusTrader OKX Integration",
        EvidenceGrade.VENUE_REFERENCE,
        "https://nautilustrader.io/docs/latest/integrations/okx/",
        "Crypto spot/derivatives/options/spreads/event-contract capability reference.",
    ),
    StrategySource(
        "mastertrd-native",
        "MasterTrd Existing Executable Strategy Semantics",
        EvidenceGrade.EXPERIMENTAL,
        "https://github.com/itxsam57/MasterTrd",
        "Exact recipes backed by current shared research/execution primitives.",
    ),
)


_ALL_TRADITIONAL = (
    AssetClass.EQUITY,
    AssetClass.FX,
    AssetClass.FUTURES,
    AssetClass.COMMODITY,
    AssetClass.RATES,
)
_ALL_LIQUID = (AssetClass.CRYPTO, *_ALL_TRADITIONAL)


def _exact(
    recipe_id: str,
    name: str,
    family: str,
    entry_kind: str,
    exit_kind: str,
    *,
    assets: tuple[AssetClass, ...] = _ALL_LIQUID,
    horizons: tuple[TradingHorizon, ...] = (TradingHorizon.INTRADAY, TradingHorizon.SWING),
    sources: tuple[str, ...] = ("mastertrd-native",),
    tags: tuple[str, ...] = (),
) -> StrategyRecipe:
    return StrategyRecipe(
        recipe_id=recipe_id,
        name=name,
        family=family,
        asset_classes=assets,
        horizons=horizons,
        readiness=RecipeReadiness.EXECUTABLE,
        source_ids=sources,
        entry_kind=entry_kind,
        exit_kind=exit_kind,
        tags=tags,
    )


def _blocked(
    recipe_id: str,
    name: str,
    family: str,
    *,
    assets: tuple[AssetClass, ...],
    horizons: tuple[TradingHorizon, ...],
    readiness: RecipeReadiness,
    sources: tuple[str, ...],
    blocker: str,
    tags: tuple[str, ...] = (),
    entry_kind: str | None = None,
    exit_kind: str | None = None,
) -> StrategyRecipe:
    return StrategyRecipe(
        recipe_id=recipe_id,
        name=name,
        family=family,
        asset_classes=assets,
        horizons=horizons,
        readiness=readiness,
        source_ids=sources,
        entry_kind=entry_kind,
        exit_kind=exit_kind,
        blocker=blocker,
        tags=tags,
    )


_EXECUTABLE_RECIPES: tuple[StrategyRecipe, ...] = (
    _exact("ema-cross-fast", "EMA Cross Fast", "trend", "ema_cross", "cross_reverse", sources=("mastertrd-native", "moskowitz-tsmom")),
    _exact("ema-cross-balanced", "EMA Cross Balanced", "trend", "ema_cross", "cross_reverse", sources=("mastertrd-native", "moskowitz-tsmom")),
    _exact("ema-cross-slow", "EMA Cross Slow", "trend", "ema_cross", "cross_reverse", sources=("mastertrd-native", "moskowitz-tsmom"), horizons=(TradingHorizon.SWING, TradingHorizon.POSITION)),
    _exact("ema-cross-crypto", "EMA Cross Crypto", "trend", "ema_cross", "cross_reverse", assets=(AssetClass.CRYPTO,), sources=("mastertrd-native", "moskowitz-tsmom")),
    _exact("ema-cross-futures", "EMA Cross Futures", "trend", "ema_cross", "cross_reverse", assets=(AssetClass.FUTURES, AssetClass.COMMODITY, AssetClass.RATES), sources=("mastertrd-native", "moskowitz-tsmom")),
    _exact("ema-cross-fx", "EMA Cross FX", "trend", "ema_cross", "cross_reverse", assets=(AssetClass.FX,), sources=("mastertrd-native", "moskowitz-tsmom")),
    _exact("rsi-momentum-fast", "RSI Momentum Fast", "momentum", "rsi_momentum", "atr_bracket", sources=("mastertrd-native", "jegadeesh-titman-momentum")),
    _exact("rsi-momentum-balanced", "RSI Momentum Balanced", "momentum", "rsi_momentum", "atr_bracket", sources=("mastertrd-native", "jegadeesh-titman-momentum")),
    _exact("rsi-momentum-slow", "RSI Momentum Slow", "momentum", "rsi_momentum", "atr_bracket", horizons=(TradingHorizon.SWING, TradingHorizon.POSITION), sources=("mastertrd-native", "jegadeesh-titman-momentum")),
    _exact("rsi-momentum-crypto", "RSI Momentum Crypto", "momentum", "rsi_momentum", "atr_bracket", assets=(AssetClass.CRYPTO,), sources=("mastertrd-native", "crypto-common-factors")),
    _exact("rsi-momentum-equity", "RSI Momentum Equity", "momentum", "rsi_momentum", "atr_bracket", assets=(AssetClass.EQUITY,), sources=("mastertrd-native", "jegadeesh-titman-momentum")),
    _exact("donchian-breakout-20", "Donchian Breakout 20", "breakout", "donchian_breakout", "atr_bracket", sources=("mastertrd-native", "moskowitz-tsmom")),
    _exact("donchian-breakout-55", "Donchian Breakout 55", "breakout", "donchian_breakout", "atr_bracket", sources=("mastertrd-native", "moskowitz-tsmom")),
    _exact("donchian-breakout-fast", "Donchian Breakout Fast", "breakout", "donchian_breakout", "atr_bracket"),
    _exact("donchian-breakout-crypto", "Donchian Breakout Crypto", "breakout", "donchian_breakout", "atr_bracket", assets=(AssetClass.CRYPTO,)),
    _exact("donchian-breakout-futures", "Donchian Breakout Futures", "breakout", "donchian_breakout", "atr_bracket", assets=(AssetClass.FUTURES, AssetClass.COMMODITY, AssetClass.RATES), sources=("mastertrd-native", "moskowitz-tsmom")),
    _exact("zscore-reversion-fast", "Z-Score Reversion Fast", "mean_reversion", "zscore_reversion", "mean_or_atr_stop"),
    _exact("zscore-reversion-balanced", "Z-Score Reversion Balanced", "mean_reversion", "zscore_reversion", "mean_or_atr_stop"),
    _exact("zscore-reversion-slow", "Z-Score Reversion Slow", "mean_reversion", "zscore_reversion", "mean_or_atr_stop", horizons=(TradingHorizon.SWING, TradingHorizon.POSITION)),
    _exact("zscore-reversion-crypto", "Z-Score Reversion Crypto", "mean_reversion", "zscore_reversion", "mean_or_atr_stop", assets=(AssetClass.CRYPTO,)),
    _exact("zscore-reversion-equity", "Z-Score Reversion Equity", "mean_reversion", "zscore_reversion", "mean_or_atr_stop", assets=(AssetClass.EQUITY,)),
    _exact("atr-vol-breakout-fast", "ATR Volatility Breakout Fast", "volatility", "volatility_breakout", "atr_bracket"),
    _exact("atr-vol-breakout-balanced", "ATR Volatility Breakout Balanced", "volatility", "volatility_breakout", "atr_bracket"),
    _exact("atr-vol-breakout-slow", "ATR Volatility Breakout Slow", "volatility", "volatility_breakout", "atr_bracket", horizons=(TradingHorizon.SWING, TradingHorizon.POSITION)),
    _exact("atr-vol-breakout-crypto", "ATR Volatility Breakout Crypto", "volatility", "volatility_breakout", "atr_bracket", assets=(AssetClass.CRYPTO,)),
    _exact("pullback-trend-fast", "Pullback Trend Fast", "swing", "pullback_trend", "atr_bracket", horizons=(TradingHorizon.INTRADAY, TradingHorizon.SWING)),
    _exact("pullback-trend-balanced", "Pullback Trend Balanced", "swing", "pullback_trend", "atr_bracket", horizons=(TradingHorizon.SWING,)),
    _exact("pullback-trend-crypto", "Pullback Trend Crypto", "swing", "pullback_trend", "atr_bracket", assets=(AssetClass.CRYPTO,), horizons=(TradingHorizon.SWING,)),
    _exact("pullback-trend-fx", "Pullback Trend FX", "swing", "pullback_trend", "atr_bracket", assets=(AssetClass.FX,), horizons=(TradingHorizon.SWING,)),
    _exact("long-horizon-trend-balanced", "Long-Horizon Trend Balanced", "position", "long_horizon_trend", "trailing_atr", horizons=(TradingHorizon.POSITION,), sources=("mastertrd-native", "moskowitz-tsmom")),
    _exact("long-horizon-trend-slow", "Long-Horizon Trend Slow", "position", "long_horizon_trend", "trailing_atr", horizons=(TradingHorizon.POSITION,), sources=("mastertrd-native", "moskowitz-tsmom")),
    _exact("long-horizon-trend-futures", "Long-Horizon Trend Futures", "position", "long_horizon_trend", "trailing_atr", assets=(AssetClass.FUTURES, AssetClass.COMMODITY, AssetClass.RATES), horizons=(TradingHorizon.POSITION,), sources=("mastertrd-native", "moskowitz-tsmom")),
    _exact("pairs-cointegration-balanced", "Cointegration Pairs Balanced", "stat_arb", "cointegration_spread", "spread_mean_exit", sources=("mastertrd-native", "gatev-pairs")),
    _exact("pairs-cointegration-slow", "Cointegration Pairs Slow", "stat_arb", "cointegration_spread", "spread_mean_exit", horizons=(TradingHorizon.SWING, TradingHorizon.POSITION), sources=("mastertrd-native", "gatev-pairs")),
    _exact("crypto-funding-basis", "Crypto Funding Basis", "funding_basis", "funding_basis", "edge_decay", assets=(AssetClass.CRYPTO,), sources=("mastertrd-native", "koijen-carry")),
    _exact("crypto-hedged-basis", "Crypto Hedged Basis", "delta_neutral", "hedged_basis", "rebalance", assets=(AssetClass.CRYPTO,), sources=("mastertrd-native", "koijen-carry")),
    _exact("multi-asset-momentum-rotation", "Multi-Asset Momentum Rotation", "portfolio", "strategy_rotation", "rebalance", assets=(AssetClass.MULTI_ASSET,), horizons=(TradingHorizon.SWING, TradingHorizon.POSITION), sources=("mastertrd-native", "asness-value-momentum")),
    _exact("crypto-momentum-rotation", "Crypto Momentum Rotation", "portfolio", "strategy_rotation", "rebalance", assets=(AssetClass.CRYPTO,), sources=("mastertrd-native", "crypto-common-factors")),
)


_SPECIALIST_RECIPES: tuple[StrategyRecipe, ...] = (
    _blocked("options-iv-rv-defined-risk", "Options IV/RV Defined-Risk", "options", assets=(AssetClass.OPTIONS,), horizons=(TradingHorizon.SWING,), readiness=RecipeReadiness.SPECIALIST_DATA_REQUIRED, sources=("mastertrd-native",), blocker="qualifying_option_chain_and_greeks_data_required", entry_kind="volatility_signal", exit_kind="greeks_or_time_exit"),
    _blocked("crypto-micro-momentum", "Crypto Micro Momentum Scalper", "scalping", assets=(AssetClass.CRYPTO,), horizons=(TradingHorizon.SCALP,), readiness=RecipeReadiness.SPECIALIST_DATA_REQUIRED, sources=("mastertrd-native", "hummingbot-strategies"), blocker="qualifying_real_tick_evidence_required", entry_kind="micro_momentum", exit_kind="ticks_or_timeout"),
    _blocked("crypto-dynamic-grid", "Crypto Dynamic Grid", "grid", assets=(AssetClass.CRYPTO,), horizons=(TradingHorizon.SCALP, TradingHorizon.INTRADAY), readiness=RecipeReadiness.SPECIALIST_DATA_REQUIRED, sources=("mastertrd-native", "hummingbot-strategies"), blocker="qualifying_real_tick_evidence_required", entry_kind="dynamic_grid", exit_kind="inventory_exit"),
    _blocked("inventory-skew-market-maker", "Inventory-Skew Market Maker", "market_making", assets=(AssetClass.CRYPTO,), horizons=(TradingHorizon.SCALP,), readiness=RecipeReadiness.SPECIALIST_DATA_REQUIRED, sources=("mastertrd-native", "avellaneda-stoikov", "hummingbot-strategies"), blocker="qualifying_real_l2_queue_latency_evidence_required", entry_kind="inventory_skew_mm", exit_kind="inventory_flatten"),
    _blocked("order-book-imbalance", "Order-Book Imbalance", "order_book", assets=(AssetClass.CRYPTO,), horizons=(TradingHorizon.SCALP,), readiness=RecipeReadiness.SPECIALIST_DATA_REQUIRED, sources=("mastertrd-native",), blocker="qualifying_real_l2_queue_latency_evidence_required", entry_kind="order_book_imbalance", exit_kind="imbalance_reversal_or_ticks"),
    _blocked("cross-venue-spread-crypto", "Cross-Venue Crypto Spread", "cross_venue_arb", assets=(AssetClass.CRYPTO,), horizons=(TradingHorizon.SCALP, TradingHorizon.INTRADAY), readiness=RecipeReadiness.SPECIALIST_DATA_REQUIRED, sources=("mastertrd-native", "hummingbot-strategies"), blocker="qualifying_synchronized_cross_venue_tick_evidence_required", entry_kind="cross_venue_spread", exit_kind="spread_convergence"),
)


# Research targets are intentionally cataloged even when MasterTrd cannot yet
# represent them exactly. A blocker is part of the contract, not a TODO hidden
# behind a proxy signal.
_TARGET_SPECS = (
    ("cross-sectional-momentum", "Cross-Sectional Momentum", "momentum", (AssetClass.EQUITY, AssetClass.FUTURES, AssetClass.FX, AssetClass.CRYPTO), (TradingHorizon.SWING, TradingHorizon.POSITION), "jegadeesh-titman-momentum"),
    ("dual-momentum", "Dual Momentum", "momentum", (AssetClass.MULTI_ASSET,), (TradingHorizon.POSITION,), "asness-value-momentum"),
    ("residual-momentum", "Residual Momentum", "momentum", (AssetClass.EQUITY,), (TradingHorizon.SWING, TradingHorizon.POSITION), "quantconnect-strategy-library"),
    ("sector-momentum", "Sector Momentum", "momentum", (AssetClass.EQUITY,), (TradingHorizon.SWING, TradingHorizon.POSITION), "quantconnect-strategy-library"),
    ("industry-momentum", "Industry Momentum", "momentum", (AssetClass.EQUITY,), (TradingHorizon.SWING, TradingHorizon.POSITION), "quantconnect-strategy-library"),
    ("country-momentum", "Country Momentum", "momentum", (AssetClass.EQUITY,), (TradingHorizon.POSITION,), "quantconnect-strategy-library"),
    ("52-week-high-momentum", "52-Week High Momentum", "momentum", (AssetClass.EQUITY,), (TradingHorizon.SWING, TradingHorizon.POSITION), "quantconnect-strategy-library"),
    ("earnings-momentum", "Earnings Momentum", "momentum", (AssetClass.EQUITY,), (TradingHorizon.SWING,), "quantconnect-strategy-library"),
    ("intraday-momentum", "Intraday Momentum", "momentum", (AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.FUTURES), (TradingHorizon.INTRADAY,), "quantconnect-strategy-library"),
    ("volume-confirmed-momentum", "Volume-Confirmed Momentum", "momentum", (AssetClass.CRYPTO, AssetClass.EQUITY, AssetClass.FUTURES), (TradingHorizon.INTRADAY, TradingHorizon.SWING), "freqtrade-strategies"),
    ("absolute-momentum", "Absolute Momentum", "momentum", (AssetClass.MULTI_ASSET,), (TradingHorizon.POSITION,), "asness-value-momentum"),
    ("factor-momentum", "Factor Momentum", "momentum", (AssetClass.EQUITY, AssetClass.MULTI_ASSET), (TradingHorizon.POSITION,), "aqr-data-library"),
    ("bollinger-reversion", "Bollinger Band Reversion", "mean_reversion", (AssetClass.CRYPTO, AssetClass.EQUITY, AssetClass.FX, AssetClass.FUTURES), (TradingHorizon.INTRADAY, TradingHorizon.SWING), "freqtrade-strategies"),
    ("rsi2-reversion", "RSI-2 Reversion", "mean_reversion", (AssetClass.EQUITY, AssetClass.CRYPTO), (TradingHorizon.INTRADAY, TradingHorizon.SWING), "quantconnect-strategy-library"),
    ("vwap-reversion", "VWAP Reversion", "mean_reversion", (AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.FUTURES), (TradingHorizon.INTRADAY,), "quantconnect-strategy-library"),
    ("gap-fade", "Gap Fade", "mean_reversion", (AssetClass.EQUITY, AssetClass.FUTURES), (TradingHorizon.INTRADAY,), "quantconnect-strategy-library"),
    ("failed-breakout-reversal", "Failed Breakout Reversal", "mean_reversion", (AssetClass.CRYPTO, AssetClass.EQUITY, AssetClass.FUTURES), (TradingHorizon.INTRADAY, TradingHorizon.SWING), "quantconnect-strategy-library"),
    ("liquidity-shock-reversal", "Liquidity Shock Reversal", "mean_reversion", (AssetClass.EQUITY, AssetClass.CRYPTO), (TradingHorizon.INTRADAY,), "quantconnect-strategy-library"),
    ("kalman-pairs", "Kalman Filter Pairs", "stat_arb", (AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.FUTURES), (TradingHorizon.INTRADAY, TradingHorizon.SWING), "gatev-pairs"),
    ("pca-residual-stat-arb", "PCA Residual Statistical Arbitrage", "stat_arb", (AssetClass.EQUITY, AssetClass.CRYPTO), (TradingHorizon.INTRADAY, TradingHorizon.SWING), "gatev-pairs"),
    ("copula-pairs", "Copula Pairs Trading", "stat_arb", (AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.FX), (TradingHorizon.SWING,), "gatev-pairs"),
    ("basket-cointegration", "Basket Cointegration", "stat_arb", (AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.FX), (TradingHorizon.SWING,), "gatev-pairs"),
    ("opening-range-breakout", "Opening Range Breakout", "breakout", (AssetClass.EQUITY, AssetClass.FUTURES, AssetClass.FX), (TradingHorizon.INTRADAY,), "quantconnect-strategy-library"),
    ("dual-thrust", "Dual Thrust Breakout", "breakout", (AssetClass.CRYPTO, AssetClass.FUTURES), (TradingHorizon.INTRADAY,), "quantconnect-strategy-library"),
    ("bollinger-squeeze-breakout", "Bollinger Squeeze Breakout", "breakout", (AssetClass.CRYPTO, AssetClass.EQUITY, AssetClass.FX), (TradingHorizon.INTRADAY, TradingHorizon.SWING), "freqtrade-strategies"),
    ("nr7-breakout", "NR7 Range Compression Breakout", "breakout", (AssetClass.EQUITY, AssetClass.FUTURES), (TradingHorizon.INTRADAY,), "quantconnect-strategy-library"),
    ("vwap-breakout", "VWAP Breakout", "breakout", (AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.FUTURES), (TradingHorizon.INTRADAY,), "quantconnect-strategy-library"),
    ("supertrend", "SuperTrend", "trend", (AssetClass.CRYPTO, AssetClass.EQUITY, AssetClass.FX, AssetClass.FUTURES), (TradingHorizon.INTRADAY, TradingHorizon.SWING), "freqtrade-strategies"),
    ("ichimoku-trend", "Ichimoku Trend", "trend", (AssetClass.CRYPTO, AssetClass.EQUITY, AssetClass.FX), (TradingHorizon.SWING,), "freqtrade-strategies"),
    ("adx-dmi-trend", "ADX/DMI Trend", "trend", (AssetClass.CRYPTO, AssetClass.EQUITY, AssetClass.FX, AssetClass.FUTURES), (TradingHorizon.INTRADAY, TradingHorizon.SWING), "freqtrade-strategies"),
    ("parabolic-sar-trend", "Parabolic SAR Trend", "trend", (AssetClass.CRYPTO, AssetClass.EQUITY, AssetClass.FX), (TradingHorizon.INTRADAY, TradingHorizon.SWING), "freqtrade-strategies"),
    ("macd-trend", "MACD Trend", "trend", (AssetClass.CRYPTO, AssetClass.EQUITY, AssetClass.FX, AssetClass.FUTURES), (TradingHorizon.INTRADAY, TradingHorizon.SWING), "freqtrade-strategies"),
    ("equity-value", "Equity Value", "position", (AssetClass.EQUITY,), (TradingHorizon.POSITION,), "asness-value-momentum"),
    ("gross-profitability", "Gross Profitability", "position", (AssetClass.EQUITY,), (TradingHorizon.POSITION,), "novy-marx-profitability"),
    ("quality-minus-junk", "Quality / Profitability Composite", "position", (AssetClass.EQUITY,), (TradingHorizon.POSITION,), "aqr-data-library"),
    ("betting-against-beta", "Betting Against Beta", "position", (AssetClass.EQUITY,), (TradingHorizon.POSITION,), "frazzini-pedersen-bab"),
    ("low-volatility-equity", "Low Volatility Equity", "position", (AssetClass.EQUITY,), (TradingHorizon.POSITION,), "quantconnect-strategy-library"),
    ("post-earnings-announcement-drift", "Post-Earnings Announcement Drift", "swing", (AssetClass.EQUITY,), (TradingHorizon.SWING,), "quantconnect-strategy-library"),
    ("overnight-anomaly", "Overnight Anomaly", "swing", (AssetClass.EQUITY,), (TradingHorizon.INTRADAY, TradingHorizon.SWING), "quantconnect-strategy-library"),
    ("turn-of-month", "Turn-of-Month", "swing", (AssetClass.EQUITY, AssetClass.FUTURES), (TradingHorizon.SWING,), "quantconnect-strategy-library"),
    ("pre-holiday", "Pre-Holiday Effect", "swing", (AssetClass.EQUITY,), (TradingHorizon.SWING,), "quantconnect-strategy-library"),
    ("fx-carry", "FX Carry", "funding_basis", (AssetClass.FX,), (TradingHorizon.SWING, TradingHorizon.POSITION), "koijen-carry"),
    ("fx-value", "FX Value / PPP", "position", (AssetClass.FX,), (TradingHorizon.POSITION,), "asness-value-momentum"),
    ("fx-cross-sectional-momentum", "FX Cross-Sectional Momentum", "momentum", (AssetClass.FX,), (TradingHorizon.SWING, TradingHorizon.POSITION), "asness-value-momentum"),
    ("fx-session-breakout", "FX Session Breakout", "breakout", (AssetClass.FX,), (TradingHorizon.INTRADAY,), "quantconnect-strategy-library"),
    ("fx-triangular-arbitrage", "FX Triangular Arbitrage", "cross_venue_arb", (AssetClass.FX,), (TradingHorizon.SCALP,), "quantconnect-strategy-library"),
    ("commodity-roll-yield", "Commodity Roll Yield", "funding_basis", (AssetClass.COMMODITY, AssetClass.FUTURES), (TradingHorizon.SWING, TradingHorizon.POSITION), "koijen-carry"),
    ("commodity-term-structure", "Commodity Term Structure", "funding_basis", (AssetClass.COMMODITY, AssetClass.FUTURES), (TradingHorizon.SWING, TradingHorizon.POSITION), "koijen-carry"),
    ("commodity-seasonality", "Commodity Seasonality", "position", (AssetClass.COMMODITY, AssetClass.FUTURES), (TradingHorizon.POSITION,), "quantconnect-strategy-library"),
    ("calendar-spread-futures", "Futures Calendar Spread", "stat_arb", (AssetClass.FUTURES, AssetClass.COMMODITY), (TradingHorizon.SWING,), "quantconnect-strategy-library"),
    ("crack-spread", "Crack Spread", "stat_arb", (AssetClass.COMMODITY, AssetClass.FUTURES), (TradingHorizon.SWING,), "quantconnect-strategy-library"),
    ("bond-carry-roll-down", "Bond Carry and Roll-Down", "funding_basis", (AssetClass.RATES,), (TradingHorizon.POSITION,), "koijen-carry"),
    ("yield-curve-steepener", "Yield Curve Steepener", "stat_arb", (AssetClass.RATES, AssetClass.FUTURES), (TradingHorizon.SWING, TradingHorizon.POSITION), "quantconnect-strategy-library"),
    ("yield-curve-flattener", "Yield Curve Flattener", "stat_arb", (AssetClass.RATES, AssetClass.FUTURES), (TradingHorizon.SWING, TradingHorizon.POSITION), "quantconnect-strategy-library"),
    ("yield-curve-butterfly", "Yield Curve Butterfly", "stat_arb", (AssetClass.RATES, AssetClass.FUTURES), (TradingHorizon.SWING, TradingHorizon.POSITION), "quantconnect-strategy-library"),
    ("spot-perp-cash-carry", "Spot/Perpetual Cash-and-Carry", "funding_basis", (AssetClass.CRYPTO,), (TradingHorizon.INTRADAY, TradingHorizon.SWING), "hummingbot-strategies"),
    ("perp-funding-differential", "Perpetual Funding Differential", "funding_basis", (AssetClass.CRYPTO,), (TradingHorizon.INTRADAY, TradingHorizon.SWING), "hummingbot-strategies"),
    ("crypto-calendar-basis", "Crypto Futures Calendar Basis", "funding_basis", (AssetClass.CRYPTO,), (TradingHorizon.SWING,), "koijen-carry"),
    ("stablecoin-dislocation", "Stablecoin Dislocation", "mean_reversion", (AssetClass.CRYPTO,), (TradingHorizon.INTRADAY,), "hummingbot-strategies"),
    ("cex-dex-arbitrage", "CEX/DEX Arbitrage", "cross_venue_arb", (AssetClass.CRYPTO,), (TradingHorizon.SCALP, TradingHorizon.INTRADAY), "hummingbot-strategies"),
    ("dex-dex-arbitrage", "DEX/DEX Arbitrage", "cross_venue_arb", (AssetClass.CRYPTO,), (TradingHorizon.SCALP, TradingHorizon.INTRADAY), "hummingbot-strategies"),
    ("crypto-triangular-arbitrage", "Crypto Triangular Arbitrage", "cross_venue_arb", (AssetClass.CRYPTO,), (TradingHorizon.SCALP,), "hummingbot-strategies"),
    ("crypto-lead-lag", "Crypto Cross-Venue Lead/Lag", "cross_venue_arb", (AssetClass.CRYPTO,), (TradingHorizon.SCALP,), "hummingbot-strategies"),
    ("funding-open-interest-regime", "Funding and Open-Interest Regime", "volatility", (AssetClass.CRYPTO,), (TradingHorizon.INTRADAY, TradingHorizon.SWING), "crypto-common-factors"),
    ("liquidation-regime", "Liquidation Regime", "volatility", (AssetClass.CRYPTO,), (TradingHorizon.INTRADAY,), "crypto-common-factors"),
    ("avellaneda-stoikov-mm", "Avellaneda-Stoikov Market Making", "market_making", (AssetClass.CRYPTO,), (TradingHorizon.SCALP,), "avellaneda-stoikov"),
    ("queue-aware-mm", "Queue-Aware Market Making", "market_making", (AssetClass.CRYPTO,), (TradingHorizon.SCALP,), "hummingbot-strategies"),
    ("microprice-scalper", "Microprice Scalper", "order_book", (AssetClass.CRYPTO, AssetClass.FUTURES), (TradingHorizon.SCALP,), "mastertrd-native"),
    ("trade-flow-imbalance", "Trade-Flow Imbalance", "order_book", (AssetClass.CRYPTO, AssetClass.FUTURES), (TradingHorizon.SCALP,), "mastertrd-native"),
    ("queue-imbalance", "Queue Imbalance", "order_book", (AssetClass.CRYPTO, AssetClass.FUTURES), (TradingHorizon.SCALP,), "mastertrd-native"),
    ("volatility-sensitive-quoting", "Volatility-Sensitive Quoting", "market_making", (AssetClass.CRYPTO, AssetClass.FUTURES), (TradingHorizon.SCALP,), "avellaneda-stoikov"),
    ("options-volatility-risk-premium", "Options Volatility Risk Premium", "options", (AssetClass.OPTIONS,), (TradingHorizon.SWING, TradingHorizon.POSITION), "quantconnect-strategy-library"),
    ("options-delta-neutral-straddle", "Delta-Neutral Straddle", "options", (AssetClass.OPTIONS,), (TradingHorizon.SWING,), "quantconnect-strategy-library"),
    ("options-delta-neutral-strangle", "Delta-Neutral Strangle", "options", (AssetClass.OPTIONS,), (TradingHorizon.SWING,), "quantconnect-strategy-library"),
    ("options-put-write", "Put Write", "options", (AssetClass.OPTIONS,), (TradingHorizon.SWING, TradingHorizon.POSITION), "quantconnect-strategy-library"),
    ("options-covered-call", "Covered Call", "options", (AssetClass.OPTIONS,), (TradingHorizon.SWING, TradingHorizon.POSITION), "quantconnect-strategy-library"),
    ("options-iron-condor", "Iron Condor", "options", (AssetClass.OPTIONS,), (TradingHorizon.SWING,), "quantconnect-strategy-library"),
    ("options-calendar-spread", "Options Calendar Spread", "options", (AssetClass.OPTIONS,), (TradingHorizon.SWING,), "quantconnect-strategy-library"),
    ("options-skew-risk-reversal", "Options Skew / Risk Reversal", "options", (AssetClass.OPTIONS,), (TradingHorizon.SWING,), "quantconnect-strategy-library"),
    ("options-gamma-scalping", "Gamma Scalping", "options", (AssetClass.OPTIONS,), (TradingHorizon.INTRADAY, TradingHorizon.SWING), "quantconnect-strategy-library"),
    ("options-dispersion", "Options Dispersion", "options", (AssetClass.OPTIONS,), (TradingHorizon.SWING,), "quantconnect-strategy-library"),
    ("minimum-variance-portfolio", "Minimum Variance Portfolio", "portfolio", (AssetClass.MULTI_ASSET,), (TradingHorizon.SWING, TradingHorizon.POSITION), "moreira-muir-vol-managed"),
    ("risk-parity", "Risk Parity", "portfolio", (AssetClass.MULTI_ASSET,), (TradingHorizon.SWING, TradingHorizon.POSITION), "moreira-muir-vol-managed"),
    ("inverse-volatility", "Inverse Volatility Allocation", "portfolio", (AssetClass.MULTI_ASSET,), (TradingHorizon.SWING, TradingHorizon.POSITION), "moreira-muir-vol-managed"),
    ("maximum-diversification", "Maximum Diversification", "portfolio", (AssetClass.MULTI_ASSET,), (TradingHorizon.SWING, TradingHorizon.POSITION), "moreira-muir-vol-managed"),
    ("trend-carry-portfolio", "Trend + Carry Portfolio", "portfolio", (AssetClass.MULTI_ASSET,), (TradingHorizon.SWING, TradingHorizon.POSITION), "koijen-carry"),
    ("value-momentum-quality", "Value + Momentum + Quality", "portfolio", (AssetClass.MULTI_ASSET,), (TradingHorizon.POSITION,), "asness-value-momentum"),
    ("regime-switching-allocation", "Regime-Switching Allocation", "portfolio", (AssetClass.MULTI_ASSET,), (TradingHorizon.SWING, TradingHorizon.POSITION), "moreira-muir-vol-managed"),
    ("polymarket-probability-value", "Polymarket Probability Value", "mean_reversion", (AssetClass.PREDICTION,), (TradingHorizon.INTRADAY, TradingHorizon.SWING), "nautilus-polymarket"),
    ("polymarket-cross-market-arb", "Polymarket Cross-Market Arbitrage", "stat_arb", (AssetClass.PREDICTION,), (TradingHorizon.INTRADAY,), "nautilus-polymarket"),
    ("polymarket-order-book-mm", "Polymarket Order-Book Market Making", "market_making", (AssetClass.PREDICTION,), (TradingHorizon.SCALP,), "nautilus-polymarket"),
    ("polymarket-related-event-spread", "Polymarket Related-Event Spread", "stat_arb", (AssetClass.PREDICTION,), (TradingHorizon.INTRADAY, TradingHorizon.SWING), "nautilus-polymarket"),
    ("betfair-book-imbalance", "Betfair Book Imbalance", "order_book", (AssetClass.BETTING,), (TradingHorizon.SCALP, TradingHorizon.INTRADAY), "nautilus-betfair"),
    ("betfair-market-making", "Betfair Market Making", "market_making", (AssetClass.BETTING,), (TradingHorizon.SCALP,), "nautilus-betfair"),
    ("betfair-cross-market-relative-value", "Betfair Cross-Market Relative Value", "stat_arb", (AssetClass.BETTING,), (TradingHorizon.INTRADAY,), "nautilus-betfair"),
    ("event-contract-relative-value", "Event-Contract Relative Value", "stat_arb", (AssetClass.PREDICTION,), (TradingHorizon.INTRADAY, TradingHorizon.SWING), "nautilus-okx"),
    ("gradient-boosting-factor-ranker", "Gradient-Boosting Factor Ranker", "portfolio", (AssetClass.MULTI_ASSET,), (TradingHorizon.SWING, TradingHorizon.POSITION), "quantconnect-strategy-library"),
    ("random-forest-regime", "Random-Forest Regime Model", "portfolio", (AssetClass.MULTI_ASSET,), (TradingHorizon.SWING,), "quantconnect-strategy-library"),
    ("autoencoder-residual-stat-arb", "Autoencoder Residual Statistical Arbitrage", "stat_arb", (AssetClass.EQUITY, AssetClass.CRYPTO), (TradingHorizon.INTRADAY, TradingHorizon.SWING), "quantconnect-strategy-library"),
    ("meta-labeling", "Meta-Labeling", "portfolio", (AssetClass.MULTI_ASSET,), (TradingHorizon.INTRADAY, TradingHorizon.SWING), "quantconnect-strategy-library"),
    ("reinforcement-learning-allocation", "Reinforcement Learning Allocation", "portfolio", (AssetClass.MULTI_ASSET,), (TradingHorizon.SWING, TradingHorizon.POSITION), "quantconnect-strategy-library"),
)


def _target_recipe(spec: tuple) -> StrategyRecipe:
    recipe_id, name, family, assets, horizons, source_id = spec
    provider_required = AssetClass.PREDICTION in assets or AssetClass.BETTING in assets
    specialist_required = family in {"market_making", "order_book", "scalping", "grid", "cross_venue_arb", "options"}
    if provider_required:
        readiness = RecipeReadiness.PROVIDER_REQUIRED
        blocker = "provider_not_admitted_to_mastertrd_runtime"
    elif specialist_required:
        readiness = RecipeReadiness.SPECIALIST_DATA_REQUIRED
        blocker = "exact_specialist_primitive_and_qualifying_market_data_required"
    else:
        readiness = RecipeReadiness.PRIMITIVE_REQUIRED
        blocker = "exact_strategy_primitive_not_yet_implemented"
    return _blocked(
        recipe_id,
        name,
        family,
        assets=assets,
        horizons=horizons,
        readiness=readiness,
        sources=(source_id,),
        blocker=blocker,
    )


STRATEGY_RECIPES: tuple[StrategyRecipe, ...] = (
    *_EXECUTABLE_RECIPES,
    *_SPECIALIST_RECIPES,
    *tuple(_target_recipe(spec) for spec in _TARGET_SPECS),
)


def strategy_recipe(recipe_id: str) -> StrategyRecipe:
    for recipe in STRATEGY_RECIPES:
        if recipe.recipe_id == recipe_id:
            return recipe
    raise ValueError(f"unknown strategy recipe: {recipe_id}")


def recipes_for(
    *,
    family: str | None = None,
    asset_class: AssetClass | None = None,
    readiness: RecipeReadiness | None = None,
) -> tuple[StrategyRecipe, ...]:
    return tuple(
        recipe
        for recipe in STRATEGY_RECIPES
        if (family is None or recipe.family == family)
        and (asset_class is None or asset_class in recipe.asset_classes)
        and (readiness is None or recipe.readiness is readiness)
    )
