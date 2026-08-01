"""Ordering comparison demands cross Python keyword/default call binding."""

from __future__ import annotations

import ast

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.expectation_not_met_effect import ExpectationNotMetEffect
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import Complete, ExitSet, Halted
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


def _exception_identity(name: str):
    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


class _Expected:
    def __init__(self, name: str):
        self.identity = _exception_identity(name)

    def exception_type_identity(self):
        return self.identity


def _program_outcomes():
    source = (
        "def helper(left, right=2):\n"
        "    return left < right\n\n"
        "helper(None, 2)\n"
        "helper(None, right=2)\n"
        "helper(None)\n"
        "helper(1, right=2)\n"
    )
    nodes = tuple(_tree(source).nodes())
    function = next(node for node in nodes if isinstance(node, FunctionDef))
    calls = tuple(node for node in nodes if isinstance(node, Call))
    return function.sugar().desugar(None), tuple(
        call.sugar().desugar(None) for call in calls
    )


def _named_type_error(outcome: object) -> Halted:
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _exception_identity("TypeError")
    assert isinstance(halted.effect.occurrence_id, str) and ":" in halted.effect.occurrence_id, (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )
    return halted


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
        if isinstance(node, ast.FunctionDef) and node.name == "assert_invalid_comparison"
    )
    assert helper.lineno == 89
    with_node = next(node for node in ast.walk(helper) if isinstance(node, ast.With))
    manager = with_node.items[0].context_expr
    assert with_node.lineno == 143
    assert isinstance(manager, ast.Call)
    assert ast.unparse(manager.args[0]) == "TypeError"
    assert [(keyword.arg, ast.unparse(keyword.value)) for keyword in manager.keywords] == [
        ("match", "msg")
    ]
    msg = next(
        node
        for node in helper.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "msg" for target in node.targets)
    )
    assert isinstance(msg.value, ast.Call)
    assert ast.unparse(msg.value.func) == "'|'.join"
    assert len(msg.value.args) == 1 and isinstance(msg.value.args[0], ast.List)
    assert tuple(ast.literal_eval(item) for item in msg.value.args[0].elts) == MATCH_PARTS
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
    assert any(node.lineno == 90 and len(node.args) == 3 and not node.keywords for node in calls)


def test_helper_alone_is_undischarged_and_all_three_bindings_reach_one_demand() -> None:
    pending, (positional, keyword, default, normal) = _program_outcomes()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "less_than"

    halted = tuple(_named_type_error(outcome) for outcome in (positional, keyword, default))
    assert len({face.effect.occurrence_id for face in halted}) == 1
    assert isinstance(normal, ExitSet)
    assert len(normal.exits) == 1
    assert not any(isinstance(face, Halted) for face in normal.exits)


def test_wrong_boundary_type_does_not_consume_or_create_the_exception_identity() -> None:
    _, (_, keyword, _, _) = _program_outcomes()
    producer_halt = _named_type_error(keyword)
    separately_minted_expected = _Expected("TypeError")
    assert producer_halt.effect.exception_type_coordinate == separately_minted_expected.identity
    assert producer_halt.effect.exception_type_coordinate is not separately_minted_expected.identity

    projected = keyword.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_Expected("ValueError")),
            unmet=ExpectationNotMetEffect("raise", "assertion-site"),
        ),
    )
    assert len(projected.exits) == 1
    assert isinstance(projected.exits[0], Halted)
    assert projected.exits[0].effect is producer_halt.effect


def test_swapped_ordering_retains_distinct_ordered_coordinates() -> None:
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
    assert isinstance(forward, NativeOperationExitCarrierV1)
    assert isinstance(swapped, NativeOperationExitCarrierV1)
    assert forward.demand.operand_coordinate_cids == tuple(
        coordinate.coordinate_cid for coordinate in forward_function.formal_coordinates()
    )
    assert swapped.demand.operand_coordinate_cids == tuple(
        coordinate.coordinate_cid
        for coordinate in reversed(swapped_function.formal_coordinates())
    )
    assert forward.demand.demand_cid != swapped.demand.demand_cid


def test_identity_law_never_acquires_a_native_operation_carrier() -> None:
    source = "def helper(left, right=2):\n    return left is right\n"
    outcome = next(
        node for node in _tree(source).nodes() if isinstance(node, FunctionDef)
    ).sugar().desugar(None)
    assert isinstance(outcome, Complete)
    assert not isinstance(outcome, NativeOperationExitCarrierV1)
