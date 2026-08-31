from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_hft_strategy_is_owned_by_focused_execution_gate() -> None:
    core = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    execution = (ROOT / ".github/workflows/execution-stack.yml").read_text(encoding="utf-8")

    assert "src/mastertrd/hft_strategy.py" in core
    assert execution.count("src/mastertrd/hft_strategy.py") >= 2
    assert execution.count("tests/test_hft_strategy.py") >= 3
    assert execution.count("tests/integration/test_hft_nautilus_execution.py") >= 3


def test_risk_state_is_owned_by_focused_execution_gate() -> None:
    execution = (ROOT / ".github/workflows/execution-stack.yml").read_text(encoding="utf-8")

    for path in (
        "src/mastertrd/risk_state.py",
        "src/mastertrd/risk_runtime.py",
        "src/mastertrd/nautilus_risk_hook.py",
        "src/mastertrd/execution_runtime.py",
    ):
        assert execution.count(path) >= 2

    for path in (
        "tests/test_risk_state.py",
        "tests/test_risk_runtime.py",
        "tests/integration/test_risk_execution_hook.py",
        "tests/integration/test_runtime_recovery.py",
    ):
        assert execution.count(path) >= 3
