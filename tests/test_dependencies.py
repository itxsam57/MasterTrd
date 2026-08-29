from mastertrd.dependencies import DEPENDENCIES, dependency_availability


def test_dependency_registry_has_one_authoritative_execution_engine():
    execution = [d for d in DEPENDENCIES.values() if 'execution' in d.role]
    assert [d.key for d in execution] == ['nautilus']


def test_dependency_availability_returns_all_registered_keys():
    assert dependency_availability().keys() == DEPENDENCIES.keys()


def test_ccxt_is_data_fallback_not_execution():
    assert 'fallback' in DEPENDENCIES['ccxt'].role
