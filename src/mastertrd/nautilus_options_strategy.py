from __future__ import annotations

from .execution_signals import SignalDecision, SignalDirection
from .nautilus_bar_strategy import GeneratedBarStrategy, GeneratedBarStrategyConfig


class GeneratedOptionsStrategyConfig(GeneratedBarStrategyConfig):
    defined_risk_only: bool = True


class GeneratedOptionsStrategy(GeneratedBarStrategy):
    """Defined-risk options path.

    MasterTrd permits long-premium exposure on a single option instrument here.
    A SHORT volatility decision closes an existing long rather than opening a naked
    short. Multi-leg defined-risk spreads can be added through the multi-leg path
    when a venue supplies an option chain and compatible instruments.
    """

    def _apply_decision(self, decision: SignalDecision) -> None:
        if not self.config.defined_risk_only:
            raise RuntimeError("options execution requires defined_risk_only")
        if decision.direction is SignalDirection.SHORT:
            if self.portfolio.is_net_long(self.config.instrument_id):
                self.close_all_positions(self.config.instrument_id)
            return
        super()._apply_decision(decision)
