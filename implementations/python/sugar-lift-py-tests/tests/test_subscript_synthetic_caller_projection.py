"""Synthetic caller completion for the real pandas Subscript absence.

REAL PINNED-CORPUS FACT: pandas 3.0.3 has two direct-formal
``pytest.raises`` Subscript helpers, at
``tests/extension/base/getitem.py:256-259`` and
``tests/indexes/test_any_index.py:149-162``, but no source caller supplying
both actuals.  ``test_pandas_subscript_caller_gap.py`` authenticates that
absence by manifest CID and keeps its inserted-caller lying twin unchanged.

SYNTHETIC EXTENSION: this module supplies ``helper(actual_obj, actual_key)``
calls solely to show the one way a caller's actuals reach the read: the
helper's ``obj[key]`` is the one undecided read in its own proof (#7757,
audit 2 row NEW-1, #9016), never a carrier waiting on a caller's actual, and
each caller's call is its coordinate and edge, joined at prove.  The
IndexError the read raises on ``[7]`` and ``1`` is the read door's own
decided face (``discharge_subscript``).  These calls are evidence for the
general Python mechanism, never claims about pandas source.
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
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import ListValue, TermValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.unanswered_calls import owed_calls
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef, Subscript
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


def _helper(source: str = CALLER_SOURCE) -> ExitSet:
    """The helper's own reduction: an ``ExitSet``, never a carrier."""
    function = next(
        node
        for node in _tree(source).nodes()
        if isinstance(node, FunctionDef) and node.name == "helper"
    )
    outcome = function.sugar().desugar(None)
    assert isinstance(outcome, ExitSet), type(outcome)
    return outcome


def _read_site(source: str = CALLER_SOURCE):
    """The site of the helper's one ``obj[key]``."""
    return next(
        node for node in _tree(source).nodes() if isinstance(node, Subscript)
    ).fragment


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


def test_helper_alone_is_the_undecided_read_owed_at_its_site() -> None:
    """With no caller the helper's ``obj[key]`` is the one undecided read
    (#7757, audit 2 row NEW-1, #9016): its value keyed per evaluation,
    ``python:subscript_result(obj, key, <key>)``, completing only under its
    ``python:subscript_op.completes`` atom, its ``UndeterminedRaiseEffect``
    kept at the same key under the complement, and the read owed at its
    site.  No IndexError is guessed and no member is chosen."""
    exits = _helper("def helper(obj, key=1):\n    return obj[key]\n")

    halts = [
        face
        for face in exits.exits
        if isinstance(face, Halted)
        and isinstance(face.effect, UndeterminedRaiseEffect)
        and face.effect.producer_node_owner == "SymbolicValue.subscript"
    ]
    assert len(halts) == 1, exits
    (done,) = [face for face in exits.exits if isinstance(face, Completed)]
    guard = repr(done.guard)
    assert "python:subscript_op.completes" in guard
    assert halts[0].effect.occurrence in guard
    assert "python:subscript_result" in repr(exits)
    assert any(item.site is not None for item in owed_calls(exits))


def _the_call(outcome: ExitSet):
    """The call value on the one completed face of a caller's call: a
    same-file call is its coordinate and edge, joined at prove (#7757 steps
    5 and 6, #8705), completing under its ``completes`` atom and owing its
    halt under the complement -- the face prove types by the helper's
    contract, whose row states the IndexError locus."""
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.outcome.exit_set import complement_guard

    halted = [face for face in outcome.exits if isinstance(face, Halted)]
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(completed) == 1, outcome
    assert completed[0].guard.name == "python:unknown_callee_call.completes"
    assert any(
        face.guard == complement_guard(completed[0].guard) for face in halted
    ), outcome
    call = completed[0].value
    assert isinstance(call, CallSiteValue), type(call)
    return call


def _coordinate(call):
    """The call's coordinate ``call:<target>(<arguments>)``: the completed
    face's value is ``python:call_result(<call term>, <occurrence>)``
    (#7757 steps 5 and 6, #8705), so the binding prove's one binder reads is
    the call term's arguments, never the result's."""
    result = call.term
    assert result.name == "python:call_result", result
    coordinate = result.args[0]
    assert coordinate.name.startswith("call:"), coordinate
    return coordinate


def _int(call, value: int):
    return TermValue(value).to_term(owner=str(call.site))


def _class(key: str, name: str):
    """``py.class(<key>, python:builtin("<name>"))`` (#8857)."""
    from sugar_lift_py_tests.receiver_dispatch import (
        CLASS_ARGUMENT,
        builtin_class_term,
    )

    return ctor(CLASS_ARGUMENT, [str_const(key), builtin_class_term(name)])


def _decided_read(site, key: int) -> ExitSet:
    """``[7][key]`` through the one read door at the helper's site: the
    decided operands a caller supplies, read by the floor's own law (the
    halt checks that rode a carrier discharge run on the door, #9016)."""
    from sugar_lift_py_tests.operations.subscript_operation import (
        discharge_subscript,
    )

    return discharge_subscript(
        fresh(ListValue, (TermValue(7),)),
        TermValue(key),
        site,
        None,
        owner="SubscriptSugar",
    )


def _index_error():
    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("IndexError")],
    )


def test_positional_keyword_and_default_callers_bind_the_same_read() -> None:
    # Expected verdict changed (#7757 steps 5 and 6, #8705): each caller's
    # call no longer holds the IndexError the followed body raised, stamped
    # with that call's occurrence; it is the edge, which owes its halt, and
    # prove joins the helper's halt at each call (#8690, #8749).  The three
    # forms carry the same binding of ``key``; the read door on the decided
    # operands is the one ``obj[key]`` (no carrier, #9016).
    #
    # After the actuals ride the classes the caller decides, keyed by the
    # argument each is (#8857, ``receiver_dispatch.class_arguments``): the
    # ``[7]`` it built is a ``list`` at ``"0"``, a supplied ``int`` key an
    # ``int`` at its position or keyword; a default supplies none.
    _helper()
    site = _read_site()
    completed, positional, keyword, default = (
        _the_call(outcome) for outcome in _caller_outcomes()
    )
    assert list(_coordinate(completed).args[1:]) == [
        _int(completed, 0),
        _class("0", "list"),
        _class("1", "int"),
    ]
    assert list(_coordinate(positional).args[1:]) == [
        _int(positional, 1),
        _class("0", "list"),
        _class("1", "int"),
    ]
    assert list(_coordinate(keyword).args[1:]) == [
        ctor("py.kwarg", [str_const("key"), _int(keyword, 1)]),
        _class("0", "list"),
        _class("key", "int"),
    ]
    assert list(_coordinate(default).args[1:]) == [
        ctor("py.default", [str_const("key"), _int(default, 1)]),
        _class("0", "list"),
    ]

    assert isinstance(_decided_read(site, 0).exits[0], Completed)
    halted = _decided_read(site, 1).exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _index_error()
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
    site = _read_site()
    discharged = _decided_read(site, 1)
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
    # The routed halt is the original occurrence of the subscript.
    assert escaped.effect.occurrence_id == original.effect.occurrence_id
    assert escaped.effect.occurrence_id.startswith(
        f"{site.filename}:{site.line}:{site.col}"
    )
    assert escaped.effect.exception_type_coordinate == _index_error()
    assert escaped.effect.exception_type_coordinate != _Expected("ValueError").identity
