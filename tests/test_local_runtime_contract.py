from pathlib import Path


def test_runtime_has_no_oracle_product_path():
    for path in (
        "src/mastertrd/oracle.py",
        "src/mastertrd/oracle_paper_status.py",
        "src/mastertrd/paper_diagnostics.py",
        ".github/workflows/oracle-deploy.yml",
        ".github/workflows/paper-status.yml",
    ):
        assert not Path(path).exists()
    assert Path("src/mastertrd/live_node.py").exists()
    assert Path("src/mastertrd/asset_transfer.py").exists()
