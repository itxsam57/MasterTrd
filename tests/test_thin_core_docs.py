from pathlib import Path


def test_thin_core_progress_and_inventory_exist():
    progress = Path("docs/THIN_CORE_PROGRESS.md").read_text(encoding="utf-8")
    inventory = Path("docs/THIN_CORE_INVENTORY.md").read_text(encoding="utf-8")
    assert "Thin Core / Full Lab / One Local App" in progress
    assert "Current slice" in progress
    assert "Next incomplete slice" in progress
    for token in ("KEEP", "MERGE", "REPLACE", "DELETE"):
        assert token in inventory
