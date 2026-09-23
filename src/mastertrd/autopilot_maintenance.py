from __future__ import annotations

import json

from .autopilot import run_autopilot_maintenance


def main() -> int:
    payload = run_autopilot_maintenance()
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
