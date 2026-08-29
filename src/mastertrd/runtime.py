from __future__ import annotations

from dataclasses import dataclass
import os

from .contracts import RuntimeMode


_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    mode: RuntimeMode
    live_trading_enabled: bool
    oracle_enabled: bool

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "RuntimeConfig":
        source = os.environ if env is None else env
        mode = RuntimeMode(source.get("MASTERTRD_MODE", "PAPER").upper())
        live = source.get("LIVE_TRADING_ENABLED", "false").lower() in _TRUE
        oracle = source.get("ORACLE_ENABLED", "false").lower() in _TRUE
        if mode is RuntimeMode.LIVE and not live:
            raise RuntimeError("LIVE mode requires LIVE_TRADING_ENABLED=true")
        if live and mode is not RuntimeMode.LIVE:
            raise RuntimeError("LIVE_TRADING_ENABLED=true is invalid outside LIVE mode")
        return cls(mode=mode, live_trading_enabled=live, oracle_enabled=oracle)
