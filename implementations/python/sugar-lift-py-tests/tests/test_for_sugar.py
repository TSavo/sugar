"""ForSugar: for x in it: body threads over py.iter_elem(it).

Simple-Name target, empty orelse only. Tuple targets and for/else stay loud gaps.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.effect import GetattrRuntimeEffect
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    ObjectField,
    ObjectValue,
    ReturnValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.idd.sugar_witness_instruments import (
    DEFAULT_SUGAR_WITNESS_SEEDS,
)
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar.for_sugar import ForSugar
from sugar_lift_py_tests.sugar.loop_control_scope_sugar import LoopControlScopeSugar
from sugar_lift_py_tests.temporal import TemporalContext
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


def test_append_rebind_is_loop_carried_state() -> None:
    loop = _site(
        "for item in items:\n" "    if item:\n" "        results.append(item)\n"
    )

    classification = LoopControlScopeSugar.classify(
        loop, target_name=loop.for_target_name()
    )
    built = ForSugar.new(
        loop, FactoryBuildContext(filename="t.py", catalog=default_catalog())
    )

    assert classification.carried_names == ("results",)
    assert built.carried == ("results",)
    assert built.curried is True


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


def test_bound_finite_list_unfolds_its_constructed_elements() -> None:
    block = compose_block(
        "    names = ['x']\n" "    for name in names:\n" "        return name\n"
    )

    returned = next(
        statement
        for statement in block.statements
        if isinstance(statement, ReturnValue)
    )
    assert returned.value == StringValue("x")


def test_nonempty_static_for_exports_final_constructed_binding() -> None:
    block = compose_block(
        "    for unit in ['ms', 'us', 'ns']:\n" "        x = unit\n" "    return x\n"
    )

    returned = next(
        statement
        for statement in block.statements
        if isinstance(statement, ReturnValue)
    )
    assert returned.value == StringValue("ns")


def test_empty_static_for_does_not_invent_post_binding() -> None:
    with pytest.raises(FactoryPanic) as caught:
        compose_block("    for unit in []:\n        x = unit\n    return x\n")

    assert caught.value.info.owner == "TemporalContext"
    assert caught.value.info.observed == "x"


def test_static_for_post_binding_witness_truthful_sat_lying_unsat(
    tmp_path: Path,
) -> None:
    prefix = (
        "def A():\n"
        "    for unit in ['ms', 'us', 'ns']:\n"
        "        x = unit\n"
        "    return x\n"
        "\n"
    )
    truthful = run_source_through_real_solver(
        tmp_path / "truthful",
        prefix + "def test_a():\n    assert A() == 'ns'\n",
    )
    lying = run_source_through_real_solver(
        tmp_path / "lying",
        prefix + "def test_a():\n    assert A() == 'us'\n",
    )

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"


def test_symbolic_iterable_dynamic_getattr_remains_authenticated_runtime() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    body = ctx.build_body(
        ast.parse("for name in names:\n" "    return getattr(1, name)\n").body[0],
        SugarRole.STATEMENT,
    )
    reduce_ctx = ReduceContext(
        temporal=TemporalContext.empty().bind_value(
            "names", SymbolicValue(make_var("names"))
        )
    )

    outcome = body.reduce(reduce_ctx)

    assert isinstance(outcome, Complete)
    effect_statement = outcome.value.statements[0]
    assert isinstance(effect_statement, Incomplete)
    assert isinstance(effect_statement.effect, GetattrRuntimeEffect)
    assert effect_statement.effect.witness.operand == ctor(
        "py.iter_elem", [make_var("names")]
    )


def test_ground_tuple_dynamic_getattr_stays_loud_at_owner() -> None:
    from sugar_lift_py_tests.factory import FactoryPanic
    from sugar_lift_py_tests.floor import TupleValue

    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    body = ctx.build_body(
        ast.parse("getattr(obj, name)", mode="eval").body,
        SugarRole.TERM,
    )
    names = TupleValue((StringValue("a"), StringValue("b")))
    reduce_ctx = ReduceContext(
        temporal=(
            TemporalContext.empty()
            .bind_value("obj", SymbolicValue(make_var("obj")))
            .bind_value(
                "name",
                SymbolicValue(ctor("py.iter_elem", [names.to_term(owner="test")])),
            )
        )
    )

    with pytest.raises(FactoryPanic) as raised:
        body.reduce(reduce_ctx)

    assert raised.value.info.owner == "GetattrBuiltinSugar"
    assert raised.value.info.requested == "statically enumerated attribute name"


def test_for_consumes_constructed_finite_generator_members() -> None:
    block = compose_block(
        "    for value in (getattr(obj, name) for name in ('a', 'b')):\n"
        "        return value\n",
        binds={
            "obj": ObjectValue(
                class_name="Box",
                fields=(
                    ObjectField(name="a", value=TermValue(1)),
                    ObjectField(name="b", value=TermValue(2)),
                ),
            )
        },
    )

    assert [
        statement.value
        for statement in block.statements
        if isinstance(statement, ReturnValue)
    ] == [TermValue(1), TermValue(2)]


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


def test_bound_finite_getattr_witness_refutes_wrong_twin(tmp_path: Path) -> None:
    seed = next(
        item
        for item in DEFAULT_SUGAR_WITNESS_SEEDS
        if item.name == "for_bound_finite_getattr_return"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "bound-finite-getattr-truthful", seed.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / "bound-finite-getattr-lying", seed.lying.source
    )

    assert "ForSugar" in truthful.selected_sugars
    assert "GetattrBuiltinSugar" in truthful.selected_sugars
    assert truthful.verdict == "sat"
    assert "ForSugar" in lying.selected_sugars
    assert "GetattrBuiltinSugar" in lying.selected_sugars
    assert lying.verdict == "unsat"


def test_continue_loop_with_unclassified_attribute_mutation_stays_loud() -> None:
    with pytest.raises(FactoryPanic) as raised:
        compose_block(
            "    for item in items:\n"
            "        if item == 0:\n"
            "            continue\n"
            "        factory().value = item\n",
            binds={
                "items": SymbolicValue(make_var("items")),
            },
        )

    assert raised.value.info.owner == "ForSugar"
    assert raised.value.info.observed == "nonlocal mutation"
    assert raised.value.info.requested == "classifiable loop-carried local state"


def test_loop_mutation_recognizer_constructs_structural_coordinates() -> None:
    attribute = _site(
        "for item in items:\n"
        "    if item:\n"
        "        continue\n"
        "    holder.value = item\n"
    )
    local_nested = _site(
        "for item in items:\n"
        "    if item:\n"
        "        continue\n"
        "    value = table[item]\n"
        "    value[item][item] = 1\n"
    )
    opaque = _site(
        "for item in items:\n"
        "    if item:\n"
        "        continue\n"
        "    factory().value = item\n"
    )

    attribute_scope = LoopControlScopeSugar.classify(
        attribute, target_name=attribute.for_target_name()
    )
    local_scope = LoopControlScopeSugar.classify(
        local_nested, target_name=local_nested.for_target_name()
    )
    opaque_scope = LoopControlScopeSugar.classify(
        opaque, target_name=opaque.for_target_name()
    )

    assert tuple(
        (binding.coordinate, binding.requires_input)
        for binding in attribute_scope.mutation_bindings
    ) == (("holder.value", True),)
    assert tuple(
        (binding.coordinate, binding.requires_input)
        for binding in local_scope.mutation_bindings
    ) == (("value", False),)
    assert attribute_scope.has_unclassified_mutation is False
    assert local_scope.has_unclassified_mutation is False
    assert opaque_scope.has_unclassified_mutation is True


def test_curried_for_projects_recognized_attribute_mutation() -> None:
    site = _site(
        "for item in items:\n"
        "    if item:\n"
        "        continue\n"
        "    holder.value = item\n"
    )
    factory_ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    body = factory_ctx.build_body(site, SugarRole.STATEMENT)
    reduce_ctx = ReduceContext(
        temporal=(
            TemporalContext.empty()
            .bind_value("items", SymbolicValue(make_var("items")))
            .bind_value("holder", SymbolicValue(make_var("holder")))
            .bind_value("holder.value", TermValue(0))
        )
    )

    outcome = body.reduce(reduce_ctx)
    assert isinstance(outcome, Complete)

    after = outcome.extend_scope(reduce_ctx)
    projected = after.temporal.value_for("holder.value")
    assert isinstance(projected, CallSiteValue)
    assert projected.target_name.startswith("loop:")
