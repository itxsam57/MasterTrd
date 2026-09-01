from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _load(name: str) -> tuple[str, dict]:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    assert isinstance(workflow, dict)
    return text, workflow


def _on(workflow: dict) -> dict:
    triggers = workflow.get("on", workflow.get(True, {}))
    assert isinstance(triggers, dict)
    return triggers


def test_public_metadata_dependency_retriggers_autonomous_research_on_main():
    _, workflow = _load("autonomous-research.yml")
    push = _on(workflow)["push"]
    assert push["branches"] == ["main"]
    assert "src/mastertrd/nautilus_paper.py" in set(push["paths"])


def test_research_stack_owns_public_metadata_loader_and_regression_contract():
    text, workflow = _load("research-stack.yml")
    triggers = _on(workflow)
    required_paths = {
        "src/mastertrd/nautilus_paper.py",
        "tests/test_binance_public_metadata.py",
        "tests/test_research_metadata_workflow_policy.py",
    }
    assert required_paths <= set(triggers["push"]["paths"])
    assert required_paths <= set(triggers["pull_request"]["paths"])

    lower = text.lower()
    assert "tests/test_binance_public_metadata.py" in lower
    assert "tests/test_research_metadata_workflow_policy.py" in lower
