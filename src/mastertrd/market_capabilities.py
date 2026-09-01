from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from mastertrd.strategy_universe import AssetClass


class ProviderKind(StrEnum):
    EXCHANGE = "EXCHANGE"
    DEX = "DEX"
    BROKER = "BROKER"
    DATA_PROVIDER = "DATA_PROVIDER"
    PREDICTION_MARKET = "PREDICTION_MARKET"
    BETTING_EXCHANGE = "BETTING_EXCHANGE"


class MasterTrdAdmission(StrEnum):
    ADMITTED = "ADMITTED"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    NOT_ADMITTED = "NOT_ADMITTED"


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    provider_id: str
    name: str
    kind: ProviderKind
    asset_classes: tuple[AssetClass, ...]
    products: tuple[str, ...]
    nautilus_available: bool
    market_data: bool
    execution: bool
    mastertrd_admission: MasterTrdAdmission
    source_url: str
    blocker: str | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if not self.provider_id or not self.name:
            raise ValueError("provider identity is required")
        if not self.asset_classes:
            raise ValueError("provider asset_classes are required")
        if not self.products:
            raise ValueError("provider products are required")
        if self.kind is ProviderKind.DATA_PROVIDER and self.execution:
            raise ValueError("data-only provider cannot claim execution")
        if self.mastertrd_admission is MasterTrdAdmission.ADMITTED and self.blocker:
            raise ValueError("admitted provider cannot retain an admission blocker")
        if self.mastertrd_admission is not MasterTrdAdmission.ADMITTED and not self.blocker:
            raise ValueError("unadmitted provider requires an explicit blocker")


_NAUTILUS_INTEGRATIONS = "https://nautilustrader.io/docs/latest/integrations/"
_NOT_ADMITTED = "mastertrd_provider_admission_not_yet_completed"
_DATA_ONLY = "data_provider_only_no_execution_client"


PROVIDER_CAPABILITIES: tuple[ProviderCapability, ...] = (
    ProviderCapability(
        "binance",
        "Binance",
        ProviderKind.EXCHANGE,
        (AssetClass.CRYPTO,),
        ("SPOT", "USD_M_PERPETUAL", "USD_M_FUTURE", "COIN_M_PERPETUAL", "COIN_M_FUTURE"),
        True,
        True,
        True,
        MasterTrdAdmission.ADMITTED,
        "https://nautilustrader.io/docs/latest/integrations/binance/",
        note="Current MasterTrd execution/testnet venue. Admission does not imply LIVE eligibility.",
    ),
    ProviderCapability(
        "coinbase",
        "Coinbase",
        ProviderKind.EXCHANGE,
        (AssetClass.CRYPTO,),
        ("SPOT", "PERPETUAL", "FUTURE"),
        True,
        True,
        True,
        MasterTrdAdmission.NOT_ADMITTED,
        "https://nautilustrader.io/docs/latest/integrations/coinbase/",
        _NOT_ADMITTED,
    ),
    ProviderCapability(
        "bitmex",
        "BitMEX",
        ProviderKind.EXCHANGE,
        (AssetClass.CRYPTO,),
        ("SPOT", "PERPETUAL", "FUTURE"),
        True,
        True,
        True,
        MasterTrdAdmission.NOT_ADMITTED,
        "https://nautilustrader.io/docs/latest/integrations/bitmex/",
        _NOT_ADMITTED,
    ),
    ProviderCapability(
        "bybit",
        "Bybit",
        ProviderKind.EXCHANGE,
        (AssetClass.CRYPTO, AssetClass.OPTIONS),
        ("SPOT", "PERPETUAL", "FUTURE", "OPTION"),
        True,
        True,
        True,
        MasterTrdAdmission.NOT_ADMITTED,
        "https://nautilustrader.io/docs/latest/integrations/bybit/",
        _NOT_ADMITTED,
        "Strong future crypto-options admission candidate because the adapter exposes option greeks and L2 data.",
    ),
    ProviderCapability(
        "deribit",
        "Deribit",
        ProviderKind.EXCHANGE,
        (AssetClass.CRYPTO, AssetClass.OPTIONS),
        ("SPOT", "PERPETUAL", "FUTURE", "OPTION", "SPREAD"),
        True,
        True,
        True,
        MasterTrdAdmission.NOT_ADMITTED,
        "https://nautilustrader.io/docs/latest/integrations/deribit/",
        _NOT_ADMITTED,
    ),
    ProviderCapability(
        "kraken",
        "Kraken",
        ProviderKind.EXCHANGE,
        (AssetClass.CRYPTO, AssetClass.EQUITY),
        ("SPOT", "TOKENIZED_ASSET", "FUTURE", "PERPETUAL"),
        True,
        True,
        True,
        MasterTrdAdmission.NOT_ADMITTED,
        "https://nautilustrader.io/docs/latest/integrations/kraken/",
        _NOT_ADMITTED,
        "Spot includes tokenized assets; futures has a demo environment. MasterTrd has not admitted this adapter.",
    ),
    ProviderCapability(
        "okx",
        "OKX",
        ProviderKind.EXCHANGE,
        (AssetClass.CRYPTO, AssetClass.OPTIONS, AssetClass.PREDICTION),
        ("SPOT", "MARGIN", "PERPETUAL", "FUTURE", "OPTION", "SPREAD", "EVENT_CONTRACT"),
        True,
        True,
        True,
        MasterTrdAdmission.NOT_ADMITTED,
        "https://nautilustrader.io/docs/latest/integrations/okx/",
        _NOT_ADMITTED,
        "Broad crypto derivatives/options/event-contract surface; MasterTrd admission remains separate.",
    ),
    ProviderCapability(
        "hyperliquid",
        "Hyperliquid",
        ProviderKind.DEX,
        (AssetClass.CRYPTO, AssetClass.PREDICTION),
        ("SPOT", "PERPETUAL", "HIP3_PERPETUAL", "BINARY_OUTCOME"),
        True,
        True,
        True,
        MasterTrdAdmission.NOT_ADMITTED,
        "https://nautilustrader.io/docs/latest/integrations/hyperliquid/",
        _NOT_ADMITTED,
    ),
    ProviderCapability(
        "derive",
        "Derive",
        ProviderKind.DEX,
        (AssetClass.CRYPTO, AssetClass.OPTIONS),
        ("PERPETUAL", "OPTION"),
        True,
        True,
        True,
        MasterTrdAdmission.NOT_ADMITTED,
        "https://nautilustrader.io/docs/latest/integrations/derive/",
        _NOT_ADMITTED,
    ),
    ProviderCapability(
        "dydx",
        "dYdX",
        ProviderKind.DEX,
        (AssetClass.CRYPTO,),
        ("PERPETUAL",),
        True,
        True,
        True,
        MasterTrdAdmission.NOT_ADMITTED,
        "https://nautilustrader.io/docs/latest/integrations/dydx/",
        _NOT_ADMITTED,
    ),
    ProviderCapability(
        "lighter",
        "Lighter",
        ProviderKind.DEX,
        (AssetClass.CRYPTO,),
        ("SPOT", "PERPETUAL"),
        True,
        True,
        True,
        MasterTrdAdmission.NOT_ADMITTED,
        "https://nautilustrader.io/docs/latest/integrations/lighter/",
        _NOT_ADMITTED,
    ),
    ProviderCapability(
        "polymarket",
        "Polymarket",
        ProviderKind.PREDICTION_MARKET,
        (AssetClass.PREDICTION,),
        ("BINARY_OPTION", "L2_CLOB"),
        True,
        True,
        True,
        MasterTrdAdmission.NOT_ADMITTED,
        "https://nautilustrader.io/docs/latest/integrations/polymarket/",
        _NOT_ADMITTED,
        "Prediction-market execution must use a dedicated admission and wallet/credential isolation path.",
    ),
    ProviderCapability(
        "betfair",
        "Betfair",
        ProviderKind.BETTING_EXCHANGE,
        (AssetClass.BETTING,),
        ("BETTING_INSTRUMENT", "EXCHANGE_ODDS"),
        True,
        True,
        True,
        MasterTrdAdmission.NOT_ADMITTED,
        "https://nautilustrader.io/docs/latest/integrations/betfair/",
        _NOT_ADMITTED,
        "Separate regulated betting-exchange semantics; never treated as a normal financial position model.",
    ),
    ProviderCapability(
        "interactive-brokers",
        "Interactive Brokers",
        ProviderKind.BROKER,
        (AssetClass.EQUITY, AssetClass.FX, AssetClass.FUTURES, AssetClass.COMMODITY, AssetClass.RATES, AssetClass.OPTIONS),
        ("STOCK", "ETF", "FX", "FUTURE", "FUTURE_SPREAD", "OPTION", "OPTION_SPREAD", "BOND", "FUND"),
        True,
        True,
        True,
        MasterTrdAdmission.NOT_ADMITTED,
        "https://nautilustrader.io/docs/latest/integrations/interactive_brokers/",
        _NOT_ADMITTED,
        "Highest-priority future broad traditional-market execution admission.",
    ),
    ProviderCapability(
        "ax-exchange",
        "AX Exchange",
        ProviderKind.EXCHANGE,
        (AssetClass.EQUITY, AssetClass.FX, AssetClass.FUTURES, AssetClass.COMMODITY, AssetClass.RATES),
        ("TRADITIONAL_DERIVATIVE", "PERPETUAL"),
        True,
        True,
        True,
        MasterTrdAdmission.NOT_ADMITTED,
        "https://nautilustrader.io/docs/latest/integrations/ax/",
        _NOT_ADMITTED,
    ),
    ProviderCapability(
        "databento",
        "Databento",
        ProviderKind.DATA_PROVIDER,
        (AssetClass.EQUITY, AssetClass.FX, AssetClass.FUTURES, AssetClass.COMMODITY, AssetClass.RATES, AssetClass.OPTIONS),
        ("STOCK_DATA", "FUTURE_DATA", "OPTION_DATA", "FUTURE_SPREAD_DATA", "OPTION_SPREAD_DATA", "FX_SPOT_DATA", "L1", "L2", "L3"),
        True,
        True,
        False,
        MasterTrdAdmission.NOT_ADMITTED,
        "https://nautilustrader.io/docs/latest/integrations/databento/",
        _DATA_ONLY,
        "Traditional-market research data candidate; execution must route through another admitted adapter.",
    ),
    ProviderCapability(
        "tardis",
        "Tardis",
        ProviderKind.DATA_PROVIDER,
        (AssetClass.CRYPTO, AssetClass.OPTIONS),
        ("HISTORICAL_TRADE_DATA", "ORDER_BOOK_DATA", "DERIVATIVES_DATA", "OPTION_DATA"),
        True,
        True,
        False,
        MasterTrdAdmission.NOT_ADMITTED,
        "https://nautilustrader.io/docs/latest/integrations/tardis/",
        _DATA_ONLY,
        "Broad multi-venue crypto historical-data source, including many venues beyond direct execution adapters.",
    ),
    ProviderCapability(
        "blockchain",
        "Blockchain / DeFi Data",
        ProviderKind.DATA_PROVIDER,
        (AssetClass.CRYPTO,),
        ("DEFI_DATA", "CHAIN_DATA"),
        True,
        True,
        False,
        MasterTrdAdmission.NOT_ADMITTED,
        "https://nautilustrader.io/docs/latest/integrations/blockchain/",
        _DATA_ONLY,
    ),
)


def provider_capability(provider_id: str) -> ProviderCapability:
    for provider in PROVIDER_CAPABILITIES:
        if provider.provider_id == provider_id:
            return provider
    raise ValueError(f"unknown provider capability: {provider_id}")


def providers_for(
    *,
    asset_class: AssetClass | None = None,
    execution: bool | None = None,
    market_data: bool | None = None,
    admission: MasterTrdAdmission | None = None,
) -> tuple[ProviderCapability, ...]:
    return tuple(
        provider
        for provider in PROVIDER_CAPABILITIES
        if (asset_class is None or asset_class in provider.asset_classes)
        and (execution is None or provider.execution is execution)
        and (market_data is None or provider.market_data is market_data)
        and (admission is None or provider.mastertrd_admission is admission)
    )
