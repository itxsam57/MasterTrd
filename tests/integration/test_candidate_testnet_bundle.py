from __future__ import annotations

from decimal import Decimal

import pytest

from mastertrd.genome import StrategyGenome
from mastertrd.testnet_candidate import TestnetCandidateManifest
from mastertrd.venue import BinanceProduct


def candidate() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="S-CHAMPION-001",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 5, "slow_period": 20},
        exit={"kind": "cross_reverse"},
        risk={"risk_fraction": 0.01},
    )


def test_candidate_manifest_round_trips_exact_public_identity():
    genome = candidate()
    manifest = TestnetCandidateManifest.from_candidate(
        genome,
        code_hash="code-champion-001",
        dataset_hash="dataset-champion-001",
        product=BinanceProduct.SPOT,
        probe_instrument="BTCUSDT.BINANCE",
        order_notional_cap=Decimal("10"),
    )

    payload = manifest.to_public_payload()
    loaded = TestnetCandidateManifest.from_public_payload(payload)

    assert loaded.candidate == genome
    assert loaded.strategy_id == genome.strategy_id
    assert loaded.genome_hash == genome.genome_hash
    assert loaded.code_hash == "code-champion-001"
    assert loaded.dataset_hash == "dataset-champion-001"
    assert loaded.product is BinanceProduct.SPOT
    assert loaded.probe_instrument == "BTCUSDT.BINANCE"
    assert loaded.order_notional_cap == Decimal("10")
    assert "api_key" not in str(payload).lower()
    assert "api_secret" not in str(payload).lower()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("strategy_id", "OTHER", "strategy_id"),
        ("genome_hash", "0" * 64, "genome_hash"),
        ("probe_instrument", "ETHUSDT.BINANCE", "probe_instrument"),
        ("order_notional_cap", "0", "order_notional_cap"),
    ],
)
def test_candidate_manifest_rejects_tampered_or_unsafe_identity(field, value, message):
    manifest = TestnetCandidateManifest.from_candidate(
        candidate(),
        code_hash="code-champion-001",
        dataset_hash="dataset-champion-001",
        product=BinanceProduct.SPOT,
        probe_instrument="BTCUSDT.BINANCE",
        order_notional_cap=Decimal("10"),
    )
    payload = manifest.to_public_payload()
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        TestnetCandidateManifest.from_public_payload(payload)


def test_candidate_manifest_rejects_empty_provenance_identity():
    with pytest.raises(ValueError, match="code_hash"):
        TestnetCandidateManifest.from_candidate(
            candidate(),
            code_hash="",
            dataset_hash="dataset-champion-001",
            product=BinanceProduct.SPOT,
            probe_instrument="BTCUSDT.BINANCE",
            order_notional_cap=Decimal("10"),
        )
