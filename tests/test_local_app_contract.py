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


def test_local_app_exposes_matrix_results_emergency_stop_and_safe_provider_settings():
    text = Path("src/mastertrd/local_app.py").read_text(encoding="utf-8")
    for required in (
        "Run backtest matrix",
        "launch_research_matrix",
        "local_result_rows",
        "EMERGENCY STOP",
        "activate_emergency_stop",
        "save_local_settings",
        "positions",
        "daily_pnl",
        "drawdown",
        "leverage",
    ):
        assert required in text
    assert "BINANCE_TESTNET_API_SECRET" not in text
