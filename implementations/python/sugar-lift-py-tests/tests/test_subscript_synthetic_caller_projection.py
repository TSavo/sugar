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

from frame_fresh import fresh
from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.floor import ListValue, TermValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import (
    Completed,
    ExitSet,
    Halted,
    NativeOperationExitCarrierV1,
)
from sugar_lift_py_tests.unanswered_calls import owed_calls
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile

# Each caller stands in its own function, called after import.  In the module
# body, ``helper([7], 1)`` raises IndexError: the module's one run completes on
# no arm, no import completes, and a later call omitting ``key`` has no
# ``def`` statement's evaluation of the default to read (the key is read off
# that run, ``module_final_default_keys``) -- refused by name, as Python
# never reaches it.
CALLER_SOURCE = (
    "def helper(obj, key=1):\n"
    "    return obj[key]\n"
    "\n"
    "def completed():\n"
    "    helper([7], 0)\n"
    "def positional():\n"
    "    helper([7], 1)\n"
    "def keyword():\n"
    "    helper([7], key=1)\n"
    "def default():\n"
    "    helper([7])\n"
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

    # No caller actual: the subscript is the cited unanswered face (#7825).
    exits = carrier.discharge(None, {})
    assert carrier.unanswered_call() in owed_calls(exits)
    assert exits.completed_value() is None



def _the_call(outcome: ExitSet):
    """The call value on the one completed face of a caller's call: a
    same-file call is its coordinate and edge, joined at prove (#7757 steps
    5 and 6, #8705), completing under its ``completes`` atom and owing its
    halt under the complement."""
    from sugar_lift_py_tests.floor import CallSiteValue

    assert [face for face in outcome.exits if isinstance(face, Halted)], outcome
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(completed) == 1, outcome
    call = completed[0].value
    assert isinstance(call, CallSiteValue), type(call)
    return call


def _int(call, value: int):
    return TermValue(value).to_term(owner=str(call.site))


def _discharged(carrier, key: int) -> ExitSet:
    """The helper's row discharged with ``[7]`` and ``key``: what prove's one
    binder binds its carrier with at a call that supplies them."""
    obj_cid, key_cid = carrier.demand.operand_coordinate_cids
    return carrier.discharge(
        None, {obj_cid: fresh(ListValue, (TermValue(7),)), key_cid: TermValue(key)}
    )


def _index_error():
    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("IndexError")],
    )


def test_positional_keyword_and_default_callers_reach_the_same_demand() -> None:
    # Expected verdict changed (#7757 steps 5 and 6, #8705): each caller's
    # call no longer holds the IndexError the followed body raised, stamped
    # with that call's occurrence; it is the edge, which owes its halt, and
    # prove joins the helper's halt at each call (#8690, #8749).  The three
    # forms carry the same binding of ``key``; the helper's row discharged
    # with it reaches the one ``obj[key]``.
    carrier = _carrier()
    completed, positional, keyword, default = (
        _the_call(outcome) for outcome in _caller_outcomes()
    )
    assert list(completed.term.args[1:]) == [_int(completed, 0)]
    assert list(positional.term.args[1:]) == [_int(positional, 1)]
    assert list(keyword.term.args[1:]) == [
        ctor("py.kwarg", [str_const("key"), _int(keyword, 1)])
    ]
    assert list(default.term.args[1:]) == [
        ctor("py.default", [str_const("key"), _int(default, 1)])
    ]

    assert isinstance(_discharged(carrier, 0).exits[0], Completed)
    halted = _discharged(carrier, 1).exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _index_error()
    site = carrier.site
    assert halted.effect.occurrence_id.startswith(
        f"{site.filename}:{site.line}:{site.col}"
    )


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
    discharged = _discharged(carrier, 1)
    original = discharged.exits[0]
    assert isinstance(original, Halted)

    routed = discharged.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_Expected("ValueError")),
            unmet=ExpectationNotMetEffect("raise", "assertion-site"),
        ),
    )

    assert len(routed.exits) == 1
    escaped = routed.exits[0]
    assert isinstance(escaped, Halted)
    site = carrier.site
    # The routed halt is the original occurrence of the subscript.
    assert escaped.effect.occurrence_id == original.effect.occurrence_id
    assert escaped.effect.occurrence_id.startswith(
        f"{site.filename}:{site.line}:{site.col}"
    )
    assert escaped.effect.exception_type_coordinate == _index_error()
    assert escaped.effect.exception_type_coordinate != _Expected("ValueError").identity
