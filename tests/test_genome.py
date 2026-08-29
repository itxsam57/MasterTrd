from mastertrd.genome import StrategyGenome


def make_genome(entry):
    return StrategyGenome(
        strategy_id="S-TEST",
        family="trend",
        style="swing",
        instruments=("BTCUSDT",),
        timeframe="1h",
        entry=entry,
        exit={"type": "atr_stop", "multiple": 2.0},
        risk={"fraction": 0.005},
    )


def test_hash_is_deterministic_for_mapping_order():
    a = make_genome({"op": "and", "left": {"b": 2, "a": 1}, "right": True})
    b = make_genome({"right": True, "left": {"a": 1, "b": 2}, "op": "and"})
    assert a.genome_hash == b.genome_hash


def test_hash_changes_with_strategy_semantics():
    assert make_genome({"rsi_gt": 50}).genome_hash != make_genome({"rsi_gt": 55}).genome_hash
