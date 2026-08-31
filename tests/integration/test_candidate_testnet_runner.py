from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path

import pytest

from mastertrd.genome import StrategyGenome
from mastertrd.testnet_candidate import TestnetCandidateManifest
from mastertrd import testnet_smoke
from mastertrd.testnet_smoke import SpotTestnetRules
from mastertrd.venue import BinanceProduct


def _candidate() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="S-CHAMPION-TESTNET-001",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 5, "slow_period": 20},
        exit={"kind": "cross_reverse"},
        risk={"risk_fraction": 0.01},
    )


def _manifest(path: Path, *, code_hash: str = "code-champion-001", cap: str = "10") -> TestnetCandidateManifest:
    manifest = TestnetCandidateManifest.from_candidate(
        _candidate(),
        code_hash=code_hash,
        dataset_hash="dataset-champion-001",
        product=BinanceProduct.SPOT,
        probe_instrument="BTCUSDT.BINANCE",
        order_notional_cap=Decimal(cap),
    )
    path.write_text(json.dumps(manifest.to_public_payload()), encoding="utf-8")
    return manifest


def _env(path: Path, *, code_hash: str = "code-champion-001") -> dict[str, str]:
    return {
        "MASTERTRD_MODE": "TESTNET",
        "LIVE_TRADING_ENABLED": "false",
        "GITHUB_SHA": code_hash,
        "MASTERTRD_TESTNET_CANDIDATE_PATH": str(path),
        # Deliberately conflicting legacy symbol: candidate manifest must win.
        "MASTERTRD_TESTNET_SYMBOL": "ETHUSDT",
        "BINANCE_TESTNET_API_KEY": "test-key",
        "BINANCE_TESTNET_API_SECRET": "test-secret",
        "BINANCE_TESTNET_ACCOUNT_ID": "test-account",
    }


def _rules(min_notional: str = "5") -> SpotTestnetRules:
    return SpotTestnetRules(
        symbol="BTCUSDT",
        min_notional=Decimal(min_notional),
        step_size=Decimal("0.00001"),
        min_quantity=Decimal("0.00001"),
    )


def test_testnet_runner_uses_exact_candidate_and_manifest_provenance(monkeypatch, tmp_path: Path):
    path = tmp_path / "candidate.json"
    manifest = _manifest(path)
    seen: dict[str, object] = {}

    monkeypatch.setattr(testnet_smoke, "fetch_spot_testnet_rules", lambda symbol: seen.setdefault("symbol", symbol) or _rules())
    # Avoid the truthiness trick above returning the symbol instead of rules.
    def fake_rules(symbol: str):
        seen["symbol"] = symbol
        return _rules()

    monkeypatch.setattr(testnet_smoke, "fetch_spot_testnet_rules", fake_rules)

    def fake_submit(**kwargs):
        seen["minimum_notional"] = Decimal(str(kwargs["minimum_notional"]))
        seen["submitted_symbol"] = kwargs["symbol"]
        return True

    monkeypatch.setattr(testnet_smoke, "_submit_nautilus_spot_testnet_order", fake_submit)

    payload = testnet_smoke.run(_env(path))

    assert payload["strategy_id"] == manifest.strategy_id
    assert payload["genome_hash"] == manifest.genome_hash
    assert payload["dataset_hash"] == manifest.dataset_hash
    assert payload["code_hash"] == manifest.code_hash
    assert payload["symbol"] == "BTCUSDT"
    assert seen["symbol"] == "BTCUSDT"
    assert seen["submitted_symbol"] == "BTCUSDT"
    assert seen["minimum_notional"] == Decimal("5")


def test_testnet_runner_rejects_manifest_for_different_code_sha(tmp_path: Path):
    path = tmp_path / "candidate.json"
    _manifest(path, code_hash="champion-code")

    with pytest.raises(RuntimeError, match="code_hash"):
        testnet_smoke.run(_env(path, code_hash="different-code"))


def test_testnet_runner_refuses_venue_minimum_above_candidate_notional_cap(monkeypatch, tmp_path: Path):
    path = tmp_path / "candidate.json"
    _manifest(path, cap="5")
    monkeypatch.setattr(testnet_smoke, "fetch_spot_testnet_rules", lambda symbol: _rules("10"))
    monkeypatch.setattr(
        testnet_smoke,
        "_submit_nautilus_spot_testnet_order",
        lambda **kwargs: pytest.fail("order submission must not run above candidate cap"),
    )

    with pytest.raises(RuntimeError, match="order_notional_cap"):
        testnet_smoke.run(_env(path))
