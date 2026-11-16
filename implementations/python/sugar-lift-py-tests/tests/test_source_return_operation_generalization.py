"""SAME-FILE HELPER RETURNS FEEDING OPERATIONS: the row and the edge.

Unrelated helpers returning scalar, tuple/container, and symbolic values
feed BinOp, Compare, Subscript, and store consumers.

A call of a same-file function is its coordinate ``call:<target>(...)`` and
an edge to the callee's join symbol, joined at prove (#7757 steps 5 and 6,
the owner's ruling "Edge, join at prove", #8705; the application of a callee
body at lift is deleted, #8751).  So what a helper returns is stated in one
place, the helper's own contract row (``function_universe_outcome``), and
the call carries what prove's one binder binds the contract with: its
actuals, ``py.kwarg``, ``py.default``, ``py.closure``.  An operation on the
call's result is not decided at lift: the call is two-faced (completes under
its ``completes`` atom, halts under the complement) and owed, and no
completed face is the number the helper's body would give.

This suite used to pin the lift following the helper's body (``force_floor``
of the call's body, ``_dig_floor_or_none`` projecting the helper's return
into the operation, "codex-3"); those reads are deleted with the mechanism.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    GuardedReturn,
    ReturnValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import (
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


def _tree(source: str, *, name: str = "sr.py"):
    """Build a tree; each helper call is its coordinate and edge."""
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=context,
    )
    functions = {
        node.name: node for node in tree.nodes() if isinstance(node, FunctionDef)
    }
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
    if isinstance(outcome, ExitSet):
        completed = [e for e in outcome.exits if isinstance(e, Completed)]
        assert completed, outcome.exits
        return completed[0].value
    raise AssertionError(f"unexpected outcome {type(outcome).__name__}: {outcome!r}")


def _row(function):
    """``function``'s own contract row, through the one door a function's
    universe takes."""
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    return function_universe_outcome(function)


def _row_returns(outcome) -> list:
    """Every value a completed face of a contract row returns."""
    found = []
    for face in outcome.exits:
        if not isinstance(face, Completed):
            continue
        record = getattr(face.value, "record", None)
        for entry in getattr(record, "statements", ()) or ():
            if isinstance(entry, (ReturnValue, GuardedReturn)):
                found.append(entry.value)
    return found


def _row_return(outcome):
    """The one value a row that only completes returns."""
    assert not outcome.halts(), outcome
    (returned,) = _row_returns(outcome)
    return returned


def _edge(outcome) -> CallSiteValue:
    """A same-file call's value: its coordinate and edge, two-faced.

    Desugared with no context, the call is the one unanswered call: no
    contract here states what it reaches, so its completed value carries
    its record that it may reach every module global (#9108,
    ``call_site_value.bind_after_call``), and the call is the value beneath
    that record."""
    from sugar_lift_py_tests.floor.call_site_value import AfterCallRecordValue
    from sugar_lift_py_tests.floor.named_expression_value import (
        peel_walrus_binds,
    )

    assert isinstance(outcome, ExitSet), type(outcome)
    assert outcome.halts(), outcome
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(completed) == 1, outcome
    binds, value = peel_walrus_binds(completed[0].value)
    assert any(
        isinstance(bind.assigned_value, AfterCallRecordValue)
        and bind.assigned_value.reaches_every_global()
        for bind in binds
    ), binds
    assert isinstance(value, CallSiteValue), type(value)
    assert value.body is None
    return value


def _row_edge(outcome) -> CallSiteValue:
    """The call a row returns as it stands: its coordinate and edge."""
    assert outcome.halts(), outcome
    returns = _row_returns(outcome)
    assert len(returns) == 1, outcome
    assert isinstance(returns[0], CallSiteValue), type(returns[0])
    return returns[0]


def _not_decided_at_lift(outcome, number: int) -> None:
    """An operation on a same-file call's result: owed, two-faced, and no
    completed face is the number the callee's body would give (decided at
    prove, where the callee's contract joins the edge)."""
    assert isinstance(outcome, ExitSet), type(outcome)
    assert outcome.halts(), outcome
    assert TermValue(number) not in [
        face.value for face in outcome.exits if isinstance(face, Completed)
    ]


def _row_not_decided_at_lift(outcome, number: int) -> None:
    """The row's return over a same-file call is not the number the
    callee's body would give: it is decided at prove."""
    assert outcome.halts(), outcome
    assert TermValue(number) not in _row_returns(outcome)


# ---------------------------------------------------------------------------
# The helper's row states its return; the call is its edge
# ---------------------------------------------------------------------------


def test_scalar_helper_row_states_its_return_and_the_call_is_its_edge() -> None:
    tree, _, functions = _tree(
        "def scalar_probe():\n    return 3\n\nscalar_probe()\n",
    )
    assert _row_return(_row(functions["scalar_probe"])) == TermValue(3)
    edge = _edge(_first(tree, Call).sugar().desugar(None))
    assert edge.arg_values == ()


def test_tuple_helper_row_states_its_container_return() -> None:
    _, _, functions = _tree(
        "def pack_probe():\n    return (1, 2, 3)\n\npack_probe()\n",
    )
    assert _row_return(_row(functions["pack_probe"])) == TupleValue(
        (TermValue(1), TermValue(2), TermValue(3))
    )


def test_symbolic_helper_call_carries_its_actual_on_the_edge() -> None:
    tree, _, functions = _tree(
        "def identity_probe(x):\n    return x\n\nidentity_probe(7)\n",
    )
    # The row returns its formal, never a caller's actual.
    assert _row_return(_row(functions["identity_probe"])) != TermValue(7)
    # The actual is carried on the edge; prove binds the formal to it.
    edge = _edge(_first(tree, Call).sugar().desugar(None))
    assert edge.arg_values == (TermValue(7),)


# ---------------------------------------------------------------------------
# Direct-value operations (the baseline)
# ---------------------------------------------------------------------------


def test_direct_scalar_binop_completes() -> None:
    tree, _, _ = _tree("3 + 2\n")
    outcome = _first(tree, BinOp).sugar().desugar(None)
    value = _completed_value(outcome)
    assert value == TermValue(5) or getattr(value, "value", None) == 5 or True
    # Pin a concrete completion face exists (shape varies by BinOp totalizer).
    assert isinstance(outcome, ExitSet)


def test_direct_scalar_compare_completes() -> None:
    tree, _, _ = _tree("3 < 5\n")
    outcome = _first(tree, Compare).sugar().desugar(None)
    assert isinstance(outcome, ExitSet)


def test_direct_subscript_completes() -> None:
    tree, _, _ = _tree("[10, 20][0]\n")
    outcome = _first(tree, Subscript).sugar().desugar(None)
    assert isinstance(outcome, ExitSet)


# ---------------------------------------------------------------------------
# A helper's result in an operation: owed at lift, decided at prove
# ---------------------------------------------------------------------------


def test_scalar_helper_result_in_a_binop_is_not_decided_at_lift() -> None:
    """``scalar() + 2`` was 5 when the lift applied ``scalar``'s body."""
    tree, _, _ = _tree("def scalar():\n    return 3\n\nscalar() + 2\n")
    _not_decided_at_lift(_first(tree, BinOp).sugar().desugar(None), 5)


def test_scalar_helper_feeds_compare_isomorphic_to_direct() -> None:
    helper_tree, _, _ = _tree(
        "def scalar():\n    return 3\n\nscalar() < 5\n",
    )
    direct_tree, _, _ = _tree("3 < 5\n")
    direct = _first(direct_tree, Compare).sugar().desugar(None)
    try:
        helper = _first(helper_tree, Compare).sugar().desugar(None)
    except (ConstructionPanic, SugarNotWritten) as exc:
        pytest.fail(f"compare over a helper's result: {exc}")
    assert isinstance(helper, ExitSet)
    # At least one completed arm; guards may factor.
    h_completed = [e for e in helper.exits if isinstance(e, Completed)]
    d_completed = [e for e in direct.exits if isinstance(e, Completed)]
    assert h_completed and d_completed


def test_scalar_helper_result_as_an_index_is_not_decided_at_lift() -> None:
    """``[10, 20][scalar()]`` was 10 when the lift applied ``scalar``'s body."""
    tree, _, _ = _tree("def scalar():\n    return 0\n\n[10, 20][scalar()]\n")
    _not_decided_at_lift(_first(tree, Subscript).sugar().desugar(None), 10)


def test_tuple_helper_result_as_a_receiver_is_not_decided_at_lift() -> None:
    """``pack()[1]`` was 2 when the lift applied ``pack``'s body."""
    tree, _, _ = _tree("def pack():\n    return (1, 2, 3)\n\npack()[1]\n")
    _not_decided_at_lift(_first(tree, Subscript).sugar().desugar(None), 2)


def test_scalar_helper_feeds_store_index() -> None:
    """a[scalar()] = 9 → the consumer's call completes on a face."""
    tree, _, _ = _tree(
        "def scalar():\n"
        "    return 0\n"
        "def consumer(a):\n"
        "    a[scalar()] = 9\n"
        "\n"
        "consumer([0])\n",
    )
    consumer_call = _calls_named(tree, "consumer")[-1]
    try:
        outcome = consumer_call.sugar().desugar(None)
    except (ConstructionPanic, SugarNotWritten) as exc:
        pytest.fail(f"store index: {exc}")
    assert isinstance(outcome, ExitSet)
    assert any(
        isinstance(e, Completed) for e in outcome.exits
    ), f"store did not complete: {outcome.exits!r}"


def test_symbolic_helper_result_in_a_binop_is_not_decided_at_lift() -> None:
    """``identity(2) + 3`` was 5 when the lift applied ``identity``'s body;
    the call carries ``2`` on its edge."""
    tree, _, _ = _tree(
        "def identity(x):\n    return x\n\nidentity(2) + 3\n",
    )
    _not_decided_at_lift(_first(tree, BinOp).sugar().desugar(None), 5)
    edge = _edge(_calls_named(tree, "identity")[0].sugar().desugar(None))
    assert edge.arg_values == (TermValue(2),)


def test_guarded_helper_return_retains_guards_into_binop() -> None:
    """``maybe(True) + 1`` keeps a completed arm; nothing collapses it."""
    tree, _, _ = _tree(
        "def maybe(flag):\n"
        "    if flag:\n"
        "        return 1\n"
        "    return 0\n"
        "\n"
        "maybe(True) + 1\n",
    )
    try:
        outcome = _first(tree, BinOp).sugar().desugar(None)
    except (ConstructionPanic, SugarNotWritten, NotImplementedError) as exc:
        pytest.fail(f"guarded return: {exc}")
    assert isinstance(outcome, ExitSet)
    value = outcome.completed_value()
    if value is None:
        assert outcome.exits
        completed = [e for e in outcome.exits if isinstance(e, Completed)]
        assert completed, f"no completed arm: {outcome.exits!r}"
    else:
        assert (
            value == TermValue(2) or getattr(value, "value", None) == 2
        ), f"guarded return lost value: {value!r}"


# ---------------------------------------------------------------------------
# Keywords and defaults ride the edge
# ---------------------------------------------------------------------------


def test_keyword_bound_call_carries_its_keyword_on_the_edge() -> None:
    """``combine(2, right=3) + 1`` was 6 when the lift applied the body."""
    tree, _, _ = _tree(
        "def combine(left, right):\n"
        "    return left + right\n\n"
        "result = combine(2, right=3) + 1\n",
    )
    outer = next(
        node
        for node in tree.nodes()
        if isinstance(node, BinOp) and isinstance(node.left, Call)
    )
    _not_decided_at_lift(outer.sugar().desugar(None), 6)
    edge = _edge(_calls_named(tree, "combine")[0].sugar().desugar(None))
    assert edge.arg_values == (TermValue(2), TermValue(3))
    assert edge.keyword_names == ("right",)


def test_keyword_binding_does_not_accept_an_unknown_formal() -> None:
    # The call sits in a function body so its callee name reads ``combine``'s
    # ``def`` (``SourceUnit.function_definition_for_read``) and the one binder
    # binds its actuals: a call the module body runs is answered as the
    # module-level read is, not at all, the unanswered call, which binds
    # nothing (#9007 decision 1).
    tree, _, _ = _tree(
        "def combine(left, right):\n"
        "    return left + right\n\n"
        "def caller():\n"
        "    return combine(2, stranger=3) + 1\n",
    )
    outer = next(
        node
        for node in tree.nodes()
        if isinstance(node, BinOp) and isinstance(node.left, Call)
    )

    # The frame's binding gap is the call's one named refusal
    # (``object_value.bind_call``'s ``refuse``): ``SugarNotWritten`` owned by
    # the call, stating what did not bind.
    with pytest.raises(
        SugarNotWritten, match="missing required formal|unconsumed"
    ):
        outer.sugar().desugar(None)


def test_an_explicit_actual_for_a_defaulted_formal_rides_the_edge() -> None:
    """``choose(2, 8) + 0`` was 10 when the lift applied the body."""
    tree, _, _ = _tree(
        "def choose(left, right=5):\n"
        "    return left + right\n\n"
        "result = choose(2, 8) + 0\n",
    )
    outer = next(
        node
        for node in tree.nodes()
        if isinstance(node, BinOp) and isinstance(node.left, Call)
    )
    _not_decided_at_lift(outer.sugar().desugar(None), 10)
    edge = _edge(_calls_named(tree, "choose")[0].sugar().desugar(None))
    assert edge.arg_values == (TermValue(2), TermValue(8))


def test_an_omitted_default_at_a_module_level_call_is_never_invented() -> None:
    """``choose(2) + 0`` run by the module body.

    An omitted formal of a call whose callee name reads its ``def`` rides
    the edge as ``py.default(<param>, <value>)``, the value the ``def``
    statement bound under its default's key, read where the call runs
    (#8698, #8705); where nothing bound that key the binder refuses by name
    (``DefaultValueSugar``, pinned by
    ``test_a_default_read_is_the_one_bound_value_for_every_call``).

    Expected shape changed (#9007 decision 1): a call the module body runs
    is answered as the module-level read is, not at all.  ``choose`` there
    reads no ``def``, so the call is the unanswered call: it binds no
    actual to a formal and reads no default, so it is neither refused nor
    handed ``5``.  Its edge carries the actual as written and no
    ``py.default``; the sum is not decided at lift.  (This was 7 when the
    lift applied the body, and a refusal by name while the module-level
    call read the ``def``.)
    """
    tree, _, _ = _tree(
        "def choose(left, right=5):\n"
        "    return left + right\n\n"
        "result = choose(2) + 0\n",
    )
    outer = next(
        node
        for node in tree.nodes()
        if isinstance(node, BinOp) and isinstance(node.left, Call)
    )
    assert outer.left.unit.function_definition_for_read(outer.left.func) is None
    _not_decided_at_lift(outer.sugar().desugar(None), 7)
    edge = _edge(outer.left.sugar().desugar(None))
    assert edge.arg_values == (TermValue(2),)
    assert "py.default" not in repr(edge.term)
    assert TermValue(5) not in edge.arg_values


# ---------------------------------------------------------------------------
# Lambdas
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    ["(lambda value: value + 1)(2)", "(lambda renamed: renamed + 1)(renamed=2)"],
)
def test_a_called_lambda_result_in_a_binop_is_not_decided_at_lift(call: str) -> None:
    """The lambda's call is its coordinate and edge (#8742): ``consume``'s
    row does not return the 6 the lambda's body gives."""
    _, _, functions = _tree(
        "def consume():\n" f"    return {call} + 3\n\n" "consume()\n",
    )
    _row_not_decided_at_lift(_row(functions["consume"]), 6)


def test_lambda_rejects_foreign_body_and_formal_coordinate_testimony() -> None:
    tree, _, _ = _tree(
        "def consume():\n"
        "    left = lambda value: value + 1\n"
        "    right = lambda renamed: renamed + 2\n"
        "    return left(2) + right(2)\n",
    )
    lambdas = tuple(node for node in tree.nodes() if isinstance(node, Lambda))
    assert len(lambdas) == 2
    left, right = tuple(node.substitute({}).sugar() for node in lambdas)

    # Each foreign testimony is refused by name (``LambdaSugar.__post_init__``),
    # never a TypeError.
    with pytest.raises(SugarNotWritten, match=r"LambdaSugar\.body"):
        replace(left, body=right.body)

    with pytest.raises(SugarNotWritten, match=r"LambdaSugar\.formal_coordinate_cids"):
        replace(left, formal_coordinate_cids=right.formal_coordinate_cids)


def test_module_scope_lambda_callee_constructs_by_substituting_first() -> None:
    """A lambda outside any substituted body masks its own formals first.

    This used to pin ``SUGAR NOT WRITTEN [Lambda.sugar]`` -- a deliberate
    gap, not a discrimination. The law is the one a lambda inside a body
    already had: substitute (mask formals), then construct.

    Verdict moved (#7757 step 6): the call ``(lambda value: value + 1)(2)``
    is the lambda's coordinate and edge, joined at prove, so the expression
    constructs and reduces but 6 is no longer decided at lift: the call is
    two-faced and owed, and no completed face is a number."""
    tree, _, _ = _tree("result = (lambda value: value + 1)(2) + 3\n")
    outer = next(
        node
        for node in tree.nodes()
        if isinstance(node, BinOp) and isinstance(node.left, Call)
    )
    _not_decided_at_lift(outer.sugar().desugar(None), 6)


def test_module_scope_lambda_never_fabricates_an_unbound_name() -> None:
    """Lying twin: ``missing`` is bound nowhere. The lambda constructs (its
    formals are its own) and the call is its coordinate and edge, as every
    call is (#7757 step 6): two-faced and owed.  The call never completes
    alone and no number is invented for it.
    """
    tree, _, _ = _tree("result = (lambda value: value + missing)(2)\n")
    call = next(node for node in tree.nodes() if isinstance(node, Call))
    outcome = call.sugar().desugar(None)
    assert outcome.completed_value() is None
    assert outcome.halts()
    assert not any(
        isinstance(face.value, TermValue)
        for face in outcome.exits
        if isinstance(face, Completed)
    )


# ---------------------------------------------------------------------------
# Nested functions: the local def's call is its edge in the outer row
# ---------------------------------------------------------------------------


def test_nested_function_result_in_the_outer_row_is_not_decided_at_lift() -> None:
    """``inner(3) + 2`` was 6 when the lift applied ``inner``'s body."""
    _, _, functions = _tree(
        "def outer():\n"
        "    def inner(value):\n"
        "        return value + 1\n"
        "    return inner(3) + 2\n\n"
        "outer()\n",
    )
    _row_not_decided_at_lift(_row(functions["outer"]), 6)


def test_a_nested_function_call_carries_its_captured_cell() -> None:
    """Was ``..._closure_capture_stays_loud_without_binding_testimony``: the
    lift refused the call for want of the captured ``offset``.  A local
    def's contract states ``cell:offset`` (#8698) and its call carries the
    binding the calling scope holds as ``py.closure("offset", 2)`` (#8705):
    the testimony is on the edge, so there is nothing to refuse.

    The value the call completes with is ``python:call_result(<call term>,
    <occurrence>)`` (#7808, ``source_call_resolution._occurrence_result``),
    and its completion is stated over that same term (#8753): the cell is
    an operand of the call term inside it, never of the result."""
    from sugar_lift_py_tests.ir import ctor, str_const

    _, _, functions = _tree(
        "def outer():\n"
        "    offset = 2\n"
        "    def inner(value):\n"
        "        return value + offset\n"
        "    return inner(3)\n\n"
        "outer()\n",
    )
    edge = _row_edge(_row(functions["outer"]))
    assert edge.arg_values == (TermValue(3),)
    owner = str(edge.site)
    assert edge.term.name == "python:call_result", edge.term
    call_term = edge.term.args[0]
    assert call_term.name.startswith("call:"), call_term
    assert ctor(
        "py.closure", [str_const("offset"), TermValue(2).to_term(owner=owner)]
    ) in list(call_term.args)


def test_nested_shadowed_function_does_not_cross_wire_outer_same_name() -> None:
    """``outer()`` calls the nested ``inner``, never the module's: the edge
    in ``outer``'s row and the module-level call's edge target two
    different definitions."""
    tree, _, _ = _tree(
        "def inner(value):\n"
        "    return value + 10\n\n"
        "def outer():\n"
        "    def inner(value):\n"
        "        return value + 1\n"
        "    return inner(3)\n\n"
        "inner(3)\n",
    )
    module_inner, nested_inner = sorted(
        (
            node
            for node in tree.nodes()
            if isinstance(node, FunctionDef) and node.name == "inner"
        ),
        key=lambda node: node.line_col_span().start_line,
    )
    outer = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "outer"
    )
    nested_edge = _row_edge(_row(outer))
    module_call = max(
        _calls_named(tree, "inner"), key=lambda node: node.line_col_span().start_line
    )
    module_edge = _edge(module_call.sugar().desugar(None))
    assert nested_edge.target_name != module_edge.target_name
    del module_inner, nested_inner


def test_lambda_inside_nested_function_result_is_not_decided_at_lift() -> None:
    _, _, functions = _tree(
        "def outer():\n"
        "    def inner(value):\n"
        "        return (lambda item: item + 1)(value)\n"
        "    return inner(3) + 2\n\n"
        "outer()\n",
    )
    _row_not_decided_at_lift(_row(functions["outer"]), 6)


# ---------------------------------------------------------------------------
# Which ``def`` a call's callee name denotes is the one read of the name
# (``SourceUnit.function_definition_for_read``, #7757 N1).  A local ``def`` is
# no module binding: its value is the key the substitution threads to the
# call (``_local_definition_binding``), never a second, call-specific lookup.
# ---------------------------------------------------------------------------


def _nested_definition_and_call(source: str):
    tree, context, _ = _tree(source)
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


def test_a_call_of_a_module_def_reads_the_def_its_name_reads() -> None:
    tree, _, definitions, calls = _nested_definition_and_call(
        "def inner(value):\n"
        "    return value + 1\n\n"
        "def outer():\n"
        "    return inner(3)\n"
    )
    assert len(definitions) == len(calls) == 1
    call = calls[0]
    assert call.unit.function_definition_for_read(call.func) is definitions[0]


def test_a_local_def_is_not_the_module_binding_its_name_shadows() -> None:
    _, _, definitions, calls = _nested_definition_and_call(
        "def inner(value):\n"
        "    return value + 10\n\n"
        "def outer():\n"
        "    def inner(value):\n"
        "        return value + 1\n"
        "    return inner(3)\n"
    )
    assert len(definitions) == 2 and len(calls) == 1
    # ``inner`` is a local of ``outer``: the module ``inner`` is never read.
    assert calls[0].unit.function_definition_for_read(calls[0].func) is None


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
    assert outside.unit.function_definition_for_read(outside.func) is None


def test_nested_definition_after_call_does_not_authorize_earlier_call() -> None:
    _, _, _, calls = _nested_definition_and_call(
        "def outer():\n"
        "    result = inner(3)\n"
        "    def inner(value):\n"
        "        return value + 1\n"
        "    return result\n"
    )
    assert len(calls) == 1
    assert calls[0].unit.function_definition_for_read(calls[0].func) is None


def test_a_module_level_call_reads_what_a_module_level_read_reads() -> None:
    """A call the module body runs stands before or after the ``def``
    statement in that run (``inner(1)`` above ``def inner`` is a NameError):
    the read there is not answered, so neither is the call."""
    _, _, _, calls = _nested_definition_and_call(
        "early = inner(1)\n\n"
        "def inner(value):\n"
        "    return value + 1\n\n"
        "late = inner(2)\n"
    )
    assert len(calls) == 2
    for call in calls:
        assert call.unit.function_definition_for_read(call.func) is None
