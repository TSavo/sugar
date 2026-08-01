from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
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
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


class _ValueSugar(ConstructedTermSugar):
    def __init__(self, value):
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "site", None)

    def desugar(self, ctx=None):
        del ctx
        from sugar_lift_py_tests.outcome import Complete

        return Complete(self.value)

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


def _carrier() -> tuple[NativeOperationExitCarrierV1, FormalParameterCoordinateV1]:
    node = _attribute_node()
    formal = _formal(node)
    outcome = AttributeSugar(
        _ValueSugar(SymbolicValue(make_var("receiver"), formal)),
        "value",
        node.fragment,
    ).desugar(None)
    assert isinstance(outcome, NativeOperationExitCarrierV1)
    return outcome, formal


def test_formal_attribute_completes_or_halts_from_authenticated_actual() -> None:
    carrier, formal = _carrier()
    completed = carrier.discharge(
        {
            formal.coordinate_cid: ObjectValue(
                "Receiver", (ObjectField("value", TermValue(7)),)
            )
        }
    )
    halted = carrier.discharge({formal.coordinate_cid: NoneValue()})

    from sugar_lift_py_tests.ir import ctor, str_const

    assert carrier.demand.operator == "attribute_named"
    assert len(completed.exits) == 1
    assert isinstance(completed.exits[0], Completed)
    assert completed.exits[0].value == TermValue(7)
    assert len(halted.exits) == 1
    assert isinstance(halted.exits[0], Halted)
    # Pin the positive identity — `is not None` under an identity-promising
    # name is a weak tooth; the named AttributeError must be the value.
    attribute_error = ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("AttributeError")],
    )
    assert halted.exits[0].effect.exception_type_coordinate == attribute_error
    assert isinstance(halted.exits[0].effect.occurrence_id, str) and ":" in halted.exits[0].effect.occurrence_id, (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.exits[0].effect.occurrence_id!r}"
    )


def test_undecidable_attribute_actual_remains_named_loud() -> None:
    carrier, formal = _carrier()

    with pytest.raises(SugarNotWritten, match="undecided receiver runtime type"):
        carrier.discharge(
            {formal.coordinate_cid: SymbolicValue(make_var("still_unknown"))}
        )


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

    carrier, formal = _carrier()
    exits = carrier.discharge({formal.coordinate_cid: NoneValue()})
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
    carrier, formal = _carrier()
    exits = carrier.discharge(
        {
            formal.coordinate_cid: ObjectValue(
                "Receiver", (ObjectField("value", TermValue(7)),)
            )
        }
    )

    assert all(isinstance(face, Completed) for face in exits.exits)


def test_authenticated_attribute_family_has_a_closed_nonzero_exit_split() -> None:
    from sugar_lift_py_tests.no_call_body_attribution import (
        ProducerFamily,
        run_authenticated_attribution,
    )

    repo_root = Path(__file__).resolve().parents[4]
    report = run_authenticated_attribution(
        repo_root, families=frozenset({ProducerFamily.ATTRIBUTE})
    )
    row = report.by_family[ProducerFamily.ATTRIBUTE]

    print(report.render())
    assert row.enrolled == 53
    assert row.authenticated_exceptional_exits > 0
    assert row.authenticated_exceptional_exits + row.named_refusals == 53
    assert row.construction_panics == 0
    assert report.discrepancies == ()


def test_attribute_construction_has_no_vendor_exception_name_arm() -> None:
    production = Path(__file__).resolve().parents[1] / "src" / "sugar_lift_py_tests"
    source_tree = Path(__file__).resolve().parents[2] / "sugar-source-tree" / "src"
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
