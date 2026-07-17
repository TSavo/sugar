from __future__ import annotations

import ast
from pathlib import Path

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.effect import SubscriptStoreRuntimeEffect
from sugar_lift_py_tests.floor import (
    BlockValue,
    OpaqueOpCallsite,
    ReturnValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file, lift_file_payload


def _site(source: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(source).body[0], "t.py")


def _build_statement(source: str):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    return build_node(
        ast.parse(source).body[0],
        filename="t.py",
        role=SugarRole.STATEMENT,
        ctx=ctx,
    )


def test_delete_names_unbinds_each_name_and_preserves_later_statements() -> None:
    assert compose_block(
        "    a = 1\n    b = 2\n    del a, b\n    return 3\n"
    ) == BlockValue((ReturnValue(TermValue(3)),))


def test_read_after_delete_reaches_the_unbound_name_floor_loudly() -> None:
    with pytest.raises(FactoryPanic) as raised:
        compose_block("    x = 1\n    del x\n    return x\n")

    info = raised.value.info.to_json()
    assert info["owner"] == "TemporalContext"
    assert info["observed"] == "x"
    assert info["requested"] == "value"


@pytest.mark.parametrize("source", ["del obj.attr", "del d[1:]"])
def test_non_name_delete_targets_stay_loud(source: str) -> None:
    with pytest.raises(FactoryPanic):
        _build_statement(source)


def test_delete_sugar_owns_only_flat_all_name_targets() -> None:
    from sugar_lift_py_tests.sugar.delete_sugar import DeleteSugar

    assert DeleteSugar.owns(_site("del a"))
    assert DeleteSugar.owns(_site("del a, b"))
    assert not DeleteSugar.owns(_site("del d[k]"))
    assert not DeleteSugar.owns(_site("del obj.attr"))

    built = _build_statement("del a, b")
    assert type(built.sugar).__name__ == "DeleteSugar"
    assert built.sugar.names == ("a", "b")
    assert built.sugar.walk_children() == ()


def test_subscript_delete_reuses_store_post_state_and_negative_index_floor() -> None:
    assert compose_block(
        "    xs = [1, 2, 3]\n    del xs[-1]\n    return xs[-1]\n"
    ) == BlockValue((ReturnValue(TermValue(2)),))

    built = _build_statement("del xs[-1]")
    assert type(built.sugar).__name__ == "SubscriptDeleteSugar"


def test_full_slice_delete_constructs_the_list_post_state() -> None:
    block = compose_block("    xs = [1, 2, 3]\n    del xs[:]\n    return len(xs)\n")
    returned = block.statements[0]
    assert isinstance(returned, ReturnValue)
    assert isinstance(returned.value, OpaqueOpCallsite)
    assert returned.value.computed == TermValue(0)

    built = _build_statement("del xs[:]")
    assert type(built.sugar).__name__ == "SubscriptDeleteSugar"


def test_runtime_slice_delete_is_a_named_store_effect() -> None:
    block = compose_block(
        "    xs = [1, 2, 3]\n    del xs[start:]\n    return 1\n",
        binds={"start": SymbolicValue(make_var("start"))},
    )

    effect = next(
        statement for statement in block.statements if isinstance(statement, Incomplete)
    )
    assert isinstance(effect.effect, SubscriptStoreRuntimeEffect)
    assert "runtime slice bounds" in effect.reason


def test_heterogeneous_multi_delete_remains_loud() -> None:
    with pytest.raises(FactoryPanic):
        _build_statement("del xs[:], name")


def test_full_datetime_delete_is_owned_and_later_assertions_now_lift(
    cpython_311_datetime_path,
) -> None:
    path = cpython_311_datetime_path
    source = path.read_text(encoding="utf-8")
    assert len(source.splitlines()) == 2882

    report, gaps = audit_lift_file(source, str(path))
    delete_row = next(
        row
        for row in report.factory_audits
        if "Delete" in str(row.get("observed"))
        and "datetime.py:2203:" in str(row.get("blame", ""))
    )
    # datetime.__repr__ L[-1] deletes precede the fold/tzinfo asserts.
    assert delete_row["selected"] == "SubscriptDeleteSugar"
    assert gaps == []
    # Full artifact now lifts without panic (#4104 stable zero).
    lift_file_payload(source, str(path))

    payload = report.to_rpc()
    assertions = account_lift_coverage(
        census_source(source, file=str(path)), payload
    ).to_json()["assertions"]
    assert assertions["stated"] == 45
    assert assertions["lifted_cited"] == 45
    assert assertions["refused_loud"] == 0
    assert assertions["silently_unaccounted"] == 0
    assert {2212, 2215} <= {locus["line"] for locus in assertions["lifted_loci"]}
