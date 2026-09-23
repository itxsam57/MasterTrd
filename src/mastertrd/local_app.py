from __future__ import annotations

from collections import Counter
from pathlib import Path

import streamlit as st

from mastertrd.autopilot import (
    AutopilotConfig,
    autopilot_state_path,
    load_autopilot_config,
    run_autopilot_cycle,
    save_autopilot_config,
)
from mastertrd.local_jobs import (
    launch_research_matrix,
    list_local_jobs,
    local_paper_candidates,
    local_result_rows,
    recommended_archive_months,
)
from mastertrd.market_universe import load_or_refresh_universe
from mastertrd.research_job import research_recipe_coverage, scheduled_public_recipe_ids
from mastertrd.strategy_families import family_spec
from mastertrd.strategy_universe import strategy_recipe_timeframes
from mastertrd.trading_service import TradingService


JOB_ROOT = Path("artifacts/local-jobs")
UNIVERSE_ROOT = Path("artifacts/market-universe")


_COVERAGE_REASON = {
    "public_binance_spot_asset_class_unavailable": "Needs a non-spot / non-crypto market data path.",
    "public_binance_product_asset_class_unavailable": "This strategy does not match the selected Binance product.",
    "scheduled_exact_multi_leg_validation_unavailable": "Needs exact multi-leg scheduled validation.",
    "qualifying_public_tick_data_unavailable": "Needs qualifying tick data.",
    "qualifying_public_l2_data_unavailable": "Needs qualifying L2 order-book data.",
    "qualifying_public_option_data_unavailable": "Needs qualifying options chain / Greeks data.",
    "exact_strategy_primitive_not_yet_implemented": "The strategy idea exists in the plan, but its exact signal primitive is not implemented yet.",
    "provider_not_admitted_to_mastertrd_runtime": "Needs a provider to be admitted and validated.",
    "experimental_model_requires_separate_validation_contract": "Experimental model; requires its own validation contract.",
    "qualifying_real_tick_evidence_required": "Needs real tick evidence before production research.",
    "qualifying_real_l2_queue_latency_evidence_required": "Needs real L2 queue and latency evidence.",
    "qualifying_synchronized_cross_venue_tick_evidence_required": "Needs synchronized tick data from multiple venues.",
    "qualifying_funding_basis_market_state_required": "Needs funding/basis market state.",
    "qualifying_hedge_drift_market_state_required": "Needs hedge-drift / derivative market state.",
    "qualifying_option_chain_and_greeks_data_required": "Needs options chain and Greeks data.",
    "exact_options_primitive_and_qualifying_chain_data_required": "Needs exact options semantics plus qualifying chain/Greeks data.",
    "exact_cross_venue_primitive_and_synchronized_tick_data_required": "Needs exact cross-venue semantics and synchronized tick data.",
    "exact_mm_primitive_and_real_l2_queue_latency_data_required": "Needs exact market-making semantics plus real L2 queue/latency data.",
    "exact_order_book_primitive_and_real_l2_queue_latency_data_required": "Needs exact order-book semantics plus real L2 queue/latency data.",
}


def _parse_instruments(raw: str, *, product: str = "SPOT") -> tuple[str, ...]:
    values = tuple(dict.fromkeys(value.strip().upper() for value in raw.split(",") if value.strip()))
    if len(values) < 2:
        raise ValueError("Backtest Lab requires at least two instruments for transfer validation.")
    if any(not value.endswith(".BINANCE") for value in values):
        raise ValueError("Binance instrument IDs must end in .BINANCE.")
    normalized = str(product).strip().upper()
    if normalized == "SPOT" and any("-PERP.BINANCE" in value for value in values):
        raise ValueError("SPOT research requires spot instrument IDs such as BTCUSDT.BINANCE.")
    if normalized == "USD_M" and any("-PERP.BINANCE" not in value for value in values):
        raise ValueError("USD_M research requires perpetual IDs such as BTCUSDT-PERP.BINANCE.")
    return values


def _coverage_explanation(value: str) -> str:
    if value == "scheduled_public_bar":
        return "Runnable now with the current public Binance BAR research path."
    reason = value.removeprefix("blocked:")
    return _COVERAGE_REASON.get(reason, reason.replace("_", " "))


def _result_table(rows: list[dict[str, object]]) -> None:
    if not rows:
        st.info("No local research results yet.")
        return

    display = []
    for row in rows:
        score = row.get("best_score")
        history = row.get("history_months")
        recommended = row.get("recommended_history_months")
        display.append(
            {
                "Strategy": row.get("recipe_id"),
                "Market": row.get("product") or "SPOT",
                "Timeframe": row.get("timeframe") or "mixed",
                "Result": row.get("verdict"),
                "Validation": row.get("validation_depth"),
                "Best candidate": row.get("best_strategy_id") or "—",
                "Research score": None if score is None else round(float(score), 4),
                "History": (
                    "—"
                    if history is None
                    else f"{history} mo / {recommended} mo recommended"
                ),
                "PAPER finalists": row.get("paper_queued", 0),
                "Why": row.get("explanation"),
                "Next step": row.get("next_action"),
            }
        )
    st.dataframe(display, width="stretch", hide_index=True)
    st.caption(
        "Research score is an internal ranking signal, not expected return or expected profit. "
        "The promotion decision and failed gates matter more than the score."
    )
    with st.expander("Advanced result records"):
        st.dataframe(rows, width="stretch", hide_index=True)


def _preset_recipe_ids(
    preset: str,
    runnable_rows: list[dict[str, object]],
) -> tuple[str, ...]:
    if preset == "All runnable now":
        return tuple(str(row["recipe_id"]) for row in runnable_rows)
    family_groups = {
        "Trend / breakout / volatility": {"trend", "breakout", "volatility"},
        "Momentum / mean reversion": {"momentum", "mean_reversion"},
        "Swing / position": {"swing", "position"},
    }
    families = family_groups.get(preset)
    if families is None:
        return ()
    return tuple(
        str(row["recipe_id"])
        for row in runnable_rows
        if row.get("family") in families
    )


def _load_autopilot_state() -> dict[str, object]:
    path = autopilot_state_path()
    if not path.is_file():
        return {}
    try:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


@st.cache_data(ttl=3600, show_spinner=False)
def _liquid_universe(product: str, limit: int) -> tuple[dict[str, object], ...]:
    rows = load_or_refresh_universe(
        UNIVERSE_ROOT / f"{product.lower()}.json",
        product=product,
        limit=limit,
        max_age_seconds=3600.0,
    )
    return tuple(row.to_dict() for row in rows)


def _autopilot_controls(config: AutopilotConfig) -> AutopilotConfig:
    st.subheader("Autopilot")
    st.caption(
        "Autopilot rotates through the runnable strategy catalog, selects liquid Binance markets, "
        "runs isolated validation jobs, and only hands fully qualified same-product candidates to PAPER. "
        "SPOT and USD-M PAPER are credential-free; LIVE remains locked."
    )
    a1, a2, a3 = st.columns(3)
    enabled = a1.toggle("Continuous search", value=config.enabled)
    use_spot = a2.checkbox("Spot", value="SPOT" in config.products)
    use_usdm = a3.checkbox("USD-M perpetuals", value="USD_M" in config.products)
    b1, b2, b3 = st.columns(3)
    universe_size = int(
        b1.number_input(
            "Liquid markets per product",
            min_value=2,
            max_value=30,
            value=config.universe_size,
            step=1,
        )
    )
    recipes_per_cycle = int(
        b2.number_input(
            "Strategies per product / cycle",
            min_value=1,
            max_value=12,
            value=config.recipes_per_cycle,
            step=1,
        )
    )
    seed_count = int(
        b3.number_input(
            "Seeds per strategy",
            min_value=1,
            max_value=10,
            value=config.seed_count,
            step=1,
        )
    )
    c1, c2 = st.columns(2)
    auto_prepare = c1.toggle("Auto-prepare qualified PAPER portfolio", value=config.auto_prepare_paper)
    auto_start = c2.toggle("Auto-start PAPER worker when portfolio exists", value=config.auto_start_paper)
    products = tuple(
        product
        for product, selected in (("SPOT", use_spot), ("USD_M", use_usdm))
        if selected
    )
    if not products:
        products = ("SPOT",)
        st.warning("At least one market is required; SPOT will be kept enabled.")
    updated = AutopilotConfig(
        enabled=enabled,
        products=products,
        universe_size=universe_size,
        recipes_per_cycle=recipes_per_cycle,
        seed_count=seed_count,
        auto_prepare_paper=auto_prepare,
        auto_start_paper=auto_start,
        max_running_jobs=config.max_running_jobs,
    )
    if st.button("Save autopilot settings"):
        path = save_autopilot_config(updated)
        st.success(f"Saved autopilot settings to {path}")
    return updated


def render_app() -> None:
    st.set_page_config(page_title="MasterTrd", layout="wide")
    service = TradingService()
    snapshot = service.snapshot()
    strategies = service.strategy_rows()
    jobs = list_local_jobs(JOB_ROOT)
    results = local_result_rows(JOB_ROOT)
    paper_candidates = local_paper_candidates(JOB_ROOT)
    autopilot_config = load_autopilot_config()
    autopilot_state = _load_autopilot_state()

    view = st.sidebar.radio("Interface", ["Simple", "Advanced"], index=0)
    advanced = view == "Advanced"
    st.sidebar.caption(
        "Simple mode focuses on finding opportunities and PAPER readiness. "
        "Advanced mode exposes the full research matrix and capability details."
    )

    coverage = research_recipe_coverage("SPOT")
    runnable_ids = frozenset(scheduled_public_recipe_ids("SPOT"))

    st.title("MasterTrd")
    st.caption("Research → validation → PAPER → controlled production. NautilusTrader owns execution.")
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
        c2.metric("Strategy ideas", snapshot["strategy_count"])
        c3.metric(
            "Runnable now",
            len(set(scheduled_public_recipe_ids("SPOT")) | set(scheduled_public_recipe_ids("USD_M"))),
        )
        c4.metric("Emergency stop", "ACTIVE" if snapshot["emergency_stop"] else "CLEAR")

        st.subheader("Opportunity search")
        ap1, ap2, ap3, ap4 = st.columns(4)
        ap1.metric("Autopilot", "ON" if autopilot_config.enabled else "OFF")
        ap2.metric("Markets", " + ".join(autopilot_config.products))
        ap3.metric("Universe / market", autopilot_config.universe_size)
        ap4.metric("Cycles", int(autopilot_state.get("cycles", 0)))
        if autopilot_state.get("last_cycle_at"):
            st.caption(f'Last search cycle: {autopilot_state.get("last_cycle_at")}')
        if st.button("Run opportunity search now", type="primary"):
            try:
                state = run_autopilot_cycle(config=autopilot_config)
            except (RuntimeError, ValueError) as exc:
                st.error(str(exc))
            else:
                st.success(f'Search cycle launched {len(state.get("last_launched", []))} research jobs.')
                st.rerun()

        with st.expander("Autopilot settings", expanded=False):
            _autopilot_controls(autopilot_config)

        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Research jobs", len(jobs))
        r2.metric("Completed", sum(row["status"] == "SUCCEEDED" for row in results))
        r3.metric("PAPER-ready", sum(int(row.get("paper_queued", 0)) for row in results))
        r4.metric("Blocked / failed", sum(row["status"] == "FAILED" for row in results))

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
                width="stretch",
                hide_index=True,
            )
            st.subheader("PAPER strategies")
            st.dataframe(portfolio.get("strategies", []), width="stretch", hide_index=True)
        elif "paper" in snapshot:
            st.subheader("PAPER strategy")
            st.json(snapshot["paper"])
        else:
            st.info("No active persisted PAPER session is configured.")

        if results:
            st.subheader("Latest research")
            _result_table(results[:8])
        st.caption("Research workers and the trading worker are separate local processes.")

    with tabs[1]:
        st.subheader("Opportunity coverage")
        coverage_product = st.selectbox(
            "Research market",
            ["SPOT", "USD_M"],
            format_func=lambda value: "Binance Spot" if value == "SPOT" else "Binance USD-M Perpetuals",
            key="coverage_product",
        )
        coverage = research_recipe_coverage(coverage_product)
        runnable_ids = frozenset(scheduled_public_recipe_ids(coverage_product))
        readiness_counts = Counter(str(row["readiness"]) for row in strategies)
        s1, s2, s3, s4, s5, s6 = st.columns(6)
        s1.metric("Catalog", len(strategies))
        s2.metric("Runnable here", len(runnable_ids))
        s3.metric("Needs data", readiness_counts.get("SPECIALIST_DATA_REQUIRED", 0))
        s4.metric("Needs primitive", readiness_counts.get("PRIMITIVE_REQUIRED", 0))
        s5.metric("Needs provider", readiness_counts.get("PROVIDER_REQUIRED", 0))
        s6.metric("Experimental", readiness_counts.get("EXPERIMENTAL", 0))
        st.info(
            "NautilusTrader supplies execution and market mechanics; MasterTrd still needs an exact strategy "
            "signal plus the correct BAR/TICK/L2/options/funding data before an opportunity can be tested honestly."
        )

        families = sorted({str(row["family"]) for row in strategies})
        assets = sorted({asset for row in strategies for asset in row["assets"]})
        family_filter: list[str] = []
        asset_filter: list[str] = []
        availability = "All"
        if advanced:
            f1, f2, f3 = st.columns(3)
            family_filter = f1.multiselect("Family", families)
            asset_filter = f2.multiselect("Asset class", assets)
            availability = f3.selectbox(
                "Current availability",
                ["All", "Runnable now", "Future / blocked"],
            )

        opportunity_rows = []
        for row in strategies:
            recipe_id = str(row["recipe_id"])
            disposition = coverage.get(recipe_id, "blocked:unknown_recipe")
            is_runnable = recipe_id in runnable_ids
            if family_filter and row["family"] not in family_filter:
                continue
            if asset_filter and not set(asset_filter).intersection(row["assets"]):
                continue
            if availability == "Runnable now" and not is_runnable:
                continue
            if availability == "Future / blocked" and is_runnable:
                continue
            spec = family_spec(str(row["family"]))
            opportunity_rows.append(
                {
                    "Strategy": row["name"],
                    "Recipe": recipe_id,
                    "Family": row["family"],
                    "Assets": ", ".join(row["assets"]),
                    "Horizons": ", ".join(row["horizons"]),
                    "Data": spec.min_data_level.value,
                    "Engine semantics": row["readiness"],
                    "Current research": "RUN NOW" if is_runnable else "BLOCKED / FUTURE",
                    "What is missing": _coverage_explanation(disposition),
                }
            )
        if not advanced:
            runnable_rows_display = [row for row in opportunity_rows if row["Current research"] == "RUN NOW"]
            blocked_rows_display = [row for row in opportunity_rows if row["Current research"] != "RUN NOW"]
            st.subheader("Available now")
            st.dataframe(runnable_rows_display, width="stretch", hide_index=True)
            with st.expander(f"Future opportunities / missing capabilities ({len(blocked_rows_display)})"):
                st.dataframe(blocked_rows_display, width="stretch", hide_index=True)
        else:
            st.dataframe(opportunity_rows, width="stretch", hide_index=True)
        st.caption(
            f"RUN NOW means the strategy can be tested today through the public Binance {coverage_product} BAR path. "
            "Blocked rows stay visible with the exact capability that is missing."
        )

    with tabs[2]:
        st.subheader("Backtest Lab")
        research_product = st.selectbox(
            "Market",
            ["SPOT", "USD_M"],
            format_func=lambda value: "Binance Spot" if value == "SPOT" else "Binance USD-M Perpetuals",
            key="research_product",
        )
        product_runnable_ids = frozenset(scheduled_public_recipe_ids(research_product))
        runnable_rows = [
            row for row in strategies
            if str(row["recipe_id"]) in product_runnable_ids
        ]

        if not advanced:
            st.write(
                "Use **Opportunity Search** for the normal workflow. It automatically rotates through strategies "
                "instead of making you choose every technical parameter."
            )
            simple_universe_size = st.slider(
                "Liquid markets to search",
                min_value=2,
                max_value=20,
                value=autopilot_config.universe_size,
                step=1,
            )
            try:
                market_rows = _liquid_universe(research_product, simple_universe_size)
            except RuntimeError as exc:
                st.error(str(exc))
                market_rows = ()
            if market_rows:
                st.dataframe(
                    [
                        {
                            "Market": row["instrument_id"],
                            "24h quote volume": round(float(row["quote_volume_24h"]), 2),
                        }
                        for row in market_rows
                    ],
                    width="stretch",
                    hide_index=True,
                )
            st.write(
                f"MasterTrd currently has **{len(product_runnable_ids)}** runnable BAR strategies for this market. "
                "Each autopilot cycle tests a rotating subset with full promotion gates."
            )
            if st.button("Search this market now", type="primary"):
                config = AutopilotConfig(
                    enabled=True,
                    products=(research_product,),
                    universe_size=simple_universe_size,
                    recipes_per_cycle=autopilot_config.recipes_per_cycle,
                    seed_count=autopilot_config.seed_count,
                    auto_prepare_paper=autopilot_config.auto_prepare_paper,
                    auto_start_paper=autopilot_config.auto_start_paper,
                    max_running_jobs=autopilot_config.max_running_jobs,
                )
                try:
                    state = run_autopilot_cycle(config=config)
                except (RuntimeError, ValueError) as exc:
                    st.error(str(exc))
                else:
                    st.success(f'Launched {len(state.get("last_launched", []))} research jobs.')
                    st.rerun()
            st.divider()
            st.subheader("Results")
            _result_table(results)
        else:
            by_label = {
                f'{row["name"]} · {row["recipe_id"]}': str(row["recipe_id"])
                for row in runnable_rows
            }

            preset = st.selectbox(
                "Strategy preset",
                [
                    "Custom",
                    "All runnable now",
                    "Trend / breakout / volatility",
                    "Momentum / mean reversion",
                    "Swing / position",
                ],
                help="Presets make it easy to search broadly without manually selecting every strategy.",
            )
            if preset == "Custom":
                selected_labels = st.multiselect(
                    "Strategies",
                    list(by_label),
                    default=list(by_label)[:1],
                )
                selected_recipe_ids = tuple(by_label[label] for label in selected_labels)
            else:
                selected_recipe_ids = _preset_recipe_ids(preset, runnable_rows)
                st.write(f"Selected **{len(selected_recipe_ids)}** runnable strategies.")

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

            auto_universe = st.checkbox("Use automatic liquid-market universe", value=True)
            if auto_universe:
                universe_size = int(
                    st.number_input("Universe size", min_value=2, max_value=30, value=8, step=1)
                )
                try:
                    universe_rows = _liquid_universe(research_product, universe_size)
                except RuntimeError as exc:
                    st.error(str(exc))
                    universe_rows = ()
                instruments_raw = ",".join(str(row["instrument_id"]) for row in universe_rows)
                if universe_rows:
                    st.dataframe(
                        [
                            {
                                "Instrument": row["instrument_id"],
                                "24h quote volume": round(float(row["quote_volume_24h"]), 2),
                            }
                            for row in universe_rows
                        ],
                        width="stretch",
                        hide_index=True,
                    )
            else:
                default_ids = (
                    "BTCUSDT.BINANCE,ETHUSDT.BINANCE"
                    if research_product == "SPOT"
                    else "BTCUSDT-PERP.BINANCE,ETHUSDT-PERP.BINANCE"
                )
                instruments_raw = st.text_input(
                    "Binance instruments",
                    value=default_ids,
                    help="Comma-separated admitted Binance instrument IDs. At least two are required.",
                )

            recommended_history = max(
                (recommended_archive_months(recipe_id) for recipe_id in selected_recipe_ids),
                default=2,
            )
            profile = st.selectbox(
                "Validation profile",
                ["Quick exploration", "Stronger validation", "Custom"],
                help=(
                    "Quick exploration is intentionally shallow. Stronger validation uses more seeds and the "
                    "recommended history window for the selected strategy families."
                ),
            )
            seed_start = int(st.number_input("Seed start", min_value=0, value=40, step=1))
            if profile == "Quick exploration":
                seed_count = 1
                archive_months = 2
            elif profile == "Stronger validation":
                seed_count = 3
                archive_months = recommended_history
            else:
                v1, v2 = st.columns(2)
                seed_count = int(v1.number_input("Seeds per cell", min_value=1, value=3, step=1))
                archive_months = int(
                    v2.number_input(
                        "History months",
                        min_value=2,
                        value=recommended_history,
                        step=1,
                    )
                )

            if archive_months < recommended_history:
                st.warning(
                    f"This is a quick/incomplete window for the selected strategies. "
                    f"At least {recommended_history} months is recommended. A result such as "
                    "'required evidence missing' should not be interpreted as proof that the strategy is useless."
                )
            else:
                st.success(
                    f"History window meets the current recommendation for this selection "
                    f"({recommended_history} months)."
                )

            compatible_cells = sum(
                1
                for recipe_id in selected_recipe_ids
                for timeframe in selected_timeframes
                if timeframe in strategy_recipe_timeframes(recipe_id)
            )
            st.write(
                f"Matrix preview: **{compatible_cells} worker jobs**, "
                f"**{compatible_cells * seed_count} research runs**, "
                f"**{len(selected_recipe_ids)} strategies**."
            )
            st.caption(
                "Every cell uses the MasterTrd validation path. Failed and losing trials remain recorded; "
                "nothing is hidden or promoted just because it completed."
            )

            if st.button("Run backtest matrix", type="primary"):
                try:
                    receipts = launch_research_matrix(
                        selected_recipe_ids,
                        JOB_ROOT,
                        instruments=_parse_instruments(instruments_raw, product=research_product),
                        timeframes=selected_timeframes,
                        seed_start=seed_start,
                        seed_stop=seed_start + seed_count,
                        archive_months=archive_months,
                        product=research_product,
                    )
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.success(f"Started {len(receipts)} isolated research jobs.")

            st.subheader("Jobs")
            if jobs:
                job_display = [
                    {
                        "Strategy": job.recipe_id,
                        "Market": job.product,
                        "Timeframe": job.timeframe or "mixed",
                        "Status": job.status,
                        "History months": job.archive_months,
                        "Seeds": (
                            "default"
                            if job.seed_start is None or job.seed_stop is None
                            else f"{job.seed_start}–{job.seed_stop - 1}"
                        ),
                        "Error": job.error,
                    }
                    for job in jobs
                ]
                st.dataframe(job_display, width="stretch", hide_index=True)
            else:
                st.info("No local research jobs yet.")

            st.subheader("Results")
            verdict_counts = Counter(str(row.get("verdict")) for row in results)
            q1, q2, q3, q4 = st.columns(4)
            q1.metric("Ready for PAPER", verdict_counts.get("READY FOR PAPER", 0))
            q2.metric("Promising / not robust", verdict_counts.get("PROMISING, NOT ROBUST", 0))
            q3.metric("Not ready", verdict_counts.get("NOT READY", 0))
            q4.metric("Blocked / failed", verdict_counts.get("BLOCKED / FAILED", 0))
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
            st.dataframe(portfolio.get("strategies", []), width="stretch", hide_index=True)
            if snapshot.get("paper_rotation_requested"):
                st.info(
                    "PAPER evidence-window close is pending. The trading worker will rotate "
                    "the portfolio when the shared account is flat."
                )
            elif st.button("Close PAPER evidence window"):
                try:
                    service.request_paper_evidence_rotation()
                except RuntimeError as exc:
                    st.error(str(exc))
                else:
                    st.success("Evidence-window close requested; rotation waits for a flat account.")
                    st.rerun()

        st.subheader("Validated PAPER finalists")
        paper_products = sorted(
            {
                str(row.get("product") or "SPOT")
                for row in paper_candidates
            }
        )
        selected_paper_product = (
            st.selectbox(
                "PAPER product",
                paper_products,
                help="A shared PAPER portfolio cannot mix SPOT and USD-M instruments.",
            )
            if paper_products
            else None
        )
        visible_paper_candidates = [
            row
            for row in paper_candidates
            if selected_paper_product is None
            or str(row.get("product") or "SPOT") == selected_paper_product
        ]
        finalist_labels = {
            (
                f'{row.get("product") or "SPOT"} · '
                f'{row.get("recipe_id") or "generated"} · '
                f'{row.get("strategy_id")} · {row.get("timeframe")} · '
                f'{str(row.get("genome_hash"))[:10]}'
            ): row
            for row in visible_paper_candidates
        }
        selected_finalist_labels = st.multiselect(
            "Shared PAPER portfolio",
            list(finalist_labels),
            help=(
                "Only candidates that completed the research pipeline into PAPER are listed. "
                "All selected finalists must use the same Binance product."
            ),
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
        if len(visible_paper_candidates) < 2:
            st.info(
                "Run research until at least two current-code candidates for the same product "
                "qualify for PAPER before creating a shared portfolio."
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
        st.dataframe(display, width="stretch", hide_index=True)
        st.info(
            "BAR research now supports public Binance SPOT and USD-M perpetual history. "
            "Funding/basis, tick/L2 market making, options, and cross-venue strategies still require their "
            "specialist data paths before they can be promoted."
        )
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
        st.subheader("Autopilot state")
        st.json(autopilot_state or {"status": "not run yet"})
        failed = [row for row in results if row["status"] == "FAILED"]
        st.write(f"Failed research jobs: **{len(failed)}**")
        if failed:
            st.dataframe(failed, width="stretch", hide_index=True)


if __name__ == "__main__":
    render_app()
