from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable, Mapping

from .local_jobs import (
    launch_research_job,
    list_local_jobs,
    local_paper_candidates,
    local_result_rows,
    recommended_archive_months,
)
from .market_universe import MarketCandidate, load_or_refresh_universe
from .research_job import scheduled_public_recipe_ids
from .strategy_universe import strategy_recipe_timeframes
from .trading_service import TradingService


@dataclass(frozen=True, slots=True)
class AutopilotConfig:
    enabled: bool = True
    products: tuple[str, ...] = ("SPOT", "USD_M")
    universe_size: int = 8
    recipes_per_cycle: int = 4
    seed_count: int = 3
    auto_prepare_paper: bool = True
    auto_start_paper: bool = True
    max_running_jobs: int = 8

    def __post_init__(self) -> None:
        if not self.products:
            raise ValueError("autopilot requires at least one product")
        if any(product not in {"SPOT", "USD_M"} for product in self.products):
            raise ValueError("autopilot products currently support SPOT and USD_M")
        if self.universe_size < 2:
            raise ValueError("autopilot universe_size must be at least two")
        if self.recipes_per_cycle < 1:
            raise ValueError("autopilot recipes_per_cycle must be positive")
        if self.seed_count < 1:
            raise ValueError("autopilot seed_count must be positive")
        if self.max_running_jobs < 1:
            raise ValueError("autopilot max_running_jobs must be positive")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["products"] = list(self.products)
        return payload


def _runtime_config_path() -> Path:
    configured = os.environ.get("MASTERTRD_LOCAL_CONFIG", "").strip()
    return (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".mastertrd" / "runtime.json"
    )


def autopilot_config_path() -> Path:
    return _runtime_config_path().with_name("autopilot.json")


def autopilot_state_path() -> Path:
    return _runtime_config_path().with_name("autopilot-state.json")


def load_autopilot_config(path: str | Path | None = None) -> AutopilotConfig:
    source = autopilot_config_path() if path is None else Path(path)
    if not source.is_file():
        return AutopilotConfig()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("MasterTrd autopilot settings are invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("MasterTrd autopilot settings are invalid")
    products = payload.get("products", ("SPOT", "USD_M"))
    if isinstance(products, list):
        payload["products"] = tuple(str(value).strip().upper() for value in products)
    return AutopilotConfig(**payload)


def save_autopilot_config(
    config: AutopilotConfig,
    path: str | Path | None = None,
) -> Path:
    destination = autopilot_config_path() if path is None else Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(
        json.dumps(config.to_dict(), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination


def _load_state(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"cursor": {}, "cycles": 0}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("MasterTrd autopilot state is invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("MasterTrd autopilot state is invalid")
    return payload


def _save_state(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(dict(payload), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _select_recipe_batch(
    product: str,
    *,
    cursor: int,
    count: int,
) -> tuple[tuple[str, ...], int]:
    recipes = scheduled_public_recipe_ids(product)
    if not recipes:
        raise RuntimeError(f"no runnable public recipes for {product}")
    count = min(count, len(recipes))
    selected = tuple(recipes[(cursor + offset) % len(recipes)] for offset in range(count))
    return selected, (cursor + count) % len(recipes)


def _market_ids(markets: tuple[MarketCandidate, ...]) -> tuple[str, ...]:
    return tuple(market.instrument_id for market in markets)


def _deep_validation_candidate(
    *,
    job_root: Path,
    existing_jobs,
) -> dict[str, object] | None:
    """Return one promising shallow result that has not yet received its full history window."""
    deep_keys = {
        (job.recipe_id, job.product, job.timeframe)
        for job in existing_jobs
        if job.archive_months is not None
        and job.archive_months >= recommended_archive_months(job.recipe_id)
    }
    candidates = []
    for row in local_result_rows(job_root):
        score = row.get("best_score")
        if row.get("status") != "SUCCEEDED" or not isinstance(score, (int, float)):
            continue
        if float(score) <= 0.0:
            continue
        recipe_id = str(row["recipe_id"])
        product = str(row.get("product") or "SPOT")
        timeframe = row.get("timeframe")
        recommended = recommended_archive_months(recipe_id)
        history = row.get("history_months")
        if not isinstance(history, int) or history >= recommended:
            continue
        key = (recipe_id, product, timeframe)
        if key in deep_keys:
            continue
        candidates.append((float(score), row, recommended))
    if not candidates:
        return None
    _score, row, recommended = max(candidates, key=lambda item: item[0])
    return {**row, "deep_history_months": recommended}


def _worker_pid_path() -> Path:
    return _runtime_config_path().with_name("paper-worker.pid")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _ensure_paper_worker(
    service: TradingService,
    *,
    log_path: Path,
) -> dict[str, object]:
    snapshot = service.snapshot()
    if snapshot.get("mode") != "PAPER":
        return {"started": False, "reason": "runtime_not_paper"}
    if "portfolio" not in snapshot and not service.paper_portfolio_configured():
        return {"started": False, "reason": "paper_portfolio_not_configured"}

    pid_path = _worker_pid_path()
    if pid_path.is_file():
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = 0
        if _pid_alive(pid):
            return {"started": False, "reason": "already_running", "pid": pid}
        pid_path.unlink(missing_ok=True)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("ab")
    process = subprocess.Popen(
        [sys.executable, "-m", "mastertrd.cli", "trading"],
        cwd=Path(__file__).resolve().parents[2],
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    pid_path.write_text(str(process.pid) + "\n", encoding="utf-8")
    return {"started": True, "pid": process.pid}


def _auto_prepare_paper(
    service: TradingService,
    *,
    job_root: Path,
) -> dict[str, object]:
    candidates = local_paper_candidates(job_root)
    if len(candidates) < 2:
        return {"configured": False, "reason": "fewer_than_two_qualified_spot_candidates"}

    if service.paper_portfolio_configured():
        return {
            "configured": False,
            "reason": "portfolio_already_configured",
            "candidate_count": len(candidates),
        }

    configured = service.configure_paper_portfolio(
        [candidate["manifest"] for candidate in candidates[: min(4, len(candidates))]]
    )
    return {
        "configured": True,
        "candidate_count": len(candidates),
        **configured,
    }


def run_autopilot_cycle(
    *,
    config: AutopilotConfig | None = None,
    job_root: Path = Path("artifacts/local-jobs"),
    universe_root: Path = Path("artifacts/market-universe"),
    state_path: Path | None = None,
    service: TradingService | None = None,
    universe_loader: Callable[..., tuple[MarketCandidate, ...]] = load_or_refresh_universe,
) -> dict[str, object]:
    active_config = config or load_autopilot_config()
    state_file = autopilot_state_path() if state_path is None else Path(state_path)
    state = _load_state(state_file)
    now = datetime.now(timezone.utc).isoformat()

    if not active_config.enabled:
        payload = {
            **state,
            "last_cycle_at": now,
            "last_status": "DISABLED",
            "last_launched": [],
        }
        _save_state(state_file, payload)
        return payload

    jobs = list_local_jobs(job_root)
    running = [job for job in jobs if job.status in {"STARTING", "RUNNING"}]
    slots = max(active_config.max_running_jobs - len(running), 0)
    cursor = dict(state.get("cursor", {})) if isinstance(state.get("cursor"), dict) else {}
    launched: list[dict[str, object]] = []
    universes: dict[str, list[dict[str, object]]] = {}

    deep = _deep_validation_candidate(job_root=job_root, existing_jobs=jobs)
    if deep is not None and slots > 0:
        deep_product = str(deep.get("product") or "SPOT")
        if deep_product in active_config.products:
            markets = universe_loader(
                universe_root / f"{deep_product.lower()}.json",
                product=deep_product,
                limit=active_config.universe_size,
                max_age_seconds=3600.0,
            )
            universes[deep_product] = [market.to_dict() for market in markets]
            receipt = launch_research_job(
                str(deep["recipe_id"]),
                job_root,
                instruments=_market_ids(markets),
                timeframe=str(deep.get("timeframe") or strategy_recipe_timeframes(str(deep["recipe_id"]))[0]),
                seed_start=40,
                seed_stop=40 + active_config.seed_count,
                archive_months=int(deep["deep_history_months"]),
                product=deep_product,
            )
            launched.append(receipt.to_dict())
            slots -= 1

    for product in active_config.products:
        if slots <= 0:
            break
        markets = universe_loader(
            universe_root / f"{product.lower()}.json",
            product=product,
            limit=active_config.universe_size,
            max_age_seconds=3600.0,
        )
        universes[product] = [market.to_dict() for market in markets]
        selected, next_cursor = _select_recipe_batch(
            product,
            cursor=int(cursor.get(product, 0)),
            count=min(active_config.recipes_per_cycle, slots),
        )
        cursor[product] = next_cursor
        instruments = _market_ids(markets)

        for recipe_id in selected:
            if slots <= 0:
                break
            timeframe = strategy_recipe_timeframes(recipe_id)[0]
            history = min(recommended_archive_months(recipe_id), 6)
            receipt = launch_research_job(
                recipe_id,
                job_root,
                instruments=instruments,
                timeframe=timeframe,
                seed_start=40,
                seed_stop=40 + active_config.seed_count,
                archive_months=history,
                product=product,
            )
            launched.append(receipt.to_dict())
            slots -= 1

    active_service = service or TradingService()
    paper_action: dict[str, object] = {"configured": False, "reason": "disabled"}
    worker_action: dict[str, object] = {"started": False, "reason": "disabled"}
    if active_config.auto_prepare_paper:
        paper_action = _auto_prepare_paper(active_service, job_root=job_root)
    if active_config.auto_start_paper:
        worker_action = _ensure_paper_worker(
            active_service,
            log_path=Path("artifacts/trading/autopilot-paper-worker.log"),
        )

    payload = {
        "schema_version": 1,
        "last_cycle_at": now,
        "last_status": "OK",
        "cycles": int(state.get("cycles", 0)) + 1,
        "cursor": cursor,
        "running_jobs_before": len(running),
        "last_launched": launched,
        "universes": universes,
        "paper_action": paper_action,
        "paper_worker": worker_action,
    }
    _save_state(state_file, payload)
    return payload


def main() -> int:
    payload = run_autopilot_cycle()
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
