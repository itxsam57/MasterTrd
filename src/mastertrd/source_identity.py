from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def git_head(*, require_clean: bool = True) -> str:
    root = repository_root()
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    commit = result.stdout.strip()
    if not commit:
        raise RuntimeError("MasterTrd git identity is unavailable")
    if require_clean:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        if status.stdout.strip():
            raise RuntimeError(
                "MasterTrd source checkout must be clean before creating provenance-bound artifacts"
            )
    return commit


def lock_hash() -> str:
    path = repository_root() / "uv.lock"
    if not path.is_file():
        raise RuntimeError("uv.lock is required")
    return hashlib.sha256(path.read_bytes()).hexdigest()
