from __future__ import annotations

from hashlib import sha256
import json
import re
import sys
from collections.abc import Iterable


_FRAME_RE = re.compile(r'^\s*File "(?P<path>[^"]+)", line (?P<line>\d+), in (?P<function>.+?)\s*$')
_EXCEPTION_RE = re.compile(
    r"^(?P<type>[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Timeout|Interrupt|Cancelled))(?::|$)"
)
_FAILURE_MARKERS = (
    ("main_process_exited", "Main process exited"),
    ("failed_result", "Failed with result"),
    ("signal_kill", "code=killed"),
    ("oom_kill", "oom-kill"),
    ("out_of_memory", "Out of memory"),
    ("killed_process", "Killed process"),
)


def _safe_frame(path: str, line: str, function: str) -> dict[str, object] | None:
    normalized = path.replace("\\", "/")
    marker = "/src/mastertrd/"
    if marker in normalized:
        relative = "mastertrd/" + normalized.split(marker, 1)[1]
    elif normalized.startswith("src/mastertrd/"):
        relative = normalized.removeprefix("src/")
    elif normalized.startswith("mastertrd/"):
        relative = normalized
    else:
        return None
    return {
        "module": relative,
        "line": int(line),
        "function": function.strip(),
    }


def sanitize_service_journal(lines: Iterable[str]) -> dict[str, object]:
    """Reduce service journal text to a public-safe crash fingerprint.

    Raw log lines, exception messages, payload values, host paths, and credentials
    are intentionally never returned. The fingerprint keeps only the exception
    class, the last repository-owned traceback frame, a one-way signature of the
    exception line, and coarse systemd/kernel failure-marker counts.
    """

    last_exception_type: str | None = None
    last_exception_signature: str | None = None
    last_frame: dict[str, object] | None = None
    failure_marker_count = 0
    last_failure_marker: str | None = None

    for raw in lines:
        line = str(raw).rstrip("\r\n")
        frame_match = _FRAME_RE.match(line)
        if frame_match is not None:
            safe = _safe_frame(
                frame_match.group("path"),
                frame_match.group("line"),
                frame_match.group("function"),
            )
            if safe is not None:
                last_frame = safe

        stripped = line.strip()
        exception_match = _EXCEPTION_RE.match(stripped)
        if exception_match is not None:
            last_exception_type = exception_match.group("type").rsplit(".", 1)[-1]
            last_exception_signature = sha256(stripped.encode("utf-8")).hexdigest()

        for marker_name, token in _FAILURE_MARKERS:
            if token in line:
                failure_marker_count += 1
                last_failure_marker = marker_name
                break

    return {
        "last_exception_type": last_exception_type,
        "last_traceback_frame": last_frame,
        "last_exception_signature_sha256": last_exception_signature,
        "failure_marker_count": failure_marker_count,
        "last_failure_marker": last_failure_marker,
    }


def main() -> None:
    payload = sanitize_service_journal(sys.stdin)
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
