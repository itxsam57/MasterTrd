from __future__ import annotations

from pathlib import Path

import streamlit as st

from mastertrd.app_service import AppService
from mastertrd.local_jobs import launch_research_job, list_local_jobs


JOB_ROOT = Path("artifacts/local-jobs")


def render_app() -> None:
    st.set_page_config(page_title="MasterTrd", layout="wide")
    service = AppService()
    snapshot = service.snapshot()
    strategies = service.strategy_rows()
    jobs = list_local_jobs(JOB_ROOT)

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
        c1, c2, c3 = st.columns(3)
        c1.metric("Mode", snapshot["mode"])
        c2.metric("Strategies", snapshot["strategy_count"])
        c3.metric("LIVE", "ENABLED" if snapshot["live_enabled"] else "LOCKED")
        st.caption("Local-first control plane. Research jobs run outside the UI process.")

    with tabs[1]:
        st.dataframe(strategies, use_container_width=True, hide_index=True)

    with tabs[2]:
        executable = [row for row in strategies if row["readiness"] == "EXECUTABLE"]
        by_name = {f'{row["name"]} · {row["recipe_id"]}': row["recipe_id"] for row in executable}
        selected = st.selectbox("Strategy", list(by_name))
        if st.button("Run backtest", type="primary"):
            receipt = launch_research_job(by_name[selected], JOB_ROOT)
            st.success(f"Started {receipt.job_id}")
            st.code(receipt.job_dir)
        if jobs:
            st.dataframe([job.to_dict() for job in jobs], use_container_width=True, hide_index=True)
        else:
            st.info("No local research jobs yet.")

    with tabs[3]:
        st.subheader("Trading")
        st.write(f'Current mode: **{snapshot["mode"]}**')
        if snapshot["live_enabled"]:
            st.warning("LIVE is enabled by runtime configuration. Provider admission and risk gates still apply.")
        else:
            st.success("LIVE is locked. PAPER remains the safe default.")
        st.caption("Trading controls move here only through the shared Nautilus/risk path; the UI never submits orders directly.")

    with tabs[4]:
        st.subheader("Accounts / Providers")
        st.write("Provider admission is fail-closed. Credentials stay local and outside git.")
        st.write("Binance is the currently admitted execution provider in the existing runtime; other catalog providers remain blocked until admitted.")

    with tabs[5]:
        st.subheader("System Health")
        st.json(snapshot)
        st.write(f"Local job root: `{JOB_ROOT}`")
        st.write(f"Known local jobs: **{len(jobs)}**")


if __name__ == "__main__":
    render_app()
