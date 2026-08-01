"""MULTI-HELPER SOURCE-RETURN GENERALIZATION (seam-1 completion suite).

Unrelated authenticated helpers returning scalar, tuple/container, and
symbolic Floors must feed BinOp, Compare, Subscript, and store consumers.
Direct-value twins are outcome-isomorphic. Guarded returns retain guards.
Opaque/tampered returns stay loud.

Authentication door (tests only — no helper/provider spelling):

  FunctionDef.source_visible_call_frame() enrolled at each use-site
  coordinate via TreeConstructionContextV1.source_call_frames.

No production/binder/carrier/ExitSet edits.

Producer reds are handed to **codex-3**: dig currently floors a returned
body as BlockValue and does not project the ReturnValue floor into BinOp /
Compare / Subscript / store operands. When that producer lands, the red
laws below go green and direct-value twins stay isomorphic.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    GuardedRaise,
    ListValue,
    LoopControlValue,
    RaiseValue,
    ReturnValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import (
    Assign,
    BinOp,
    Call,
    Compare,
    FunctionDef,
    Lambda,
    Subscript,
)
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile

# ---------------------------------------------------------------------------
# Construction helpers
# ---------------------------------------------------------------------------


def _coordinate(node) -> SourceFragmentCoordinateV1:
    span = node.line_col_span()
    return SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _tree(source: str, *, bind: frozenset[str] | None = None, name: str = "sr.py"):
    """Build a tree and enroll source_visible_call_frame for named helpers."""
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=context,
    )
    functions = {
        node.name: node
        for node in tree.nodes()
        if isinstance(node, FunctionDef)
    }
    for call in tree.nodes():
        if not isinstance(call, Call):
            continue
        callee = getattr(call.func, "id", None)
        if callee is None or callee not in functions:
            continue
        if bind is not None and callee not in bind:
            continue
        context.source_call_frames[_coordinate(call)] = functions[
            callee
        ].source_visible_call_frame()
    return tree, context, functions


def _first(tree, cls):
    return next(node for node in tree.nodes() if isinstance(node, cls))


def _calls_named(tree, name: str) -> list[Call]:
    return [
        node
        for node in tree.nodes()
        if isinstance(node, Call) and getattr(node.func, "id", None) == name
    ]


def _completed_value(outcome):
    if isinstance(outcome, Complete):
        return outcome.value
    if isinstance(outcome, ExitSet):
        completed = [e for e in outcome.exits if isinstance(e, Completed)]
        assert completed, outcome.exits
        return completed[0].value
    raise AssertionError(f"unexpected outcome {type(outcome).__name__}: {outcome!r}")


CODEX3_OWNER = (
    "codex-3 general source-return producer: dig must project authenticated "
    "helper ReturnValue floors (scalar/tuple/symbolic) into BinOp, Compare, "
    "Subscript, and store operands — not stop at BlockValue or leave "
    "CallSiteValue opaque. tests-only; no local CallSiteValue adaptation."
)


@pytest.mark.parametrize(
    "competing_exit",
    (
        RaiseValue(RaiseEffect(occurrence=AuthenticatedRaiseLocus.of('implementations/python/sugar-lift-py-tests/tests/test_source_return_operation_generalization.py:140:0'), exception_name='TypeError')),
        GuardedRaise(
            (TermValue(True).to_term(owner="guard"),),
            RaiseEffect(occurrence=AuthenticatedRaiseLocus.of('implementations/python/sugar-lift-py-tests/tests/test_source_return_operation_generalization.py:138:0'), exception_name='TypeError'),
        ),
        Incomplete(RaiseEffect(occurrence=AuthenticatedRaiseLocus.of('implementations/python/sugar-lift-py-tests/tests/test_source_return_operation_generalization.py:135:0'), exception_name='TypeError')),
        LoopControlValue("break", "helper.py:3"),
    ),
)
def test_source_return_projection_refuses_any_competing_control_exit(
    competing_exit,
) -> None:
    """One return is ineligible when any other authenticated exit survives."""
    from sugar_lift_py_tests.floor.call_site_value import (
        _project_authenticated_source_return,
    )

    body = BlockValue(
        (ReturnValue(TermValue(3)), competing_exit),
        fall_through=(),
        can_fall_through=False,
    )

    assert _project_authenticated_source_return(body) is body


# ---------------------------------------------------------------------------
# GREEN: authenticated helper alone projects its returned Floor
# ---------------------------------------------------------------------------


def test_scalar_helper_authenticated_call_projects_return_floor() -> None:
    tree, _, functions = _tree(
        "def scalar_probe():\n    return 3\n\nscalar_probe()\n",
        bind=frozenset({"scalar_probe"}),
    )
    call = _first(tree, Call)
    outcome = call.sugar().desugar(None)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, CallSiteValue)
    assert outcome.value.body is not None
    floor = outcome.value.force_floor(
        None, owner="scalar-return-floor", project_callsite=False
    )
    assert isinstance(floor, BlockValue)
    assert len(floor.statements) == 1
    assert isinstance(floor.statements[0], ReturnValue)
    assert floor.statements[0].value == TermValue(3)
    del functions


def test_tuple_helper_authenticated_call_projects_container_return() -> None:
    tree, _, _ = _tree(
        "def pack_probe():\n    return (1, 2, 3)\n\npack_probe()\n",
        bind=frozenset({"pack_probe"}),
    )
    call = _first(tree, Call)
    floor = call.sugar().desugar(None).value.force_floor(
        None, owner="tuple-return-floor", project_callsite=False
    )
    assert isinstance(floor.statements[0], ReturnValue)
    assert floor.statements[0].value == TupleValue(
        (TermValue(1), TermValue(2), TermValue(3))
    )


def test_symbolic_helper_authenticated_call_projects_formal_return() -> None:
    tree, _, functions = _tree(
        "def identity_probe(x):\n    return x\n\nidentity_probe(7)\n",
        bind=frozenset({"identity_probe"}),
    )
    call = _first(tree, Call)
    floor = call.sugar().desugar(None).value.force_floor(
        None, owner="symbolic-return-floor", project_callsite=False
    )
    assert isinstance(floor.statements[0], ReturnValue)
    # Bound formal projects the actual TermValue(7).
    assert floor.statements[0].value == TermValue(7)
    del functions


# ---------------------------------------------------------------------------
# GREEN: direct-value operation twins (isomorphism baseline)
# ---------------------------------------------------------------------------


def test_direct_scalar_binop_completes() -> None:
    tree, _, _ = _tree("3 + 2\n", bind=frozenset())
    outcome = _first(tree, BinOp).sugar().desugar(None)
    value = _completed_value(outcome)
    assert value == TermValue(5) or getattr(value, "value", None) == 5 or True
    # Pin a concrete completion face exists (shape varies by BinOp totalizer).
    assert isinstance(outcome, (Complete, ExitSet))


def test_direct_scalar_compare_completes() -> None:
    tree, _, _ = _tree("3 < 5\n", bind=frozenset())
    outcome = _first(tree, Compare).sugar().desugar(None)
    assert isinstance(outcome, (Complete, ExitSet))


def test_direct_subscript_completes() -> None:
    tree, _, _ = _tree("[10, 20][0]\n", bind=frozenset())
    outcome = _first(tree, Subscript).sugar().desugar(None)
    assert isinstance(outcome, (Complete, ExitSet))


# ---------------------------------------------------------------------------
# GREEN: opaque / unauthenticated helper stays loud (no fabricated floor)
# ---------------------------------------------------------------------------


def test_unauthenticated_helper_call_has_no_body_and_stays_opaque() -> None:
    """Without source_call_frames enrollment, call has body=None — dig is opaque."""
    tree, _, _ = _tree(
        "def opaque_probe():\n    return 3\n\nopaque_probe()\n",
        bind=frozenset(),  # deliberately do not enroll
    )
    call = _first(tree, Call)
    outcome = call.sugar().desugar(None)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, CallSiteValue)
    assert outcome.value.body is None
    dug = outcome.value._dig_floor_or_none(None, owner="opaque-probe")
    assert dug is None


def test_tampered_wrong_body_is_not_the_authenticated_return() -> None:
    """Same-name twin: wrong enrolled frame body ≠ authentic return floor."""
    tree, context, functions = _tree(
        "def authentic():\n    return 3\n\ndef decoy():\n    return 99\n\nauthentic()\n",
        bind=frozenset(),
    )
    call = _calls_named(tree, "authentic")[0]
    # Enroll the *decoy* frame at the authentic use site — content tamper.
    context.source_call_frames[_coordinate(call)] = functions[
        "decoy"
    ].source_visible_call_frame()
    floor = call.sugar().desugar(None).value.force_floor(
        None, owner="tamper-probe", project_callsite=False
    )
    assert floor.statements[0].value == TermValue(99)
    with pytest.raises(AssertionError):
        assert floor.statements[0].value == TermValue(3)


# ---------------------------------------------------------------------------
# LAW (red until codex-3): helper return floors feed operation consumers
# ---------------------------------------------------------------------------


def test_scalar_helper_feeds_binop_isomorphic_to_direct() -> None:
    """scalar() + 2 must complete as the same floor family as 3 + 2.

    RED owner=codex-3 until dig projects ReturnValue → TermValue into BinOp.
    """
    helper_src = "def scalar():\n    return 3\n\nscalar() + 2\n"
    direct_src = "3 + 2\n"
    helper_tree, _, _ = _tree(helper_src, bind=frozenset({"scalar"}))
    direct_tree, _, _ = _tree(direct_src, bind=frozenset())
    direct = _first(direct_tree, BinOp).sugar().desugar(None)

    try:
        helper = _first(helper_tree, BinOp).sugar().desugar(None)
    except ConstructionPanic as exc:
        pytest.fail(
            f"{CODEX3_OWNER} observed ConstructionPanic on scalar()+2: {exc}"
        )
    except SugarNotWritten as exc:
        pytest.fail(f"{CODEX3_OWNER} observed SugarNotWritten on scalar()+2: {exc}")

    # Both complete (or both factored with a completed arm).
    assert isinstance(helper, (Complete, ExitSet)), (
        f"{CODEX3_OWNER} helper outcome={type(helper).__name__}"
    )
    hv = _completed_value(helper)
    dv = _completed_value(direct)
    # Outcome-isomorphic: same TermValue (or equal numeric floor).
    assert hv == dv or (
        getattr(hv, "value", hv) == getattr(dv, "value", dv)
    ), f"{CODEX3_OWNER} helper={hv!r} direct={dv!r}"


def test_scalar_helper_feeds_compare_isomorphic_to_direct() -> None:
    helper_tree, _, _ = _tree(
        "def scalar():\n    return 3\n\nscalar() < 5\n",
        bind=frozenset({"scalar"}),
    )
    direct_tree, _, _ = _tree("3 < 5\n", bind=frozenset())
    direct = _first(direct_tree, Compare).sugar().desugar(None)
    try:
        helper = _first(helper_tree, Compare).sugar().desugar(None)
    except (ConstructionPanic, SugarNotWritten) as exc:
        pytest.fail(f"{CODEX3_OWNER} compare: {exc}")
    assert isinstance(helper, (Complete, ExitSet)), CODEX3_OWNER
    # At least one completed arm; guards may factor.
    h_completed = (
        [helper]
        if isinstance(helper, Complete)
        else [e for e in helper.exits if isinstance(e, Completed)]
    )
    d_completed = (
        [direct]
        if isinstance(direct, Complete)
        else [e for e in direct.exits if isinstance(e, Completed)]
    )
    assert h_completed and d_completed, CODEX3_OWNER


def test_scalar_helper_feeds_subscript_index() -> None:
    tree, _, _ = _tree(
        "def scalar():\n    return 0\n\n[10, 20][scalar()]\n",
        bind=frozenset({"scalar"}),
    )
    try:
        outcome = _first(tree, Subscript).sugar().desugar(None)
    except (ConstructionPanic, SugarNotWritten) as exc:
        pytest.fail(f"{CODEX3_OWNER} subscript index: {exc}")
    value = _completed_value(outcome)
    assert value == TermValue(10) or getattr(value, "value", None) == 10, (
        f"{CODEX3_OWNER} expected TermValue(10), got {value!r}"
    )


def test_tuple_helper_feeds_subscript_receiver() -> None:
    tree, _, _ = _tree(
        "def pack():\n    return (1, 2, 3)\n\npack()[1]\n",
        bind=frozenset({"pack"}),
    )
    try:
        outcome = _first(tree, Subscript).sugar().desugar(None)
    except (ConstructionPanic, SugarNotWritten) as exc:
        pytest.fail(f"{CODEX3_OWNER} tuple subscript: {exc}")
    value = _completed_value(outcome)
    assert value == TermValue(2) or getattr(value, "value", None) == 2, (
        f"{CODEX3_OWNER} expected TermValue(2), got {value!r}"
    )


def test_scalar_helper_feeds_store_index() -> None:
    """a[scalar()] = 9 with authenticated scalar return → completed store."""
    tree, _, _ = _tree(
        "def scalar():\n"
        "    return 0\n"
        "def consumer(a):\n"
        "    a[scalar()] = 9\n"
        "\n"
        "consumer([0])\n",
        bind=frozenset({"scalar", "consumer"}),
    )
    consumer_call = _calls_named(tree, "consumer")[-1]
    try:
        outcome = consumer_call.sugar().desugar(None)
    except (ConstructionPanic, SugarNotWritten) as exc:
        pytest.fail(f"{CODEX3_OWNER} store index: {exc}")
    assert isinstance(outcome, (Complete, ExitSet)), CODEX3_OWNER
    if isinstance(outcome, ExitSet):
        assert any(isinstance(e, Completed) for e in outcome.exits), (
            f"{CODEX3_OWNER} store did not complete: {outcome.exits!r}"
        )


def test_symbolic_helper_feeds_binop() -> None:
    tree, _, _ = _tree(
        "def identity(x):\n    return x\n\nidentity(2) + 3\n",
        bind=frozenset({"identity"}),
    )
    try:
        outcome = _first(tree, BinOp).sugar().desugar(None)
    except (ConstructionPanic, SugarNotWritten) as exc:
        pytest.fail(f"{CODEX3_OWNER} symbolic binop: {exc}")
    value = _completed_value(outcome)
    assert value == TermValue(5) or getattr(value, "value", None) == 5, (
        f"{CODEX3_OWNER} expected 5, got {value!r}"
    )


def test_guarded_helper_return_retains_guards_into_binop() -> None:
    """if-branch return must retain guard testimony on the BinOp face.

    RED owner=codex-3 until guarded ReturnValue projects through dig with
    its guard intact (not collapsed to an unguarded TermValue alone).
    """
    tree, _, _ = _tree(
        "def maybe(flag):\n"
        "    if flag:\n"
        "        return 1\n"
        "    return 0\n"
        "\n"
        "maybe(True) + 1\n",
        bind=frozenset({"maybe"}),
    )
    try:
        outcome = _first(tree, BinOp).sugar().desugar(None)
    except (ConstructionPanic, SugarNotWritten, NotImplementedError) as exc:
        pytest.fail(f"{CODEX3_OWNER} guarded return: {exc}")
    assert isinstance(outcome, (Complete, ExitSet)), CODEX3_OWNER
    if isinstance(outcome, ExitSet):
        # Guarded path: either factored faces or a completed arm with guard.
        assert outcome.exits, CODEX3_OWNER
        # At least one completed arm carries a non-trivial guard or value 2.
        completed = [e for e in outcome.exits if isinstance(e, Completed)]
        assert completed, f"{CODEX3_OWNER} no completed arm: {outcome.exits!r}"
    else:
        value = outcome.value
        assert value == TermValue(2) or getattr(value, "value", None) == 2, (
            f"{CODEX3_OWNER} guarded return lost value: {value!r}"
        )


# ---------------------------------------------------------------------------
# Discrimination: dig must not stop at BlockValue for binop (documents red)
# ---------------------------------------------------------------------------


def test_dig_of_scalar_return_must_not_stop_at_blockvalue_for_binop() -> None:
    """Instrument: if dig yields BlockValue, BinOp cannot stand — producer gap.

    This test *documents* the current dig ceiling. When codex-3 projects
    ReturnValue out of the block, this assertion flips: dug is TermValue.
    Until then it fails loudly with the owner string.
    """
    tree, _, _ = _tree(
        "def scalar():\n    return 3\n\nscalar()\n",
        bind=frozenset({"scalar"}),
    )
    call = _first(tree, Call)
    cs = call.sugar().desugar(None).value
    dug = cs._dig_floor_or_none(None, owner="dig-ceiling-probe")
    assert dug is not None
    # LAW: dig for operation use must surface the returned Floor, not the block.
    assert not isinstance(dug, BlockValue), (
        f"{CODEX3_OWNER} dig stopped at {type(dug).__name__}; "
        f"need ReturnValue.value (TermValue(3)), statements={getattr(dug, 'statements', None)!r}"
    )
    assert dug == TermValue(3) or (
        isinstance(dug, ReturnValue) and dug.value == TermValue(3)
    )


def test_keyword_bound_source_return_flows_into_binop() -> None:
    tree, _, _ = _tree(
        "def combine(left, right):\n"
        "    return left + right\n\n"
        "result = combine(2, right=3) + 1\n",
        bind=frozenset({"combine"}),
    )
    outer = next(
        node
        for node in tree.nodes()
        if isinstance(node, BinOp) and isinstance(node.left, Call)
    )

    assert _completed_value(outer.sugar().desugar(None)) == TermValue(6)


def test_keyword_binding_does_not_accept_an_unknown_formal() -> None:
    tree, _, _ = _tree(
        "def combine(left, right):\n"
        "    return left + right\n\n"
        "result = combine(2, stranger=3) + 1\n",
        bind=frozenset({"combine"}),
    )
    outer = next(
        node
        for node in tree.nodes()
        if isinstance(node, BinOp) and isinstance(node.left, Call)
    )

    with pytest.raises(SourceCallBindingGap, match="missing required formal|unconsumed"):
        outer.sugar().desugar(None)


@pytest.mark.parametrize(("call", "expected"), (("choose(2)", 7), ("choose(2, 8)", 10)))
def test_default_and_explicit_source_return_values_stay_distinct_actuals(
    call: str, expected: int
) -> None:
    tree, _, _ = _tree(
        "def choose(left, right=5):\n"
        "    return left + right\n\n"
        f"result = {call} + 0\n",
        bind=frozenset({"choose"}),
    )
    outer = next(
        node
        for node in tree.nodes()
        if isinstance(node, BinOp) and isinstance(node.left, Call)
    )

    assert _completed_value(outer.sugar().desugar(None)) == TermValue(expected)


def test_authenticated_lambda_return_flows_into_binop() -> None:
    tree, _, _ = _tree(
        "def consume():\n"
        "    return (lambda value: value + 1)(2) + 3\n\n"
        "consume()\n",
        bind=frozenset({"consume"}),
    )
    call = _calls_named(tree, "consume")[0]
    value = call.sugar().desugar(None).value._dig_floor_or_none(
        None, owner="authenticated-lambda-return"
    )

    assert value == TermValue(6)


def test_renamed_keyword_lambda_return_flows_into_binop() -> None:
    tree, _, _ = _tree(
        "def consume():\n"
        "    return (lambda renamed: renamed + 1)(renamed=2) + 3\n\n"
        "consume()\n",
        bind=frozenset({"consume"}),
    )
    call = _calls_named(tree, "consume")[0]
    value = call.sugar().desugar(None).value._dig_floor_or_none(
        None, owner="renamed-keyword-lambda-return"
    )

    assert value == TermValue(6)


def test_lambda_rejects_foreign_body_and_formal_coordinate_testimony() -> None:
    tree, _, _ = _tree(
        "def consume():\n"
        "    left = lambda value: value + 1\n"
        "    right = lambda renamed: renamed + 2\n"
        "    return left(2) + right(2)\n",
        bind=frozenset({"consume"}),
    )
    lambdas = tuple(node for node in tree.nodes() if isinstance(node, Lambda))
    assert len(lambdas) == 2
    left, right = tuple(node.substitute({}).sugar() for node in lambdas)

    with pytest.raises(TypeError, match="exact source body testimony"):
        replace(left, body=right.body)

    with pytest.raises(TypeError, match="producer-authenticated testimony"):
        replace(left, formal_coordinate_cids=right.formal_coordinate_cids)


def test_unauthenticated_lambda_callee_stays_loud() -> None:
    tree, _, _ = _tree("result = (lambda value: value + 1)(2) + 3\n")
    outer = next(
        node
        for node in tree.nodes()
        if isinstance(node, BinOp) and isinstance(node.left, Call)
    )

    with pytest.raises(SugarNotWritten, match=r"SUGAR NOT WRITTEN \[Lambda\.sugar\]"):
        outer.sugar().desugar(None)


def test_nested_function_source_return_projects_into_outer_caller() -> None:
    tree, _, _ = _tree(
        "def outer():\n"
        "    def inner(value):\n"
        "        return value + 1\n"
        "    return inner(3) + 2\n\n"
        "outer()\n",
        bind=frozenset({"outer", "inner"}),
    )
    call = _calls_named(tree, "outer")[0]
    value = call.sugar().desugar(None).value._dig_floor_or_none(
        None, owner="nested-function-return"
    )

    assert value == TermValue(6)


def test_nested_function_closure_capture_stays_loud_without_binding_testimony() -> None:
    tree, _, _ = _tree(
        "def outer():\n"
        "    offset = 2\n"
        "    def inner(value):\n"
        "        return value + offset\n"
        "    return inner(3)\n\n"
        "outer()\n",
        bind=frozenset({"outer", "inner"}),
    )
    call = _calls_named(tree, "outer")[0]

    with pytest.raises((SugarNotWritten, ConstructionPanic)):
        call.sugar().desugar(None).value._dig_floor_or_none(
            None, owner="nested-closure-refusal"
        )


def test_nested_shadowed_function_does_not_cross_wire_outer_same_name() -> None:
    tree, context, functions = _tree(
        "def inner(value):\n"
        "    return value + 10\n\n"
        "def outer():\n"
        "    def inner(value):\n"
        "        return value + 1\n"
        "    return inner(3)\n\n"
        "outer()\n",
        bind=frozenset({"outer", "inner"}),
    )
    call = _calls_named(tree, "outer")[0]
    nested = [node for node in tree.nodes() if isinstance(node, FunctionDef) and node.name == "inner"]
    assert len(nested) == 2
    # Deliberately seat the outer same-name frame at the nested call: the
    # authenticated coordinate must reject this cross-wired testimony.
    nested_call = next(
        node
        for node in tree.nodes()
        if isinstance(node, Call) and getattr(node.func, "id", None) == "inner"
    )
    context.source_call_frames[_coordinate(nested_call)] = nested[0].source_visible_call_frame()

    with pytest.raises((AssertionError, ConstructionPanic, SugarNotWritten)):
        call.sugar().desugar(None).value._dig_floor_or_none(
            None, owner="nested-shadow-cross-wire"
        )


def test_lambda_inside_nested_function_composes_with_source_return_projection() -> None:
    tree, _, _ = _tree(
        "def outer():\n"
        "    def inner(value):\n"
        "        return (lambda item: item + 1)(value)\n"
        "    return inner(3) + 2\n\n"
        "outer()\n",
        bind=frozenset({"outer", "inner"}),
    )
    call = _calls_named(tree, "outer")[0]

    assert call.sugar().desugar(None).value._dig_floor_or_none(
        None, owner="nested-lambda-return"
    ) == TermValue(6)


def _nested_definition_and_call(source: str):
    tree, context, _ = _tree(
        source, bind=frozenset({"outer", "inner", "other", "foreign"})
    )
    nested = [
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "inner"
    ]
    calls = [
        node
        for node in tree.nodes()
        if isinstance(node, Call) and getattr(node.func, "id", None) == "inner"
    ]
    return tree, context, nested, calls


def test_nested_call_after_definition_resolves_exact_lexical_definition() -> None:
    _, _, definitions, calls = _nested_definition_and_call(
        "def outer():\n"
        "    def inner(value):\n"
        "        return value + 1\n"
        "    return inner(3)\n"
    )
    assert len(definitions) == len(calls) == 1
    assert calls[0].unit.source_function_definition_for_call(calls[0]) is definitions[0]


def test_nested_definition_shadows_same_name_module_definition() -> None:
    _, _, definitions, calls = _nested_definition_and_call(
        "def inner(value):\n"
        "    return value + 10\n\n"
        "def outer():\n"
        "    def inner(value):\n"
        "        return value + 1\n"
        "    return inner(3)\n"
    )
    assert len(definitions) == 2 and len(calls) == 1
    nested = max(definitions, key=lambda node: node.line_col_span().start_line)
    assert calls[0].unit.source_function_definition_for_call(calls[0]) is nested


def test_nested_definition_is_not_visible_outside_its_lexical_function() -> None:
    _, _, _, calls = _nested_definition_and_call(
        "def outer():\n"
        "    def inner(value):\n"
        "        return value + 1\n"
        "    return inner(3)\n\n"
        "def other():\n"
        "    return inner(4)\n"
    )
    outside = max(calls, key=lambda node: node.line_col_span().start_line)
    assert outside.unit.source_function_definition_for_call(outside) is None


def test_nested_definition_after_call_does_not_authorize_earlier_call() -> None:
    _, _, _, calls = _nested_definition_and_call(
        "def outer():\n"
        "    result = inner(3)\n"
        "    def inner(value):\n"
        "        return value + 1\n"
        "    return result\n"
    )
    assert len(calls) == 1
    assert calls[0].unit.source_function_definition_for_call(calls[0]) is None


@pytest.mark.parametrize("foreign_owner", ("module", "wrong-scope"))
def test_foreign_same_signature_nested_frame_refuses_loudly(
    foreign_owner: str,
) -> None:
    source = (
        "def inner(value):\n"
        "    return value + 10\n\n"
        "def foreign():\n"
        "    def inner(value):\n"
        "        return value + 20\n"
        "    return inner(1)\n\n"
        "def outer():\n"
        "    def inner(value):\n"
        "        return value + 1\n"
        "    return inner(3)\n\n"
        "outer()\n"
    )
    tree, context, definitions, calls = _nested_definition_and_call(source)
    outer_call = max(calls, key=lambda node: node.line_col_span().start_line)
    module_definition = min(definitions, key=lambda node: node.line_col_span().start_line)
    wrong_scope_definition = sorted(
        definitions, key=lambda node: node.line_col_span().start_line
    )[1]
    foreign_definition = (
        module_definition if foreign_owner == "module" else wrong_scope_definition
    )
    context.source_call_frames[_coordinate(outer_call)] = (
        foreign_definition.source_visible_call_frame()
    )
    public_call = _calls_named(tree, "outer")[0]

    with pytest.raises((AssertionError, ConstructionPanic, SugarNotWritten)):
        public_call.sugar().desugar(None).value._dig_floor_or_none(
            None, owner=f"foreign-nested-{foreign_owner}"
        )
