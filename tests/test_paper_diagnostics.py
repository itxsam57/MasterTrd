from __future__ import annotations

import importlib
import io
import json
import sys


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
            "kernel: oom-kill: constraint=CONSTRAINT_NONE",
            "kernel: Out of memory: Killed process 123 python",
        ]
    )

    assert payload["last_exception_type"] is None
    assert payload["last_traceback_frame"] is None
    assert payload["failure_marker_count"] == 4
    assert payload["last_failure_marker"] == "out_of_memory"


def test_safe_frame_normalizes_repo_paths_and_rejects_external_paths():
    module = importlib.import_module("mastertrd.paper_diagnostics")

    assert module._safe_frame("src/mastertrd/runtime.py", "7", "run") == {
        "module": "mastertrd/runtime.py",
        "line": 7,
        "function": "run",
    }
    assert module._safe_frame("mastertrd/live_node.py", "12", "main") == {
        "module": "mastertrd/live_node.py",
        "line": 12,
        "function": "main",
    }
    assert module._safe_frame(
        r"C:\\work\\src\\mastertrd\\binance_stream.py", "21", "__iter__"
    ) == {
        "module": "mastertrd/binance_stream.py",
        "line": 21,
        "function": "__iter__",
    }
    assert module._safe_frame("/usr/lib/python/site-packages/websockets/foo.py", "1", "recv") is None


def test_diagnostics_cli_emits_only_sanitized_json(monkeypatch, capsys):
    module = importlib.import_module("mastertrd.paper_diagnostics")
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            '  File "/opt/mastertrd/src/mastertrd/runtime_factory.py", line 99, in build\n'
            "RuntimeError: credential=must-not-escape\n"
        ),
    )

    module.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["last_exception_type"] == "RuntimeError"
    assert payload["last_traceback_frame"]["module"] == "mastertrd/runtime_factory.py"
    assert "must-not-escape" not in repr(payload)
