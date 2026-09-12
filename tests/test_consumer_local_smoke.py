import json
import subprocess


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["mastertrd", *args], capture_output=True, text=True, check=False)


def test_consumer_commands_are_available():
    status = _run("status")
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["live_enabled"] is False

    strategies = _run("strategies")
    assert strategies.returncode == 0, strategies.stderr
    assert len(json.loads(strategies.stdout)) >= 189

    jobs = _run("jobs")
    assert jobs.returncode == 0, jobs.stderr
    assert isinstance(json.loads(jobs.stdout), list)

    app_help = _run("app", "--help")
    assert app_help.returncode == 0, app_help.stderr
    assert "usage: mastertrd app" in app_help.stdout
