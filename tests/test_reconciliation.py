from decimal import Decimal

from mastertrd.reconciliation import ExecutionState, Reconciler


def state(
    *,
    account_id: str = "acct-1",
    btc: str = "1.0",
    orders: frozenset[str] = frozenset({"order-1"}),
    usdt: str = "1000",
) -> ExecutionState:
    return ExecutionState(
        account_id=account_id,
        positions={"BTCUSDT": Decimal(btc)},
        open_order_ids=orders,
        balances={"USDT": Decimal(usdt)},
    )


def test_reconciler_accepts_matching_engine_and_venue_state():
    result = Reconciler().reconcile(state(), state())

    assert result.ok is True
    assert result.mismatches == ()


def test_reconciler_detects_position_order_account_and_balance_mismatch():
    engine = state()
    venue = state(
        account_id="acct-2",
        btc="0.5",
        orders=frozenset({"order-2"}),
        usdt="900",
    )

    result = Reconciler().reconcile(engine, venue)

    assert result.ok is False
    assert set(result.mismatches) == {
        "account_id",
        "position:BTCUSDT",
        "orders",
        "balance:USDT",
    }


def test_reconciler_uses_explicit_numeric_tolerance_only():
    engine = state(btc="1.000000001", usdt="1000.000000001")
    venue = state(btc="1.0", usdt="1000")

    assert Reconciler(tolerance=Decimal("0.00000001")).reconcile(engine, venue).ok is True
    assert Reconciler(tolerance=Decimal("0")).reconcile(engine, venue).ok is False
