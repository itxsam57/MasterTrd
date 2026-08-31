from __future__ import annotations

from decimal import Decimal

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import InstrumentId
from nautilus_trader.trading.strategy import Strategy

from .genome import StrategyGenome
from .nautilus_risk_hook import NautilusRiskMixin
from .risk_runtime import RiskRuntime


class GeneratedHftStrategyConfig(StrategyConfig):
    instrument_ids: tuple[InstrumentId, ...]
    trade_size: Decimal
    family: str
    genome_hash: str
    data_level: str


class GeneratedHftStrategy(NautilusRiskMixin, Strategy):
    """Authoritative Nautilus shell for HFT-family execution.

    Tick/L2 subscriptions, state transitions and order intents are deliberately
    added behind separate behavior tests. This constructor establishes the
    dedicated execution boundary and mandatory risk dependency first.
    """

    def __init__(
        self,
        *,
        config: GeneratedHftStrategyConfig,
        genome: StrategyGenome,
        risk_runtime: RiskRuntime | None = None,
    ) -> None:
        super().__init__(config)
        self.genome = genome
        self._configure_risk_runtime(genome.strategy_id, risk_runtime)
