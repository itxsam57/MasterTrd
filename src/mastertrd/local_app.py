from __future__ import annotations

from pathlib import Path

import streamlit as st

from mastertrd.local_jobs import (
    launch_research_matrix,
    list_local_jobs,
    local_paper_candidates,
    local_result_rows,
)
from mastertrd.strategy_universe import strategy_recipe_timeframes
from mastertrd.trading_service import TradingService


JOB_ROOT = Path("artifacts/local-jobs")


def _parse_instruments(raw: str) -> tuple[str, ...]:
    values = tuple(dict.fromkeys(value.strip().upper() for value in raw.split(",") if value.strip()))
    if len(values) < 2:
        raise ValueError("Backtest Lab requires at least two instruments for transfer validation.")
    return values


def _result_table(rows: list[dict[str, object]]) -> None:
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No local research results yet.")


def render_app() -> None:
    st.set_page_config(page_title="MasterTrd", layout="wide")
    service = TradingService()
    snapshot = service.snapshot()
    strategies = service.strategy_rows()
    jobs = list_local_jobs(JOB_ROOT)
    results = local_result_rows(JOB_ROOT)
    paper_candidates = local_paper_candidates(JOB_ROOT)

    st.title("MasterTrd")
    tabs = st.tabs([
        "Dashboard",
        "Strategies",
        "Backtest Lab",
        "Trading",
        "Accounts / Providers",
        "System Health",
    ])

    with tabs[0]:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Mode", snapshot["mode"])
        c2.metric("Strategies", snapshot["strategy_count"])
        c3.metric("LIVE", "ENABLED" if snapshot["live_enabled"] else "LOCKED")
        c4.metric("Emergency stop", "ACTIVE" if snapshot["emergency_stop"] else "CLEAR")

        portfolio = snapshot.get("portfolio")
        if isinstance(portfolio, dict):
            risk = portfolio.get("risk", {})
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("P&L", f'{float(risk.get("daily_pnl", 0.0)):,.2f}')
            p2.metric("Exposure", f'{float(risk.get("exposure", 0.0)):,.2f}')
            p3.metric("Drawdown", f'{float(risk.get("drawdown", 0.0)):.2%}')
            p4.metric("Leverage", f'{float(risk.get("leverage", 0.0)):.2f}x')
            st.subheader("Positions")
            positions = portfolio.get("positions", {})
            st.dataframe(
                [{"instrument": key, "quantity": value} for key, value in positions.items()],
                use_container_width=True,
                hide_index=True,
            )
            st.subheader("PAPER strategies")
            st.dataframe(portfolio.get("strategies", []), use_container_width=True, hide_index=True)
        elif "paper" in snapshot:
            st.subheader("PAPER strategy")
            st.json(snapshot["paper"])
        else:
            st.info("No active persisted PAPER session is configured.")

        j1, j2 = st.columns(2)
        j1.metric("Local jobs", len(jobs))
        j2.metric("Completed result records", sum(row["report"] is not None for row in results))
        st.caption("Research workers and the trading worker are separate local processes.")

    with tabs[1]:
        st.dataframe(strategies, use_container_width=True, hide_index=True)

    with tabs[2]:
        executable = [row for row in strategies if row["readiness"] == "EXECUTABLE"]
        by_label = {
            f'{row["name"]} · {row["recipe_id"]}': row["recipe_id"]
            for row in executable
        }
        selected_labels = st.multiselect(
            "Strategies",
            list(by_label),
            default=list(by_label)[:1],
        )
        selected_recipe_ids = tuple(by_label[label] for label in selected_labels)
        supported_timeframes = sorted({
            timeframe
            for recipe_id in selected_recipe_ids
            for timeframe in strategy_recipe_timeframes(recipe_id)
        })
        selected_timeframes = tuple(
            st.multiselect(
                "Timeframes",
                supported_timeframes,
                default=supported_timeframes[:1],
            )
        )
        instruments_raw = st.text_input(
            "Binance instruments",
            value="BTCUSDT.BINANCE,ETHUSDT.BINANCE",
            help="Comma-separated admitted Binance spot instrument IDs. At least two are required for transfer validation.",
        )
        b1, b2, b3 = st.columns(3)
        seed_start = int(b1.number_input("Seed start", min_value=0, value=40, step=1))
        seed_count = int(b2.number_input("Seeds per cell", min_value=1, value=1, step=1))
        archive_months = int(b3.number_input("History months", min_value=2, value=2, step=1))
        st.caption(
            "Every matrix cell runs the full MasterTrd validation path: screening, optimization, "
            "evolution, execution-realistic validation, robustness, hidden/OOS and required specialist gates."
        )

        if st.button("Run backtest matrix", type="primary"):
            try:
                receipts = launch_research_matrix(
                    selected_recipe_ids,
                    JOB_ROOT,
                    instruments=_parse_instruments(instruments_raw),
                    timeframes=selected_timeframes,
                    seed_start=seed_start,
                    seed_stop=seed_start + seed_count,
                    archive_months=archive_months,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.success(f"Started {len(receipts)} isolated research jobs.")

        st.subheader("Jobs")
        if jobs:
            st.dataframe([job.to_dict() for job in jobs], use_container_width=True, hide_index=True)
        else:
            st.info("No local research jobs yet.")
        st.subheader("Results")
        _result_table(results)

    with tabs[3]:
        st.subheader("Trading")
        st.write(f'Current mode: **{snapshot["mode"]}**')
        if snapshot["live_enabled"]:
            st.warning("LIVE is enabled by runtime configuration. Provider admission and risk gates still apply.")
        else:
            st.success("LIVE is locked. PAPER remains the safe default.")

        if snapshot["emergency_stop"]:
            st.error("EMERGENCY STOP IS ACTIVE. Trading worker start/order flow is blocked.")
            if snapshot["mode"] != "LIVE" and st.button("Clear emergency stop"):
                service.clear_emergency_stop()
                st.rerun()
        elif st.button("EMERGENCY STOP", type="primary"):
            service.activate_emergency_stop()
            st.rerun()

        portfolio = snapshot.get("portfolio")
        if isinstance(portfolio, dict):
            st.subheader("Shared portfolio / risk")
            st.json(portfolio.get("risk", {}))
            st.dataframe(portfolio.get("strategies", []), use_container_width=True, hide_index=True)

        st.subheader("Validated PAPER finalists")
        finalist_labels = {
            (
                f'{row.get("recipe_id") or "generated"} · '
                f'{row.get("strategy_id")} · {row.get("timeframe")} · '
                f'{str(row.get("genome_hash"))[:10]}'
            ): row
            for row in paper_candidates
        }
        selected_finalist_labels = st.multiselect(
            "Shared PAPER portfolio",
            list(finalist_labels),
            help="Only candidates that completed the research pipeline into PAPER are listed.",
        )
        if st.button("Prepare shared PAPER portfolio"):
            selected_manifests = [
                finalist_labels[label]["manifest"]
                for label in selected_finalist_labels
            ]
            try:
                configured = service.configure_paper_portfolio(selected_manifests)
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))
            else:
                st.success(
                    "Configured shared PAPER portfolio "
                    f'{configured["portfolio_id"]}. Start or restart mastertrd trading.'
                )
                st.rerun()
        if len(paper_candidates) < 2:
            st.info(
                "Run research until at least two current-code candidates qualify for PAPER "
                "before creating a shared portfolio."
            )
        st.caption("The app never submits orders directly; the persistent trading worker owns execution.")

    with tabs[4]:
        st.subheader("Accounts / Providers")
        providers = service.provider_rows()
        display = []
        for row in providers:
            item = dict(row)
            item["credential_names"] = ", ".join(item["credential_names"])
            display.append(item)
        st.dataframe(display, use_container_width=True, hide_index=True)
        st.subheader("Local runtime settings")
        safe_modes = ["PAPER", "DEMO", "TESTNET"]
        configured_mode = snapshot["mode"] if snapshot["mode"] in safe_modes else "PAPER"
        selected_mode = st.selectbox(
            "Mode",
            safe_modes,
            index=safe_modes.index(configured_mode),
            help="LIVE is intentionally not writable from the app.",
        )
        selected_product = st.selectbox(
            "Binance product",
            ["SPOT", "USD_M", "COIN_M"],
            index=["SPOT", "USD_M", "COIN_M"].index(display[0]["product"])
            if display[0]["product"] in {"SPOT", "USD_M", "COIN_M"}
            else 0,
        )
        if st.button("Save local runtime settings"):
            path = service.save_local_settings(mode=selected_mode, product=selected_product)
            st.success(f"Saved non-secret settings to {path}")
            st.rerun()
        if snapshot["mode"] == "LIVE":
            st.warning("LIVE is active through explicit environment configuration and cannot be enabled or cleared here.")
        st.info(
            "Credentials are read only from the protected local environment/OS secret source. "
            "MasterTrd does not save API secrets, account IDs, or keys in the app, artifacts, or repository."
        )

    with tabs[5]:
        st.subheader("System Health")
        st.json(snapshot)
        st.write(f"Local job root: `{JOB_ROOT}`")
        st.write(f"Known local jobs: **{len(jobs)}**")
        failed = [row for row in results if row["status"] == "FAILED"]
        st.write(f"Failed research jobs: **{len(failed)}**")
        if failed:
            st.dataframe(failed, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    render_app()
