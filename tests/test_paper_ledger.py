from decimal import Decimal

import pytest

from mastertrd.paper import PaperFill, PaperLedger, JsonPaperStateStore


def fill(event_id: str, side: str, qty: str, price: str, fee: str = "0") -> PaperFill:
    return PaperFill(
        event_id=event_id,
        symbol="BTCUSDT",
        side=side,
        quantity=Decimal(qty),
        price=Decimal(price),
        fee=Decimal(fee),
    )


def test_buy_opens_long_and_debits_cash_and_fee():
    ledger = PaperLedger.create(initial_cash=Decimal("10000"))
    assert ledger.apply(fill("e1", "BUY", "0.1", "50000", "5")) is True
    position = ledger.positions["BTCUSDT"]
    assert position.quantity == Decimal("0.1")
    assert position.average_price == Decimal("50000")
    assert ledger.cash == Decimal("4995")
    assert ledger.fees_paid == Decimal("5")


def test_duplicate_fill_event_is_idempotent():
    ledger = PaperLedger.create(initial_cash=Decimal("10000"))
    trade = fill("same-event", "BUY", "0.1", "50000")
    assert ledger.apply(trade) is True
    snapshot = ledger.to_dict()
    assert ledger.apply(trade) is False
    assert ledger.to_dict() == snapshot


def test_sell_closes_long_and_realizes_profit():
    ledger = PaperLedger.create(initial_cash=Decimal("10000"))
    ledger.apply(fill("e1", "BUY", "0.1", "50000"))
    ledger.apply(fill("e2", "SELL", "0.1", "51000", "1"))
    assert ledger.positions["BTCUSDT"].quantity == Decimal("0")
    assert ledger.realized_pnl == Decimal("100")
    assert ledger.cash == Decimal("10099")


def test_sell_can_open_short_and_buy_can_close_it():
    ledger = PaperLedger.create(initial_cash=Decimal("10000"))
    ledger.apply(fill("s1", "SELL", "0.2", "50000"))
    assert ledger.positions["BTCUSDT"].quantity == Decimal("-0.2")
    ledger.apply(fill("s2", "BUY", "0.2", "49000"))
    assert ledger.positions["BTCUSDT"].quantity == Decimal("0")
    assert ledger.realized_pnl == Decimal("200")
    assert ledger.cash == Decimal("10200")


def test_crossing_from_long_to_short_realizes_closed_piece_and_reprices_remainder():
    ledger = PaperLedger.create(initial_cash=Decimal("10000"))
    ledger.apply(fill("x1", "BUY", "1", "100"))
    ledger.apply(fill("x2", "SELL", "1.5", "110"))
    position = ledger.positions["BTCUSDT"]
    assert position.quantity == Decimal("-0.5")
    assert position.average_price == Decimal("110")
    assert ledger.realized_pnl == Decimal("10")


def test_invalid_fill_fails_closed():
    ledger = PaperLedger.create(initial_cash=Decimal("100"))
    with pytest.raises(ValueError, match="quantity and price must be positive"):
        ledger.apply(fill("bad", "BUY", "0", "10"))


def test_json_store_round_trip_preserves_decimal_state_and_event_ids(tmp_path):
    path = tmp_path / "paper-state.json"
    ledger = PaperLedger.create(initial_cash=Decimal("10000"))
    ledger.apply(fill("persisted", "BUY", "0.1", "50000", "2"))
    store = JsonPaperStateStore(path)
    store.save(ledger)

    loaded = store.load()
    assert loaded.to_dict() == ledger.to_dict()
    assert loaded.apply(fill("persisted", "BUY", "0.1", "50000", "2")) is False
