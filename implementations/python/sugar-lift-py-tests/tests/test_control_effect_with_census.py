from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/control_effect_recensus.py"


def _module():
    spec = importlib.util.spec_from_file_location("control_effect_recensus", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_with_census_emits_the_complete_closed_vocabulary_and_conserves():
    from sugar_source_tree.panic import WithConstructionGapKind

    module = _module()
    partition = module._with_census_partition(
        Counter(
            {
                "derived-contract": 2,
                "gap:runtime-selected": 3,
                "gap:force-floor": 5,
            }
        ),
        Counter({"site:with-item": 10}),
    )

    assert tuple(partition["typed_gaps"]) == tuple(
        member.value for member in WithConstructionGapKind
    )
    assert partition["typed_gap_kinds_total"] == len(WithConstructionGapKind)
    assert partition["typed_gap_kinds_total"] == 39
    assert partition["accounted"] == partition["with_items_total"] == 10
    assert partition["unrecognized_resolution_kinds"] == {}
    assert partition["reconciliation"] == "10 = 2 constructed + 8 typed gaps"
    assert partition["conserves"] is True


def test_with_census_refuses_an_escape_bucket():
    module = _module()

    with pytest.raises(ValueError, match="outside its closed vocabulary"):
        module._with_census_partition(
            Counter({"derived-contract": 1, "unclassified": 1}),
            Counter({"site:with-item": 2}),
        )


def test_with_census_refuses_a_nonconserving_denominator():
    module = _module()

    with pytest.raises(ValueError, match="does not conserve"):
        module._with_census_partition(
            Counter({"derived-contract": 1}),
            Counter({"site:with-item": 2}),
        )


def test_unknown_wire_kind_maps_to_the_typed_sentinel():
    from types import SimpleNamespace

    module = _module()

    assert module._cm_resolution_bucket(SimpleNamespace(kind="future-kind")) == (
        "gap:unrecognized-resolution-kind"
    )


def test_with_census_emits_preserved_unknown_wire_kinds_beside_sentinel():
    module = _module()

    partition = module._with_census_partition(
        Counter({"gap:unrecognized-resolution-kind": 3}),
        Counter({"site:with-item": 3}),
        Counter({"future-kind": 2, "another-future-kind": 1}),
    )

    assert partition["unrecognized_resolution_kinds"] == {
        "another-future-kind": 1,
        "future-kind": 2,
    }


def test_with_census_refuses_sentinel_without_preserved_unknown_kinds():
    module = _module()

    with pytest.raises(ValueError, match="lacks preserved resolution kinds"):
        module._with_census_partition(
            Counter({"gap:unrecognized-resolution-kind": 1}),
            Counter({"site:with-item": 1}),
        )


def test_driver_refuses_wrong_pandas_manifest_before_source_selection(
    tmp_path, monkeypatch, capsys
):
    from sugar_lift_py_tests import lift_rpc

    corpus = tmp_path / "pandas"
    corpus.mkdir()
    (corpus / "one.py").write_text("with manager():\n    pass\n", encoding="utf-8")

    def source_selection_must_not_start(_root):
        raise AssertionError("source selection ran before corpus authentication")

    monkeypatch.setattr(
        lift_rpc,
        "provisional_contract_refs_from_demands",
        source_selection_must_not_start,
    )
    module = _module()
    saved = sys.argv
    sys.argv = [
        "control_effect_recensus.py",
        str(corpus),
        "--corpus-distribution",
        "pandas",
        "--corpus-version",
        "3.0.3",
        "--out-dir",
        str(tmp_path / "out"),
    ]
    try:
        result = module.main()
    finally:
        sys.argv = saved

    captured = capsys.readouterr()
    assert result == 2
    assert "corpus aggregate hash mismatch" in captured.err
    assert (
        "required "
        "bbb70a76f4032eda3362102c8bd872ca769b6f8143a91f60a36374fa1066b76c"
    ) in captured.err
    assert not (tmp_path / "out").exists()


def test_declared_pandas_corpus_accepts_both_known_good_axes():
    from types import SimpleNamespace

    module = _module()
    module._authenticate_declared_pandas_corpus(
        SimpleNamespace(aggregate_hash=module._PANDAS_3_0_3_AGGREGATE_HASH),
        module._PANDAS_3_0_3_MANIFEST_SHAPE_CID,
    )


def test_content_drift_refuses_even_when_manifest_shape_is_unchanged():
    from types import SimpleNamespace

    module = _module()
    with pytest.raises(ValueError, match="corpus aggregate hash mismatch"):
        module._authenticate_declared_pandas_corpus(
            SimpleNamespace(aggregate_hash="0" * 64),
            module._PANDAS_3_0_3_MANIFEST_SHAPE_CID,
        )


def test_shape_drift_is_a_separately_named_refusal():
    from types import SimpleNamespace

    module = _module()
    with pytest.raises(ValueError, match="corpus manifest shape CID mismatch"):
        module._authenticate_declared_pandas_corpus(
            SimpleNamespace(aggregate_hash=module._PANDAS_3_0_3_AGGREGATE_HASH),
            "sha256:" + "0" * 64,
        )
