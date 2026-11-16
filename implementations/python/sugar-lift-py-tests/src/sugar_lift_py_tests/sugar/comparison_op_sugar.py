"""A comparison `<left> <op> <right>` for the ordering family and `!=`.

`==` keeps its own sugar (EqualityOpSugar, which also refines); this owns the
rest: the node carries the operator, and this routes the reduced left value to
the floor method that operator names (`less_than`, `greater_equal`, ...). Each
is `py.lt` / `py.le` / ... -- vendor comparison, not SMT `<`, so the sort
universe adjudicates (same NaN/reflexivity split as py.eq). `!=` is `==` negated:
Python `a != b` is `not (a == b)`, so it stands on the equals floor and negates
that predicate -- never a bespoke inequality atom.

Compare construction is partitioned by law — not one monomorphic refusal:

- **ordering** (`<` `<=` `>` `>=`): rich-method dispatch may complete or raise;
  the left value's ordering floor answers it whole
- **membership** (`in` / `not in`): container owns ``__contains__`` / iteration
- **equality** (`==` / `!=`): ``__eq__`` may complete or raise; the left
  value's equals floor answers it whole (``equality_atom.answered_equality``)
- **identity** (`is` / `is not`): total object identity; never user-code dispatch
- **chaining** (`a < b < c`): pair laws composed under short-circuit ``And`` at
  ``Compare._construct_sugar`` (ChainedCompareSugar carrying adjacent values)

Each value type answers an undecided comparison itself, with the one keyed
two-faced ``python:compare_result`` (:func:`undecided_dispatch_faces`), or
decides it where it truly decides: no halt is patched onto a bare predicate
after the floor answered (#7757).
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)
from sugar_lift_py_tests.sugar.witnesses import _boolop_wrapped_pair

# Comparison operator kind -> the floor method that owns its meaning. `Eq` is
# absent (EqualityOpSugar owns it); `NotEq` is absent (equals + negate, below).
COMPARE_METHODS: dict[str, str] = {
    "Lt": "less_than",
    "LtE": "less_equal",
    "Gt": "greater_than",
    "GtE": "greater_equal",
}

# Every comparison kind this sugar owns (Eq is EqualityOpSugar's, not here).
# `NotEq`/`IsNot`/`NotIn` are their positive form negated; `Is` stands on the
# identity floor; `In` on the membership floor (the CONTAINER is the right
# operand: `x in xs` is `xs.contains(x)`).
COMPARISON_KINDS = frozenset(COMPARE_METHODS) | {"NotEq", "Is", "IsNot", "In", "NotIn"}


def construct_identity_comparison(left, right, site, *, negated: bool = False):
    """Identity law: total object identity; never a dual-edge raise partition.

    Python ``is`` / ``is not`` does not dispatch user code, so there is no
    exceptional face to publish. The floor's ``is_identical`` atom is the whole
    meaning; ``site`` is the identity floor's blame coordinate.
    """
    outcome = left.is_identical(right, site)
    if not negated:
        return outcome
    return outcome.and_then(lambda predicate: predicate.negate())


def undecided_dispatch_faces(predicate, site, op_kind: str):
    """Two faces for one undecided rich-comparison dispatch.

    The one answer every value type gives a comparison whose operands'
    runtime types select a method this frame did not look at (the #7585
    law): the floor's undecided equality (``equality_atom.
    answered_equality``), ordering (:func:`undecided_ordering_faces`) and
    membership (``FloorValue.undecided_contains``).  It completes with the
    truth of the comparison's value, keyed per evaluation
    (``python:truth_result(python:compare_result(<kind>, left, right,
    <key>), <key>)``), only under ``python:compare.completes(
    python:compare(op, left, right, <key>))``, and halts with an
    ``UndeterminedRaiseEffect`` (owner ``UndecidedCompare:<op>``) under the
    complement.  No exception type is named: the halt is undetermined.
    """
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.ir import atomic, ctor, str_const
    from sugar_lift_py_tests.occurrence import occurrence_key
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    key = occurrence_key(site)
    # The completes atom names the operation it is about -- its operator and
    # the operand terms of the comparison the predicate states -- as every
    # undecided operation's does (``python:binary_op(<result>, <key>)``,
    # ``python:subscript(<term>, <key>)``): where a joined contract decides
    # the operands' types at prove, the solver reads whether Python completes
    # the comparison, and the member this operation owes is answered there
    # (#7766).  Where nothing decides them it stays the opaque atom it was.
    dispatch = ctor(
        "python:compare",
        (str_const(op_kind), *compared_terms(predicate), str_const(key)),
    )
    completes = atomic("python:compare.completes", [dispatch])
    # The completed value is keyed per evaluation, as the completes atom and
    # the halt are (#7757 NEW-1, the owner's key rule): two evaluations of
    # one comparison over the same operand terms (a counting ``__eq__``
    # asked twice) are two unknowns, so a truthful ``(p == q) != (p == q)``
    # cannot read ``unsat``.  Prove reads the keyed result over operands
    # whose builtin type it decides exactly as the unkeyed atom.
    from dataclasses import replace

    return ExitSet.two_faced(
        replace(predicate, formula=keyed_comparison(predicate.formula, key)),
        UndeterminedRaiseEffect(
            blame=str(site),
            occurrence=key,
            producer_node_owner=f"UndecidedCompare:{op_kind}",
            site=site,
        ),
        guard=completes,
        site=site,
    )


# The undecided Python comparison atoms a floor states (``py.eq``,
# ``py.lt``, ... ``py.in``), by the operator kind their keyed result names.
# The theory atoms (``=``, ``<``, ...) a sort warrant decides are not here:
# their operands' type is stated, and they stay as they are.
_KEYED_COMPARISON_KINDS: dict[str, str] = {
    "py.eq": "Eq",
    "py.lt": "Lt",
    "py.le": "LtE",
    "py.gt": "Gt",
    "py.ge": "GtE",
    "py.in": "In",
}


def keyed_comparison(formula, key: str):
    """``formula`` with each undecided comparison atom in it keyed per
    evaluation: ``py.<op>(<left>, <right>)`` becomes the one truth rule's
    atom over the comparison's value, ``python:truth_result(
    python:compare_result("<Kind>", <left>, <right>, <key>), <key>)``
    (``floor_value.undecided_truth_result`` /
    ``floor_value.undecided_compare_result``), the operands in the atom's
    own order (``py.in(item, container)`` stays item first).  The
    comparison is always a value and never a predicate: carried as a value
    (``PredicateValue.to_term``) it is the ``python:compare_result`` term.
    Any other atom is unchanged; a connective is rebuilt over its keyed
    operands."""
    from sugar_lift_py_tests.floor.floor_value import (
        undecided_compare_result,
        undecided_truth_result,
    )
    from sugar_lift_py_tests.ir import _Atomic, _Connective, connective

    if isinstance(formula, _Atomic):
        kind = _KEYED_COMPARISON_KINDS.get(formula.name)
        if kind is None or len(formula.args) != 2:
            return formula
        left, right = formula.args
        return undecided_truth_result(
            undecided_compare_result(kind, left, right, key), key
        )
    if isinstance(formula, _Connective):
        return connective(
            formula.kind,
            [keyed_comparison(operand, key) for operand in formula.operands],
        )
    return formula


def compared_terms(predicate) -> tuple:
    """The operand terms of the one comparison ``predicate`` states: the
    arguments of its atom (``py.eq(l, r)``, ``py.lt(l, r)``, ``py.in(item,
    container)``), in the atom's own order.

    A predicate that is not one atom (a comparison the floor answered with a
    connective) names no operand pair: its completes atom then names only the
    operator and the site, nothing at prove decides it, and its member stays
    owed.
    """
    from sugar_lift_py_tests.ir import _Atomic

    formula = predicate.formula
    if isinstance(formula, _Atomic):
        return tuple(formula.args)
    return ()


_ORDERING_BY_OPERATOR: dict[str, tuple[str, str]] = {
    "<": ("Lt", "lt"),
    "<=": ("LtE", "le"),
    ">": ("Gt", "gt"),
    ">=": ("GtE", "ge"),
}


def undecided_ordering_faces(left, right, site, *, operator: str):
    """Two faces for ``left <op> right`` whose operand runtime types are undecided.

    The same law as undecided ``==``: the rich method (and its reflection)
    Python selects is one this frame did not look at, so the comparison
    completes with the undecided ``py.lt/le/gt/ge`` predicate, keyed per
    evaluation: the truth of the comparison's value
    (``python:truth_result(python:compare_result("Lt", left, right, <key>),
    <key>)`` ..., :func:`keyed_comparison`), only under
    ``python:compare.completes(python:compare(op, left, right, <key>))`` and
    halts with an
    ``UndeterminedRaiseEffect`` (owner ``UndecidedCompare:<op>``) under the
    complement.  Nothing is folded and no ``TypeError`` is invented.
    """
    from sugar_lift_py_tests.floor.comparison_atom import resolve_comparison_atom
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue

    op_kind, atom_operator = _ORDERING_BY_OPERATOR[operator]
    predicate = PredicateValue(
        resolve_comparison_atom(atom_operator, left, right, owner=str(site)),
        site,
        operand_callsites=(*left.callsites(), *right.callsites()),
    )
    return undecided_dispatch_faces(predicate, site, op_kind)


def _operation_receiver_outcome(value, ctx, *, owner: str):
    """Project ``value`` to the receiver(s) that own the next comparison.

    Sequenced through the ExitSet algebra; a projected value that is itself
    a different producer is projected again, so every completed face ends on
    a value that is its own receiver.
    """
    from sugar_lift_py_tests.outcome import ExitSet

    def settle(projected):
        if projected is value:
            return ExitSet.completed(projected)
        return _operation_receiver_outcome(projected, ctx, owner=owner)

    return value.project_operation_receiver_outcome(ctx, owner=owner).and_then(settle)


@dataclass(frozen=True)
class ComparisonOpSugar(ConstructedTermSugar):
    op_kind: str
    left: ConstructedTermSugar
    right: ConstructedTermSugar
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        if self.op_kind not in COMPARISON_KINDS:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="ComparisonOpSugar",
                blame=self.site,
                observed=f"comparison operator {self.op_kind!r} has no ComparisonOpSugar arm",
                requested="a written comparison kind in COMPARISON_KINDS",
                fix=f"enroll {self.op_kind!r} in ComparisonOpSugar or refuse earlier",
            )
        require_constructed_term_sugar(self.left, owner="ComparisonOpSugar.left")
        require_constructed_term_sugar(self.right, owner="ComparisonOpSugar.right")

    @classmethod
    def witnesses(cls):
        return _boolop_wrapped_pair(
            name="comparison_lt",
            owner_sugar="ComparisonOpSugar",
            truthful="1 < 2",
            lying="2 < 1",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:comparison-construction",
            (
                self.occurrence_term(owner=owner),
                str_const(self.op_kind),
                self.left.to_term(owner=owner),
                self.right.to_term(owner=owner),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            evaluated_after,
            written_by,
        )

        # The right side is evaluated after the left, with the left's writes
        # applied, and its halt carries them (``evaluated_after``).  The
        # comparison runs on the values the sides present, through the one
        # operand door (``consume_operands``), as a chained comparison's leg
        # does: a write a side carries (a walrus's bind, a callee's store, the
        # record of what a call may have changed, ``bind_after_call``) rides
        # the comparison's completed result, and its halts carry it.  Handed
        # the carrier itself, ``in`` asked the carrier for ``contains`` (a
        # construction panic) and the undecided-dispatch rule asked it
        # whether it denotes a value, dropping the undecided halt (#7757 H7).
        return self.left.desugar(ctx).and_then(
            lambda left: evaluated_after(
                (left,), self.right, written_by(left, ctx)
            ).and_then(
                lambda right: consume_operands(
                    lambda presented_left, presented_right: self.apply_reduced(
                        presented_left, presented_right, ctx
                    ),
                    left,
                    right,
                )
            )
        )

    def apply_reduced(self, left, right, ctx: object = None) -> ExitSet:
        """Apply this leg's existing law to operands already evaluated once.

        Each operand is sequenced through its operation-receiver ExitSet: a
        constructed object whose construction may raise is a partition of
        receiver states, and the comparison runs on each receiver it can be
        (a construction halt leaves as itself), exactly as a call actual does.
        A projection that exposes another producer (a call whose authenticated
        return is that partition) is projected again until the receiver owns
        itself.
        """
        return _operation_receiver_outcome(
            left, ctx, owner="ComparisonOpSugar left operation receiver"
        ).and_then(
            lambda left_receiver: _operation_receiver_outcome(
                right, ctx, owner="ComparisonOpSugar right operation receiver"
            ).and_then(
                lambda right_receiver: self._apply(left_receiver, right_receiver, ctx)
            )
        )

    def _membership(self, container, item):
        """Membership law: container owns containment; undecided dispatch dual-edges.

        A parameter on either side is not deferred to a caller: ``in`` is
        ``__contains__``, then iteration, then the ``__getitem__`` sequence
        protocol, which no one dispatched method states.  The container's own
        floor answers it, two-faced wherever a type is undecided (#7757,
        audit row NEW-1): its answer is the whole meaning, with no halt
        patched on afterwards (#7757 H10)."""
        return container.contains(item, self.site)

    def _ordering(self, left, right, ctx):
        """Ordering law: left owns the rich method; undecided dispatch dual-edges."""
        from sugar_lift_py_tests.floor.floor_value import ORDERING_FLOOR_OPERATIONS

        method = COMPARE_METHODS[self.op_kind]
        # The ordering floor's own explicit call (#7757), never a method
        # looked up by its name.  A parameter operand is not deferred to a
        # caller: an ordering is the rich method, then its reflection after
        # ``NotImplemented`` (the subclass rule first), which no one
        # dispatched method states, so an undecided operand takes the
        # undecided ordering's two faces (audit row NEW-1) -- from the
        # floor itself (``FloorValue._refuse_ordering_meaning``), whose
        # answer is the whole meaning (#7757).
        return ORDERING_FLOOR_OPERATIONS[method](left, right, self.site, ctx)

    def _negated_truth(self, result):
        """``not result`` for the result ``a != b`` (``a == b``'s) or ``a not
        in b`` (``a in b``'s) negates.

        The result is whatever the positive comparison completed with: a
        decided boolean, or -- for a comparison its caller left unanswered,
        or one whose operands' types are undecided -- a value whose ``bool``
        may run code.  Its truth is taken through the one truth rule and only
        the completed truth is negated (``bool_op_sugar.negated_truth_of``);
        the value is never asked to negate itself.
        """
        from sugar_lift_py_tests.sugar.bool_op_sugar import negated_truth_of

        return negated_truth_of(
            result, self.site, owner=f"ComparisonOpSugar.{self.op_kind}"
        )

    def _apply(self, left, right, ctx):
        if self.op_kind == "NotEq":
            from sugar_lift_py_tests.floor.object_value import ObjectValue

            # A class's own ``__ne__`` (or one the lookup does not decide
            # absent) replaces ``object.__ne__``'s ``not (a == b)``: the
            # left's is called exactly as ``==`` calls ``__eq__``
            # (``ObjectValue.not_equals``); the right's is Python's
            # reflection, ``type(b).__ne__(b, a)``, after the left's
            # ``NotImplemented`` -- the one unanswered call, two faces, owed,
            # its halt kept.  Never a construction refusal (#7757 H13).
            if isinstance(left, ObjectValue) and left.has_method("__ne__") is not False:
                return left.not_equals(right, self.site, ctx)
            if (
                isinstance(right, ObjectValue)
                and right.has_method("__ne__") is not False
            ):
                return right.unanswered_method_call("__ne__", (left,), (), self.site)
            # Equality law: a != b is not (a == b); the equals floor's
            # answer, then the completed truth negated.  A parameter operand
            # is not deferred to a caller (``==``'s reflection and identity
            # fallback are no one dispatched method): the floor answers an
            # undecided operand with the undecided equality's two faces
            # (``equality_atom.answered_equality``), whose halt stands.
            return left.equals(right, self.site, ctx).and_then(self._negated_truth)
        if self.op_kind == "Is":
            return construct_identity_comparison(left, right, self.site, negated=False)
        if self.op_kind == "IsNot":
            return construct_identity_comparison(left, right, self.site, negated=True)
        if self.op_kind == "In":
            # a in b: the CONTAINER (right) owns membership -- b.contains(a).
            return self._membership(right, left)
        if self.op_kind == "NotIn":
            # a not in b is not (a in b): membership floor, then the truth of
            # its result negated.
            return self._membership(right, left).and_then(self._negated_truth)
        return self._ordering(left, right, ctx)
