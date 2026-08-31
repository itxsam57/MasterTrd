from __future__ import annotations

from collections.abc import Mapping

from .execution_runtime import ExecutionRuntime
from .runtime import RuntimeConfig


def build_execution_runtime(
    runtime: RuntimeConfig,
    environ: Mapping[str, str],
) -> ExecutionRuntime:
    """Build the repository-owned persistent execution runtime.

    Mode-specific construction is intentionally fail-closed until the runtime
    inputs required by the persistent PAPER/DEMO/TESTNET/LIVE adapters are
    supplied by the checked-in factory implementation.
    """
    del runtime, environ
    raise RuntimeError("canonical execution runtime construction is not configured")
