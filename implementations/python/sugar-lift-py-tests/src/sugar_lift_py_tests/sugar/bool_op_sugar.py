"""Python operand-selecting short-circuit operations ``and`` and ``or``.

Each non-final operand is evaluated once and truth-tested once.  Its stopping
face returns that exact operand; only its continuing face evaluates the next
operand.  The final operand is returned without truth coercion.  A halted truth
dispatch halts the sequence before any later operand is evaluated.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.ir import Term
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)
from sugar_lift_py_tests.sugar.witnesses import _boolop_wrapped_pair

_BOOL_OPERATOR_COORDINATE = {
    "And": "and",
    "Or": "or",
}


def _refuse_undecided_truth(value, site, *, operator: str, floor: str) -> None:
    """Keep an undecided ``bool(operand)`` with no two-faced form loud.

    The one truth rule (:func:`truth_of`) answers an undecided call result or
    bare symbolic operand with its two faces.  Any other value that denotes a
    runtime value of undecided type has no truth floor that could state those
    faces: emitting ``py.truthy`` invents a total completion, and naming an
    exception invents its identity.  It is refused by name at the producer
    that asked (``floor``), until source-visible type testimony decides.
    """
    denotes = getattr(value, "denotes_value", None)
    decided = getattr(value, "runtime_type_is_decided", None)
    if not callable(denotes) or not callable(decided):
        return
    if not denotes() or decided():
        return

    from sugar_source_tree.panic import SugarNotWritten

    raise SugarNotWritten(
        blame=site,
        owner=floor,
        observed=f"{type(value).__name__} {operator}",
        requested=(
            "source-visible native truth testimony selecting completion "
            "or an authenticated exceptional exit"
        ),
        fix=(
            "preserve the undecided third value at the truth producer; "
            "resolve native operand types and their __bool__/__len__ bodies "
            "from source, or retain this named refusal without inventing an "
            "exception identity"
        ),
    )


def truth_of(value, site, *, operator: str, owner: str, floor: str):
    """``bool(value)`` taken once at ``site``: the one truth rule.

    ``a and b`` / ``a or b`` (on each non-final operand), ``not x`` and the
    negation in ``a != b`` all take the operand's truth through here.

    - An opaque call result or a bare symbolic operand (no formal coordinate)
      of undecided runtime type has undecided ``__bool__`` / ``__len__``, and
      taking its truth may run code (#7585 / #7681): its truth completes with
      the undecided ``py.truthy`` only under ``python:truth.completes(
      python:truth(<operand term>, <site>))``, keyed on the exact source site,
      and halts with an ``UndeterminedRaiseEffect`` (producer ``owner``) under
      the complement.  No exception type is named and no truth is decided;
      both faces owe the one ``undecided`` member (reason ``unanswered``) at
      the site (``ExitSet.two_faced``).
    - Any other undecided-type value is refused by name (``floor``).
    - A decided value answers through its own truth floor.

    A formal's truth is not taken here: its producer defers it to the
    caller's actual on the native operation carrier.
    """
    if _is_undecided_call_result(value) or _is_undecided_symbolic_operand(value):
        from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
        from sugar_lift_py_tests.ir import atomic, ctor, str_const
        from sugar_lift_py_tests.occurrence import occurrence_key
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            plain_completed_value,
        )

        truth = value.truth(site)
        truth_value = plain_completed_value(truth)
        if truth_value is None:
            # A truth that did not complete plainly is left as produced.
            return truth
        key = occurrence_key(site)
        term = ctor("python:truth", (value.to_term(owner=owner), str_const(key)))
        return ExitSet.two_faced(
            truth_value,
            UndeterminedRaiseEffect(
                blame=str(site),
                occurrence=key,
                producer_node_owner=owner,
                site=site,
            ),
            guard=atomic("python:truth.completes", [term]),
            site=site,
        )
    _refuse_undecided_truth(value, site, operator=operator, floor=floor)
    return value.truth(site)


def _is_undecided_call_result(value) -> bool:
    """An opaque call result whose runtime type the lift did not decide."""
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

    if not isinstance(value, CallSiteValue):
        return False
    denotes = getattr(value, "denotes_value", None)
    decided = getattr(value, "runtime_type_is_decided", None)
    return bool(
        callable(denotes) and callable(decided) and denotes() and not decided()
    )


def _is_undecided_symbolic_operand(value) -> bool:
    """A bare symbolic term (no formal coordinate) of undecided runtime type.

    ``encoding or "utf-8"`` inside ``pandas.io.common.get_handle`` when the
    manager derivation projects the frame with the caller's actual: nothing
    names the operand's Python type, so ``bool(operand)`` may complete or
    raise exactly as for an opaque call result.  A formal coordinate is
    excluded: it is discharged against the caller's actual instead.
    """
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

    return (
        type(value) is SymbolicValue
        and value.formal_coordinate is None
        and value.denotes_value()
        and not value.runtime_type_is_decided()
    )


def select_boolop_operand(
    value,
    *,
    op_kind: str,
    site,
    index: int,
    on_continue,
):
    """Truth-test one already-evaluated operand and select its Python face."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.outcome.exit_set import (
        complement_guard,
        false_guard,
        partition,
        true_guard,
    )

    stop_formula = false_guard() if op_kind == "And" else true_guard()
    continue_formula = true_guard() if op_kind == "And" else false_guard()

    def truth_formula(truth_value):
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        if isinstance(truth_value, TrueBoolLiteralSugar):
            return true_guard()
        if isinstance(truth_value, FalseBoolLiteralSugar):
            return false_guard()
        if isinstance(truth_value, PredicateValue):
            from sugar_lift_py_tests.sugar.if_sugar import _ground_atomic_truth

            # Same door IfSugar already uses: `=("b", "^")` is a decided
            # constant atom, not a symbolic split. Leaving it raw forces
            # later `and` operands (including is_fully_escaped) to run.
            ground = _ground_atomic_truth(truth_value.formula)
            if ground is True:
                return true_guard()
            if ground is False:
                return false_guard()
            return truth_value.formula

        from sugar_lift_py_tests.gap.info import GapKind, GapLocus
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="BoolOpSugar.truth_formula",
            blame=site,
            observed=type(truth_value).__name__,
            requested="a truth-floor boolean or PredicateValue",
            fix=(
                "make the selected operand's truth floor return its native "
                "truth value without re-evaluating the operand"
            ),
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )

    def continue_from(selected_operand, formula):
        if formula == stop_formula:
            return ExitSet.completed(selected_operand)
        if formula == continue_formula:
            return on_continue()

        rhs_guard = formula if op_kind == "And" else complement_guard(formula)
        rhs_face, stop_face = partition(("BoolOpSugar", str(site), index, op_kind))
        continued = on_continue()
        stopped = ExitSet.completed(
            selected_operand, complement_guard(rhs_guard)
        )
        if isinstance(continued, NativeOperationExitCarrierV1):
            return continued.short_circuit(
                continuing_guard=rhs_guard,
                stopped=stopped,
                continuing_face=rhs_face,
                stopped_face=stop_face,
            )
        rhs = continued.guarded(rhs_guard, rhs_face)
        return rhs.union(stopped.guarded(true_guard(), stop_face))

    formal_coordinate = getattr(value, "formal_coordinate", None)
    if formal_coordinate is not None:
        tested = NativeOperationExitCarrierV1.mint(
            site=site,
            operator="boolop_truth",
            operands=(value,),
            coordinates=(formal_coordinate,),
        )
    else:
        # The operand's truth is taken once through the one truth rule; the
        # operand itself is what the stopping face returns.
        from sugar_lift_py_tests.floor.boolop_truth_selection import (
            BoolOpTruthSelection,
        )

        tested = truth_of(
            value,
            site,
            operator=_BOOL_OPERATOR_COORDINATE[op_kind],
            owner="BoolOpSugar.truth",
            floor="boolean_operation_exception_floor",
        ).and_then(
            lambda truth_value: ExitSet.completed(
                BoolOpTruthSelection(value, truth_value)
            )
        )

    return tested.and_then(
        lambda selection: continue_from(
            selection.operand, truth_formula(selection.truth_value)
        )
    )


@dataclass(frozen=True)
class BoolOpSugar(ConstructedTermSugar):
    op_kind: str  # "And" | "Or"
    values: tuple[ConstructedTermSugar, ...]
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        for value in self.values:
            require_constructed_term_sugar(value, owner="BoolOpSugar.values")

    @classmethod
    def witnesses(cls):
        # `(z == 1) and (z != 2)` holds at z == 1 and fails when the asserted
        # value contradicts a conjunct.
        return _boolop_wrapped_pair(
            name="boolop_and",
            owner_sugar="BoolOpSugar",
            truthful="(1 == 1) and (2 == 2)",
            lying="(1 == 1) and (2 == 3)",
        )

    def to_term(self, *, owner: str) -> Term:
        """Project the authenticated operator and ordered operands canonically."""
        from sugar_lift_py_tests.ir import ctor, str_const

        if self.op_kind not in _BOOL_OPERATOR_COORDINATE:
            raise ValueError(
                f"{owner} requires an authenticated BoolOp operator, got {self.op_kind!r}"
            )
        if len(self.values) < 2:
            raise ValueError(f"{owner} requires at least two BoolOp operands")

        operands = [value.to_term(owner=owner) for value in self.values]

        return ctor(
            "python:bool-op-construction",
            (
                str_const(_BOOL_OPERATOR_COORDINATE[self.op_kind]),
                self.occurrence_term(owner=owner),
                ctor(
                    "python:bool-op-operands",
                    tuple(operands),
                    symbol_kind="coordinate",
                ),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            evaluated_after,
            written_by,
        )
        from sugar_lift_py_tests.outcome.exit_set import factored_operand

        def reduce_from(index: int, operand_ctx, inside=()):
            operand = self.values[index]
            # The operand runs inside the operand doors of the ones before
            # it (``inside``), which lay their stores in its halts; its
            # record-less halt is recorded at its head, in the context
            # their writes left (``evaluated_after``).
            evaluated = factored_operand(
                evaluated_after((), operand, operand_ctx, inside=inside)
            )

            # Python returns the final operand; it does not call bool(final).
            # Its value is the result on the face that reached it, so a
            # walrus in it rides that face only.
            if index == len(self.values) - 1:
                return evaluated

            # A non-final operand goes through the one operand door: a walrus
            # in it binds on its stopping face and on every face the later
            # operands reach, since it ran on both.  The later operands are
            # evaluated after it, so they reduce with its binds applied
            # (``written_by``): a read of its walrus there is a reference to
            # the walrus's key (``nodes._scope_after``: ``(m := f()) and
            # m.group(1)``).
            return evaluated.and_then(
                lambda value: consume_operands(
                    lambda presented: select_boolop_operand(
                        presented,
                        op_kind=self.op_kind,
                        site=self.site,
                        index=index,
                        on_continue=lambda: reduce_from(
                            index + 1,
                            written_by(value, operand_ctx),
                            (*inside, value),
                        ),
                    ),
                    value,
                )
            )

        return reduce_from(0, ctx)
