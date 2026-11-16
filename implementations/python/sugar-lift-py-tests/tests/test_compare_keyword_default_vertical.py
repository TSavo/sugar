"""Ordering comparison demands cross Python keyword/default call binding."""

from __future__ import annotations

import ast

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.ir import str_const
from sugar_lift_py_tests.outcome import ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile

MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)
PANDAS_HELPER = "tests/arithmetic/common.py"
PANDAS_CALLER = "tests/arithmetic/test_datetime64.py"
MATCH_PARTS = (
    "Invalid comparison between",
    "Cannot compare type",
    "not supported between",
    "invalid type promotion",
    "The DTypes <class 'numpy.dtype\\[datetime64\\]'> and "
    "<class 'numpy.dtype\\[int64\\]'> do not have a common DType. For example "
    "they cannot be stored in a single array unless the dtype is `object`.",
)


def _tree(source: str) -> SourceFile:
    return SourceFile(
        (source, "compare-keyword-default.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _program_outcomes():
    """``helper`` alone, then each ``helper(...)`` reduced where it runs: in
    ``caller``'s body, so after import.

    A default is evaluated once, by the ``def`` statement: a call that omits
    the formal reads the value the module run bound under the default's key
    (``with_module_final_globals``, ``DefaultValueSugar``). A module-level
    call reduced alone is part of no module run -- no statement bound the key
    -- and is refused by name, so the calls stand in a body here.
    """
    source = (
        "def helper(left, right=2):\n"
        "    return left < right\n\n\n"
        "def caller():\n"
        "    helper(None, 2)\n"
        "    helper(None, right=2)\n"
        "    helper(None)\n"
        "    helper(1, right=2)\n"
    )
    nodes = tuple(_tree(source).nodes())
    function = next(
        node
        for node in nodes
        if isinstance(node, FunctionDef) and node.name == "helper"
    )
    calls = tuple(node for node in nodes if isinstance(node, Call))
    assert len(calls) == 4
    return function.sugar().desugar(None), tuple(
        call.sugar().desugar(None) for call in calls
    )


def _call_term(outcome: object):
    """The call's coordinate, ``call:<target>(<arguments>)``.

    #7757 step 5 (#8705, "Edge, join at prove"): a call of a same-file def is
    its coordinate and edge, never the callee's body applied to its actuals.
    It is the one unanswered call: it completes under its
    ``python:unknown_callee_call.completes`` atom with ``python:call_result(
    <call term>, <occurrence>)`` and halts under the complement naming no
    exception (``helper``'s contract states the ``TypeError``; prove types it
    where the join binds ``None``).  The call term carries the binding exactly
    as prove's one binder binds the contract: a positional actual as written,
    a keyword as ``py.kwarg``, an omitted defaulted formal as ``py.default``
    with the value its ``def`` statement bound."""
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 2
    (halted,) = outcome.halts()
    assert isinstance(halted, Halted)
    assert halted.effect.exception_name is None
    assert halted.effect.exception_type_coordinate is None
    (completed,) = (face for face in outcome.exits if face is not halted)
    assert completed.guard.name == "python:unknown_callee_call.completes"
    result = completed.value.term
    assert result.name == "python:call_result"
    call = result.args[0]
    assert call.name.startswith("call:")
    return call


def test_real_pandas_ordering_helper_and_positional_caller_are_content_pinned() -> None:
    """The corpus evidence is real; keyword/default are binder-shape twins."""
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.manifest_cid, corpus.file_count) == (
        "3.0.3",
        MANIFEST_CID,
        1421,
    )
    helper_source = (corpus.root / PANDAS_HELPER).read_text(encoding="utf-8")
    helper_tree = ast.parse(helper_source)
    helper = next(
        node
        for node in ast.walk(helper_tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "assert_invalid_comparison"
    )
    assert helper.lineno == 89
    with_node = next(node for node in ast.walk(helper) if isinstance(node, ast.With))
    manager = with_node.items[0].context_expr
    assert with_node.lineno == 143
    assert isinstance(manager, ast.Call)
    assert ast.unparse(manager.args[0]) == "TypeError"
    assert [
        (keyword.arg, ast.unparse(keyword.value)) for keyword in manager.keywords
    ] == [("match", "msg")]
    msg = next(
        node
        for node in helper.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "msg"
            for target in node.targets
        )
    )
    assert isinstance(msg.value, ast.Call)
    assert ast.unparse(msg.value.func) == "'|'.join"
    assert len(msg.value.args) == 1 and isinstance(msg.value.args[0], ast.List)
    assert (
        tuple(ast.literal_eval(item) for item in msg.value.args[0].elts) == MATCH_PARTS
    )
    comparison = next(
        node
        for node in ast.walk(with_node)
        if isinstance(node, ast.Compare) and ast.unparse(node) == "left < right"
    )
    assert comparison.lineno == 144

    caller_source = (corpus.root / PANDAS_CALLER).read_text(encoding="utf-8")
    calls = [
        node
        for node in ast.walk(ast.parse(caller_source))
        if isinstance(node, ast.Call)
        and ast.unparse(node.func).endswith("assert_invalid_comparison")
    ]
    assert any(
        node.lineno == 90 and len(node.args) == 3 and not node.keywords
        for node in calls
    )


def _compare_dispatch(outcome: ExitSet):
    """The one ``python:compare(<op>, left, right, <key>)`` the outcome's
    ``python:compare.completes`` atom names."""
    found: list = []

    def walk(formula) -> None:
        if getattr(formula, "name", None) == "python:compare.completes":
            (dispatch,) = formula.args
            if dispatch not in found:
                found.append(dispatch)
            return
        for operand in getattr(formula, "operands", None) or ():
            walk(operand)
        inner = getattr(formula, "operand", None)
        if inner is not None:
            walk(inner)

    for exit_ in outcome.exits:
        walk(exit_.guard)
    (dispatch,) = found
    assert dispatch.name == "python:compare"
    return dispatch


def _assert_undecided_ordering(outcome: object) -> tuple[str, str]:
    """``helper`` alone over its formals: no carrier (#7757, audit row
    NEW-1), the undecided ordering's two faces, owing the undecided member.
    Returns the names of the operands its completes atom states, in order."""
    assert isinstance(outcome, ExitSet)
    halts = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == "UndecidedCompare:Lt"
    ]
    assert len(halts) == 1, outcome.exits
    assert halts[0].effect.exception_name is None
    dispatch = _compare_dispatch(outcome)
    assert dispatch.args[0] == str_const("Lt")
    return tuple(term.name for term in dispatch.args[1:3])


def test_helper_alone_is_undischarged_and_all_three_bindings_reach_one_demand() -> None:
    """``helper`` alone is the undecided ordering over its formals (its
    contract), never a carrier.  Each call is its coordinate, carrying the
    binding prove's binder binds those formals with: ``right`` by position,
    by keyword and by its default all reach the one ``left < right`` at the
    join.

    Before #8705 each call applied ``helper``'s body here and named the
    ``TypeError`` of ``None < 2`` at the call; that body-following is
    deleted.  Also covers the former ``test_wrong_boundary_type_does_not_
    consume_or_create_the_exception_identity``: the call's halt creates no
    exception identity at all (``_call_term``)."""
    helper, (positional, keyword, default, normal) = _program_outcomes()
    assert _assert_undecided_ordering(helper) == ("left", "right")

    positional_call, keyword_call, default_call, normal_call = (
        _call_term(outcome) for outcome in (positional, keyword, default, normal)
    )
    # After the actuals ride the classes the caller decides (#8857,
    # ``receiver_dispatch.class_arguments``): an ``int`` actual's
    # ``py.class`` keyed by its position or keyword; ``None`` and a default
    # supply none.
    assert len({positional_call.name, keyword_call.name, default_call.name}) == 1
    none_actual, two_actual, two_class = positional_call.args
    assert two_class == _int_class("1")
    for call, form in ((keyword_call, "py.kwarg"), (default_call, "py.default")):
        actual, bound = call.args[:2]
        assert actual == none_actual
        assert bound.name == form
        assert bound.args[0] == str_const("right")
    assert list(keyword_call.args[2:]) == [_int_class("right")]
    assert len(default_call.args) == 2
    assert keyword_call.args[1].args[1] == two_actual
    one_actual, keyword_two, *classes = normal_call.args
    assert one_actual != none_actual
    assert keyword_two.name == "py.kwarg"
    assert keyword_two.args[1] == two_actual
    assert classes == [_int_class("0"), _int_class("right")]


def _int_class(key: str):
    """``py.class(<key>, python:builtin("int"))`` (#8857)."""
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.receiver_dispatch import (
        CLASS_ARGUMENT,
        builtin_class_term,
    )

    return ctor(CLASS_ARGUMENT, [str_const(key), builtin_class_term("int")])


def test_swapped_ordering_retains_distinct_ordered_operands() -> None:
    forward_source = "def helper(left, right=2):\n    return left < right\n"
    swapped_source = "def helper(left, right=2):\n    return right < left\n"
    forward_function = next(
        node for node in _tree(forward_source).nodes() if isinstance(node, FunctionDef)
    )
    swapped_function = next(
        node for node in _tree(swapped_source).nodes() if isinstance(node, FunctionDef)
    )
    forward = forward_function.sugar().desugar(None)
    swapped = swapped_function.sugar().desugar(None)
    forward_names = tuple(
        coordinate.declared_name
        for coordinate in forward_function.formal_coordinates()
    )
    swapped_names = tuple(
        coordinate.declared_name
        for coordinate in reversed(swapped_function.formal_coordinates())
    )
    assert _assert_undecided_ordering(forward) == forward_names
    assert _assert_undecided_ordering(swapped) == swapped_names
    assert _compare_dispatch(forward) != _compare_dispatch(swapped)


def test_identity_law_never_acquires_a_native_operation_carrier() -> None:
    source = "def helper(left, right=2):\n    return left is right\n"
    outcome = (
        next(node for node in _tree(source).nodes() if isinstance(node, FunctionDef))
        .sugar()
        .desugar(None)
    )
    assert outcome.completed_value() is not None
