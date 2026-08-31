import pytest

from mastertrd.data.orderbook import OrderBookDataset, OrderBookEvent, OrderBookLevel, OrderBookTrade


def level(price: float, size: float = 1.0) -> OrderBookLevel:
    return OrderBookLevel(price=price, size=size)


def event(
    sequence: int,
    exchange_timestamp_ns: int,
    *,
    bid: float = 100.0,
    ask: float = 100.2,
    local_timestamp_ns: int | None = None,
    trades: tuple[OrderBookTrade, ...] = (),
) -> OrderBookEvent:
    if local_timestamp_ns is None:
        local_timestamp_ns = exchange_timestamp_ns + 100
    return OrderBookEvent(
        sequence=sequence,
        exchange_timestamp_ns=exchange_timestamp_ns,
        local_timestamp_ns=local_timestamp_ns,
        bids=(level(bid),),
        asks=(level(ask),),
        trades=trades,
    )


def dataset(*events: OrderBookEvent, synthetic: bool = False) -> OrderBookDataset:
    return OrderBookDataset(
        venue="BINANCE",
        instrument="BTCUSDT",
        source_id="historical-l2-fixture",
        events=events,
        synthetic=synthetic,
    )


def test_orderbook_dataset_has_content_bound_deterministic_hash():
    first = dataset(event(10, 1_000), event(11, 2_000, bid=100.1, ask=100.3))
    second = dataset(event(10, 1_000), event(11, 2_000, bid=100.1, ask=100.3))
    changed = dataset(event(10, 1_000), event(11, 2_000, bid=100.1, ask=100.4))

    assert first.dataset_hash == second.dataset_hash
    assert len(first.dataset_hash) == 64
    assert first.dataset_hash != changed.dataset_hash


def test_missing_orderbook_sequence_number_fails_closed():
    with pytest.raises(ValueError, match="sequence"):
        dataset(event(10, 1_000), event(12, 2_000))


def test_crossed_orderbook_fails_closed():
    with pytest.raises(ValueError, match="crossed"):
        dataset(event(10, 1_000, bid=100.3, ask=100.2))


def test_negative_depth_size_fails_closed():
    with pytest.raises(ValueError, match="size"):
        OrderBookEvent(
            sequence=10,
            exchange_timestamp_ns=1_000,
            local_timestamp_ns=1_100,
            bids=(level(100.0, -1.0),),
            asks=(level(100.2),),
        )


def test_orderbook_clock_integrity_fails_closed():
    with pytest.raises(ValueError, match="local timestamp"):
        dataset(event(10, 1_000, local_timestamp_ns=999))

    with pytest.raises(ValueError, match="timestamp"):
        dataset(event(10, 2_000), event(11, 1_000))


def test_orderbook_requires_two_sided_depth_and_positive_trade_fields():
    with pytest.raises(ValueError, match="two-sided"):
        OrderBookEvent(
            sequence=10,
            exchange_timestamp_ns=1_000,
            local_timestamp_ns=1_100,
            bids=(),
            asks=(level(100.2),),
        )

    with pytest.raises(ValueError, match="trade"):
        OrderBookTrade(side="BUY", price=100.2, size=-1.0)
