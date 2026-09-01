# MasterTrd Market & Provider Matrix

Strategy Universe V1 records two separate facts:

1. what the pinned/current NautilusTrader integration surface can represent, and
2. what MasterTrd has actually admitted through its own data, execution, reconciliation, risk, PAPER/TESTNET, and Governor gates.

**Nautilus availability is never MasterTrd admission.** The only currently admitted execution provider is Binance, and admission does not imply LIVE eligibility. `LIVE_TRADING_ENABLED=false` remains the default and real-world TESTNET/Governor evidence is still required before any guarded LIVE state can exist.

## Admission states

- **ADMITTED** — MasterTrd owns the adapter-specific runtime path and tests. This still does not bypass strategy, credential, TESTNET, reconciliation, or LIVE gates.
- **RESEARCH_ONLY** — data may be admitted for research but cannot route orders.
- **NOT_ADMITTED** — Nautilus/provider capability is recorded only; MasterTrd must fail closed if asked to execute through it.

## Provider matrix

| Provider | Kind | Major products / markets | Nautilus data | Nautilus execution | MasterTrd | Next admission requirement |
| --- | --- | --- | --- | --- | --- | --- |
| Binance | CEX | Spot, USD-M/COIN-M perpetuals and futures | Yes | Yes | **ADMITTED** | Real protected TESTNET evidence + Governor approval remain required for LIVE eligibility |
| Interactive Brokers | Broker | Stocks, ETFs, equity/index options, futures, FX/forwards, bonds/funds, commodities, indices, warrants, supported crypto | Yes | Yes | **NOT_ADMITTED** | Instrument loader + paper gateway + order/reconciliation parity + asset-class risk tests + credential isolation |
| Polymarket | Prediction market | Binary outcomes / binary options, CLOB L2 | Yes | Yes | **NOT_ADMITTED** | Dedicated binary-outcome position model + wallet/credential isolation + CLOB reconciliation + PAPER/sandbox evidence |
| OKX | CEX | Spot, margin, perpetuals, futures, options, spreads, event contracts | Yes | Yes | **NOT_ADMITTED** | Multi-product instrument mapping + demo/test execution + options/event-contract risk and reconciliation |
| Deribit | CEX | Spot, perpetuals, dated futures, options, future/option combos | Yes | Yes | **NOT_ADMITTED** | Testnet admission + option-chain/Greeks evidence + combo/multi-leg reconciliation |
| Hyperliquid | DEX | Spot, perpetuals, HIP-3 builder perps, binary outcomes | Yes | Yes | **NOT_ADMITTED** | Wallet isolation + DEX reconciliation + product/quote mapping verification + testnet/sandbox proof where available |
| Bybit | CEX | Spot, perpetuals, futures, options | Yes | Yes | **NOT_ADMITTED** | Testnet admission + option Greeks/L2 validation + reconciliation |
| Coinbase | CEX | Spot, perpetuals, futures | Yes | Yes | **NOT_ADMITTED** | Sandbox/paper admission + reconciliation + risk parity |
| Kraken | CEX | Spot, tokenized assets, futures/perpetuals | Yes | Yes | **NOT_ADMITTED** | Demo admission + tokenized-asset classification + reconciliation |
| BitMEX | CEX | Spot, perpetuals, futures | Yes | Yes | **NOT_ADMITTED** | Test environment admission + reconciliation |
| Derive | DEX | Perpetuals, options | Yes | Yes | **NOT_ADMITTED** | Wallet isolation + options risk/Greeks + reconciliation |
| dYdX | DEX | Perpetuals | Yes | Yes | **NOT_ADMITTED** | Wallet/key isolation + chain/venue reconciliation + test evidence |
| Lighter | DEX | Spot, perpetuals | Yes | Yes | **NOT_ADMITTED** | Wallet isolation + reconciliation + test evidence |
| Betfair | Betting exchange | Exchange odds / betting instruments | Yes | Yes | **NOT_ADMITTED** | Separate regulated betting position semantics + account/order reconciliation; never reuse normal financial PnL assumptions blindly |
| AX Exchange | Exchange | Traditional derivatives / perpetual-style products | Yes | Yes | **NOT_ADMITTED** | Instrument/product verification + paper/test environment + reconciliation |
| Databento | Data provider | Equities, futures, options, spreads, FX; L1/L2/L3 market data | Yes | **No** | **NOT_ADMITTED** | Research-data ingestion/provenance gate only; execution must use another admitted provider |
| Tardis | Data provider | Multi-venue historical crypto trades/order books/derivatives/options | Yes | **No** | **NOT_ADMITTED** | Historical data integrity/provenance gate; useful for HFT/L2 research, never an execution route |
| Blockchain / DeFi data | Data provider | Chain and DeFi data | Yes | **No** | **NOT_ADMITTED** | Research-data integrity/provenance gate; no execution claim |

## Recommended admission order

### P0 — protect the existing path

Keep Binance as the only admitted execution venue until exact-head regression, real TESTNET evidence, reconciliation and Governor gates remain green. Do not weaken current runtime state ownership or LIVE defaults to accelerate expansion.

### P1 — Interactive Brokers: broad traditional-market reach

IBKR is the highest-leverage traditional-market adapter because one admission can unlock a large part of the requested universe: equities/ETFs, equity and index options, futures, FX/forwards, bonds/funds and related products. Admission should be built asset-class by asset-class behind one common broker adapter contract; a working stock order must not automatically admit options or futures.

Required proof before an asset class becomes admitted:
- exact instrument metadata/contract mapping;
- deterministic historical/PAPER execution parity;
- order state and fill reconciliation;
- fees, multipliers, currencies, margin and session semantics;
- market-hours/holiday handling where relevant;
- asset-class-specific risk limits and kill behavior;
- paper-gateway evidence before any live-broker credential path.

### P2 — Polymarket: prediction-market specialist

Polymarket is a real Nautilus execution integration for binary-outcome CLOB markets and exposes L2 market data. It should be a dedicated specialist surface, not shoehorned into spot/perpetual semantics.

Required proof:
- binary outcome/instrument semantics;
- price/probability and settlement accounting;
- wallet/API credential isolation;
- CLOB order/fill/cancel reconciliation;
- liquidity/spread/min-size controls;
- related-event/cross-market research validation;
- jurisdiction/account eligibility remains an external owner/environment gate.

### P3 — OKX + Deribit: options and deep crypto derivatives

These are the strongest near-term routes to broaden crypto products beyond the current Binance path. OKX adds options, spreads and event contracts; Deribit is especially valuable for options and combo structures.

Do not mark options admitted until MasterTrd has true option-chain/Greeks data, contract-expiry/settlement handling, multi-leg atomicity/reconciliation, and option-specific risk evidence.

### P4 — Hyperliquid and other DEX adapters

DEX venues add useful perp/spot/outcome surfaces but introduce wallet, chain, nonce/finality and venue-specific reconciliation risks. Each DEX needs an isolated signer/wallet boundary and must prove recovery/reconciliation behavior before admission.

### P5 — broader CEX redundancy

Coinbase, Kraken, Bybit, BitMEX and similar adapters are useful for venue redundancy, cross-venue research and eventually arbitrage. Cross-venue strategies remain blocked until synchronized tick/order-book evidence and execution/reconciliation are proven on every leg.

## Data-provider role

Databento and Tardis are intentionally separate from execution adapters.

- **Databento** is the strongest route in this matrix for high-quality traditional-market research data, including deeper book schemas where available.
- **Tardis** is useful for broad historical crypto tick/order-book data and can help satisfy specialist HFT/L2 research prerequisites.

A successful data-provider import can only prove data availability/integrity. It can never make an execution provider `ADMITTED` and can never satisfy LIVE authorization by itself.

## Strategy/product boundary

Strategy Universe recipes may target all cataloged markets, but their readiness remains independent of provider capability:

- `EXECUTABLE` means MasterTrd can express the strategy semantics with current primitives; it does **not** mean every listed market/provider is admitted.
- `SPECIALIST_DATA_REQUIRED` means real tick/L2/options evidence is still missing.
- `PROVIDER_REQUIRED` means the strategy concept is cataloged but the venue/runtime is not admitted.
- `PRIMITIVE_REQUIRED` means no exact current strategy primitive exists; MasterTrd must not substitute a vaguely similar signal.
- `EXPERIMENTAL` means it requires a separate validation contract before promotion-grade use.

This separation is deliberate: breadth is recorded immediately, but execution authority expands only when each wall is independently proven.

## Source-of-truth references

- Nautilus integrations: https://nautilustrader.io/docs/latest/integrations/
- Interactive Brokers: https://nautilustrader.io/docs/latest/integrations/interactive_brokers/
- Polymarket: https://nautilustrader.io/docs/latest/integrations/polymarket/
- OKX: https://nautilustrader.io/docs/latest/integrations/okx/
- Deribit: https://nautilustrader.io/docs/latest/integrations/deribit/
- Hyperliquid: https://nautilustrader.io/docs/latest/integrations/hyperliquid/
- Betfair: https://nautilustrader.io/docs/latest/integrations/betfair/
- Databento: https://nautilustrader.io/docs/latest/integrations/databento/
- Tardis: https://nautilustrader.io/docs/latest/integrations/tardis/

The executable registry is `src/mastertrd/market_capabilities.py`; this document explains the operational admission policy around it.
