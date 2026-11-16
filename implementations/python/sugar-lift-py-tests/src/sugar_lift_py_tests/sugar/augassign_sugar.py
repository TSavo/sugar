from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field as dataclass_field
from typing import ClassVar

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _assertion_pair


@dataclass(frozen=True)
class AugAssignSugar(Sugar):
    """Lexical Name ``x OP= rhs`` — authenticated inplace owns the rebind.

    Composition (same substrate as attribute/subscript, store replaced by
    lexical rebind):

      1. Evaluate ``left`` (prior binding) once
      2. Evaluate ``rhs`` once
      3. ``result = project_augmented / project_inplace`` (iadd edge, NotImplemented law)
      4. On success: the iadd result IS the binding.  It is bound under the
         statement's evaluation key (``evaluation``, qualified by the live
         loop item it runs in: ``evaluation_here``), which every later read
         answers: a read substitution rewrote in the same body, a function's
         read of a module global (``FunctionDef._module_global_references``)
         and a module class body's read of a module name
         (``ClassDef._module_name_references``) are all ``EvaluationRef``.
         The name is never written, inside a live loop either: the
         recurrence reads a carried name's latest write by its key, this
         evaluation among them (``live_loop_construction._carried_writes``).
      5. On halt: no rebind (a halted arm bypasses and_then) — prior binding stands

    Substitute does **not** thread ``_make_binop`` (__add__) as the rebind.
    Dual-eval of discarded project_inplace + add-binding is the forbidden
    shape.  A statement that was never substituted has no evaluation key and
    rebinds the name alone.
    """

    name: str
    left: Sugar
    right: Sugar
    operation: Callable
    op_site: object = dataclass_field(compare=False)
    site: object = dataclass_field(compare=False)
    evaluation: str | None = None
    # Every halt (the read, the right-hand side, the inplace operation) is
    # before the rebind: its pre-halt record is the block's prefix.
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        return _assertion_pair(
            name="augassign_read_op_store",
            owner_sugar=cls.__name__,
            statements="renamed = 3\nrenamed += 2",
            truthful="renamed == 5",
            lying="renamed == 3",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        return self.left.desugar(ctx).and_then(
            lambda left: self.right.desugar(ctx).and_then(
                lambda right: project_augmented(
                    left,
                    right,
                    projector=self.operation,
                    site=self.op_site,
                    ctx=ctx,
                ).and_then(self._rebind)
            )
        )

    def _rebind(self, result) -> ExitSet:
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind, ScopeRebinds
        from sugar_lift_py_tests.outcome import ExitSet

        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here

        if self.evaluation is None:
            return ExitSet.completed(ScopeRebind(self.name, result))
        # In a live loop each item's evaluation is its own key.
        return ExitSet.completed(
            ScopeRebinds(((evaluation_here(self.evaluation), result),))
        )


def project_augmented(
    left,
    right,
    *,
    projector: Callable,
    site,
    ctx,
) -> ExitSet:
    """``left OP= right`` through the operator's own in-place edge.

    ``projector`` is the operator's ``BinaryOperator.project_inplace``: the
    receiver's ``inplace_binary_operator_with`` floor, then the ordinary
    binary after ``NotImplemented``, applied under ``ctx``, the statement's
    context.

    A parameter operand, on either side, is not deferred to a caller: ``OP=``
    is a protocol with a fallback (``__iop__``, then ``__op__``, then the
    reflected ``__rop__``), which no one dispatched method states.  So it
    takes the floor's edge like any other operand: over an undecided operand
    that is the one undecided binary law's two faces, which complete under
    their own atom and owe the undecided member, or raise something
    undetermined (#7757, audit row NEW-1).
    """
    return projector(left, right, site, ctx)


@dataclass(frozen=True)
class AttributeAugAssignSugar(Sugar):
    """The value ``receiver.attr OP= rhs`` stores: the field's in-place
    result.  The store itself is the one field store
    (``ReceiverFieldStoreStatement``, ``ReceiverFieldStoreSugar``), which
    stores this value once it completes.

    (An item target, ``receiver[index] OP= rhs``, is the one mutation door's
    read-modify-store: ``PathContainerCallSugar._read_modify_store``.)

      1. ``current`` is the field's read **before** the RHS: the one
         attribute lookup (``AttributeSugar``) off the read of the receiver
         the statement evaluated once, first, and bound under its key
         (``KeyedStoreSugar``) -- or, for ``o.x OP= yield v`` in a
         generator, the read of the key the field's value was bound under
         before the suspension (``ReceiverFieldStoreStatement.keyed_store``)
      2. Evaluate ``rhs``
      3. ``result = current OP rhs`` via ``project_augmented`` / inplace edge

    Composition is ``ExitSet.and_then`` only — no control-kind ladder.
    """

    current: Sugar
    rhs: Sugar
    operation: Callable
    op_site: object = dataclass_field(compare=False)
    site: object = dataclass_field(compare=False)
    # Every halt (the read, the RHS, the inplace operation) is before the
    # store: its pre-halt record is the block's prefix.
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> ExitSet:
        # Ordering: the field's read (off the receiver's key) → RHS → inplace.
        return self.current.desugar(ctx).and_then(
            lambda current: self.rhs.desugar(ctx).and_then(
                lambda right: project_augmented(
                    current,
                    right,
                    projector=self.operation,
                    site=self.op_site,
                    ctx=ctx,
                )
            )
        )
