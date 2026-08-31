from __future__ import annotations

from decimal import Decimal
from importlib import import_module
from importlib.util import find_spec
import json

import pytest

from mastertrd.genome import StrategyGenome
from mastertrd.testnet_candidate import TestnetCandidateManifest
from mastertrd.venue import BinanceProduct


def test_testnet_smoke_runner_exists_and_rounds_up_to_venue_minimum():
    spec = find_spec("mastertrd.testnet_smoke")
    assert spec is not None, "missing production TESTNET smoke runner"

    module = import_module("mastertrd.testnet_smoke")
    calculate = getattr(module, "calculate_minimum_order_quantity", None)
    assert callable(calculate), "TESTNET smoke runner must expose minimum-size calculation"

    quantity = calculate(
        min_notional=Decimal("5"),
        limit_price=Decimal("49995"),
        step_size=Decimal("0.00001"),
        min_quantity=Decimal("0.00001"),
    )

    assert quantity == Decimal("0.00011")
    assert quantity * Decimal("49995") >= Decimal("5")


def test_testnet_smoke_runner_never_rounds_below_exchange_min_quantity():
    spec = find_spec("mastertrd.testnet_smoke")
    assert spec is not None, "missing production TESTNET smoke runner"

    module = import_module("mastertrd.testnet_smoke")
    calculate = getattr(module, "calculate_minimum_order_quantity", None)
    assert callable(calculate)

    quantity = calculate(
        min_notional=Decimal("1"),
        limit_price=Decimal("100000"),
        step_size=Decimal("0.0001"),
        min_quantity=Decimal("0.001"),
    )

    assert quantity == Decimal("0.001")


def _champion() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="S-CHAMPION-SMOKE-001",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 5, "slow_period": 20},
        exit={"kind": "cross_reverse"},
        risk={"risk_fraction": 0.01},
    )


def _manifest_path(tmp_path, *, code_hash: str = "code-champion-001"):
    manifest = TestnetCandidateManifest.from_candidate(
        _champion(),
        code_hash=code_hash,
        dataset_hash="dataset-champion-001",
        product=BinanceProduct.SPOT,
        probe_instrument="BTCUSDT.BINANCE",
        order_notional_cap=Decimal("10"),
    )
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(manifest.to_public_payload()), encoding="utf-8")
    return path, manifest


def test_testnet_smoke_runner_uses_candidate_bound_manifest(monkeypatch, tmp_path):
    module = import_module("mastertrd.testnet_smoke")
    manifest_path, manifest = _manifest_path(tmp_path)
    seen = {}

    monkeypatch.setattr(
        module,
        "fetch_spot_testnet_rules",
        lambda symbol: module.SpotTestnetRules(
            symbol=symbol,
            min_notional=Decimal("5"),
            step_size=Decimal("0.00001"),
            min_quantity=Decimal("0.00001"),
        ),
    )

    def fake_run_testnet_smoke(candidate, **kwargs):
        seen["candidate"] = candidate
        seen.update(kwargs)
        return type(
            "Evidence",
            (),
            {
                "__dataclass_fields__": {},
            },
        )()

    # Return a real dataclass-shaped value so production asdict remains active.
    from mastertrd.live_evidence import LiveEvidenceStatus, LiveValidationEvidence

    def capture(candidate, **kwargs):
        seen["candidate"] = candidate
        seen.update(kwargs)
        return LiveValidationEvidence(
            strategy_id=candidate.strategy_id,
            genome_hash=candidate.genome_hash,
            evidence_type="testnet_smoke",
            dataset_hash=kwargs["dataset_hash"],
            code_hash=kwargs["code_hash"],
            engine="test",
            engine_version="1",
            passed=True,
            metrics={"submitted_notional": 5.0},
            status=LiveEvidenceStatus.COMPLETED,
        )

    monkeypatch.setattr(module, "run_testnet_smoke", capture)

    payload = module.run(
        {
            "MASTERTRD_MODE": "TESTNET",
            "MASTERTRD_TESTNET_CANDIDATE_MANIFEST": str(manifest_path),
            "GITHUB_SHA": manifest.code_hash,
            "BINANCE_TESTNET_API_KEY": "test-key",
            "BINANCE_TESTNET_API_SECRET": "test-secret",
            "BINANCE_TESTNET_ACCOUNT_ID": "test-account",
        }
    )

    assert seen["candidate"] == manifest.candidate
    assert seen["dataset_hash"] == manifest.dataset_hash
    assert seen["code_hash"] == manifest.code_hash
    assert seen["venue_minimum_notional"] == 5.0
    assert payload["strategy_id"] == manifest.strategy_id
    assert payload["genome_hash"] == manifest.genome_hash


def test_testnet_smoke_runner_rejects_manifest_for_different_code(monkeypatch, tmp_path):
    module = import_module("mastertrd.testnet_smoke")
    manifest_path, _ = _manifest_path(tmp_path, code_hash="expected-sha")
    monkeypatch.setattr(
        module,
        "fetch_spot_testnet_rules",
        lambda symbol: module.SpotTestnetRules(
            symbol=symbol,
            min_notional=Decimal("5"),
            step_size=Decimal("0.00001"),
            min_quantity=Decimal("0.00001"),
        ),
    )

    with pytest.raises(RuntimeError, match="code"):
        module.run(
            {
                "MASTERTRD_MODE": "TESTNET",
                "MASTERTRD_TESTNET_CANDIDATE_MANIFEST": str(manifest_path),
                "GITHUB_SHA": "different-sha",
            }
        )
