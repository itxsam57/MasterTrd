from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from mastertrd import source_identity


def test_git_head_requires_clean_checkout(monkeypatch, tmp_path):
    monkeypatch.setattr(source_identity, "repository_root", lambda: tmp_path)
    responses = iter(
        (
            SimpleNamespace(stdout="a" * 40 + "\n"),
            SimpleNamespace(stdout=" M src/mastertrd/trading_service.py\n"),
        )
    )
    monkeypatch.setattr(source_identity.subprocess, "run", lambda *args, **kwargs: next(responses))

    with pytest.raises(RuntimeError, match="checkout must be clean"):
        source_identity.git_head()


def test_git_head_returns_exact_sha_for_clean_checkout(monkeypatch, tmp_path):
    monkeypatch.setattr(source_identity, "repository_root", lambda: tmp_path)
    responses = iter(
        (
            SimpleNamespace(stdout="b" * 40 + "\n"),
            SimpleNamespace(stdout=""),
        )
    )
    monkeypatch.setattr(source_identity.subprocess, "run", lambda *args, **kwargs: next(responses))

    assert source_identity.git_head() == "b" * 40


def test_lock_hash_binds_uv_lock(monkeypatch, tmp_path):
    lock = tmp_path / "uv.lock"
    lock.write_text("locked\n", encoding="utf-8")
    monkeypatch.setattr(source_identity, "repository_root", lambda: tmp_path)

    assert source_identity.lock_hash() == hashlib.sha256(lock.read_bytes()).hexdigest()


def test_repository_root_points_to_checkout():
    root = source_identity.repository_root()
    assert (root / "pyproject.toml").is_file()
    assert (root / "uv.lock").is_file()


def test_git_head_can_read_identity_without_cleanliness_probe(monkeypatch, tmp_path):
    monkeypatch.setattr(source_identity, "repository_root", lambda: tmp_path)
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args[0])
        return SimpleNamespace(stdout="c" * 40 + "\n")

    monkeypatch.setattr(source_identity.subprocess, "run", fake_run)
    assert source_identity.git_head(require_clean=False) == "c" * 40
    assert calls == [["git", "rev-parse", "HEAD"]]


def test_lock_hash_requires_lockfile(monkeypatch, tmp_path):
    monkeypatch.setattr(source_identity, "repository_root", lambda: tmp_path)
    with pytest.raises(RuntimeError, match="uv.lock is required"):
        source_identity.lock_hash()
