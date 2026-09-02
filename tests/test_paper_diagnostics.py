from __future__ import annotations

import importlib


def test_sanitized_paper_diagnostics_exposes_identity_not_raw_log_text():
    module = importlib.import_module("mastertrd.paper_diagnostics")
    payload = module.sanitize_service_journal(
        [
            "Traceback (most recent call last):",
            '  File "/opt/mastertrd/src/mastertrd/binance_stream.py", line 173, in __iter__',
            "    for message in connection:",
            "websockets.exceptions.ConnectionClosedError: no close frame received or sent token=super-secret",
        ]
    )

    assert payload["last_exception_type"] == "ConnectionClosedError"
    assert payload["last_traceback_frame"] == {
        "module": "mastertrd/binance_stream.py",
        "line": 173,
        "function": "__iter__",
    }
    assert isinstance(payload["last_exception_signature_sha256"], str)
    assert len(payload["last_exception_signature_sha256"]) == 64
    serialized = repr(payload)
    assert "no close frame" not in serialized
    assert "super-secret" not in serialized
    assert "/opt/mastertrd" not in serialized


def test_sanitized_paper_diagnostics_handles_non_python_failure_markers():
    module = importlib.import_module("mastertrd.paper_diagnostics")
    payload = module.sanitize_service_journal(
        [
            "mastertrd.service: Main process exited, code=killed, status=9/KILL",
            "mastertrd.service: Failed with result 'signal'.",
        ]
    )

    assert payload["last_exception_type"] is None
    assert payload["last_traceback_frame"] is None
    assert payload["failure_marker_count"] == 2
