"""WithSugar: with cm as y substitutes the frozen cm coordinate for y.

Single-item synchronous With only. Multi-item and AsyncWith stay loud gaps.
"""

from __future__ import annotations

import ast

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    ReturnValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file
from sugar_lift_py_tests.sugar.with_sugar import WithSugar


def _site(source: str):
    node = ast.parse(source).body[0]
    return SourceFragment.from_node(node, "t.py")


def test_with_body_threads_and_binds_enter_coordinate() -> None:
    """(1) Body contributes; as-target is call:__enter__(cm)."""
    block = compose_block(
        "    with z as g:\n" "        return g\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    assert isinstance(block, BlockValue)
    # BlockValue splices the with-body return -- no wrapper residue.
    assert len(block.statements) == 1
    ret = block.statements[0]
    assert isinstance(ret, ReturnValue)
    value = ret.value
    assert isinstance(value, CallSiteValue)
    assert value.target_name == "__enter__"
    assert value.term == ctor("call:__enter__", [make_var("z")])


def test_context_expression_discriminates_the_enter_coordinate() -> None:
    """(2) Different cm produces a different enter coordinate."""
    with_z = compose_block(
        "    with z as g:\n" "        return g\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    with_w = compose_block(
        "    with w as g:\n" "        return g\n",
        binds={"w": SymbolicValue(make_var("w"))},
    )
    term_z = with_z.statements[0].value.term
    term_w = with_w.statements[0].value.term
    assert term_z == ctor("call:__enter__", [make_var("z")])
    assert term_w == ctor("call:__enter__", [make_var("w")])
    assert term_z != term_w


def test_owns_single_item_not_multi_or_plain_expr() -> None:
    """(3) owns single-item with; multi-item stays unowned; not Expr."""
    assert WithSugar.owns(_site("with cm as y:\n    pass\n")) is True
    assert WithSugar.owns(_site("with cm:\n    pass\n")) is True
    assert WithSugar.owns(_site("with a, b:\n    pass\n")) is True
    assert WithSugar.owns(_site("with a as x, b as y:\n    pass\n")) is True
    assert WithSugar.owns(_site("with a as (x, y):\n    pass\n")) is False
    assert WithSugar.owns(_site("x = 1\n")) is False

    catalog = default_catalog()
    single = _site("with cm as y:\n    pass\n")
    multi = _site("with a, b:\n    pass\n")
    assert any(
        c.name == "WithSugar"
        for c in catalog.candidates_for(SugarRole.STATEMENT, single)
    )
    assert [
        candidate.name
        for candidate in catalog.candidates_for(SugarRole.STATEMENT, multi)
    ] == ["WithSugar"]


def test_multi_item_with_is_a_loud_factory_gap() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("with a, b:\n    pass\n").body[0]
    with pytest.raises(FactoryPanic) as raised:
        build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert raised.value.info.observed == "With"


def test_with_without_as_still_reduces_context_and_body() -> None:
    # Context expr is not dropped when there is no as-target.
    block = compose_block(
        "    with z:\n" "        return 1\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    ret = block.statements[0]
    assert isinstance(ret, ReturnValue)
    from sugar_lift_py_tests.floor import TermValue

    assert ret.value == TermValue(1)


def test_callsite_context_manager_substitutes_coordinate_for_as_name() -> None:
    opaque = CallSiteValue(
        target_name="manager",
        arg_values=(),
        parameters=(),
        term=ctor("call:manager", []),
        body=None,
    )

    outcome = compose_block(
        "    with manager as entered:\n" "        return entered\n",
        binds={"manager": opaque},
    )

    returned = outcome.statements[0]
    assert isinstance(returned, ReturnValue)
    assert returned.value is not opaque
    assert returned.value.target_name == "__enter__"
    assert "call:__enter__" in repr(returned.value)
    assert repr(returned.value.term) != repr(opaque.term)


def test_enter_result_twin_cannot_inherit_bare_manager_coordinate() -> None:
    manager = CallSiteValue(
        target_name="transaction",
        arg_values=(),
        parameters=(),
        term=ctor("call:transaction", []),
        body=None,
    )
    block = compose_block(
        "    with manager as cursor:\n" "        return cursor\n",
        binds={"manager": manager},
    )

    cursor = block.statements[0].value
    assert cursor.term == ctor("call:__enter__", [manager.term])
    assert cursor.term != manager.term


def test_with_as_binding_survives_into_the_continuing_scope() -> None:
    manager = CallSiteValue(
        target_name="manager",
        arg_values=(),
        parameters=(),
        term=ctor("call:manager", []),
        body=None,
    )

    block = compose_block(
        "    with manager as entered:\n" "        pass\n" "    return entered\n",
        binds={"manager": manager},
    )

    returned = block.statements[-1]
    assert isinstance(returned, ReturnValue)
    assert returned.value.target_name == "__enter__"
    assert returned.value.term == ctor("call:__enter__", [manager.term])


def test_with_body_rebind_wins_over_the_entered_value_after_exit() -> None:
    manager = CallSiteValue(
        target_name="manager",
        arg_values=(),
        parameters=(),
        term=ctor("call:manager", []),
        body=None,
    )

    block = compose_block(
        "    with manager as entered:\n" "        entered = 9\n" "    return entered\n",
        binds={"manager": manager},
    )

    returned = block.statements[-1]
    assert isinstance(returned, ReturnValue)
    assert returned.value == TermValue(9)


def test_continuing_with_as_binding_conserves_assertion_mass() -> None:
    source = (
        "def A(z):\n"
        "    with z.lock() as entered:\n"
        "        pass\n"
        "    entered\n"
        "    return 1\n"
        "\n"
        "def test_a():\n"
        "    assert A(5) == 1\n"
    )

    payload, gaps = audit_lift_file(source, "with_binding.py")
    rpc = payload.to_rpc()
    assertions = account_lift_coverage(
        census_source(source, file="with_binding.py"), rpc
    ).to_json()["assertions"]

    assert gaps == []
    assert rpc["effects"] == []
    assert assertions["stated"] == 1
    assert assertions["lifted_cited"] == 1
    assert assertions["silently_unaccounted"] == 0


def test_continuing_with_body_projects_constructed_binding() -> None:
    manager = CallSiteValue(
        target_name="manager",
        arg_values=(),
        parameters=(),
        term=ctor("call:manager", []),
        body=None,
    )

    block = compose_block(
        "    with manager:\n" "        result = 5\n" "    return result\n",
        binds={"manager": manager},
    )

    assert isinstance(block.statements[-1], ReturnValue)
    assert block.statements[-1].value == TermValue(5)


def test_continuing_with_body_binds_after_nested_subscript_store_effect() -> None:
    """#4978: nested `receiver[i][...] = v` is red store testimony, not a halt.

    Live locus: numpy test_nditer assigns `res` after `nditer.operands[-1][...] = 0`
    inside with; NameSugar must see `res` after the with exits.
    """
    manager = CallSiteValue(
        target_name="manager",
        arg_values=(),
        parameters=(),
        term=ctor("call:manager", []),
        body=None,
    )

    block = compose_block(
        "    with manager:\n"
        "        manager.operands[-1][...] = 0\n"
        "        res = 5\n"
        "    return res\n",
        binds={"manager": manager},
    )

    assert isinstance(block.statements[-1], ReturnValue)
    assert block.statements[-1].value == TermValue(5)
    from sugar_lift_py_tests.outcome import Incomplete

    assert any(isinstance(entry, Incomplete) for entry in block.statements)


def test_continuing_with_body_does_not_invent_missing_binding() -> None:
    manager = CallSiteValue(
        target_name="manager",
        arg_values=(),
        parameters=(),
        term=ctor("call:manager", []),
        body=None,
    )

    with pytest.raises(FactoryPanic) as raised:
        compose_block(
            "    with manager:\n" "        pass\n" "    return result\n",
            binds={"manager": manager},
        )

    assert raised.value.info.owner == "TemporalContext"
    assert raised.value.info.observed == "result"
    assert raised.value.info.requested == "value"


def test_unresolved_exit_contract_keeps_raise_carrying_body_loud() -> None:
    manager = CallSiteValue(
        target_name="manager",
        arg_values=(),
        parameters=(),
        term=ctor("call:manager", []),
        body=None,
    )
    with pytest.raises(FactoryPanic, match="__exit__"):
        compose_block(
            "    with manager:\n" "        raise ValueError('boom')\n",
            binds={"manager": manager},
        )


def test_complex_as_target_constructs_and_runtime_enter_is_a_named_effect() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("with cm as (a, b):\n    pass\n").body[0]
    built = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert type(built.sugar).__name__ == "WithSugar"

    manager = CallSiteValue(
        target_name="manager",
        arg_values=(),
        parameters=(),
        term=ctor("call:manager", []),
        body=None,
    )
    outcome = compose_block(
        "    with cm as (a, b):\n        return a\n",
        binds={"cm": manager},
    )
    effect = outcome.statements[0]
    assert type(effect.effect).__name__ == "ContextManagerUnpackRuntimeEffect"
