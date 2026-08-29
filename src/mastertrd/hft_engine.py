from __future__ import annotations

from dataclasses import dataclass

from .genome import StrategyGenome
from .hft_validation import HftStressReport


@dataclass(frozen=True, slots=True)
class HftEngineProbeResult:
    engine: str
    engine_version: str
    event_count: int
    best_bid: float
    best_ask: float
    processed: bool


def _validate_stress_request(dataset_hash: str, code_hash: str, cycles: int) -> None:
    if not dataset_hash:
        raise ValueError("dataset_hash is required")
    if not code_hash:
        raise ValueError("code_hash is required")
    if cycles <= 0:
        raise ValueError("cycles must be positive")


def probe_hftbacktest_engine() -> HftEngineProbeResult:
    from .research.hft_specialist import probe_hftbacktest_engine_impl

    return probe_hftbacktest_engine_impl()


def run_hftbacktest_stress_suite(
    candidate: StrategyGenome,
    *,
    dataset_hash: str,
    code_hash: str,
    cycles: int = 30,
) -> HftStressReport:
    _validate_stress_request(dataset_hash, code_hash, cycles)
    from .research.hft_specialist import run_hftbacktest_stress_suite_impl

    return run_hftbacktest_stress_suite_impl(
        candidate,
        dataset_hash=dataset_hash,
        code_hash=code_hash,
        cycles=cycles,
    )
