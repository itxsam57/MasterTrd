from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from time import monotonic, sleep
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .contracts import RuntimeMode
from .credentials import load_binance_credentials
from .execution import BinanceExecutionProfile
from .genome import StrategyGenome
from .live_evidence import run_testnet_smoke
from .nautilus_binance import build_nautilus_binance_configs
from .runtime import RuntimeConfig
from .testnet_candidate import TestnetCandidateManifest
from .venue import BinanceProduct


_TESTNET_API = "https://testnet.binance.vision"
_SYMBOL = re.compile(r"^[A-Z0-9]{5,20}$")


@dataclass(frozen=True, slots=True)
class SpotTestnetRules:
    symbol: str
    min_notional: Decimal
    step_size: Decimal
    min_quantity: Decimal

    def canonical_payload(self) -> dict[str, str]:
        return {
            "symbol": self.symbol,
            "min_notional": str(self.min_notional),
            "step_size": str(self.step_size),
            "min_quantity": str(self.min_quantity),
        }

    @property
    def dataset_hash(self) -> str:
        payload = json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def calculate_minimum_order_quantity(
    *,
    min_notional: Decimal,
    limit_price: Decimal,
    step_size: Decimal,
    min_quantity: Decimal,
) -> Decimal:
    values = {
        "min_notional": min_notional,
        "limit_price": limit_price,
        "step_size": step_size,
        "min_quantity": min_quantity,
    }
    if any(value <= 0 for value in values.values()):
        raise ValueError("TESTNET order sizing inputs must all be positive")

    required = max(min_quantity, min_notional / limit_price)
    steps = (required / step_size).to_integral_value(rounding=ROUND_CEILING)
    quantity = steps * step_size
    return max(min_quantity, quantity)


def parse_spot_order_rules(payload: dict[str, Any], *, symbol: str) -> SpotTestnetRules:
    symbols = payload.get("symbols")
    if not isinstance(symbols, list) or len(symbols) != 1:
        raise ValueError("Binance TESTNET exchangeInfo did not return exactly one symbol")
    record = symbols[0]
    if not isinstance(record, dict) or str(record.get("symbol", "")).upper() != symbol:
        raise ValueError("Binance TESTNET exchangeInfo symbol mismatch")

    filters = record.get("filters")
    if not isinstance(filters, list):
        raise ValueError("Binance TESTNET exchangeInfo is missing filters")

    by_type = {
        str(item.get("filterType")): item
        for item in filters
        if isinstance(item, dict) and item.get("filterType")
    }
    lot = by_type.get("LOT_SIZE")
    notional = by_type.get("NOTIONAL") or by_type.get("MIN_NOTIONAL")
    if not isinstance(lot, dict) or not isinstance(notional, dict):
        raise ValueError("Binance TESTNET symbol is missing LOT_SIZE or minimum-notional rules")

    min_notional = Decimal(str(notional.get("minNotional", "0")))
    step_size = Decimal(str(lot.get("stepSize", "0")))
    min_quantity = Decimal(str(lot.get("minQty", "0")))
    if min_notional <= 0 or step_size <= 0 or min_quantity <= 0:
        raise ValueError("Binance TESTNET returned non-positive order constraints")

    return SpotTestnetRules(
        symbol=symbol,
        min_notional=min_notional,
        step_size=step_size,
        min_quantity=min_quantity,
    )


def fetch_spot_testnet_rules(symbol: str) -> SpotTestnetRules:
    symbol = symbol.strip().upper()
    if not _SYMBOL.fullmatch(symbol):
        raise ValueError("invalid Binance TESTNET symbol")
    query = urlencode({"symbol": symbol})
    request = Request(
        f"{_TESTNET_API}/api/v3/exchangeInfo?{query}",
        headers={"User-Agent": "MasterTrd-Testnet-Smoke/1"},
    )
    with urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Binance TESTNET exchangeInfo returned an invalid payload")
    return parse_spot_order_rules(payload, symbol=symbol)


def _candidate(symbol: str) -> StrategyGenome:
    return StrategyGenome(
        strategy_id="MASTERTRD-TESTNET-SMOKE",
        family="execution_probe",
        style="testnet",
        instruments=(f"{symbol}.BINANCE",),
        timeframe="1m",
        entry={"kind": "bounded_testnet_order"},
        exit={"kind": "cancel_on_shutdown"},
    )


def _require_testnet_runtime(environ: dict[str, str]) -> RuntimeConfig:
    runtime = RuntimeConfig.from_env(environ)
    if runtime.mode is not RuntimeMode.TESTNET:
        raise RuntimeError("TESTNET smoke refuses every runtime mode except TESTNET")
    if environ.get("BINANCE_TESTNET_WITHDRAWAL_CAPABLE", "").strip():
        raise RuntimeError("TESTNET smoke refuses credentials marked withdrawal-capable")
    return runtime


def _submit_nautilus_spot_testnet_order(
    *,
    environ: dict[str, str],
    symbol: str,
    rules: SpotTestnetRules,
    minimum_notional: float,
    timeout_seconds: float = 45.0,
) -> bool:
    credentials = load_binance_credentials(RuntimeMode.TESTNET, environ)
    if credentials is None:
        return False

    from nautilus_trader.adapters.binance import BINANCE
    from nautilus_trader.adapters.binance import BinanceLiveDataClientFactory
    from nautilus_trader.adapters.binance import BinanceLiveExecClientFactory
    from nautilus_trader.config import LiveExecEngineConfig
    from nautilus_trader.config import LoggingConfig
    from nautilus_trader.config import StrategyConfig
    from nautilus_trader.config import TradingNodeConfig
    from nautilus_trader.live.node import TradingNode
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.enums import OrderSide
    from nautilus_trader.model.events import OrderAccepted, OrderDenied, OrderRejected
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.model.identifiers import TraderId
    from nautilus_trader.trading.strategy import Strategy

    instrument_id = InstrumentId.from_str(f"{symbol}.{BINANCE}")
    profile = BinanceExecutionProfile(
        product=BinanceProduct.SPOT,
        environment="TESTNET",
        api_key=credentials.api_key,
        api_secret=credentials.api_secret,
    )
    configs = build_nautilus_binance_configs(
        profile=profile,
        account_id=credentials.account_id,
        instrument_ids=frozenset({instrument_id}),
    )

    done = threading.Event()
    result: dict[str, bool] = {"accepted": False}

    class SmokeConfig(StrategyConfig, frozen=True):
        instrument_id: InstrumentId
        min_notional: Decimal
        step_size: Decimal
        min_quantity: Decimal
        tob_offset_ticks: int = 500

    class SmokeStrategy(Strategy):
        def __init__(self, config: SmokeConfig) -> None:
            super().__init__(config)
            self.instrument = None
            self.order = None

        def on_start(self) -> None:
            self.instrument = self.cache.instrument(self.config.instrument_id)
            if self.instrument is None:
                done.set()
                self.stop()
                return
            self.subscribe_quote_ticks(self.config.instrument_id)

        def on_quote_tick(self, quote: QuoteTick) -> None:
            if self.instrument is None or self.order is not None:
                return
            offset = self.instrument.price_increment * self.config.tob_offset_ticks
            limit_price = self.instrument.make_price(quote.bid_price - offset)
            limit_price_decimal = Decimal(str(limit_price))
            if limit_price_decimal <= 0:
                done.set()
                return

            quantity_decimal = calculate_minimum_order_quantity(
                min_notional=self.config.min_notional,
                limit_price=limit_price_decimal,
                step_size=self.config.step_size,
                min_quantity=self.config.min_quantity,
            )
            self.order = self.order_factory.limit(
                instrument_id=self.config.instrument_id,
                order_side=OrderSide.BUY,
                quantity=self.instrument.make_qty(quantity_decimal),
                price=limit_price,
                post_only=True,
            )
            self.submit_order(self.order)

        def on_order_accepted(self, event: OrderAccepted) -> None:
            if self.order is not None and event.client_order_id == self.order.client_order_id:
                result["accepted"] = True
                done.set()

        def on_order_rejected(self, event: OrderRejected) -> None:
            if self.order is not None and event.client_order_id == self.order.client_order_id:
                done.set()

        def on_order_denied(self, event: OrderDenied) -> None:
            if self.order is not None and event.client_order_id == self.order.client_order_id:
                done.set()

        def on_stop(self) -> None:
            self.cancel_all_orders(self.config.instrument_id)

    requested_notional = Decimal(str(minimum_notional))
    strategy = SmokeStrategy(
        SmokeConfig(
            instrument_id=instrument_id,
            min_notional=requested_notional,
            step_size=rules.step_size,
            min_quantity=rules.min_quantity,
        ),
    )
    node = TradingNode(
        config=TradingNodeConfig(
            trader_id=TraderId("MASTERTRD-TESTNET-001"),
            logging=LoggingConfig(log_level="INFO"),
            exec_engine=LiveExecEngineConfig(
                reconciliation=True,
                reconciliation_lookback_mins=1440,
            ),
            data_clients={BINANCE: configs.data},
            exec_clients={BINANCE: configs.execution},
            timeout_connection=30.0,
            timeout_reconciliation=10.0,
            timeout_portfolio=10.0,
            timeout_disconnection=10.0,
            timeout_post_stop=2.0,
        ),
    )
    node.trader.add_strategy(strategy)
    node.add_data_client_factory(BINANCE, BinanceLiveDataClientFactory)
    node.add_exec_client_factory(BINANCE, BinanceLiveExecClientFactory)
    node.build()

    def stop_when_probe_finishes() -> None:
        deadline = monotonic() + timeout_seconds
        while not done.is_set() and monotonic() < deadline:
            sleep(0.1)
        loop = node.get_event_loop()
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(node.stop)

    watcher = threading.Thread(
        target=stop_when_probe_finishes,
        name="mastertrd-testnet-smoke-watchdog",
        daemon=True,
    )
    watcher.start()
    try:
        node.run(raise_exception=True)
    finally:
        if node.is_running():
            node.stop()
        node.dispose()
        watcher.join(timeout=1.0)

    return result["accepted"]


def _load_candidate_manifest(environ: dict[str, str]) -> TestnetCandidateManifest | None:
    manifest_path = (
        environ.get("MASTERTRD_TESTNET_CANDIDATE_MANIFEST", "").strip()
        or environ.get("MASTERTRD_TESTNET_CANDIDATE_PATH", "").strip()
    )
    if not manifest_path:
        return None
    path = Path(manifest_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"TESTNET candidate manifest could not be loaded: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("TESTNET candidate manifest must contain a JSON object")
    try:
        return TestnetCandidateManifest.from_public_payload(payload)
    except ValueError as exc:
        raise RuntimeError(f"invalid TESTNET candidate manifest: {exc}") from exc


def _manifest_spot_symbol(manifest: TestnetCandidateManifest) -> str:
    if manifest.product is not BinanceProduct.SPOT:
        raise RuntimeError("TESTNET candidate product is not supported by the spot smoke adapter")
    suffix = ".BINANCE"
    if not manifest.probe_instrument.endswith(suffix):
        raise RuntimeError("TESTNET candidate probe_instrument must target BINANCE")
    symbol = manifest.probe_instrument[: -len(suffix)].strip().upper()
    if not _SYMBOL.fullmatch(symbol):
        raise RuntimeError("TESTNET candidate probe_instrument contains an invalid symbol")
    return symbol


def run(environ: dict[str, str] | None = None) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    _require_testnet_runtime(env)
    code_hash = env.get("GITHUB_SHA", "").strip() or env.get("MASTERTRD_CODE_HASH", "").strip()
    if not code_hash:
        raise RuntimeError("TESTNET smoke requires GITHUB_SHA or MASTERTRD_CODE_HASH")

    manifest = _load_candidate_manifest(env)
    if manifest is None:
        symbol = env.get("MASTERTRD_TESTNET_SYMBOL", "BTCUSDT").strip().upper()
        candidate = _candidate(symbol)
        dataset_hash = None
    else:
        if manifest.code_hash != code_hash:
            raise RuntimeError("TESTNET candidate manifest code_hash does not match checkout code_hash")
        symbol = _manifest_spot_symbol(manifest)
        candidate = manifest.candidate
        dataset_hash = manifest.dataset_hash

    if manifest is not None:
        try:
            load_binance_credentials(RuntimeMode.TESTNET, env)
        except ValueError:
            evidence = run_testnet_smoke(
                candidate,
                environ=env,
                dataset_hash=manifest.dataset_hash,
                code_hash=manifest.code_hash,
                runtime_mode=RuntimeMode.TESTNET,
                venue_minimum_notional=float(manifest.order_notional_cap),
                submit_test_order=None,
            )
            payload = asdict(evidence)
            payload["symbol"] = symbol
            payload["runtime_mode"] = RuntimeMode.TESTNET.value
            payload["live_enabled"] = False
            payload["product"] = manifest.product.value
            payload["probe_instrument"] = manifest.probe_instrument
            payload["order_notional_cap"] = str(manifest.order_notional_cap)
            payload["blocker"] = "BLOCKED_OWNER_INPUT"
            return payload

    rules = fetch_spot_testnet_rules(symbol)
    if manifest is not None and rules.min_notional > manifest.order_notional_cap:
        raise RuntimeError("venue minimum notional exceeds candidate order_notional_cap")

    evidence = run_testnet_smoke(
        candidate,
        environ=env,
        dataset_hash=dataset_hash or rules.dataset_hash,
        code_hash=manifest.code_hash if manifest is not None else code_hash,
        runtime_mode=RuntimeMode.TESTNET,
        venue_minimum_notional=float(rules.min_notional),
        submit_test_order=lambda minimum: _submit_nautilus_spot_testnet_order(
            environ=env,
            symbol=symbol,
            rules=rules,
            minimum_notional=minimum,
        ),
    )
    payload = asdict(evidence)
    payload["symbol"] = symbol
    payload["runtime_mode"] = RuntimeMode.TESTNET.value
    payload["live_enabled"] = False
    if manifest is not None:
        payload["product"] = manifest.product.value
        payload["probe_instrument"] = manifest.probe_instrument
        payload["order_notional_cap"] = str(manifest.order_notional_cap)
    return payload


def main() -> int:
    payload = run()
    output = Path(os.environ.get("MASTERTRD_TESTNET_EVIDENCE_PATH", "artifacts/testnet_smoke.json"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "TESTNET smoke "
        f"status={payload['status']} passed={payload['passed']} "
        f"symbol={payload['symbol']} code_sha={payload['code_hash']}",
    )
    return 0 if bool(payload["passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
