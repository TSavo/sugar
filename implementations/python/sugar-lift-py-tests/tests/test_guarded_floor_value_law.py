"""General Floor laws for values and suites carried under a control guard."""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.floor.class_definition_value import ClassDefinitionValue
from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
from sugar_lift_py_tests.floor.floor_value import FloorValue
from sugar_lift_py_tests.floor.guarded_value import GuardedValue
from sugar_lift_py_tests.floor.inv_value import InvValue
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import atomic, ctor, implies
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


GUARD = atomic("renamed_guard", [])


@pytest.mark.parametrize(
    "value",
    (
        TrueBoolLiteralSugar(site="truth-site"),
        FalseBoolLiteralSugar(site="false-site"),
        StringValue("renamed-value"),
        SymbolicValue(ctor("renamed-coordinate", [])),
        ClassDefinitionValue(
            "RenamedClass",
            "blake3-512:renamed-class-definition",
            (),
            None,
        ),
        ComprehensionValue(ctor("renamed-comprehension", [])),
        GuardedValue(
            atomic("renamed_inner_guard", []),
            StringValue("then-value"),
            StringValue("else-value"),
        ),
    ),
    ids=(
        "true",
        "false",
        "string",
        "symbolic",
        "class",
        "comprehension",
        "guarded-value",
    ),
)
def test_pure_constructed_value_rides_under_guard_unchanged(value) -> None:
    """Deleting the guard-stable Floor law must fail every enrolled carrier."""
    assert value.guarded(GUARD) is value


def test_block_guards_each_entry_and_preserves_fallthrough_metadata() -> None:
    claim = atomic("renamed_claim", [])
    block = BlockValue(
        (InvValue(claim, "claim-site"), StringValue("tail")),
        fall_through=(atomic("renamed_fallthrough", []),),
        can_fall_through=True,
    )

    guarded = block.guarded(GUARD)

    assert guarded is not block
    assert guarded.statements[0].formula == implies(GUARD, claim)
    assert guarded.statements[1] is block.statements[1]
    assert guarded.fall_through == block.fall_through
    assert guarded.can_fall_through is True


def test_obligation_is_not_guard_stable() -> None:
    """Lying face: obligations weaken; they never masquerade as pure values."""
    claim = atomic("renamed_claim", [])
    obligation = InvValue(claim, "claim-site")
    guarded = obligation.guarded(GUARD)
    assert guarded is not obligation
    assert guarded.formula == implies(GUARD, claim)


def test_unknown_floor_value_stays_loud_under_guard() -> None:
    """Lying face: the category is explicit, not a permissive base default."""

    class RenamedUnguardableValue(FloorValue):
        pass

    with pytest.raises(ConstructionPanic) as excinfo:
        RenamedUnguardableValue().guarded(GUARD)
    assert excinfo.value.info.owner == "guarded"
    assert excinfo.value.info.observed == "RenamedUnguardableValue"
