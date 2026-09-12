from __future__ import annotations

from .trading_service import TradingService


def main() -> None:
    TradingService().run_forever(
        heartbeat=lambda state: print(f"MasterTrd heartbeat: {state}", flush=True),
    )


if __name__ == "__main__":
    main()
