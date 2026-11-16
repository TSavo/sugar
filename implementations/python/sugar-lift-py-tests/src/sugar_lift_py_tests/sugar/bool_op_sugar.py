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


def truth_of(value, site, *, owner: str):
    """``bool(value)`` taken once at ``site``: the one truth rule.

    Every truth question takes the operand's truth through here: ``a and b``
    / ``a or b`` (on each non-final operand), ``not x``, the negation in
    ``a != b`` and ``a not in b``, an ``if`` / ``while`` / ``assert`` /
    conditional-expression test, each arm of a guarded value
    (``GuardedValue.truth``), and a ground call
    result's dug body (``CallSiteValue._construct_decidable_truth``).

    The value is consumed through the one operand door (``consume_operands``):
    a walrus or a callee's store it carries rides the truth, and the rule
    answers for the value it presents.

    - A value whose truth is not decided here -- it denotes a runtime value
      whose type the lift did not decide (``runtime_type_is_decided``), so
      its ``__bool__`` / ``__len__`` is undecided and taking its truth may
      run code (#7585 / #7681) -- is the undecided member's two faces
      (:func:`_unanswered_truth`).  A formal (a parameter, a contract input:
      truth is ``__bool__`` then ``__len__`` then ``True``, a protocol with a
      fallback no one dispatched method states, so it is the two faces
      whether or not its class is an input, #7757 NEW-1), an opaque call
      result, a bare symbolic
      value, an imported module member (``if mod.FLAG:``), a non-dict mutable
      global, the exception an undetermined raise threw and its type, and the
      class a raise threw (``RaisedExitTypeValue``) all take them, each with
      its own term at its own site.  Nothing waits on a caller's actual.
      Nothing stops here by
      name: a value whose term cannot be stated stops at its own
      ``to_term``.
    - A decided value answers through its own truth floor.
    """
    from sugar_lift_py_tests.floor.named_expression_value import consume_operands

    return consume_operands(
        lambda presented: _presented_truth(presented, site, owner=owner), value
    )


def _presented_truth(value, site, *, owner: str):
    """:func:`truth_of` for the value an operand presents (no walrus on it)."""
    if _truth_is_undecided(value):
        return _unanswered_truth(value, site, owner=owner)
    return value.truth(site)


def _truth_is_undecided(value) -> bool:
    """Whether ``bool(value)`` is not decided here: ``value`` denotes a
    runtime value whose type the lift did not decide."""
    denotes = getattr(value, "denotes_value", None)
    decided = getattr(value, "runtime_type_is_decided", None)
    return bool(
        callable(denotes) and callable(decided) and denotes() and not decided()
    )


def _unanswered_truth(value, site, *, owner: str):
    """``bool(value)`` not decided here: the undecided member's two faces.

    The truth completes with the undecided ``py.truthy(<operand term>)`` only
    under ``python:truth.completes(python:truth(<operand term>, <site>))``,
    keyed on the exact source site and its occurrence so two truth tests of
    one term are never forced to agree, and halts with an
    ``UndeterminedRaiseEffect`` (producer ``owner``) under the complement.
    No exception type is named and no truth is decided; both faces owe the
    one ``undecided`` member (reason ``unanswered``) at the site
    (``ExitSet.two_faced``).  The operand's term is the one an undecided read
    names it by (``object_identity.identity_term``); a value with no term
    stops there, under its own name, and a site with no coordinate stops at
    its key (``occurrence.site_coordinate_cid``).
    """
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.object_identity import identity_term
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.ir import atomic, ctor, py_truthy, str_const
    from sugar_lift_py_tests.occurrence import occurrence_key

    operand = identity_term(value, site, "receiver", owner=owner)
    key = occurrence_key(site)
    return ExitSet.two_faced(
        PredicateValue(
            py_truthy(operand), site, operand_callsites=tuple(value.callsites())
        ),
        UndeterminedRaiseEffect(
            blame=str(site),
            occurrence=key,
            producer_node_owner=owner,
            site=site,
        ),
        guard=atomic(
            "python:truth.completes",
            [ctor("python:truth", (operand, str_const(key)))],
        ),
        site=site,
    )


def negated_truth_of(value, site, *, owner: str):
    """``not bool(value)``: the one truth rule, then only its completed truth
    negated.

    ``not x``, ``a != b`` (``not (a == b)``) and ``a not in b`` (``not (a in
    b)``) negate through here.  A halted truth has no bool to flip, so it
    stands as it is; the value is never asked to negate itself, so an
    undecided value (a formal, an unanswered result) takes its truth by the
    same rule first.
    """
    return truth_of(value, site, owner=owner).and_then(
        lambda truth: truth.negate()
    )


def boolop_truth_selection(value, site):
    """``bool(value)`` for ``a and b`` / ``a or b``, keeping ``value``.

    The truth is taken through the one truth rule; the operand itself is
    what the stopping face returns.  Every operand reaches this at
    construction, a formal's too: its truth is the undecided member's two
    faces (:func:`_unanswered_truth`, #7757 NEW-1), and the formal is what
    the stopping face returns.
    """
    from sugar_lift_py_tests.floor.boolop_truth_selection import (
        BoolOpTruthSelection,
    )

    return truth_of(value, site, owner="BoolOpSugar.truth").and_then(
        lambda truth_value: ExitSet.completed(BoolOpTruthSelection(value, truth_value))
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

    # The operand's truth is taken once through the one truth rule, a
    # formal's as every other undecided value's (its two faces, #7757
    # NEW-1); the operand itself is what the stopping face returns.
    tested = boolop_truth_selection(value, site)

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
