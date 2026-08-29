import pytest

from mastertrd.holdout import HoldoutManifest, chronological_holdout


def test_hidden_holdout_is_strict_chronological_tail_without_overlap():
    values = tuple(range(100))
    research, hidden, manifest = chronological_holdout(values, hidden_fraction=0.20)

    assert research == tuple(range(80))
    assert hidden == tuple(range(80, 100))
    assert research[-1] < hidden[0]
    assert manifest.total_count == 100
    assert manifest.research_count == 80
    assert manifest.hidden_count == 20
    assert manifest.hidden_start == 80


def test_manifest_hash_is_deterministic_and_does_not_include_hidden_values():
    _, _, first = chronological_holdout(tuple(range(50)), hidden_fraction=0.20, dataset_hash="dataset-v1")
    changed_hidden = tuple(range(40)) + tuple(range(1000, 1010))
    _, _, second = chronological_holdout(changed_hidden, hidden_fraction=0.20, dataset_hash="dataset-v1")

    assert first.manifest_hash == second.manifest_hash
    assert "1000" not in first.canonical_json


def test_manifest_changes_when_dataset_identity_or_boundary_changes():
    _, _, a = chronological_holdout(tuple(range(50)), hidden_fraction=0.20, dataset_hash="dataset-a")
    _, _, b = chronological_holdout(tuple(range(50)), hidden_fraction=0.20, dataset_hash="dataset-b")
    _, _, c = chronological_holdout(tuple(range(50)), hidden_fraction=0.30, dataset_hash="dataset-a")

    assert a.manifest_hash != b.manifest_hash
    assert a.manifest_hash != c.manifest_hash


def test_holdout_requires_enough_research_and_hidden_observations():
    with pytest.raises(ValueError, match="hidden_fraction"):
        chronological_holdout(tuple(range(20)), hidden_fraction=0)
    with pytest.raises(ValueError, match="hidden_fraction"):
        chronological_holdout(tuple(range(20)), hidden_fraction=1)
    with pytest.raises(ValueError, match="not enough observations"):
        chronological_holdout((1, 2, 3), hidden_fraction=0.20, min_research=3, min_hidden=1)


def test_manifest_is_metadata_only():
    values = tuple(range(25))
    _, _, manifest = chronological_holdout(values, hidden_fraction=0.20, dataset_hash="abc")

    assert isinstance(manifest, HoldoutManifest)
    assert not hasattr(manifest, "hidden_values")
    assert not hasattr(manifest, "research_values")
