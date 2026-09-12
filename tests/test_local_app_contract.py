from pathlib import Path


def test_local_app_has_consumer_sections():
    text = Path("src/mastertrd/local_app.py").read_text(encoding="utf-8")
    for title in (
        "Dashboard",
        "Strategies",
        "Backtest Lab",
        "Trading",
        "Accounts / Providers",
        "System Health",
    ):
        assert title in text


def test_local_app_does_not_embed_order_execution_logic():
    text = Path("src/mastertrd/local_app.py").read_text(encoding="utf-8")
    assert "submit_order" not in text
    assert "build_execution_runtime" not in text
