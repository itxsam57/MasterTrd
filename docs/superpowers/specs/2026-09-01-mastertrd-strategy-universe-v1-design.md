# MasterTrd Strategy Universe V1 Design

**Status:** APPROVED  
**Date:** 2026-09-01  
**Base:** `main` at `a659e8b592e66afccb7225a72d2f1e5984001028`

## Goal

Expand MasterTrd from one stochastic template per strategy family into a versioned, evidence-aware strategy universe that can continuously test many named archetypes and controlled mutations across crypto, equities, FX, futures, commodities, rates, options, prediction markets, betting exchanges, and multi-asset portfolios without weakening the existing Promotion Governor, execution engine, risk gates, or evidence requirements.

## Principles

1. NautilusTrader remains the sole authoritative execution engine.
2. Outside code is never copied merely because it is popular. External repositories and papers are research sources; MasterTrd expresses admitted ideas as its own `StrategyGenome` semantics.
3. Every outside idea is untrusted until reproduced by MasterTrd.
4. The catalog distinguishes an idea from an executable implementation. A strategy may be cataloged while remaining blocked on a missing primitive, missing specialist data, or an unadmitted venue.
5. The catalog records source/evidence provenance, market applicability, horizon, data level, and execution readiness.
6. Existing working strategies remain behaviorally unchanged. Strategy Universe V1 adds deterministic recipe selection on top of the existing family generator.
7. HFT/scalping/order-book/market-making recipes remain blocked from promotion without qualifying real tick/L2 evidence.
8. Options recipes remain blocked from promotion without option-compatible instrument metadata and option evidence.
9. Venue/provider support is split into two facts: what the locked NautilusTrader version exposes, and what MasterTrd has actually admitted/tested in its own runtime.
10. LIVE remains disabled by default.

## Evidence classes

- `ACADEMIC`: peer-reviewed or established working-paper evidence describing the concept.
- `VENUE_REFERENCE`: strategy/market mechanics from an exchange, broker, or official engine documentation.
- `OPEN_SOURCE_REFERENCE`: concept found in a mature open-source trading ecosystem; treated as an idea source, not profitability evidence.
- `EXPERIMENTAL`: plausible research hypothesis without strong external replication evidence.

No evidence class can bypass MasterTrd validation.

## Recipe readiness

- `EXECUTABLE`: the current MasterTrd signal/execution semantics can represent the recipe without pretending a proxy is exact.
- `SPECIALIST_DATA_REQUIRED`: execution semantics exist but required real tick/L2/options/specialist data is unavailable in the current scheduled research job.
- `PRIMITIVE_REQUIRED`: the idea is cataloged but needs a new exact signal/execution primitive before it can enter promotion-grade testing.
- `PROVIDER_REQUIRED`: the strategy needs a market/venue not yet admitted into MasterTrd even if NautilusTrader has an adapter.
- `EXPERIMENTAL`: research-only concept until an explicit implementation/evidence plan is admitted.

## Strategy universe

V1 catalogs ideas under the existing strategy families rather than creating hundreds of hand-written strategies. Named recipes include trend/time-series momentum, moving-average systems, Turtle/Donchian breakouts, RSI momentum/reversion, Bollinger/z-score mean reversion, volatility breakouts, swing pullbacks, long-horizon trend, pairs/cointegration, funding/basis, delta-neutral, options volatility, portfolio rotation, scalping, grids, inventory-skew market making, order-book imbalance, and cross-venue spread capture.

The catalog also records additional non-executable V1 research targets including cross-sectional momentum, dual momentum, value, quality/profitability, carry, low-volatility/BAB, earnings/event anomalies, FX carry/value/momentum, commodity term structure/roll yield, volatility-risk-premium, option skew/dispersion/gamma strategies, event-market probability/value strategies, Betfair exchange strategies, and ML/RL/meta-labeling concepts.

The important scaling mechanism is recipe + parameter space + instrument universe + timeframe + regime mutation, not thousands of duplicated source files.

## Recipe compiler

`compile_strategy_recipe(recipe_id, *, instruments, seed, trade_size=None) -> StrategyGenome`

The compiler:

- resolves a versioned recipe;
- refuses non-`EXECUTABLE` recipes with the exact blocker;
- samples only declared parameter ranges deterministically from `seed`;
- preserves family data-level requirements;
- generates a deterministic strategy ID and normal `StrategyGenome` hash;
- uses existing execution entry/exit kinds so research and execution remain semantically identical;
- never converts a blocked catalog item into a proxy implementation.

`research.generator.generate_candidate(...)` remains backward compatible and gains optional `recipe_id` selection.

## Scheduled research behavior

The existing no-key Binance public-data job remains conservative and promotion-grade only for BAR-based crypto recipes supported by its data. Strategy Universe V1 expands recipe diversity inside those runnable families first. Families requiring multi-leg feeds, long histories, options, tick/L2, or other venues remain explicitly blocked until their data/provider gate is admitted.

The public research artifact will record `recipe_id` for traceability.

## Provider capability registry

Add an internal registry describing the locked NautilusTrader 1.231.0 integration surface and MasterTrd admission state.

The current stable Nautilus integration surface includes, among others:

- Binance: crypto spot, USDT-margined futures/perpetuals, coin-margined futures/perpetuals.
- Coinbase: spot, perpetuals, dated futures.
- Kraken: spot and futures.
- OKX: spot, margin, perpetual swaps, futures, options, spreads, event contracts.
- Bybit, BitMEX, Deribit, Hyperliquid, dYdX, Derive, Lighter and other crypto venues.
- Interactive Brokers: multi-venue brokerage access to equities, options, futures, currencies, bonds, funds and other instruments through TWS/IB Gateway.
- Polymarket: binary-option prediction markets with L2 CLOB data and execution.
- Betfair: betting exchange data/account/order execution.
- Databento: traditional-asset market data including equities, futures, options, futures/options spreads and FX spot; data-only.
- Tardis: broad crypto historical/market-data coverage; data-only.

A registry entry can therefore be `AVAILABLE_IN_NAUTILUS` while `mastertrd_status=NOT_ADMITTED`. This prevents documentation from implying live support before MasterTrd-specific dependency, contract, runtime, risk, recovery and smoke gates pass.

## Initial provider admission order

1. Keep Binance as the already-admitted execution venue and first TESTNET venue.
2. Add provider/data capability records immediately.
3. Next execution admissions should prioritize broad coverage per integration effort: Interactive Brokers for equities/FX/futures/options, then Polymarket for prediction markets, then an additional crypto derivatives/options venue such as OKX or Deribit.
4. Betfair remains a separate regulated betting-exchange admission because account/regulatory semantics differ from financial instruments.
5. Databento/Tardis are data-provider admissions and never become execution clients.

## Champion model

MasterTrd should not converge on one universal Frankenstein strategy. It should produce family/market Champions and then a higher-level portfolio/meta Champion that allocates among independently validated sleeves, for example trend, mean reversion, carry/basis, stat-arb, HFT/market-making, options-volatility and event-market sleeves.

Every sleeve still follows:

`IDEA -> SCREENED -> BACKTESTED -> ROBUST -> HIDDEN_PASS -> PAPER -> CHALLENGER -> CHAMPION -> LIVE_ELIGIBLE`

## Safety and licensing

- No copied proprietary strategy implementation enters the repository.
- External URLs/titles are provenance metadata only.
- No exchange/broker credentials are stored in the catalog.
- Prediction-market private keys, wallet credentials and betting credentials are never committed.
- Provider admission must pass the same dependency/security/reconciliation/kill-switch standards as Binance.
- A venue adapter being present in NautilusTrader is not proof that MasterTrd has admitted it.
