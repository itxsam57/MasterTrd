from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from math import isfinite
from statistics import fmean
from typing import Sequence

from .contracts import EvaluationResult
from .genome import StrategyGenome
from .validation import ValidationEvidence


@dataclass(frozen=True, slots=True)
class AssetTransferPolicy:
    min_transfer_assets: int
    min_trades_per_asset: int
    min_pass_ratio: float
    min_total_return: float
    max_drawdown: float

    def __post_init__(self) -> None:
        if self.min_transfer_assets <= 0:
            raise ValueError("min_transfer_assets must be positive")
        if self.min_trades_per_asset <= 0:
            raise ValueError("min_trades_per_asset must be positive")
        if not all(
            isfinite(float(value))
            for value in (self.min_pass_ratio, self.min_total_return, self.max_drawdown)
        ):
            raise ValueError("asset transfer thresholds must be finite")
        if not 0.0 <= self.min_pass_ratio <= 1.0:
            raise ValueError("min_pass_ratio must be between 0 and 1")
        if not 0.0 <= self.max_drawdown <= 1.0:
            raise ValueError("max_drawdown must be between 0 and 1")


def _logic_payload(genome: StrategyGenome) -> dict[str, object]:
    payload = genome.canonical_payload()
    payload.pop("instruments", None)
    return payload


def _aggregate_hash(cases: Sequence[tuple[StrategyGenome, EvaluationResult]]) -> str:
    payload = [
        {
            "instruments": list(transfer.instruments),
            "dataset_hash": result.dataset_hash,
        }
        for transfer, result in cases
    ]
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def asset_transfer_evidence(
    candidate: StrategyGenome,
    cases: Sequence[tuple[StrategyGenome, EvaluationResult]],
    policy: AssetTransferPolicy,
) -> ValidationEvidence:
    if len(cases) < policy.min_transfer_assets:
        raise ValueError("transfer cases must satisfy min_transfer_assets")

    target_instruments = [tuple(transfer.instruments) for transfer, _ in cases]
    if len(set(target_instruments)) != len(target_instruments):
        raise ValueError("transfer target instruments must be unique")

    candidate_instruments = tuple(candidate.instruments)
    candidate_logic = _logic_payload(candidate)
    first_result = cases[0][1]

    for transfer, result in cases:
        if tuple(transfer.instruments) == candidate_instruments:
            raise ValueError("transfer genome must use different instruments")
        if _logic_payload(transfer) != candidate_logic:
            raise ValueError("transfer genome must preserve strategy logic")
        if result.strategy_id != transfer.strategy_id:
            raise ValueError("result strategy_id does not match transfer genome")
        if result.genome_hash != transfer.genome_hash:
            raise ValueError("result genome_hash does not match transfer genome")
        if result.code_hash != first_result.code_hash:
            raise ValueError("all transfer results must share code_hash")
        if result.engine != first_result.engine:
            raise ValueError("all transfer results must use the same engine")
        if result.engine_version != first_result.engine_version:
            raise ValueError("all transfer results must share engine_version")

    passing = sum(
        result.engine == "nautilus_trader"
        and result.trade_count >= policy.min_trades_per_asset
        and result.total_return >= policy.min_total_return
        and result.max_drawdown <= policy.max_drawdown
        and float(result.scores.get("execution_backtest", 0.0)) > 0.0
        for _, result in cases
    )
    pass_ratio = passing / len(cases)

    return ValidationEvidence(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        evidence_type="asset_transfer",
        dataset_hash=_aggregate_hash(cases),
        code_hash=first_result.code_hash,
        engine=first_result.engine,
        engine_version=first_result.engine_version,
        passed=pass_ratio >= policy.min_pass_ratio,
        metrics={
            "transfer_asset_count": float(len(cases)),
            "passing_asset_count": float(passing),
            "passing_asset_ratio": float(pass_ratio),
            "minimum_trade_count": float(min(result.trade_count for _, result in cases)),
            "worst_drawdown": float(max(result.max_drawdown for _, result in cases)),
            "average_total_return": float(fmean(result.total_return for _, result in cases)),
        },
    )
