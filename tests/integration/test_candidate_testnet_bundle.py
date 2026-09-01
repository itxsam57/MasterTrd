from __future__ import annotations

from decimal import Decimal
import json

import pytest

from mastertrd.genome import StrategyGenome
from mastertrd import testnet_smoke
from mastertrd.testnet_candidate import (
    TestnetCandidateManifest,
    candidate_testnet_bundle_identity_ok,
)
from mastertrd.testnet_smoke import SpotTestnetRules
from mastertrd.validation import ValidationEvidence
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


def manifest(*, cap: Decimal = Decimal("10")) -> TestnetCandidateManifest:
    return TestnetCandidateManifest.from_candidate(
        candidate(),
        code_hash="code-champion-001",
        dataset_hash="dataset-champion-001",
        product=BinanceProduct.SPOT,
        probe_instrument="BTCUSDT.BINANCE",
        order_notional_cap=cap,
    )


def live_record(
    kind: str,
    *,
    bound_candidate: StrategyGenome | None = None,
    code_hash: str = "code-champion-001",
    dataset_hash: str = "dataset-champion-001",
) -> ValidationEvidence:
    bound = bound_candidate or candidate()
    return ValidationEvidence(
        strategy_id=bound.strategy_id,
        genome_hash=bound.genome_hash,
        evidence_type=kind,
        dataset_hash=dataset_hash,
        code_hash=code_hash,
        engine="mastertrd-live-probe",
        engine_version="1",
        passed=True,
        metrics={"completed": 1.0},
    )


def test_candidate_manifest_round_trips_exact_public_identity():
    genome = candidate()
    loaded = TestnetCandidateManifest.from_public_payload(manifest().to_public_payload())

    assert loaded.candidate == genome
    assert loaded.strategy_id == genome.strategy_id
    assert loaded.genome_hash == genome.genome_hash
    assert loaded.code_hash == "code-champion-001"
    assert loaded.dataset_hash == "dataset-champion-001"
    assert loaded.product is BinanceProduct.SPOT
    assert loaded.probe_instrument == "BTCUSDT.BINANCE"
    assert loaded.order_notional_cap == Decimal("10")
    payload = loaded.to_public_payload()
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
    payload = manifest().to_public_payload()
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


def test_candidate_testnet_bundle_requires_manifest_candidate_and_provenance_identity():
    records = tuple(
        live_record(kind)
        for kind in (
            "risk_review",
            "reconciliation_test",
            "kill_switch_test",
            "testnet_smoke",
        )
    )
    assert candidate_testnet_bundle_identity_ok(manifest(), records) is True

    wrong_code = records[:-1] + (live_record("testnet_smoke", code_hash="other-code"),)
    assert candidate_testnet_bundle_identity_ok(manifest(), wrong_code) is False

    wrong_dataset = records[:-1] + (live_record("testnet_smoke", dataset_hash="other-dataset"),)
    assert candidate_testnet_bundle_identity_ok(manifest(), wrong_dataset) is False


def test_generic_system_smoke_cannot_satisfy_champion_manifest():
    generic = StrategyGenome(
        strategy_id="MASTERTRD-TESTNET-SMOKE",
        family="execution_probe",
        style="testnet",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "bounded_testnet_order"},
        exit={"kind": "cancel_on_shutdown"},
    )
    records = tuple(
        live_record(kind, bound_candidate=generic)
        for kind in (
            "risk_review",
            "reconciliation_test",
            "kill_switch_test",
            "testnet_smoke",
        )
    )

    assert candidate_testnet_bundle_identity_ok(manifest(), records) is False


def _write_manifest(tmp_path, item: TestnetCandidateManifest) -> str:
    path = tmp_path / "champion-testnet.json"
    path.write_text(json.dumps(item.to_public_payload()), encoding="utf-8")
    return str(path)


def _testnet_env(path: str, *, code_hash: str = "code-champion-001") -> dict[str, str]:
    return {
        "MASTERTRD_MODE": "TESTNET",
        "MASTERTRD_TESTNET_CANDIDATE_MANIFEST": path,
        "GITHUB_SHA": code_hash,
        "BINANCE_TESTNET_API_KEY": "test-key",
        "BINANCE_TESTNET_API_SECRET": "test-secret",
        "BINANCE_TESTNET_ACCOUNT_ID": "test-account",
    }


def test_testnet_smoke_uses_candidate_manifest_identity_and_order_cap(monkeypatch, tmp_path):
    path = _write_manifest(tmp_path, manifest())
    rules = SpotTestnetRules(
        symbol="BTCUSDT",
        min_notional=Decimal("5"),
        step_size=Decimal("0.00001"),
        min_quantity=Decimal("0.00001"),
    )
    submitted = []
    monkeypatch.setattr(testnet_smoke, "fetch_spot_testnet_rules", lambda symbol: rules)
    monkeypatch.setattr(
        testnet_smoke,
        "_submit_nautilus_spot_testnet_order",
        lambda **kwargs: submitted.append(kwargs) or True,
    )

    payload = testnet_smoke.run(_testnet_env(path))

    assert payload["strategy_id"] == candidate().strategy_id
    assert payload["genome_hash"] == candidate().genome_hash
    assert payload["code_hash"] == "code-champion-001"
    assert payload["dataset_hash"] == "dataset-champion-001"
    assert payload["product"] == "SPOT"
    assert payload["probe_instrument"] == "BTCUSDT.BINANCE"
    assert payload["order_notional_cap"] == "10"
    assert len(submitted) == 1
    assert Decimal(str(submitted[0]["minimum_notional"])) <= Decimal("10")


def test_testnet_smoke_rejects_checkout_code_drift(monkeypatch, tmp_path):
    path = _write_manifest(tmp_path, manifest())
    monkeypatch.setattr(
        testnet_smoke,
        "fetch_spot_testnet_rules",
        lambda symbol: SpotTestnetRules(
            symbol=symbol,
            min_notional=Decimal("5"),
            step_size=Decimal("0.00001"),
            min_quantity=Decimal("0.00001"),
        ),
    )

    with pytest.raises(RuntimeError, match="code_hash"):
        testnet_smoke.run(_testnet_env(path, code_hash="different-checkout"))


def test_testnet_smoke_refuses_venue_minimum_above_candidate_cap(monkeypatch, tmp_path):
    path = _write_manifest(tmp_path, manifest(cap=Decimal("4")))
    submitted = []
    monkeypatch.setattr(
        testnet_smoke,
        "fetch_spot_testnet_rules",
        lambda symbol: SpotTestnetRules(
            symbol=symbol,
            min_notional=Decimal("5"),
            step_size=Decimal("0.00001"),
            min_quantity=Decimal("0.00001"),
        ),
    )
    monkeypatch.setattr(
        testnet_smoke,
        "_submit_nautilus_spot_testnet_order",
        lambda **kwargs: submitted.append(kwargs) or True,
    )

    with pytest.raises(RuntimeError, match="order_notional_cap"):
        testnet_smoke.run(_testnet_env(path))
    assert submitted == []


def test_testnet_smoke_without_owner_credentials_is_candidate_bound_and_never_touches_network(monkeypatch, tmp_path):
    path = _write_manifest(tmp_path, manifest())
    network_calls = []
    monkeypatch.setattr(
        testnet_smoke,
        "fetch_spot_testnet_rules",
        lambda symbol: network_calls.append(symbol) or pytest.fail("network must not be used without credentials"),
    )

    payload = testnet_smoke.run(
        {
            "MASTERTRD_MODE": "TESTNET",
            "MASTERTRD_TESTNET_CANDIDATE_MANIFEST": path,
            "GITHUB_SHA": "code-champion-001",
        }
    )

    assert payload["strategy_id"] == candidate().strategy_id
    assert payload["genome_hash"] == candidate().genome_hash
    assert payload["code_hash"] == "code-champion-001"
    assert payload["dataset_hash"] == "dataset-champion-001"
    assert payload["runtime_mode"] == "TESTNET"
    assert payload["status"] == "CREDENTIALS_UNAVAILABLE"
    assert payload["passed"] is False
    assert payload["blocker"] == "BLOCKED_OWNER_INPUT"
    assert network_calls == []
