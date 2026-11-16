from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.floor import (

    NoneValue,
    ObjectField,
    ObjectValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.ir import PrimitiveSort, ctor, make_var, str_const
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
from sugar_lift_py_tests.sugar.attribute_sugar import AttributeSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Attribute
from sugar_source_tree.tree import SourceFile

from frame_fresh import FRAME_FRESH

from sugar_lift_py_tests.repo_root import python_implementations_root, resolve_repo_root, sugar_lift_py_tests_package_root

class _ValueSugar(ConstructedTermSugar):
    def __init__(self, value):
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "site", None)

    def desugar(self, ctx=None):
        del ctx
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(self.value)

    def to_term(self, *, owner: str):
        del owner
        return str_const("test-value-sugar")

    @classmethod
    def witnesses(cls):
        return ()


def _attribute_node() -> Attribute:
    source = "def access(receiver):\n    return receiver.value\n"
    tree = SourceFile((source, "attribute_demand.py", blake3_512_of(source.encode())))
    return next(node for node in tree.nodes() if isinstance(node, Attribute))


def _formal(node: Attribute) -> FormalParameterCoordinateV1:
    span = node.fragment.line_col_span
    owner = SourceFragmentCoordinateV1(
        node.fragment.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    return FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=node.fragment.source_cid,
        owner_definition_locus=owner,
        declaration_locus=owner,
        ordinal=0,
        parameter_kind="positional-or-keyword",
        declared_name="receiver",
        sort=PrimitiveSort("Value"),
    )


def _formal_read():
    """``receiver.value`` on the formal ``receiver``: the one two-faced
    undecided read (``SymbolicValue.attribute``), never an
    ``attribute_named`` carrier waiting on a caller's actual (#7757 audit 2
    row NEW-1: a read is ``__getattribute__`` then ``__getattr__``, a
    protocol no one dispatched method states)."""
    node = _attribute_node()
    formal = _formal(node)
    return AttributeSugar(
        _ValueSugar(SymbolicValue(make_var("receiver"), formal)),
        "value",
        node.fragment,
    ).desugar(None)


def _read(actual):
    """The read the carrier's discharge applied, on the decided actual:
    its own ``attribute`` at the read's site, every face kept."""
    return actual.attribute("value", _attribute_node().fragment, None)


def _receiver():
    return ObjectValue(
        "Receiver",
        (ObjectField("value", TermValue(7)),),
        allocation=FRAME_FRESH,
    )


def test_formal_attribute_read_mints_no_carrier() -> None:
    outcome = _formal_read()
    from sugar_lift_py_tests.floor.floor_value import FloorValue

    assert not hasattr(FloorValue, "attribute_named")


def test_formal_attribute_completes_or_halts_from_authenticated_actual() -> None:
    completed = _read(_receiver())
    halted = _read(NoneValue())

    from sugar_lift_py_tests.ir import ctor, str_const

    # Expected value changed (#7757): a recorded field is the read's value
    # only under prove's ``python:plain_read`` over the instance's class
    # term (a ``__getattribute__`` or a class data descriptor answers it
    # otherwise); this receiver has no class statement, so no class term
    # guards it and the read is the undecided read, its halt kept -- never
    # the recorded ``7`` outright.
    assert completed.halts(), completed
    assert not [
        arm
        for arm in completed.exits
        if isinstance(arm, Completed) and arm.value == TermValue(7)
    ], completed
    assert len(halted.exits) == 1
    assert isinstance(halted.exits[0], Halted)
    # Pin the positive identity — `is not None` under an identity-promising
    # name is a weak tooth; the named AttributeError must be the value.
    attribute_error = ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("AttributeError")],
    )
    assert halted.exits[0].effect.exception_type_coordinate == attribute_error
    assert (
        isinstance(halted.exits[0].effect.occurrence_id, str)
        and ":" in halted.exits[0].effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.exits[0].effect.occurrence_id!r}"
    )


def test_formal_attribute_read_is_the_two_faced_unanswered_read() -> None:
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    outcome = _formal_read()
    assert outcome.completed_value() is None
    (halt,) = [arm for arm in outcome.exits if isinstance(arm, Halted)]
    (done,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert type(halt.effect) is UndeterminedRaiseEffect
    assert halt.effect.producer_node_owner == "SymbolicValue.attribute"
    # Keyed per evaluation (``floor_value.undecided_attribute_result``).
    assert "python:attribute_op.completes" in repr(done.guard)
    assert "python:attribute_result" in repr(done.value.to_term(owner="test"))
    assert any(item.site is not None for item in owed_calls(outcome))


def test_lying_exception_type_cannot_consume_attribute_halt() -> None:
    from sugar_lift_py_tests.context_manager_contract import (
        AuthenticatedRaiseMatcher,
        EffectBoundaryDisposition,
    )
    from sugar_lift_py_tests.effect import ExpectationNotMetEffect
    from sugar_lift_py_tests.outcome import ExitSet

    class _ExpectedValueError:
        def exception_type_identity(self):
            return ctor(
                "python:exception_type_identity",
                [str_const("builtins"), str_const("ValueError")],
            )

    exits = _read(NoneValue())
    routed = exits.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_ExpectedValueError()),
            unmet=ExpectationNotMetEffect("raise", "assertion-site"),
        ),
    )

    assert len(routed.exits) == 1
    assert isinstance(routed.exits[0], Halted)
    assert (
        routed.exits[0].effect.exception_type_coordinate
        != _ExpectedValueError().exception_type_identity()
    )


def test_total_attribute_actual_never_acquires_exceptional_edge() -> None:
    exits = _read(_receiver())

    assert all(isinstance(face, Completed) for face in exits.exits)


def test_authenticated_attribute_family_has_a_closed_exit_split() -> None:
    """Every enrolled body ends on one arm, and no arm is a panic.

    Each probe reduces its ``with`` body's attribute read with no context, so
    the receiver is undecided, and an attribute read on an undecided receiver
    is the one two-faced undecided read (#8175): it completes, or it raises an
    exception whose type nothing here decides.  That raise is never dropped
    and never named a type it is not: the body is undischarged, and its
    nameless face is stated by name in the identity list.  No count of
    authenticated exits is demanded."""
    from sugar_lift_py_tests.no_call_body_attribution import (
        AttributionOutcome,
        ProducerFamily,
        run_authenticated_attribution,
    )

    repo_root = resolve_repo_root()
    report = run_authenticated_attribution(
        repo_root, families=frozenset({ProducerFamily.ATTRIBUTE})
    )
    row = report.by_family[ProducerFamily.ATTRIBUTE]

    print(report.render())
    assert row.enrolled == 53
    assert row.outcome_total == 53
    assert row.construction_panics == 0
    assert report.discrepancies == ()
    assert report.conservation_shortfall == 0
    undischarged = {
        body.body_id
        for body in report.bodies
        if body.outcome is AttributionOutcome.UNDISCHARGED
    }
    assert len(undischarged) == row.undischarged
    assert {
        discrepancy.body_id
        for discrepancy in report.exceptional_exit_identity_discrepancies
    } == undischarged


def test_attribute_construction_has_no_vendor_exception_name_arm() -> None:
    production = sugar_lift_py_tests_package_root() / "src" / "sugar_lift_py_tests"
    source_tree = python_implementations_root() / "sugar-source-tree" / "src"
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            production / "sugar" / "attribute_sugar.py",
            production / "floor" / "object_value.py",
            source_tree / "sugar_source_tree" / "nodes.py",
        )
    )
    for forbidden in ("AbstractMethodError", "pandas.errors", "SeriesGroupBy"):
        assert forbidden not in text
