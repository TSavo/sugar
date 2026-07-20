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
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


def reduce_statements(statements: tuple, ctx: object):
    """Reduce a block's statement sugars in order, threading scope.

    The factory's `_collect_iterative`, verbatim in behavior, but calling
    `stmt.desugar(ctx)` directly (the tree's sugars answer `desugar`, not the
    SugarBody `reduce` wrapper). Each outcome owns its own contribution, its
    scope extension, and whether the run continues -- the loop never branches on
    a value's kind.
    """
    entries: list[object] = []
    transforms: list = []
    fall_through: list = []
    final_ctx = ctx
    can_fall_through = True

    for index, head in enumerate(statements):
        outcome = head.desugar(final_ctx)
        final_ctx = outcome.extend_scope(final_ctx)

        contribution = outcome.contribution()
        for transform in reversed(transforms):
            contribution = transform(contribution)
        entries.extend(contribution)

        follow = outcome.follow()
        if not follow.continues:
            # An early exit (return/raise) makes the tail unreachable. Handling
            # the kept-but-unreduced tail entries (they must answer
            # inv_contribution/post_contribution as "raw states nothing") is the
            # SugarBody-wrapper job the factory did; it is not ported yet. No
            # WRITTEN tree sugar halts a block today (assert continues), so this
            # is unreachable now -- and it panics loudly rather than silently
            # dropping the tail if a newly-written halting sugar reaches it.
            if follow.keeps_rest and index + 1 < len(statements):
                raise NotImplementedError(
                    "block early-exit with a kept tail is not ported to the tree "
                    "reduction yet: port the SugarBody raw-tail wrapper when the "
                    f"first halting statement sugar lands (halted at index {index})"
                )
            can_fall_through = False
            break
        if follow.transform is not None:
            transforms.append(follow.transform)
        if follow.continuation_guard is not None:
            fall_through.append(follow.continuation_guard)

    return (
        tuple(entries),
        final_ctx,
        can_fall_through,
        tuple(fall_through) if can_fall_through else (),
    )


def reduce_body(statements: tuple, ctx: object):
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
    from sugar_lift_py_tests.outcome import Incomplete

    entries, _final_ctx, can_fall_through, fall_through = reduce_statements(
        statements, ctx
    )
    # A body that is nothing but a single propagating effect IS that effect --
    # there is no value, no fact, no exit to make a contract from. Propagate it
    # so the def surfaces as an effect (a halt), never a None-returning contract.
    if len(entries) == 1 and isinstance(entries[0], Incomplete):
        return entries[0]
    return Complete(
        BlockValue(
            entries, fall_through=fall_through, can_fall_through=can_fall_through
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
        # A function body is the root of a reduction: if no context is threaded
        # in, establish a fresh one (empty temporal scope) so statements can bind
        # names and thread refinements down the body.
        from dataclasses import replace

        from sugar_lift_py_tests.floor import SymbolicValue
        from sugar_lift_py_tests.ir import make_var

        if ctx is None:
            from sugar_lift_py_tests.context.reduce_context import ReduceContext

            ctx = ReduceContext.root(owner="FunctionUniverseSugar")

        # Bind each formal to its universe variable, so a body that reads a
        # parameter reduces against a symbolic value, not an unbound name.
        temporal = ctx.temporal
        for formal in self.formals:
            temporal = temporal.bind_value(formal, SymbolicValue(make_var(formal)))
        scoped = replace(ctx, temporal=temporal)

        # `.and_then` is the Complete/Incomplete distinction: a Complete body
        # (a BlockValue record) becomes the universe; an Incomplete body (an
        # effect) propagates untouched -- an effect is never wrapped into a
        # false contract.
        return reduce_body(self.statements, scoped).and_then(
            lambda record: Complete(
                UniverseValue(name=self.name, formals=self.formals, record=record)
            )
        )
