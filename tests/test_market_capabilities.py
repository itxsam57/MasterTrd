from __future__ import annotations

import pytest

from mastertrd.market_capabilities import (
    MasterTrdAdmission,
    PROVIDER_CAPABILITIES,
    ProviderKind,
    provider_capability,
    providers_for,
)
from mastertrd.strategy_universe import AssetClass


def test_provider_ids_are_unique_and_cover_target_markets() -> None:
    provider_ids = [provider.provider_id for provider in PROVIDER_CAPABILITIES]
    assert len(provider_ids) == len(set(provider_ids))

    covered = {
        asset_class
        for provider in PROVIDER_CAPABILITIES
        for asset_class in provider.asset_classes
    }
    assert {
        AssetClass.CRYPTO,
        AssetClass.EQUITY,
        AssetClass.FX,
        AssetClass.FUTURES,
        AssetClass.COMMODITY,
        AssetClass.RATES,
        AssetClass.OPTIONS,
        AssetClass.PREDICTION,
        AssetClass.BETTING,
    }.issubset(covered)


def test_binance_is_the_only_initially_admitted_execution_venue() -> None:
    binance = provider_capability("binance")
    assert binance.nautilus_available is True
    assert binance.market_data is True
    assert binance.execution is True
    assert binance.mastertrd_admission is MasterTrdAdmission.ADMITTED

    admitted_execution = providers_for(
        execution=True,
        admission=MasterTrdAdmission.ADMITTED,
    )
    assert tuple(provider.provider_id for provider in admitted_execution) == ("binance",)


def test_data_only_providers_never_claim_execution() -> None:
    for provider_id in ("databento", "tardis"):
        provider = provider_capability(provider_id)
        assert provider.kind is ProviderKind.DATA_PROVIDER
        assert provider.market_data is True
        assert provider.execution is False


def test_broad_nautilus_venues_are_cataloged_without_false_mastertrd_admission() -> None:
    ib = provider_capability("interactive-brokers")
    assert ib.nautilus_available is True
    assert ib.execution is True
    assert ib.mastertrd_admission is MasterTrdAdmission.NOT_ADMITTED
    assert {
        AssetClass.EQUITY,
        AssetClass.FX,
        AssetClass.FUTURES,
        AssetClass.OPTIONS,
        AssetClass.RATES,
    }.issubset(set(ib.asset_classes))

    polymarket = provider_capability("polymarket")
    assert polymarket.kind is ProviderKind.PREDICTION_MARKET
    assert AssetClass.PREDICTION in polymarket.asset_classes
    assert polymarket.execution is True
    assert polymarket.mastertrd_admission is MasterTrdAdmission.NOT_ADMITTED

    betfair = provider_capability("betfair")
    assert betfair.kind is ProviderKind.BETTING_EXCHANGE
    assert AssetClass.BETTING in betfair.asset_classes
    assert betfair.execution is True
    assert betfair.mastertrd_admission is MasterTrdAdmission.NOT_ADMITTED


def test_derivatives_and_binary_outcome_surfaces_are_recorded() -> None:
    okx = provider_capability("okx")
    assert {AssetClass.CRYPTO, AssetClass.OPTIONS, AssetClass.PREDICTION}.issubset(
        set(okx.asset_classes)
    )
    assert "SPOT" in okx.products
    assert "PERPETUAL" in okx.products
    assert "FUTURE" in okx.products
    assert "OPTION" in okx.products
    assert "EVENT_CONTRACT" in okx.products

    hyperliquid = provider_capability("hyperliquid")
    assert AssetClass.PREDICTION in hyperliquid.asset_classes
    assert "BINARY_OUTCOME" in hyperliquid.products


def test_filters_and_lookup_fail_closed() -> None:
    prediction_execution = providers_for(
        asset_class=AssetClass.PREDICTION,
        execution=True,
    )
    assert prediction_execution
    assert all(provider.execution for provider in prediction_execution)
    assert all(AssetClass.PREDICTION in provider.asset_classes for provider in prediction_execution)

    with pytest.raises(ValueError, match="unknown provider capability"):
        provider_capability("missing-provider")
