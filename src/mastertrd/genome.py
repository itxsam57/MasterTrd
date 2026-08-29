from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Any, Mapping, Sequence


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _canonical(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


@dataclass(frozen=True, slots=True)
class StrategyGenome:
    strategy_id: str
    family: str
    style: str
    instruments: Sequence[str]
    timeframe: str
    entry: Mapping[str, Any]
    exit: Mapping[str, Any]
    filters: Mapping[str, Any] = field(default_factory=dict)
    risk: Mapping[str, Any] = field(default_factory=dict)
    data_requirements: Sequence[str] = field(default_factory=lambda: ("BAR",))
    allow_short: bool = False

    def __post_init__(self) -> None:
        if not self.strategy_id or not self.family or not self.style or not self.timeframe:
            raise ValueError("strategy identity fields are required")
        if not self.instruments:
            raise ValueError("at least one instrument is required")
        if not self.entry or not self.exit:
            raise ValueError("entry and exit rules are required")

    def canonical_payload(self) -> dict[str, Any]:
        return _canonical(asdict(self))

    @property
    def genome_hash(self) -> str:
        payload = json.dumps(self.canonical_payload(), separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()
