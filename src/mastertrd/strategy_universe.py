from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import random
from typing import Sequence

from mastertrd.genome import StrategyGenome
from mastertrd.strategy_families import DataLevel, family_spec


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
    StrategySource("moskowitz-tsmom", "Time Series Momentum", EvidenceGrade.ACADEMIC, "https://doi.org/10.1016/j.jfineco.2011.11.003", "Cross-asset trend evidence; concept source only."),
    StrategySource("asness-value-momentum", "Value and Momentum Everywhere", EvidenceGrade.ACADEMIC, "https://doi.org/10.1111/jofi.12021", "Cross-asset value and momentum evidence; concept source only."),
    StrategySource("jegadeesh-titman", "Returns to Buying Winners and Selling Losers", EvidenceGrade.ACADEMIC, "https://doi.org/10.1111/j.1540-6261.1993.tb04702.x", "Cross-sectional momentum evidence; concept source only."),
    StrategySource("gatev-pairs", "Pairs Trading", EvidenceGrade.ACADEMIC, "https://www.nber.org/papers/w7032", "Pairs/statistical-arbitrage evidence; concept source only."),
    StrategySource("koijen-carry", "Carry", EvidenceGrade.ACADEMIC, "https://doi.org/10.1016/j.jfineco.2017.11.002", "Cross-asset carry evidence; concept source only."),
    StrategySource("frazzini-bab", "Betting Against Beta", EvidenceGrade.ACADEMIC, "https://doi.org/10.1016/j.jfineco.2013.10.005", "Low-beta/BAB evidence; concept source only."),
    StrategySource("novy-marx", "Gross Profitability Premium", EvidenceGrade.ACADEMIC, "https://doi.org/10.1016/j.jfineco.2013.01.003", "Profitability/quality evidence; concept source only."),
    StrategySource("moreira-muir", "Volatility-Managed Portfolios", EvidenceGrade.ACADEMIC, "https://doi.org/10.1111/jofi.12513", "Volatility-managed allocation evidence; concept source only."),
    StrategySource("avellaneda-stoikov", "High-frequency trading in a limit order book", EvidenceGrade.ACADEMIC, "https://doi.org/10.1080/14697680701381228", "Inventory-aware market-making model."),
    StrategySource("crypto-factors", "Common Risk Factors in Cryptocurrency", EvidenceGrade.ACADEMIC, "https://doi.org/10.1111/jofi.13119", "Crypto factor/momentum evidence; concept source only."),
    StrategySource("aqr-data", "AQR Data Sets", EvidenceGrade.ACADEMIC, "https://www.aqr.com/Insights/Datasets", "Public factor data and research references."),
    StrategySource("french-data", "Kenneth R. French Data Library", EvidenceGrade.ACADEMIC, "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html", "Public equity factor data."),
    StrategySource("quantconnect-library", "QuantConnect Strategy Library", EvidenceGrade.OPEN_SOURCE_REFERENCE, "https://www.quantconnect.com/docs/v2/writing-algorithms/strategy-library", "Taxonomy/implementation reference, not profitability evidence."),
    StrategySource("hummingbot", "Hummingbot Strategy Examples", EvidenceGrade.OPEN_SOURCE_REFERENCE, "https://hummingbot.org/strategies/scripts/examples/", "Market-making/arbitrage mechanics reference."),
    StrategySource("freqtrade", "Freqtrade Strategy Examples", EvidenceGrade.OPEN_SOURCE_REFERENCE, "https://github.com/freqtrade/freqtrade-strategies", "Idea source only; examples are not proof of profitability."),
    StrategySource("nautilus-integrations", "NautilusTrader Integrations", EvidenceGrade.VENUE_REFERENCE, "https://nautilustrader.io/docs/latest/integrations/", "Venue/data-provider capability reference."),
    StrategySource("nautilus-polymarket", "NautilusTrader Polymarket Integration", EvidenceGrade.VENUE_REFERENCE, "https://nautilustrader.io/docs/latest/integrations/polymarket/", "Prediction-market mechanics reference."),
    StrategySource("nautilus-betfair", "NautilusTrader Betfair Integration", EvidenceGrade.VENUE_REFERENCE, "https://nautilustrader.io/docs/latest/integrations/betfair/", "Betting-exchange mechanics reference."),
    StrategySource("nautilus-okx", "NautilusTrader OKX Integration", EvidenceGrade.VENUE_REFERENCE, "https://nautilustrader.io/docs/latest/integrations/okx/", "Crypto derivatives/options/event-contract reference."),
    StrategySource("mastertrd-native", "MasterTrd Existing Executable Semantics", EvidenceGrade.EXPERIMENTAL, "https://github.com/itxsam57/MasterTrd", "Exact current research/execution primitives."),
)


ALL_LIQUID = (AssetClass.CRYPTO, AssetClass.EQUITY, AssetClass.FX, AssetClass.FUTURES, AssetClass.COMMODITY, AssetClass.RATES)
BAR_HORIZONS = (TradingHorizon.INTRADAY, TradingHorizon.SWING)


def _exact(recipe_id: str, name: str, family: str, entry: str, exit_kind: str, *, assets: tuple[AssetClass, ...] = ALL_LIQUID, horizons: tuple[TradingHorizon, ...] = BAR_HORIZONS, sources: tuple[str, ...] = ("mastertrd-native",)) -> StrategyRecipe:
    return StrategyRecipe(recipe_id, name, family, assets, horizons, RecipeReadiness.EXECUTABLE, sources, entry, exit_kind)


def _blocked(recipe_id: str, name: str, family: str, *, assets: tuple[AssetClass, ...], horizons: tuple[TradingHorizon, ...], readiness: RecipeReadiness, sources: tuple[str, ...], blocker: str, entry: str | None = None, exit_kind: str | None = None) -> StrategyRecipe:
    return StrategyRecipe(recipe_id, name, family, assets, horizons, readiness, sources, entry, exit_kind, blocker)


_EXECUTABLE_RECIPES: tuple[StrategyRecipe, ...] = (
    _exact("ema-cross-fast", "EMA Cross Fast", "trend", "ema_cross", "cross_reverse", sources=("mastertrd-native", "moskowitz-tsmom")),
    _exact("ema-cross-balanced", "EMA Cross Balanced", "trend", "ema_cross", "cross_reverse", sources=("mastertrd-native", "moskowitz-tsmom")),
    _exact("ema-cross-slow", "EMA Cross Slow", "trend", "ema_cross", "cross_reverse", horizons=(TradingHorizon.SWING, TradingHorizon.POSITION), sources=("mastertrd-native", "moskowitz-tsmom")),
    _exact("ema-cross-crypto", "EMA Cross Crypto", "trend", "ema_cross", "cross_reverse", assets=(AssetClass.CRYPTO,)),
    _exact("ema-cross-futures", "EMA Cross Futures", "trend", "ema_cross", "cross_reverse", assets=(AssetClass.FUTURES, AssetClass.COMMODITY, AssetClass.RATES)),
    _exact("ema-cross-fx", "EMA Cross FX", "trend", "ema_cross", "cross_reverse", assets=(AssetClass.FX,)),
    _exact("rsi-momentum-fast", "RSI Momentum Fast", "momentum", "rsi_momentum", "atr_bracket", sources=("mastertrd-native", "jegadeesh-titman")),
    _exact("rsi-momentum-balanced", "RSI Momentum Balanced", "momentum", "rsi_momentum", "atr_bracket", sources=("mastertrd-native", "jegadeesh-titman")),
    _exact("rsi-momentum-slow", "RSI Momentum Slow", "momentum", "rsi_momentum", "atr_bracket", horizons=(TradingHorizon.SWING, TradingHorizon.POSITION)),
    _exact("rsi-momentum-crypto", "RSI Momentum Crypto", "momentum", "rsi_momentum", "atr_bracket", assets=(AssetClass.CRYPTO,), sources=("mastertrd-native", "crypto-factors")),
    _exact("rsi-momentum-equity", "RSI Momentum Equity", "momentum", "rsi_momentum", "atr_bracket", assets=(AssetClass.EQUITY,)),
    _exact("donchian-20", "Donchian Breakout 20", "breakout", "donchian_breakout", "atr_bracket", sources=("mastertrd-native", "moskowitz-tsmom")),
    _exact("donchian-55", "Donchian Breakout 55", "breakout", "donchian_breakout", "atr_bracket", sources=("mastertrd-native", "moskowitz-tsmom")),
    _exact("donchian-fast", "Donchian Breakout Fast", "breakout", "donchian_breakout", "atr_bracket"),
    _exact("donchian-crypto", "Donchian Breakout Crypto", "breakout", "donchian_breakout", "atr_bracket", assets=(AssetClass.CRYPTO,)),
    _exact("donchian-futures", "Donchian Breakout Futures", "breakout", "donchian_breakout", "atr_bracket", assets=(AssetClass.FUTURES, AssetClass.COMMODITY, AssetClass.RATES)),
    _exact("zscore-fast", "Z-Score Reversion Fast", "mean_reversion", "zscore_reversion", "mean_or_atr_stop"),
    _exact("zscore-balanced", "Z-Score Reversion Balanced", "mean_reversion", "zscore_reversion", "mean_or_atr_stop"),
    _exact("zscore-slow", "Z-Score Reversion Slow", "mean_reversion", "zscore_reversion", "mean_or_atr_stop", horizons=(TradingHorizon.SWING, TradingHorizon.POSITION)),
    _exact("zscore-crypto", "Z-Score Reversion Crypto", "mean_reversion", "zscore_reversion", "mean_or_atr_stop", assets=(AssetClass.CRYPTO,)),
    _exact("zscore-equity", "Z-Score Reversion Equity", "mean_reversion", "zscore_reversion", "mean_or_atr_stop", assets=(AssetClass.EQUITY,)),
    _exact("atr-breakout-fast", "ATR Volatility Breakout Fast", "volatility", "volatility_breakout", "atr_bracket"),
    _exact("atr-breakout-balanced", "ATR Volatility Breakout Balanced", "volatility", "volatility_breakout", "atr_bracket"),
    _exact("atr-breakout-slow", "ATR Volatility Breakout Slow", "volatility", "volatility_breakout", "atr_bracket", horizons=(TradingHorizon.SWING, TradingHorizon.POSITION)),
    _exact("atr-breakout-crypto", "ATR Volatility Breakout Crypto", "volatility", "volatility_breakout", "atr_bracket", assets=(AssetClass.CRYPTO,)),
    _exact("pullback-fast", "Pullback Trend Fast", "swing", "pullback_trend", "atr_bracket"),
    _exact("pullback-balanced", "Pullback Trend Balanced", "swing", "pullback_trend", "atr_bracket", horizons=(TradingHorizon.SWING,)),
    _exact("pullback-crypto", "Pullback Trend Crypto", "swing", "pullback_trend", "atr_bracket", assets=(AssetClass.CRYPTO,), horizons=(TradingHorizon.SWING,)),
    _exact("pullback-fx", "Pullback Trend FX", "swing", "pullback_trend", "atr_bracket", assets=(AssetClass.FX,), horizons=(TradingHorizon.SWING,)),
    _exact("long-trend-balanced", "Long-Horizon Trend Balanced", "position", "long_horizon_trend", "trailing_atr", horizons=(TradingHorizon.POSITION,), sources=("mastertrd-native", "moskowitz-tsmom")),
    _exact("long-trend-slow", "Long-Horizon Trend Slow", "position", "long_horizon_trend", "trailing_atr", horizons=(TradingHorizon.POSITION,)),
    _exact("long-trend-futures", "Long-Horizon Trend Futures", "position", "long_horizon_trend", "trailing_atr", assets=(AssetClass.FUTURES, AssetClass.COMMODITY, AssetClass.RATES), horizons=(TradingHorizon.POSITION,)),
    _exact("pairs-cointegration-balanced", "Cointegration Pairs Balanced", "stat_arb", "cointegration_spread", "spread_mean_exit", sources=("mastertrd-native", "gatev-pairs")),
    _exact("pairs-cointegration-slow", "Cointegration Pairs Slow", "stat_arb", "cointegration_spread", "spread_mean_exit", horizons=(TradingHorizon.SWING, TradingHorizon.POSITION), sources=("mastertrd-native", "gatev-pairs")),
    _exact("crypto-funding-basis", "Crypto Funding Basis", "funding_basis", "funding_basis", "edge_decay", assets=(AssetClass.CRYPTO,), sources=("mastertrd-native", "koijen-carry")),
    _exact("crypto-hedged-basis", "Crypto Hedged Basis", "delta_neutral", "hedged_basis", "rebalance", assets=(AssetClass.CRYPTO,), sources=("mastertrd-native", "koijen-carry")),
    _exact("multi-asset-rotation", "Multi-Asset Momentum Rotation", "portfolio", "strategy_rotation", "rebalance", assets=(AssetClass.MULTI_ASSET,), horizons=(TradingHorizon.SWING, TradingHorizon.POSITION), sources=("mastertrd-native", "asness-value-momentum")),
    _exact("crypto-rotation", "Crypto Momentum Rotation", "portfolio", "strategy_rotation", "rebalance", assets=(AssetClass.CRYPTO,), sources=("mastertrd-native", "crypto-factors")),
)


_SPECIALIST_RECIPES: tuple[StrategyRecipe, ...] = (
    _blocked("options-iv-rv-defined-risk", "Options IV/RV Defined-Risk", "options", assets=(AssetClass.OPTIONS,), horizons=(TradingHorizon.SWING,), readiness=RecipeReadiness.SPECIALIST_DATA_REQUIRED, sources=("mastertrd-native",), blocker="qualifying_option_chain_and_greeks_data_required", entry="volatility_signal", exit_kind="greeks_or_time_exit"),
    _blocked("crypto-micro-momentum", "Crypto Micro Momentum Scalper", "scalping", assets=(AssetClass.CRYPTO,), horizons=(TradingHorizon.SCALP,), readiness=RecipeReadiness.SPECIALIST_DATA_REQUIRED, sources=("mastertrd-native", "hummingbot"), blocker="qualifying_real_tick_evidence_required", entry="micro_momentum", exit_kind="ticks_or_timeout"),
    _blocked("crypto-dynamic-grid", "Crypto Dynamic Grid", "grid", assets=(AssetClass.CRYPTO,), horizons=(TradingHorizon.SCALP, TradingHorizon.INTRADAY), readiness=RecipeReadiness.SPECIALIST_DATA_REQUIRED, sources=("mastertrd-native", "hummingbot"), blocker="qualifying_real_tick_evidence_required", entry="dynamic_grid", exit_kind="inventory_exit"),
    _blocked("inventory-skew-mm", "Inventory-Skew Market Maker", "market_making", assets=(AssetClass.CRYPTO,), horizons=(TradingHorizon.SCALP,), readiness=RecipeReadiness.SPECIALIST_DATA_REQUIRED, sources=("mastertrd-native", "avellaneda-stoikov"), blocker="qualifying_real_l2_queue_latency_evidence_required", entry="inventory_skew_mm", exit_kind="inventory_flatten"),
    _blocked("book-imbalance", "Order-Book Imbalance", "order_book", assets=(AssetClass.CRYPTO,), horizons=(TradingHorizon.SCALP,), readiness=RecipeReadiness.SPECIALIST_DATA_REQUIRED, sources=("mastertrd-native",), blocker="qualifying_real_l2_queue_latency_evidence_required", entry="order_book_imbalance", exit_kind="imbalance_reversal_or_ticks"),
    _blocked("cross-venue-crypto-spread", "Cross-Venue Crypto Spread", "cross_venue_arb", assets=(AssetClass.CRYPTO,), horizons=(TradingHorizon.SCALP, TradingHorizon.INTRADAY), readiness=RecipeReadiness.SPECIALIST_DATA_REQUIRED, sources=("mastertrd-native", "hummingbot"), blocker="qualifying_synchronized_cross_venue_tick_evidence_required", entry="cross_venue_spread", exit_kind="spread_convergence"),
)


def _target_group(prefix: str, family: str, names: tuple[str, ...], *, assets: tuple[AssetClass, ...], horizons: tuple[TradingHorizon, ...], source: str, readiness: RecipeReadiness = RecipeReadiness.PRIMITIVE_REQUIRED, blocker: str = "exact_strategy_primitive_not_yet_implemented") -> tuple[StrategyRecipe, ...]:
    return tuple(_blocked(f"{prefix}-{index:02d}", name, family, assets=assets, horizons=horizons, readiness=readiness, sources=(source,), blocker=blocker) for index, name in enumerate(names, 1))


_TARGET_RECIPES: tuple[StrategyRecipe, ...] = (
    _blocked(
        "cross-sectional-momentum",
        "Cross-Sectional Momentum",
        "momentum",
        assets=(AssetClass.EQUITY, AssetClass.FUTURES, AssetClass.FX, AssetClass.CRYPTO),
        horizons=(TradingHorizon.SWING, TradingHorizon.POSITION),
        readiness=RecipeReadiness.PRIMITIVE_REQUIRED,
        sources=("jegadeesh-titman",),
        blocker="exact_strategy_primitive_not_yet_implemented",
    ),
    *_target_group("momentum", "momentum", ("Dual Momentum", "Residual Momentum", "Sector Momentum", "Industry Momentum", "Country Momentum", "52-Week High Momentum", "Earnings Momentum", "Intraday Momentum", "Volume-Confirmed Momentum", "Absolute Momentum", "Factor Momentum"), assets=(AssetClass.EQUITY, AssetClass.FUTURES, AssetClass.FX, AssetClass.CRYPTO), horizons=(TradingHorizon.INTRADAY, TradingHorizon.SWING, TradingHorizon.POSITION), source="jegadeesh-titman"),
    *_target_group("reversion", "mean_reversion", ("Bollinger Reversion", "RSI-2 Reversion", "VWAP Reversion", "Gap Fade", "Failed Breakout Reversal", "Liquidity Shock Reversal", "Keltner Reversion", "Volume Exhaustion", "Long-Term Loser Reversal", "Basis Mean Reversion"), assets=(AssetClass.CRYPTO, AssetClass.EQUITY, AssetClass.FX, AssetClass.FUTURES), horizons=(TradingHorizon.INTRADAY, TradingHorizon.SWING), source="quantconnect-library"),
    *_target_group("breakout", "breakout", ("Opening Range Breakout", "Dual Thrust", "Bollinger Squeeze Breakout", "NR4 Breakout", "NR7 Breakout", "VWAP Breakout", "Previous-Day High/Low Breakout", "Multi-Timeframe Breakout"), assets=(AssetClass.CRYPTO, AssetClass.EQUITY, AssetClass.FX, AssetClass.FUTURES), horizons=(TradingHorizon.INTRADAY, TradingHorizon.SWING), source="quantconnect-library"),
    *_target_group("trend", "trend", ("SuperTrend", "Ichimoku Trend", "ADX/DMI Trend", "Parabolic SAR Trend", "MACD Trend", "Moving-Average Ribbon", "Price Channel Trend", "Crisis Trend"), assets=ALL_LIQUID, horizons=(TradingHorizon.INTRADAY, TradingHorizon.SWING, TradingHorizon.POSITION), source="moskowitz-tsmom"),
    *_target_group("factor", "position", ("Equity Value", "Gross Profitability", "Quality Minus Junk", "Betting Against Beta", "Low Volatility Equity", "Asset Growth", "Investment Factor", "Earnings Yield", "Book-to-Market", "Accruals", "Buyback/Net Issuance", "Small-Cap Factor"), assets=(AssetClass.EQUITY,), horizons=(TradingHorizon.POSITION,), source="aqr-data"),
    *_target_group("event", "swing", ("Post-Earnings Announcement Drift", "Overnight Anomaly", "Turn-of-Month", "Pre-Holiday", "January Effect", "Analyst Surprise Drift", "Option Expiry Effect", "Earnings Quality Drift"), assets=(AssetClass.EQUITY,), horizons=(TradingHorizon.SWING,), source="quantconnect-library"),
    *_target_group("statarb", "stat_arb", ("Kalman Filter Pairs", "PCA Residual Stat-Arb", "Copula Pairs", "Basket Cointegration", "Calendar Spread", "Crack Spread", "Yield Curve Steepener", "Yield Curve Flattener", "Yield Curve Butterfly", "Cross-Country Bond Relative Value"), assets=(AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.FX, AssetClass.FUTURES, AssetClass.COMMODITY, AssetClass.RATES), horizons=(TradingHorizon.INTRADAY, TradingHorizon.SWING, TradingHorizon.POSITION), source="gatev-pairs"),
    *_target_group("carry", "funding_basis", ("FX Carry", "Commodity Roll Yield", "Commodity Term Structure", "Bond Carry/Roll-Down", "Spot-Perp Cash-and-Carry", "Perpetual Funding Differential", "Crypto Calendar Basis", "Reverse Cash-and-Carry"), assets=(AssetClass.FX, AssetClass.FUTURES, AssetClass.COMMODITY, AssetClass.RATES, AssetClass.CRYPTO), horizons=(TradingHorizon.SWING, TradingHorizon.POSITION), source="koijen-carry"),
    *_target_group("vol", "volatility", ("Volatility-Managed Momentum", "Volatility-Managed Carry", "GARCH Regime", "Volatility Expansion", "Funding/OI Regime", "Liquidation Regime", "Realized Volatility Breakout", "Cross-Asset Volatility Regime"), assets=ALL_LIQUID, horizons=(TradingHorizon.INTRADAY, TradingHorizon.SWING, TradingHorizon.POSITION), source="moreira-muir"),
    *_target_group("options", "options", ("Volatility Risk Premium", "Delta-Neutral Straddle", "Delta-Neutral Strangle", "Put Write", "Covered Call", "Iron Condor", "Calendar Spread", "Diagonal Spread", "Skew/Risk Reversal", "Gamma Scalping", "Dispersion", "Implied-vs-Realized Volatility"), assets=(AssetClass.OPTIONS,), horizons=(TradingHorizon.INTRADAY, TradingHorizon.SWING, TradingHorizon.POSITION), source="quantconnect-library", readiness=RecipeReadiness.SPECIALIST_DATA_REQUIRED, blocker="exact_options_primitive_and_qualifying_chain_data_required"),
    *_target_group("portfolio", "portfolio", ("Minimum Variance", "Risk Parity", "Inverse Volatility", "Maximum Diversification", "Trend + Carry", "Value + Momentum", "Value + Momentum + Quality", "Defensive Rotation", "Regime-Switching Allocation", "Correlation-Aware Champion Allocation"), assets=(AssetClass.MULTI_ASSET,), horizons=(TradingHorizon.SWING, TradingHorizon.POSITION), source="moreira-muir"),
    *_target_group("arb", "cross_venue_arb", ("CEX/CEX Arbitrage", "CEX/DEX Arbitrage", "DEX/DEX Arbitrage", "Crypto Triangular Arbitrage", "FX Triangular Arbitrage", "Cross-Broker Arbitrage", "Cross-Venue Lead/Lag", "Stablecoin Venue Dislocation"), assets=(AssetClass.CRYPTO, AssetClass.FX), horizons=(TradingHorizon.SCALP, TradingHorizon.INTRADAY), source="hummingbot", readiness=RecipeReadiness.SPECIALIST_DATA_REQUIRED, blocker="exact_cross_venue_primitive_and_synchronized_tick_data_required"),
    *_target_group("mm", "market_making", ("Avellaneda-Stoikov", "Queue-Aware Market Making", "Adaptive Inventory Skew", "Volatility-Sensitive Quoting", "Cross-Exchange Market Making", "AMM/CEX Market Making", "Liquidity Ladder", "Spread-Regime Market Making"), assets=(AssetClass.CRYPTO, AssetClass.FUTURES), horizons=(TradingHorizon.SCALP,), source="avellaneda-stoikov", readiness=RecipeReadiness.SPECIALIST_DATA_REQUIRED, blocker="exact_mm_primitive_and_real_l2_queue_latency_data_required"),
    *_target_group("book", "order_book", ("Microprice", "Trade-Flow Imbalance", "Queue Imbalance", "Tick Imbalance", "Volume Imbalance", "Sweep Reversal", "Book Pressure Momentum", "Spread-Widening Reversion"), assets=(AssetClass.CRYPTO, AssetClass.FUTURES), horizons=(TradingHorizon.SCALP,), source="mastertrd-native", readiness=RecipeReadiness.SPECIALIST_DATA_REQUIRED, blocker="exact_order_book_primitive_and_real_l2_queue_latency_data_required"),
    *_target_group("ml", "portfolio", ("Gradient-Boosting Factor Ranker", "Random-Forest Regime Model", "Autoencoder Residual Allocation", "Meta-Labeling", "Reinforcement-Learning Allocation", "Online Drift Allocator"), assets=(AssetClass.MULTI_ASSET,), horizons=(TradingHorizon.INTRADAY, TradingHorizon.SWING, TradingHorizon.POSITION), source="quantconnect-library", readiness=RecipeReadiness.EXPERIMENTAL, blocker="experimental_model_requires_separate_validation_contract"),
    *_target_group("polymarket-rv", "stat_arb", ("Polymarket Cross-Market Arbitrage", "Polymarket Related-Event Spread", "Polymarket Probability Relative Value"), assets=(AssetClass.PREDICTION,), horizons=(TradingHorizon.INTRADAY, TradingHorizon.SWING), source="nautilus-polymarket", readiness=RecipeReadiness.PROVIDER_REQUIRED, blocker="provider_not_admitted_to_mastertrd_runtime"),
    *_target_group("polymarket-mm", "market_making", ("Polymarket Order-Book Market Making", "Polymarket Binary Outcome Spread Capture"), assets=(AssetClass.PREDICTION,), horizons=(TradingHorizon.SCALP,), source="nautilus-polymarket", readiness=RecipeReadiness.PROVIDER_REQUIRED, blocker="provider_not_admitted_to_mastertrd_runtime"),
    *_target_group("betfair-book", "order_book", ("Betfair Book Imbalance", "Betfair Price Pressure"), assets=(AssetClass.BETTING,), horizons=(TradingHorizon.SCALP, TradingHorizon.INTRADAY), source="nautilus-betfair", readiness=RecipeReadiness.PROVIDER_REQUIRED, blocker="provider_not_admitted_to_mastertrd_runtime"),
    *_target_group("betfair-rv", "stat_arb", ("Betfair Cross-Market Relative Value", "Betfair Related-Market Spread"), assets=(AssetClass.BETTING,), horizons=(TradingHorizon.INTRADAY,), source="nautilus-betfair", readiness=RecipeReadiness.PROVIDER_REQUIRED, blocker="provider_not_admitted_to_mastertrd_runtime"),
)


STRATEGY_RECIPES: tuple[StrategyRecipe, ...] = (*_EXECUTABLE_RECIPES, *_SPECIALIST_RECIPES, *_TARGET_RECIPES)


def strategy_recipe(recipe_id: str) -> StrategyRecipe:
    for recipe in STRATEGY_RECIPES:
        if recipe.recipe_id == recipe_id:
            return recipe
    raise ValueError(f"unknown strategy recipe: {recipe_id}")


def recipes_for(*, family: str | None = None, asset_class: AssetClass | None = None, readiness: RecipeReadiness | None = None) -> tuple[StrategyRecipe, ...]:
    return tuple(recipe for recipe in STRATEGY_RECIPES if (family is None or recipe.family == family) and (asset_class is None or asset_class in recipe.asset_classes) and (readiness is None or recipe.readiness is readiness))


def _validate_recipe_instruments(recipe: StrategyRecipe, instruments: Sequence[str]) -> None:
    spec = family_spec(recipe.family)
    count = len(instruments)
    if count < spec.min_instruments:
        if spec.min_instruments == spec.max_instruments:
            raise ValueError(f"recipe {recipe.recipe_id} requires exactly {spec.min_instruments} instruments")
        raise ValueError(f"recipe {recipe.recipe_id} requires at least {spec.min_instruments} instruments")
    if spec.max_instruments is not None and count > spec.max_instruments:
        if spec.min_instruments == spec.max_instruments:
            raise ValueError(f"recipe {recipe.recipe_id} requires exactly {spec.max_instruments} instruments")
        raise ValueError(f"recipe {recipe.recipe_id} accepts at most {spec.max_instruments} instruments")


def compile_strategy_recipe(recipe_id: str, *, instruments: Sequence[str], seed: int, trade_size: str | None = None) -> StrategyGenome:
    """Compile one admitted recipe using the existing shared family semantics.

    The recipe ID is salted into the RNG and strategy identity so two named recipes
    in the same family remain reproducible but distinct. Unsupported catalog ideas
    fail closed rather than receiving a proxy signal.
    """
    recipe = strategy_recipe(recipe_id)
    if recipe.readiness is not RecipeReadiness.EXECUTABLE:
        raise ValueError(recipe.blocker or f"recipe {recipe_id} is not executable")
    if not instruments:
        raise ValueError("at least one instrument is required")
    _validate_recipe_instruments(recipe, instruments)

    from mastertrd.research import generator as legacy

    digest = sha256(f"{recipe_id}|{seed}".encode()).digest()
    recipe_seed = int.from_bytes(digest[:8], "big", signed=False)
    rng = random.Random(recipe_seed)
    entry, exit_rule, filters = legacy._rules(recipe.family, rng)
    if entry.get("type") != recipe.entry_kind or exit_rule.get("type") != recipe.exit_kind:
        raise RuntimeError(f"recipe {recipe_id} no longer matches executable family semantics")
    if trade_size is not None:
        entry = dict(entry)
        entry["trade_size"] = legacy._validated_trade_size(trade_size)

    timeframe = rng.choice(legacy._TIMEFRAMES[recipe.family])
    spec = family_spec(recipe.family)
    raw_id = f"recipe|{recipe_id}|{','.join(instruments)}|{seed}|{entry}|{exit_rule}|{filters}"
    strategy_id = "R-" + sha256(raw_id.encode()).hexdigest()[:12].upper()
    data_requirements = ("BAR",) if spec.min_data_level is DataLevel.BAR else (spec.min_data_level.value,)
    return StrategyGenome(
        strategy_id=strategy_id,
        family=recipe.family,
        style=f"recipe:{recipe_id}",
        instruments=tuple(instruments),
        timeframe=timeframe,
        entry=entry,
        exit=exit_rule,
        filters=filters,
        risk={
            "risk_fraction": round(rng.uniform(0.001, 0.01), 4),
            "max_drawdown_stop": round(rng.uniform(0.05, 0.25), 3),
        },
        data_requirements=data_requirements,
        allow_short=spec.supports_short,
    )
