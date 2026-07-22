"""A function definition, lowered to its universe.

This is the SPINE the whole tree lift stands on. `FunctionDef.sugar()` (on the
AST node) constructs one of these WITH the already-built sugars of its body
statements; `desugar` reduces that body in order into a `BlockValue` record and
wraps it in a `UniverseValue`. The universe's `invs()` are the stated facts the
body emits; its `post()` is the exit constraint `out == <term>` -- the callee
contract a caller's INV discharges against.

Meaning-only, node-constructed: no `owns`, no `new`, no catalog, no SugarBody.
The block reduction here is the factory's `_collect_iterative` (block_sugar.py)
with the one factory coupling removed -- it reduces each statement by calling
`.desugar(ctx)` directly instead of through a SugarBody wrapper. The floor
values it produces (BlockValue, UniverseValue, and every entry's
inv_contribution/post_contribution) are pure meaning and are reused verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.floor import BlockValue
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.outcome import Complete, ExitSet, Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class _ReducedBlock:
    entries: tuple[object, ...]
    can_fall_through: bool
    fall_through: tuple
    transforms: tuple = ()


def reduce_block_to_exitset(statements: tuple) -> ExitSet[_ReducedBlock]:
    """Reduce a suite to guarded exits before the linear compatibility view."""
    exits = ExitSet.completed(
        _ReducedBlock(entries=(), can_fall_through=True, fall_through=())
    )

    for index, head in enumerate(statements):

        def reduce_next(state: _ReducedBlock) -> ExitSet[_ReducedBlock]:
            outcome = head.desugar()
            contribution = outcome.contribution()
            for transform in reversed(state.transforms):
                contribution = transform(contribution)
            entries = (*state.entries, *contribution)

            follow = outcome.follow()
            if not follow.continues:
                if follow.keeps_rest and index + 1 < len(statements):
                    raise NotImplementedError(
                        "block early-exit with a kept tail is not ported to the "
                        "tree reduction yet: port the SugarBody raw-tail wrapper "
                        "when the first halting statement sugar lands "
                        f"(halted at index {index})"
                    )
                if isinstance(outcome, Incomplete):
                    if outcome.branch_conditions:
                        from sugar_lift_py_tests.ir import and_

                        condition = (
                            outcome.branch_conditions[0]
                            if len(outcome.branch_conditions) == 1
                            else and_(list(outcome.branch_conditions))
                        )
                        return ExitSet.conditional_halt(
                            condition, outcome.effect, state
                        )
                    return ExitSet.halted(outcome.effect)
                return ExitSet.completed(
                    _ReducedBlock(entries, can_fall_through=False, fall_through=())
                )

            transforms = state.transforms
            if follow.transform is not None:
                transforms = (*transforms, follow.transform)
            fall_through = state.fall_through
            if follow.continuation_guard is not None:
                fall_through = (*fall_through, follow.continuation_guard)
            return ExitSet.completed(
                _ReducedBlock(entries, True, fall_through, transforms)
            )

        exits = exits.sequence(reduce_next)

    return exits


def reduce_statements(statements: tuple):
    """Return the legacy tuple only after ExitSet proves one unconditional exit."""
    collapsed = reduce_block_to_exitset(statements).collapse()
    if isinstance(collapsed, Incomplete):
        return ((collapsed,), False, ())
    if not isinstance(collapsed, Complete):
        return collapsed
    state = collapsed.value
    return state.entries, state.can_fall_through, state.fall_through


def reduce_body(statements: tuple):
    """Reduce a function body to ONE Outcome, preserving Complete/Incomplete.

    A body that reduces to a value is `Complete(BlockValue(record))` -- the
    record carries every entry, including any halting effect absorbed as red
    testimony (Incomplete.contribution is the effect itself). A body that
    reduces to a bare, non-absorbed effect stays `Incomplete` and propagates:
    the caller wraps via `.and_then`, so an effect never becomes a false
    universe. Today no written statement sugar throws an effect, so this is
    always Complete -- the distinction is carried structurally for the sugars
    (calls, unsupported statements) that will.
    """
    exits = reduce_block_to_exitset(statements)
    collapsed = exits.collapse()
    if isinstance(collapsed, Incomplete):
        return collapsed
    if not isinstance(collapsed, Complete):
        return collapsed
    state = collapsed.value
    entries = state.entries
    # A body that is nothing but a single propagating effect IS that effect --
    # there is no value, no fact, no exit to make a contract from. Propagate it
    # so the def surfaces as an effect (a halt), never a None-returning contract.
    if len(entries) == 1 and isinstance(entries[0], Incomplete):
        return entries[0]
    return Complete(
        BlockValue(
            entries,
            fall_through=state.fall_through,
            can_fall_through=state.can_fall_through,
        )
    )


@dataclass(frozen=True)
class FunctionUniverseSugar(Sugar):
    """`def <name>(<formals>): <body>` -> the body's universe.

    Constructed by `FunctionDef.sugar()` with the body statements ALREADY
    reduced to their own sugars (child-before-parent). `desugar` reduces the
    block and wraps it; the universe projects invs/post off the record.
    """

    name: str
    formals: tuple[str, ...]
    statements: tuple  # the body statements' sugars, in source order
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        # A function whose body returns its argument; the caller asserts the
        # returned value. The truthful twin's universe post (out == z) discharges
        # the assert; the lying twin's asserted value contradicts it.
        prefix = "def A(z):\n    return z\n\n"
        return _call_pair(
            name="function_universe",
            owner_sugar="FunctionUniverseSugar",
            truthful=prefix + "def test_a():\n    assert A(2) == 2\n",
            lying=prefix + "def test_a():\n    assert A(2) == 3\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # No context. The body was already SUBSTITUTED (FunctionDef.sugar), so
        # there is nothing temporal to thread: a formal reaches its NameSugar as
        # a free name and becomes its own symbolic Var, a local assignment is
        # inert (spent by substitute), a conditional binding is an IfExp phi. The
        # block reduction consults no scope -- ctx.temporal is gone, and the
        # `with`/nonlocal as-binding paths that once needed extend_scope are not
        # lifted on the tree (they panic SugarNotWritten), so nothing calls it.
        del ctx

        # `.and_then` is the Complete/Incomplete distinction: a Complete body
        # (a BlockValue record) becomes the universe; an Incomplete body (an
        # effect) propagates untouched -- an effect is never wrapped into a
        # false contract.
        return reduce_body(self.statements).and_then(
            lambda record: Complete(
                UniverseValue(name=self.name, formals=self.formals, record=record)
            )
        )
