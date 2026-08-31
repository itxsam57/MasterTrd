from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_hft_strategy_is_owned_by_focused_execution_gate() -> None:
    core = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    execution = (ROOT / ".github/workflows/execution-stack.yml").read_text(encoding="utf-8")

    assert "src/mastertrd/hft_strategy.py" in core
    assert execution.count("src/mastertrd/hft_strategy.py") >= 2
    assert execution.count("tests/test_hft_strategy.py") >= 3
