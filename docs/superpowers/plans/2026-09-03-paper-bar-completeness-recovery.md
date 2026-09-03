# PAPER Bar Completeness and Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make forward PAPER bar delivery complete and observable by detecting missed Binance closed candles, recovering them from the public REST kline endpoint, deduplicating WebSocket/REST copies, and refusing to count unhealthy data windows as valid PAPER evidence.

**Architecture:** Keep the WebSocket source as the low-latency transport, but add a small repository-owned closed-bar completeness component that owns expected candle boundaries and REST recovery. The component emits the same canonical `binance-kline:<symbol>:<timeframe>:<start_ms>` identity as the WebSocket source, so the existing execution journal remains the final duplicate guard. Strategy and Nautilus code remain unchanged; the recovery layer sits immediately before `MarketStream` dispatch and exports explicit data-health telemetry.

**Tech Stack:** Python 3.13, stdlib `urllib.request`, existing `MarketBar`/`MarketEvent` contracts, Binance public market-data endpoints, pytest, GitHub Actions.

**Spec:** Owner AAR/premortem in conversation on 2026-09-03; repository architecture and `MASTER_PLAN.md` remain authoritative for safety and promotion semantics.

## Global Constraints

- `LIVE_TRADING_ENABLED` remains false; this plan touches PAPER only.
- No credentials are required for WebSocket or REST recovery.
- Never synthesize OHLCV; a recovered candle must come from Binance public historical kline data and pass the same validation rules as bootstrap history.
- Closed candles are processed at most once economically even if both REST and WebSocket deliver them.
- Missing authoritative data fails closed and marks PAPER data unhealthy.
- Existing strategy/genome/code-hash identity semantics remain unchanged.
- No production code is written before its failing test has been observed on GitHub Actions.

---

### Task 1: Closed-bar schedule and canonical identity

**Files:**
- Create: `src/mastertrd/bar_completeness.py`
- Create: `tests/test_bar_completeness.py`

**Interfaces:**
- Produces: `timeframe_milliseconds(timeframe: str) -> int`
- Produces: `expected_closed_start_ms(*, observed_ms: int, timeframe: str) -> int`
- Produces: `canonical_binance_kline_event_id(symbol: str, timeframe: str, start_ms: int) -> str`

- [ ] **Step 1: Write the failing tests**

```python
from mastertrd.bar_completeness import (
    canonical_binance_kline_event_id,
    expected_closed_start_ms,
    timeframe_milliseconds,
)


def test_four_hour_boundary_maps_to_previous_closed_candle():
    assert timeframe_milliseconds("4h") == 14_400_000
    assert expected_closed_start_ms(
        observed_ms=1_788_436_805_000,
        timeframe="4h",
    ) == 1_788_422_400_000


def test_canonical_kline_identity_matches_websocket_contract():
    assert canonical_binance_kline_event_id("ethusdt", "4h", 1_788_422_400_000) == (
        "binance-kline:ETHUSDT:4h:1788422400000"
    )
```

- [ ] **Step 2: Run RED**

Run the branch CI test command or targeted pytest for `tests/test_bar_completeness.py`.
Expected: collection/import fails because `mastertrd.bar_completeness` does not exist.

- [ ] **Step 3: Implement the minimal schedule helpers**

```python
_SUPPORTED = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "3d": 259_200_000,
    "1w": 604_800_000,
}


def timeframe_milliseconds(timeframe: str) -> int:
    try:
        return _SUPPORTED[str(timeframe).strip()]
    except KeyError as exc:
        raise ValueError(f"unsupported fixed Binance timeframe: {timeframe}") from exc


def expected_closed_start_ms(*, observed_ms: int, timeframe: str) -> int:
    width = timeframe_milliseconds(timeframe)
    if observed_ms < width:
        raise ValueError("observed_ms is too early for a closed candle")
    return ((int(observed_ms) // width) * width) - width


def canonical_binance_kline_event_id(symbol: str, timeframe: str, start_ms: int) -> str:
    return f"binance-kline:{str(symbol).strip().upper()}:{timeframe}:{int(start_ms)}"
```

- [ ] **Step 4: Run GREEN**

Expected: `tests/test_bar_completeness.py` passes.

- [ ] **Step 5: Commit**

Commit message: `feat: define PAPER closed-bar schedule`

---

### Task 2: Public REST exact-candle recovery

**Files:**
- Modify: `src/mastertrd/bar_completeness.py`
- Modify: `tests/test_bar_completeness.py`

**Interfaces:**
- Produces: `load_public_binance_closed_kline(symbol: str, timeframe: str, start_ms: int, *, urlopen_fn=urlopen) -> RawMarketPayload`
- The payload uses the same fields and event ID as `BinancePublicMarketSource._decode_kline`.

- [ ] **Step 1: Add failing recovery tests**

```python
def test_rest_recovery_requires_exact_requested_closed_candle():
    response = FakeResponse(json.dumps([[1788422400000, "2000", "2010", "1990", "2005", "10", 1788436799999]]).encode())
    payload = load_public_binance_closed_kline(
        "ETHUSDT", "4h", 1788422400000,
        urlopen_fn=lambda *_args, **_kwargs: response,
    )
    assert payload["event_id"] == "binance-kline:ETHUSDT:4h:1788422400000"
    assert payload["close"] == 2005.0


def test_rest_recovery_fails_closed_on_wrong_or_open_candle():
    response = FakeResponse(json.dumps([[1788408000000, "1", "1", "1", "1", "1", 1788422399999]]).encode())
    with pytest.raises(RuntimeError, match="exact closed candle"):
        load_public_binance_closed_kline(
            "ETHUSDT", "4h", 1788422400000,
            urlopen_fn=lambda *_args, **_kwargs: response,
        )
```

- [ ] **Step 2: Run RED**

Expected: import/attribute failure because loader does not exist.

- [ ] **Step 3: Implement exact REST loading**

Implementation requirements:

```python
url = (
    "https://data-api.binance.vision/api/v3/klines"
    f"?symbol={symbol}&interval={timeframe}&startTime={start_ms}&endTime={start_ms + width - 1}&limit=1"
)
```

Parse one list row, require `row[0] == start_ms`, require its close timestamp is not in the future relative to an injected/derived observation clock, validate positive finite OHLC and non-negative finite volume, and return the canonical raw market payload.

- [ ] **Step 4: Run GREEN**

Expected: exact-candle recovery and fail-closed tests pass.

- [ ] **Step 5: Commit**

Commit message: `feat: recover exact Binance closed candles`

---

### Task 3: Completeness tracker and one-time recovery

**Files:**
- Modify: `src/mastertrd/bar_completeness.py`
- Modify: `tests/test_bar_completeness.py`

**Interfaces:**
- Produces immutable `BarCompletenessSnapshot` with `expected_closed_bars`, `ws_closed_bars`, `rest_recovered_bars`, `missing_closed_bars`, `last_closed_bar_ms`, `last_expected_close_ms`, `data_healthy`.
- Produces `ClosedBarCompletenessTracker.observe(event: MarketEvent) -> None`.
- Produces `ClosedBarCompletenessTracker.recover_due(observed_ms: int) -> tuple[RawMarketPayload, ...]`.

- [ ] **Step 1: Write failing behavior tests**

```python
def test_missing_expected_bar_is_recovered_once_and_late_ws_copy_is_duplicate():
    tracker = ClosedBarCompletenessTracker(
        instruments=("ETHUSDT",),
        timeframe="4h",
        first_expected_start_ms=1788422400000,
        recovery_loader=lambda *_args: recovered_payload,
    )
    assert tracker.recover_due(1788436805000) == (recovered_payload,)
    assert tracker.recover_due(1788436810000) == ()
    tracker.observe(event_from_payload(recovered_payload))
    snapshot = tracker.snapshot
    assert snapshot.rest_recovered_bars == 1
    assert snapshot.missing_closed_bars == 0
    assert snapshot.data_healthy is True


def test_failed_recovery_marks_data_unhealthy():
    tracker = ClosedBarCompletenessTracker(
        instruments=("ETHUSDT",), timeframe="4h",
        first_expected_start_ms=1788422400000,
        recovery_loader=lambda *_args: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert tracker.recover_due(1788436805000) == ()
    assert tracker.snapshot.data_healthy is False
    assert tracker.snapshot.missing_closed_bars == 1
```

- [ ] **Step 2: Run RED**

Expected: tracker types do not exist.

- [ ] **Step 3: Implement minimal tracker**

Use sets keyed by canonical kline event ID. Only authoritative closed bar IDs advance completeness. A recovery attempt may be retried only after a bounded retry interval; a successful REST payload is marked recovered before being returned so later scheduler ticks do not emit it twice. A WebSocket copy with the same ID is harmless because the runtime journal and tracker both recognize the identity.

- [ ] **Step 4: Run GREEN**

Expected: tracker tests pass.

- [ ] **Step 5: Commit**

Commit message: `feat: reconcile PAPER closed-bar completeness`

---

### Task 4: Integrate recovery into the real PAPER stream

**Files:**
- Modify: `src/mastertrd/binance_stream.py`
- Modify: `src/mastertrd/runtime_factory.py`
- Modify: `tests/integration/test_runtime_factory.py`
- Modify: `tests/test_binance_stream.py`

**Interfaces:**
- `BinancePublicMarketSource` accepts an optional completeness tracker/recovery loader without changing fixture behavior.
- The real PAPER factory enables completeness recovery; fixture PAPER remains deterministic and network-free.

- [ ] **Step 1: Write failing integration tests**

```python
def test_real_public_source_recovers_missing_closed_bar_before_next_expected_boundary(...):
    # Feed only book/open-kline messages through the fake connector.
    # Inject exact REST recovery and advance the source clock past the grace boundary.
    events = list(source)
    bars = [event for event in MarketStream(events) if event.kind == "bar"]
    assert [bar.event_id for bar in bars] == ["binance-kline:ETHUSDT:1m:<expected-start>"]


def test_fixture_paper_runtime_never_calls_rest_recovery(...):
    # Existing MASTERTRD_PUBLIC_FEED_FIXTURE path must stay network-free.
    ...
```

- [ ] **Step 2: Run RED**

Expected: no recovery path exists in the source/factory.

- [ ] **Step 3: Implement integration**

On every source iteration/reconnect boundary and periodically while book/open-kline traffic arrives, ask the tracker for overdue recoveries. Emit recovered raw payloads through the existing `MarketStream` normalization path. Preserve the existing WebSocket decoder and canonical ID.

- [ ] **Step 4: Run GREEN and regression suites**

Run targeted stream/factory tests, then CI/full-stack workflows.
Expected: no fixture network calls; existing reconnect/dedupe tests stay green.

- [ ] **Step 5: Commit**

Commit message: `fix: recover missing PAPER closed bars`

---

### Task 5: Data-health telemetry and fail-closed PAPER evidence

**Files:**
- Modify: `src/mastertrd/nautilus_paper.py`
- Modify: `src/mastertrd/paper_status.py`
- Modify: `src/mastertrd/paper_forward.py`
- Modify: `tests/test_paper_status.py`
- Modify: `tests/test_paper_forward.py`

**Interfaces:**
- PAPER strategy telemetry adds `expected_closed_bars`, `ws_closed_bars`, `rest_recovered_bars`, `missing_closed_bars`, `data_healthy`, `last_closed_bar_ms`, `last_expected_close_ms`.
- `PaperForwardReport` adds `data_healthy: bool = True` and `missing_closed_bars: int = 0` with backward-compatible defaults.
- `paper_minimum_evidence()` requires every report to be data healthy and have zero missing closed bars.

- [ ] **Step 1: Add failing status/evidence tests**

```python
def test_missing_bar_health_is_visible_in_paper_status():
    status = build_status(... telemetry={"data_healthy": False, "missing_closed_bars": 1})
    assert status["data_healthy"] is False
    assert status["missing_closed_bars"] == 1


def test_data_unhealthy_forward_session_cannot_promote():
    bad = replace(report(candidate, "session-1"), data_healthy=False, missing_closed_bars=1)
    evidence = paper_minimum_evidence(candidate, [bad, report(candidate, "session-2")], policy())
    assert evidence.passed is False
```

- [ ] **Step 2: Run RED**

Expected: report/status fields are absent and bad data does not affect promotion.

- [ ] **Step 3: Implement telemetry/evidence guard**

Persist the completeness snapshot through the existing strategy telemetry channel. `paper_minimum_evidence()` must include `data_healthy_sessions` and `missing_closed_bars` metrics and require all sessions healthy.

- [ ] **Step 4: Run GREEN and full regression**

Expected: all status/forward tests pass, including legacy journal compatibility.

- [ ] **Step 5: Commit**

Commit message: `feat: gate PAPER evidence on data health`

---

### Task 6: Real-network canary workflow contract

**Files:**
- Create: `.github/workflows/paper-market-data-canary.yml`
- Create: `src/mastertrd/paper_canary.py`
- Create: `tests/test_paper_canary.py`

**Interfaces:**
- CLI `python -m mastertrd.paper_canary` listens to real public Binance 1m data for one configured instrument, requires at least three consecutive closed candles with zero gaps, and writes a JSON receipt.
- This workflow has no exchange credentials and never submits an order; the order/fill canary is a later isolated task after data completeness is green.

- [ ] **Step 1: Write failing receipt tests**

```python
def test_canary_receipt_requires_three_consecutive_real_closed_bars():
    result = evaluate_canary_events(events=three_consecutive_bars, required=3)
    assert result.passed is True
    assert result.closed_bars == 3


def test_canary_receipt_fails_on_gap():
    result = evaluate_canary_events(events=bars_with_one_missing_interval, required=3)
    assert result.passed is False
    assert result.missing_closed_bars == 1
```

- [ ] **Step 2: Run RED**

Expected: `paper_canary` does not exist.

- [ ] **Step 3: Implement canary evaluator and workflow**

The workflow uses `workflow_dispatch` plus a conservative scheduled run. It installs the exact lock, executes the CLI against `data-stream.binance.vision`, and uploads the JSON receipt. It does not declare trading readiness; it proves only real public closed-bar completeness.

- [ ] **Step 4: Run GREEN and exact-head workflow verification**

Expected: unit tests pass; a manually/scheduled real-network workflow produces a receipt with at least three consecutive 1m closed bars and zero gaps.

- [ ] **Step 5: Commit**

Commit message: `test: add real Binance closed-bar canary`

---

## Final verification

- Run CI, Full Stack Compatibility, Execution Stack, Completion Acceptance, Public Repo Security, and Consumer Release Smoke on the exact branch head.
- Run the real-network PAPER market-data canary and inspect its artifact.
- Do not merge unless every required exact-head workflow is green and the canary receipt proves consecutive real closed bars with `missing_closed_bars == 0`.
- After merge, deploy only an exact candidate/code identity and verify Oracle status shows closed-bar counters advancing. No LIVE enablement is part of this plan.
