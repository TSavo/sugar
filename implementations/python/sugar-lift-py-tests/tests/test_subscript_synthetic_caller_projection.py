"""Synthetic caller completion for the real pandas Subscript absence.

REAL PINNED-CORPUS FACT: pandas 3.0.3 has two direct-formal
``pytest.raises`` Subscript helpers, at
``tests/extension/base/getitem.py:256-259`` and
``tests/indexes/test_any_index.py:149-162``, but no source caller supplying
both actuals.  ``test_pandas_subscript_caller_gap.py`` authenticates that
absence by manifest CID and keeps its inserted-caller lying twin unchanged.

SYNTHETIC EXTENSION: this module supplies ``helper(actual_obj, actual_key)``
calls solely to prove the now-live producer -> projector -> Python binder ->
Floor path.  These calls are evidence for the general Python mechanism, never
claims about pandas source.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import (
    Completed,
    ExitSet,
    Halted,
    NativeOperationExitCarrierV1,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile

CALLER_SOURCE = (
    "def helper(obj, key=1):\n"
    "    return obj[key]\n"
    "\n"
    "helper([7], 0)\n"
    "helper([7], 1)\n"
    "helper([7], key=1)\n"
    "helper([7])\n"
)


def _tree(source: str = CALLER_SOURCE) -> SourceFile:
    return SourceFile(
        (source, "synthetic-subscript-callers.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _carrier(source: str = CALLER_SOURCE) -> NativeOperationExitCarrierV1:
    function = next(
        node
        for node in _tree(source).nodes()
        if isinstance(node, FunctionDef) and node.name == "helper"
    )
    outcome = function.sugar().desugar(None)
    assert isinstance(outcome, NativeOperationExitCarrierV1)
    return outcome


def _caller_outcomes(source: str = CALLER_SOURCE) -> tuple[ExitSet, ...]:
    calls = sorted(
        (
            node
            for node in _tree(source).nodes()
            if isinstance(node, Call) and node.line_col_span().start_line >= 4
        ),
        key=lambda node: node.line_col_span().start_line,
    )
    outcomes = tuple(call.sugar().desugar(None) for call in calls)
    assert all(isinstance(outcome, ExitSet) for outcome in outcomes)
    return outcomes


def test_helper_alone_is_named_undischarged_without_caller_actuals() -> None:
    carrier = _carrier("def helper(obj, key=1):\n    return obj[key]\n")

    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        carrier.discharge({})


def test_positional_keyword_and_default_callers_reach_the_same_demand() -> None:
    carrier = _carrier()
    completed, positional, keyword, default = _caller_outcomes()

    assert len(completed.exits) == 1
    assert isinstance(completed.exits[0], Completed)
    exceptional = (positional, keyword, default)
    halted = tuple(outcome.exits[0] for outcome in exceptional)
    assert all(isinstance(exit_, Halted) for exit_ in halted)
    assert all(exit_.effect.exception_type_coordinate is not None for exit_ in halted)
    assert {exit_.effect.occurrence_id for exit_ in halted} == {
        str(carrier.demand.source_node.wire())
    }


class _Expected:
    def __init__(self, name: str):
        self.identity = ctor(
            "python:exception_type_identity",
            [str_const("builtins"), str_const(name)],
        )

    def exception_type_identity(self):
        return self.identity


def test_lying_boundary_type_cannot_create_or_consume_the_subscript_result() -> None:
    carrier = _carrier()
    _, positional, _, _ = _caller_outcomes()
    original = positional.exits[0]
    assert isinstance(original, Halted)

    routed = positional.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_Expected("ValueError")),
            unmet=ExpectationNotMetEffect("raise", "assertion-site"),
        ),
    )

    assert len(routed.exits) == 1
    escaped = routed.exits[0]
    assert isinstance(escaped, Halted)
    assert escaped.effect.occurrence_id == str(carrier.demand.source_node.wire())
    assert escaped.effect.exception_type_coordinate == (
        original.effect.exception_type_coordinate
    )
    assert escaped.effect.exception_type_coordinate != _Expected("ValueError").identity
