"""Comprehensions are scoped folds and preserve temporal halts verbatim."""

from dataclasses import dataclass

from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_py_tests.outcome.exit_set import true_guard
from sugar_lift_py_tests.sugar.comprehension_sugar import (
    ComprehensionGeneratorSugar,
    ComprehensionSugar,
    ComprehensionTargetSugar,
)


@dataclass(frozen=True)
class _OutcomeSugar:
    outcome: object

    def desugar(self, ctx=None):
        del ctx
        return self.outcome


def _comprehension(element_outcome):
    return ComprehensionSugar(
        kind="py.listcomp",
        generators=(
            ComprehensionGeneratorSugar(
                target=ComprehensionTargetSugar(source_name="x"),
                binding_coordinate_cid="element-cid",
                iterable=_OutcomeSugar(Complete(SymbolicValue(make_var("outer_xs")))),
                filters=(),
            ),
        ),
        element=_OutcomeSugar(element_outcome),
        site="comprehension-temporal-test",
    )


def test_completed_element_builds_fold_without_exporting_target_binding():
    result = _comprehension(Complete(SymbolicValue(make_var("outer_x")))).desugar()

    assert isinstance(result, Complete)
    term = result.value.to_term(owner="test")
    assert term.name == "py.listcomp"
    assert term.args[0] == make_var("outer_xs")
    assert term.args[1].body == make_var("outer_x")
    assert term.args[1].body != make_var("element-cid")


def test_halted_element_bypasses_fold_and_retains_exact_outer_state():
    outer_state = object()
    fabricated_state = object()
    effect = ExpectationNotMetEffect("comprehension-element", "test-site")
    incoming = ExitSet((Halted(true_guard(), effect, outer_state),))

    result = _comprehension(incoming).desugar()

    assert isinstance(result, ExitSet)
    assert len(result.exits) == 1
    halted = result.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect is effect
    assert halted.state is outer_state
    assert halted.state is not fabricated_state
    assert not any(isinstance(face, Completed) for face in result.exits)
