from dataclasses import dataclass

from mastertrd.contracts import RuntimeMode
from mastertrd.live_node import NodeReadiness, run_node
from mastertrd.runtime import RuntimeConfig


@dataclass(frozen=True)
class _Report:
    system_killed: bool
    session_rotation_requested: bool


class _RotatingRuntime:
    def __init__(self, calls: list[str], report: _Report):
        self._calls = calls
        self._report = report

    def run(self, *, stop_requested):
        self._calls.append("run")
        assert stop_requested() is False
        return self._report

    def complete_session(self):
        self._calls.append("complete")

    def close(self):
        self._calls.append("close")


def _paper_runtime() -> RuntimeConfig:
    return RuntimeConfig(
        mode=RuntimeMode.PAPER,
        live_trading_enabled=False,
        oracle_enabled=True,
    )


def test_run_node_completes_paper_session_only_after_safe_rotation_boundary():
    calls: list[str] = []
    execution = _RotatingRuntime(
        calls,
        _Report(system_killed=False, session_rotation_requested=True),
    )

    readiness = run_node(
        _paper_runtime(),
        {},
        stop_requested=lambda: False,
        sleep=lambda _seconds: None,
        heartbeat=lambda state: calls.append(state.value),
        interval_seconds=1.0,
        execution_runtime=execution,
    )

    assert readiness is NodeReadiness.PAPER_READY
    assert calls == [NodeReadiness.PAPER_READY.value, "run", "complete", "close"]


def test_run_node_never_finalizes_system_killed_session_even_if_rotation_was_requested():
    calls: list[str] = []
    execution = _RotatingRuntime(
        calls,
        _Report(system_killed=True, session_rotation_requested=True),
    )

    readiness = run_node(
        _paper_runtime(),
        {},
        stop_requested=lambda: False,
        sleep=lambda _seconds: None,
        heartbeat=lambda state: calls.append(state.value),
        interval_seconds=1.0,
        execution_runtime=execution,
    )

    assert readiness is NodeReadiness.PAPER_READY
    assert calls == [NodeReadiness.PAPER_READY.value, "run", "close"]
