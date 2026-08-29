from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from math import floor
from typing import Sequence, TypeVar


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class HoldoutManifest:
    dataset_hash: str
    total_count: int
    research_count: int
    hidden_count: int
    hidden_start: int
    version: int = 1

    @property
    def canonical_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    @property
    def manifest_hash(self) -> str:
        return hashlib.sha256(self.canonical_json.encode()).hexdigest()


def chronological_holdout(
    values: Sequence[T],
    *,
    hidden_fraction: float = 0.20,
    min_research: int = 1,
    min_hidden: int = 1,
    dataset_hash: str = "unversioned",
) -> tuple[tuple[T, ...], tuple[T, ...], HoldoutManifest]:
    if not 0 < hidden_fraction < 1:
        raise ValueError("hidden_fraction must be between 0 and 1")
    if min_research < 1 or min_hidden < 1:
        raise ValueError("minimum partition sizes must be positive")
    if not dataset_hash:
        raise ValueError("dataset_hash is required")

    total_count = len(values)
    hidden_count = max(min_hidden, floor(total_count * hidden_fraction))
    research_count = total_count - hidden_count
    if research_count < min_research or hidden_count < min_hidden:
        raise ValueError("not enough observations for research and hidden holdout")

    research = tuple(values[:research_count])
    hidden = tuple(values[research_count:])
    manifest = HoldoutManifest(
        dataset_hash=dataset_hash,
        total_count=total_count,
        research_count=research_count,
        hidden_count=hidden_count,
        hidden_start=research_count,
    )
    return research, hidden, manifest
