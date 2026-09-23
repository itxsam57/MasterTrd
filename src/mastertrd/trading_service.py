from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from enum import StrEnum
import hashlib
import json
import os
import signal
import time
from pathlib import Path
from threading import Event
from typing import Any

from .contracts import RuntimeMode
from .credentials import load_binance_credentials
from .paper_session import JsonPaperSessionStore, PaperSessionJournal
from .genome import StrategyGenome
from .runtime import RuntimeConfig
from .runtime_factory import build_execution_runtime
from .source_identity import git_head as _source_git_head, lock_hash as _source_lock_hash
from .strategy_universe import STRATEGY_RECIPES
from .venue import infer_binance_product


class TradingReadiness(StrEnum):
    PAPER_READY = "PAPER_READY"
    EXCHANGE_READY = "EXCHANGE_READY"
    LIVE_READY = "LIVE_READY"


RuntimeFactory = Callable[[RuntimeConfig, Mapping[str, str]], Any]


_STRATEGY_TELEMETRY_FIELDS = (
    "bars_seen",
    "bars_required",
    "warmup_remaining",
    "bootstrap_bars",
    "live_bars",
    "last_signal",
    "last_signal_reason",
    "last_exit_reason",
    "orders_attempted",
    "orders_allowed",
    "orders_rejected",
    "last_risk_rejection",
    "expected_closed_bars",
    "ws_closed_bars",
    "rest_recovered_bars",
    "missing_closed_bars",
    "recovery_failures",
    "last_closed_bar_ms",
    "last_expected_close_ms",
    "last_recovery_error",
    "data_healthy",
    "portfolio_equity",
    "portfolio_daily_pnl",
    "portfolio_drawdown",
    "portfolio_exposure",
    "portfolio_leverage",
)


def paper_status_payload(
    journal: PaperSessionJournal,
    *,
    observed_ns: int,
) -> dict[str, object]:
    observed_ns = int(observed_ns)
    if observed_ns < journal.started_ns:
        raise ValueError("observed_ns cannot be before session start")
    if observed_ns < journal.latest_timestamp_ns:
        raise ValueError("observed_ns cannot be before the latest session event")

    trade_returns = [float(event.value) for event in journal._events if event.kind == "closed_trade"]
    reconciliation = [bool(event.value) for event in journal._events if event.kind == "reconciliation"]
    market_events = sum(1 for event in journal._events if event.kind == "market_event")

    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in trade_returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        if peak > 0.0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)

    execution_state = journal.execution_state_checkpoint
    payload: dict[str, object] = {
        "schema_version": 1,
        "strategy_id": journal.strategy_id,
        "genome_hash": journal.genome_hash,
        "code_hash": journal.code_hash,
        "session_id": journal.session_id,
        "duration_seconds": (observed_ns - journal.started_ns) // 1_000_000_000,
        "market_events": market_events,
        "closed_trades": len(trade_returns),
        "total_return": equity - 1.0,
        "max_drawdown": max_drawdown,
        "reconciliation_checks": len(reconciliation),
        "reconciliation_errors": sum(1 for ok in reconciliation if not ok),
        "position_count": 0 if execution_state is None else len(execution_state.positions),
        "open_order_count": 0 if execution_state is None else len(execution_state.open_order_ids),
        "latest_timestamp_ns": journal.latest_timestamp_ns,
        "finalized": journal.finalized_report is not None,
    }
    # PAPER Status can be newer than the currently deployed read-only journal
    # reader during a rolling upgrade. Pre-telemetry journals legitimately lack
    # this attribute; all canonical identity/evidence above must still be
    # reportable without weakening validation or fabricating telemetry.
    telemetry = getattr(journal, "strategy_telemetry", None)
    if telemetry is not None:
        for key in _STRATEGY_TELEMETRY_FIELDS:
            if key in telemetry:
                payload[key] = telemetry[key]
    return payload


def portfolio_status_payload(portfolio, *, observed_ns: int) -> dict[str, object]:
    statuses = [
        paper_status_payload(portfolio.journal(strategy_id), observed_ns=observed_ns)
        for strategy_id in portfolio.strategy_ids
    ]
    checkpoint = portfolio.execution_state_checkpoint
    return {
        "portfolio_id": portfolio.portfolio_id,
        "strategy_count": len(statuses),
        "strategies": statuses,
        "positions": (
            {}
            if checkpoint is None
            else {key: str(value) for key, value in sorted(checkpoint.positions.items())}
        ),
        "open_order_ids": (
            []
            if checkpoint is None
            else sorted(checkpoint.open_order_ids)
        ),
        "balances": (
            {}
            if checkpoint is None
            else {key: str(value) for key, value in sorted(checkpoint.balances.items())}
        ),
        "reconciliation_errors": max(
            (int(status["reconciliation_errors"]) for status in statuses),
            default=0,
        ),
        "data_healthy": all(bool(status.get("data_healthy", True)) for status in statuses),
        "risk": {
            "orders_attempted": sum(int(status.get("orders_attempted", 0)) for status in statuses),
            "orders_allowed": sum(int(status.get("orders_allowed", 0)) for status in statuses),
            "orders_rejected": sum(int(status.get("orders_rejected", 0)) for status in statuses),
            "portfolio_equity": next(
                (status.get("portfolio_equity") for status in statuses if status.get("portfolio_equity") is not None),
                None,
            ),
            "daily_pnl": next((float(status.get("portfolio_daily_pnl", 0.0)) for status in statuses), 0.0),
            "drawdown": next((float(status.get("portfolio_drawdown", 0.0)) for status in statuses), 0.0),
            "exposure": next((float(status.get("portfolio_exposure", 0.0)) for status in statuses), 0.0),
            "leverage": next((float(status.get("portfolio_leverage", 0.0)) for status in statuses), 0.0),
        },
    }


class TradingService:
    paper_status_payload = staticmethod(paper_status_payload)
    def __init__(
        self,
        environ: Mapping[str, str] | None = None,
        *,
        runtime_factory: RuntimeFactory = build_execution_runtime,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self._environ = environ
        self._runtime_factory = runtime_factory
        self._clock_ns = clock_ns

    _LOCAL_SETTING_KEYS = frozenset(
        {
            "MASTERTRD_MODE",
            "LIVE_TRADING_ENABLED",
            "MASTERTRD_BINANCE_PRODUCT",
            "MASTERTRD_PORTFOLIO_MANIFEST",
            "MASTERTRD_SESSION_STATE",
            "MASTERTRD_CODE_HASH",
            "MASTERTRD_PAPER_ARCHIVE",
            "MASTERTRD_PAPER_HISTORY_DIR",
            "MASTERTRD_PAPER_ROTATION_REQUEST",
        }
    )

    def _local_config_path(self) -> Path:
        source = os.environ if self._environ is None else self._environ
        configured = source.get("MASTERTRD_LOCAL_CONFIG", "").strip()
        return (
            Path(configured).expanduser()
            if configured
            else Path.home() / ".mastertrd" / "runtime.json"
        )

    def _read_local_settings(self) -> dict[str, str]:
        path = self._local_config_path()
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError("local MasterTrd runtime settings are invalid") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("local MasterTrd runtime settings are invalid")
        settings: dict[str, str] = {}
        for key, value in payload.items():
            if key not in self._LOCAL_SETTING_KEYS or not isinstance(value, str):
                raise RuntimeError(
                    "local MasterTrd runtime settings contain an unsupported field"
                )
            settings[key] = value
        return settings

    def _write_local_settings(self, payload: Mapping[str, str]) -> Path:
        if set(payload) - self._LOCAL_SETTING_KEYS:
            raise ValueError("unsupported local MasterTrd runtime setting")
        path = self._local_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            json.dumps(dict(payload), sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path

    def _environment(self) -> Mapping[str, str]:
        if self._environ is not None:
            return self._environ
        merged = dict(os.environ)
        for key, value in self._read_local_settings().items():
            merged.setdefault(key, value)
        return merged

    def save_local_settings(self, *, mode: str, product: str) -> Path:
        normalized_mode = str(mode).strip().upper()
        normalized_product = str(product).strip().upper()
        if normalized_mode == "LIVE":
            raise RuntimeError("LIVE activation is not writable from the local app")
        if normalized_mode not in {"PAPER", "DEMO", "TESTNET"}:
            raise ValueError("local trading mode must be PAPER, DEMO, or TESTNET")
        from .venue import BinanceProduct

        try:
            BinanceProduct(normalized_product)
        except ValueError as exc:
            raise ValueError("unsupported Binance product") from exc

        payload = {
            "MASTERTRD_MODE": normalized_mode,
            "LIVE_TRADING_ENABLED": "false",
            "MASTERTRD_BINANCE_PRODUCT": normalized_product,
        }
        if normalized_mode == "PAPER":
            existing = self._read_local_settings()
            for key in (
                "MASTERTRD_PORTFOLIO_MANIFEST",
                "MASTERTRD_SESSION_STATE",
                "MASTERTRD_CODE_HASH",
                "MASTERTRD_PAPER_ARCHIVE",
                "MASTERTRD_PAPER_HISTORY_DIR",
                "MASTERTRD_PAPER_ROTATION_REQUEST",
            ):
                if existing.get(key):
                    payload[key] = existing[key]
        return self._write_local_settings(payload)

    def _current_code_hash(self) -> str:
        source = os.environ if self._environ is None else self._environ
        explicit = source.get("MASTERTRD_CODE_HASH", "").strip()
        current = _source_git_head()
        if explicit and explicit != current:
            raise RuntimeError(
                "MASTERTRD_CODE_HASH does not match the clean MasterTrd checkout"
            )
        return current

    @staticmethod
    def _current_lock_hash() -> str:
        return _source_lock_hash()

    def paper_candidate_matches_current_source(
        self,
        manifest: Mapping[str, object],
    ) -> bool:
        """Return whether a research handoff matches the exact current source and lock."""
        try:
            code_hash = self._current_code_hash()
            lock_hash = self._current_lock_hash()
        except RuntimeError:
            return False
        return (
            manifest.get("state") == "PAPER"
            and manifest.get("code_hash") == code_hash
            and manifest.get("lock_hash") == lock_hash
        )

    def configure_paper_portfolio(
        self,
        manifests: list[Mapping[str, object]],
        *,
        root: str | Path = "artifacts/trading",
    ) -> dict[str, str]:
        if len(manifests) < 2:
            raise ValueError("PAPER portfolio requires at least two validated finalists")
        code_hash = self._current_code_hash()
        lock_hash = self._current_lock_hash()
        candidates: list[StrategyGenome] = []
        provenance: list[dict[str, object]] = []
        for manifest in manifests:
            if manifest.get("state") != "PAPER":
                raise ValueError("portfolio accepts only PAPER-qualified research finalists")
            if manifest.get("code_hash") != code_hash:
                raise ValueError("PAPER finalist code identity does not match current checkout")
            if manifest.get("lock_hash") != lock_hash:
                raise ValueError("PAPER finalist lock identity does not match current uv.lock")
            raw_candidate = manifest.get("candidate")
            if not isinstance(raw_candidate, Mapping):
                raise ValueError("PAPER finalist candidate payload is missing")
            try:
                candidate = StrategyGenome(**dict(raw_candidate))
            except (TypeError, ValueError) as exc:
                raise ValueError("PAPER finalist candidate payload is invalid") from exc
            if manifest.get("strategy_id") != candidate.strategy_id:
                raise ValueError("PAPER finalist strategy identity mismatch")
            if manifest.get("genome_hash") != candidate.genome_hash:
                raise ValueError("PAPER finalist genome identity mismatch")
            if len(candidate.instruments) != 1:
                raise ValueError(
                    "PAPER portfolio currently accepts single-instrument finalists only"
                )
            candidates.append(candidate)
            provenance.append(
                {
                    "strategy_id": candidate.strategy_id,
                    "genome_hash": candidate.genome_hash,
                    "dataset_hash": manifest.get("dataset_hash"),
                    "recipe_id": manifest.get("recipe_id"),
                }
            )
        if len({candidate.strategy_id for candidate in candidates}) != len(candidates):
            raise ValueError("PAPER portfolio strategy identities must be unique")
        try:
            product = infer_binance_product(
                candidate.instruments[0] for candidate in candidates
            )
        except ValueError as exc:
            raise ValueError(
                "PAPER portfolio finalists must share one admitted Binance product"
            ) from exc
        identity = hashlib.sha256(
            (
                code_hash
                + ":"
                + ":".join(sorted(candidate.genome_hash for candidate in candidates))
            ).encode()
        ).hexdigest()[:16]
        portfolio_id = f"paper-{identity}"
        root_path = Path(root).expanduser().resolve()
        root_path.mkdir(parents=True, exist_ok=True)
        manifest_path = root_path / f"{portfolio_id}.json"
        state_path = root_path / f"{portfolio_id}-state.json"
        payload = {
            "portfolio_id": portfolio_id,
            "code_hash": code_hash,
            "lock_hash": lock_hash,
            "product": product.value,
            "candidates": [candidate.canonical_payload() for candidate in candidates],
            "provenance": provenance,
        }
        temporary = manifest_path.with_name(f".{manifest_path.name}.tmp")
        temporary.write_text(
            json.dumps(payload, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, manifest_path)
        settings = {
            "MASTERTRD_MODE": "PAPER",
            "LIVE_TRADING_ENABLED": "false",
            "MASTERTRD_BINANCE_PRODUCT": product.value,
            "MASTERTRD_PORTFOLIO_MANIFEST": str(manifest_path),
            "MASTERTRD_SESSION_STATE": str(state_path),
            "MASTERTRD_CODE_HASH": code_hash,
            "MASTERTRD_PAPER_ARCHIVE": str(root_path / f"{portfolio_id}-reports.json"),
            "MASTERTRD_PAPER_HISTORY_DIR": str(root_path / f"{portfolio_id}-history"),
            "MASTERTRD_PAPER_ROTATION_REQUEST": str(root_path / f"{portfolio_id}-rotate.request"),
        }
        self._write_local_settings(settings)
        return {
            "portfolio_id": portfolio_id,
            "manifest": str(manifest_path),
            "session_state": str(state_path),
            "code_hash": code_hash,
            "lock_hash": lock_hash,
            "product": product.value,
        }

    def _runtime_config(self) -> RuntimeConfig:
        return RuntimeConfig.from_env(dict(self._environment()))

    def _emergency_stop_path(self) -> Path:
        configured = self._environment().get("MASTERTRD_EMERGENCY_STOP", "").strip()
        return Path(configured or "artifacts/trading/EMERGENCY_STOP")

    def emergency_stop_active(self) -> bool:
        return self._emergency_stop_path().is_file()

    def activate_emergency_stop(self) -> Path:
        path = self._emergency_stop_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            f"mode={self._runtime_config().mode.value}\nactivated_ns={self._clock_ns()}\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path

    def clear_emergency_stop(self) -> None:
        runtime = self._runtime_config()
        if runtime.mode is RuntimeMode.LIVE:
            raise RuntimeError("cannot clear emergency stop while LIVE")
        self._emergency_stop_path().unlink(missing_ok=True)

    def paper_portfolio_configured(self) -> bool:
        return bool(
            self._environment().get("MASTERTRD_PORTFOLIO_MANIFEST", "").strip()
        )

    def paper_session_started(self) -> bool:
        raw = self._environment().get("MASTERTRD_SESSION_STATE", "").strip()
        return bool(raw and Path(raw).is_file())

    def paper_evidence_rotation_requested(self) -> bool:
        raw = self._environment().get("MASTERTRD_PAPER_ROTATION_REQUEST", "").strip()
        return bool(raw and Path(raw).is_file())

    def request_paper_evidence_rotation(self) -> Path:
        runtime = self._runtime_config()
        if runtime.mode is not RuntimeMode.PAPER:
            raise RuntimeError("PAPER evidence rotation requires PAPER mode")
        environ = self._environment()
        raw = environ.get("MASTERTRD_PAPER_ROTATION_REQUEST", "").strip()
        if not raw:
            raise RuntimeError("PAPER evidence rotation is not configured")
        state = environ.get("MASTERTRD_SESSION_STATE", "").strip()
        if not state or not Path(state).is_file():
            raise RuntimeError("PAPER evidence session has not started")
        path = Path(raw)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            f"requested_ns={self._clock_ns()}\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path

    def preflight(self) -> TradingReadiness:
        if self.emergency_stop_active():
            raise RuntimeError("emergency stop is active")
        environ = dict(self._environment())
        runtime = RuntimeConfig.from_env(environ)
        if runtime.mode in (RuntimeMode.RESEARCH, RuntimeMode.BACKTEST):
            raise RuntimeError(f"{runtime.mode} is not a persistent execution mode")
        if runtime.mode is RuntimeMode.PAPER:
            return TradingReadiness.PAPER_READY

        load_binance_credentials(runtime.mode, environ)
        if runtime.mode is RuntimeMode.LIVE:
            return TradingReadiness.LIVE_READY
        return TradingReadiness.EXCHANGE_READY

    def run(
        self,
        *,
        stop_requested: Callable[[], bool],
        heartbeat: Callable[[TradingReadiness], None] | None = None,
    ) -> TradingReadiness:
        readiness = self.preflight()
        if heartbeat is not None:
            heartbeat(readiness)
        runtime = self._runtime_factory(self._runtime_config(), dict(self._environment()))
        try:
            runtime.run(stop_requested=stop_requested)
        finally:
            close = getattr(runtime, "close", None)
            if callable(close):
                close()
        return readiness

    def run_forever(
        self,
        *,
        register_signal: Callable[[int, Any], Any] = signal.signal,
        heartbeat: Callable[[TradingReadiness], None] | None = None,
    ) -> TradingReadiness:
        stopped = Event()

        def request_stop(_signum: int, _frame: Any) -> None:
            stopped.set()

        register_signal(signal.SIGINT, request_stop)
        register_signal(signal.SIGTERM, request_stop)
        return self.run(
            stop_requested=lambda: stopped.is_set() or self.emergency_stop_active(),
            heartbeat=heartbeat,
        )

    def snapshot(self) -> dict[str, Any]:
        runtime = self._runtime_config()
        readiness = Counter(recipe.readiness.value for recipe in STRATEGY_RECIPES)
        payload: dict[str, Any] = {
            "mode": runtime.mode.value,
            "live_enabled": runtime.live_trading_enabled,
            "strategy_count": len(STRATEGY_RECIPES),
            "readiness": dict(sorted(readiness.items())),
            "emergency_stop": self.emergency_stop_active(),
            "paper_rotation_requested": self.paper_evidence_rotation_requested(),
        }
        session_path = self._environment().get("MASTERTRD_SESSION_STATE", "").strip()
        portfolio_manifest = self._environment().get("MASTERTRD_PORTFOLIO_MANIFEST", "").strip()
        if runtime.mode is RuntimeMode.PAPER and session_path and Path(session_path).is_file():
            if portfolio_manifest:
                from .paper_portfolio import JsonPaperPortfolioStore

                portfolio = JsonPaperPortfolioStore(session_path).load()
                payload["portfolio"] = portfolio_status_payload(
                    portfolio,
                    observed_ns=self._clock_ns(),
                )
            else:
                journal = JsonPaperSessionStore(session_path).load()
                payload["paper"] = self.paper_status_payload(
                    journal,
                    observed_ns=self._clock_ns(),
                )
        return payload

    def start_paper_cycle(self, *, candidate: Any, session_nonce: str) -> Any:
        from .paper_cycle import start_generated_paper_cycle
        return start_generated_paper_cycle(candidate=candidate, session_nonce=session_nonce)

    def finalize_paper_session(self, *, journal: PaperSessionJournal, session_store: JsonPaperSessionStore, archive: Any, ended_ns: int | None = None) -> Any:
        from .paper_cycle import finalize_forward_paper_session
        return finalize_forward_paper_session(journal=journal, session_store=session_store, archive=archive, ended_ns=self._clock_ns() if ended_ns is None else ended_ns)

    def provider_rows(self) -> list[dict[str, object]]:
        from .market_capabilities import PROVIDER_CAPABILITIES, MasterTrdAdmission

        runtime = self._runtime_config()
        environ = self._environment()
        namespace = runtime.mode.value
        rows: list[dict[str, object]] = []
        for provider in PROVIDER_CAPABILITIES:
            admitted = provider.mastertrd_admission is MasterTrdAdmission.ADMITTED
            is_binance = provider.provider_id == "binance"
            credentials_required = bool(
                admitted and is_binance and runtime.mode is not RuntimeMode.PAPER
            )
            credential_names = (
                f"BINANCE_{namespace}_API_KEY",
                f"BINANCE_{namespace}_API_SECRET",
                f"BINANCE_{namespace}_ACCOUNT_ID",
            ) if credentials_required else ()
            rows.append(
                {
                    "provider_id": provider.provider_id,
                    "provider": provider.name,
                    "kind": provider.kind.value,
                    "admission": provider.mastertrd_admission.value,
                    "mode": runtime.mode.value if admitted else "NOT_ADMITTED",
                    "product": (
                        environ.get("MASTERTRD_BINANCE_PRODUCT", "SPOT").strip().upper() or "SPOT"
                        if is_binance
                        else ""
                    ),
                    "credentials_required": credentials_required,
                    "credentials_configured": (
                        not credentials_required
                        or all(bool(environ.get(name, "").strip()) for name in credential_names)
                    ),
                    "credential_names": credential_names,
                    "blocker": provider.blocker,
                }
            )
        return rows

    def evaluate_forward_promotion(
        self,
        *,
        candidate: Any,
        archive: Any,
        paper_policy: Any,
        champion_policy: Any,
        incumbent_paper: Any = None,
    ) -> Any:
        from .forward_scheduler import ForwardPromotionScheduler

        return ForwardPromotionScheduler(
            paper_policy=paper_policy,
            champion_policy=champion_policy,
        ).evaluate(
            candidate=candidate,
            archive=archive,
            incumbent_paper=incumbent_paper,
        )

    def strategy_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "recipe_id": recipe.recipe_id,
                "name": recipe.name,
                "family": recipe.family,
                "readiness": recipe.readiness.value,
                "assets": [asset.value for asset in recipe.asset_classes],
                "horizons": [horizon.value for horizon in recipe.horizons],
                "blocker": recipe.blocker,
            }
            for recipe in STRATEGY_RECIPES
        ]
