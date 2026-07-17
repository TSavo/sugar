"""ForSugar: for x in it: body threads over py.iter_elem(it).

Simple-Name target, empty orelse only. Tuple targets and for/else stay loud gaps.
"""

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
from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    ReturnValue,
    SymbolicValue,
)
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.idd.sugar_witness_instruments import (
    DEFAULT_SUGAR_WITNESS_SEEDS,
)
from sugar_lift_py_tests.sugar.for_sugar import ForSugar
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _site(source: str):
    node = ast.parse(source).body[0]
    return SourceFragment.from_node(node, "t.py")


def test_for_body_threads_and_binds_iter_elem_coordinate() -> None:
    """(1) Body contributes; loop target is py.iter_elem(iterable)."""
    block = compose_block(
        "    for x in z:\n" "        return x\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    assert isinstance(block, BlockValue)
    # BlockValue splices the for-body return -- no wrapper residue.
    assert len(block.statements) == 1
    ret = block.statements[0]
    assert isinstance(ret, ReturnValue)
    value = ret.value
    assert isinstance(value, CallSiteValue)
    assert value.target_name == "iter_elem"
    assert value.term == ctor("py.iter_elem", [make_var("z")])


def test_iterable_discriminates_the_iter_elem_coordinate() -> None:
    """(2) Different iterable produces a different element coordinate."""
    for_z = compose_block(
        "    for x in z:\n" "        return x\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    for_w = compose_block(
        "    for x in w:\n" "        return x\n",
        binds={"w": SymbolicValue(make_var("w"))},
    )
    term_z = for_z.statements[0].value.term
    term_w = for_w.statements[0].value.term
    assert term_z == ctor("py.iter_elem", [make_var("z")])
    assert term_w == ctor("py.iter_elem", [make_var("w")])
    assert term_z != term_w


def test_owns_simple_name_for_not_tuple_while_or_expr() -> None:
    """(3) owns simple-Name For; not tuple target, While, or Assign."""
    assert ForSugar.owns(_site("for x in y:\n    pass\n")) is True
    assert ForSugar.owns(_site("for a, b in y:\n    pass\n")) is False
    assert ForSugar.owns(_site("while y:\n    pass\n")) is False
    assert ForSugar.owns(_site("x = 1\n")) is False
    # Non-empty else: not owned this arm.
    assert ForSugar.owns(_site("for x in y:\n    pass\nelse:\n    pass\n")) is False

    catalog = default_catalog()
    simple = _site("for x in y:\n    pass\n")
    tuple_target = _site("for a, b in y:\n    pass\n")
    assert any(
        c.name == "ForSugar"
        for c in catalog.candidates_for(SugarRole.STATEMENT, simple)
    )
    assert [
        candidate.name
        for candidate in catalog.candidates_for(SugarRole.STATEMENT, tuple_target)
    ] == ["TupleForSugar"]


def test_three_name_tuple_target_uses_flat_tuple_owner_from_4288() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("for a, b, c in y:\n    pass\n").body[0]
    built = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert type(built.sugar).__name__ == "TupleForSugar"


def test_for_else_uses_break_projection_owner() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("for x in y:\n    pass\nelse:\n    pass\n").body[0]
    built = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert type(built.sugar).__name__ == "ForElseSugar"


def test_continue_loop_does_not_curry_iteration_local_assigned_before_use() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(
        "for item in items:\n"
        "    if item == 0:\n"
        "        continue\n"
        "    local = item + 1\n"
        "    assert local > item\n"
    ).body[0]
    built = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)

    assert isinstance(built.sugar, ForSugar)
    assert built.sugar.carried == ()


def test_continue_loop_curries_only_prior_value_read_before_assignment() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(
        "for item in items:\n"
        "    local = item + 1\n"
        "    if item == 0:\n"
        "        continue\n"
        "    total += local\n"
    ).body[0]
    built = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)

    assert isinstance(built.sugar, ForSugar)
    assert built.sugar.carried == ("total",)


def test_comprehension_target_is_not_outer_loop_carried_state() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(
        "for field in fields:\n"
        "    if field == 'weekday':\n"
        "        continue\n"
        "    expected = [getattr(x, field) for x in values]\n"
    ).body[0]
    built = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)

    assert isinstance(built.sugar, ForSugar)
    assert built.sugar.carried == ()


def test_for_iteration_local_witness_refutes_wrong_twin(tmp_path: Path) -> None:
    seed = next(
        item for item in DEFAULT_SUGAR_WITNESS_SEEDS if item.name == "for_return"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "for-local-truthful", seed.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / "for-local-lying", seed.lying.source
    )

    assert "ForSugar" in truthful.selected_sugars
    assert truthful.verdict == "sat"
    assert "ForSugar" in lying.selected_sugars
    assert lying.verdict == "unsat"


def test_continue_loop_with_unclassified_attribute_mutation_stays_loud() -> None:
    with pytest.raises(FactoryPanic) as raised:
        compose_block(
            "    for item in items:\n"
            "        if item == 0:\n"
            "            continue\n"
            "        holder.value = item\n",
            binds={
                "items": SymbolicValue(make_var("items")),
                "holder": SymbolicValue(make_var("holder")),
            },
        )

    assert raised.value.info.owner == "ForSugar"
    assert raised.value.info.observed == "nonlocal mutation"
    assert raised.value.info.requested == "classifiable loop-carried local state"
