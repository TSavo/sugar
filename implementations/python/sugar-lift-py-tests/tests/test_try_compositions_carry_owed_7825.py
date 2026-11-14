"""#7825: ``try``/``finally`` and ``except*`` compose through ``ExitSet.sequence``.

An arm owes what any path into it incurred. A ``finally`` runs beneath every
arm that reaches it, and an ``except*`` handler runs beneath the body halt it
handles, so the arm that leaves either construct owes what the incoming arm
owed AND what the cleanup or handler owed. Both constructs now compose those
continuations through the one door (``sequence``, with ``consume=`` for the
halts the construct owns) instead of rebuilding arms by hand.
"""

from __future__ import annotations

from types import SimpleNamespace

from sugar_lift_py_tests.context.reduce_context import ReduceContext
from sugar_lift_py_tests.effect.authenticated_raise_locus import AuthenticatedRaiseLocus
from sugar_lift_py_tests.effect.grouped_raise_effect import GroupedRaiseEffect
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted, true_guard
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_py_tests.sugar.sugar_base import Sugar


class _Fixed(Sugar):
    """A statement whose reduction is handed in."""

    def __init__(self, build):
        self.build = build

    def desugar(self, ctx=None):
        return self.build(ctx)

    @classmethod
    def witnesses(cls):
        return ()


def _owing_completion(ctx, debt):
    return ExitSet(
        (
            Completed(
                true_guard(),
                _ReducedBlock(
                    entries=(), can_fall_through=True, fall_through=(), context=ctx
                ),
                owed=(debt,),
            ),
        )
    )


def test_a_halt_through_an_owing_finally_owes_both() -> None:
    from sugar_lift_py_tests.sugar.try_sugar import _and_finally_with_raise_context

    ctx = ReduceContext.root(owner="finally_owes_7825")
    raised = RaiseEffect(
        exception_name="ValueError",
        occurrence=AuthenticatedRaiseLocus.of("body:ve:7825"),
    )
    pre_finally = ExitSet((Halted(true_guard(), raised, None, owed=("debt:body",)),))
    finalbody = (_Fixed(lambda c: _owing_completion(c, "debt:finally")),)

    after = _and_finally_with_raise_context(
        pre_finally, finalbody, ctx=ctx, site="try-site:7825"
    )

    # The finally falls through, so it restores the body halt...
    assert [type(arm) for arm in after.exits] == [Halted], after.exits
    (halt,) = after.exits
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "ValueError"
    # ...and the restored halt owes what the body owed and what the finally owed.
    assert halt.owed == ("debt:body", "debt:finally")


def _synthetic_class(name: str):
    """One shared ClassValue identity for matcher/leaf (is-subtype uses `is`)."""
    from sugar_lift_py_tests.floor import BlockValue, ClassValue
    from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
        AuthenticatedExceptionTypeValue,
    )
    from sugar_lift_py_tests.ir import ctor, str_const

    identity = ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )
    cls = ClassValue(name, (), BlockValue(()))
    typed = AuthenticatedExceptionTypeValue(cls, identity, (identity,), class_value=cls)
    return typed, identity


def test_an_owing_except_star_handler_makes_the_result_owe_it() -> None:
    from sugar_lift_py_tests.ir import atomic, str_const
    from sugar_lift_py_tests.sugar.try_star_sugar import TryStarSugar

    ve_typed, ve_id = _synthetic_class("ValueError")
    leaf = RaiseEffect(
        exception_name="ValueError",
        occurrence=AuthenticatedRaiseLocus.of("leaf:ve:7825"),
        exception_type_coordinate=ve_id,
        exception_type_mro=(ve_id,),
        raised_value=ve_typed,
    )
    group = GroupedRaiseEffect(
        "group:root:7825",
        "g",
        (leaf,),
        occurrence=AuthenticatedRaiseLocus.of("group:root:7825"),
    )
    body_atom = atomic("body.guard", [str_const("body")])
    site = SimpleNamespace(
        filename="handler_owes.py",
        line=1,
        col=0,
        unit=SimpleNamespace(source="try-star"),
    )

    sugar = TryStarSugar(
        body=(
            _Fixed(
                lambda _c: ExitSet(
                    (Halted(body_atom, group, None, owed=("debt:body",)),)
                )
            ),
        ),
        handlers=(
            (
                (_Fixed(lambda _c: ExitSet.completed(ve_typed)),),
                (_Fixed(lambda c: _owing_completion(c, "debt:handler")),),
                "slot-ve-7825",
            ),
        ),
        site=site,
    )
    result = sugar.desugar(ReduceContext.root(owner="handler_owes_7825"))

    # The handler consumed the whole group and fell through: the try* completes
    # under the body halt's guard...
    assert [type(arm) for arm in result.exits] == [Completed], result.exits
    (completed,) = result.exits
    assert "body.guard" in str(completed.guard), completed.guard
    # ...and owes what the body halt owed and what the handler owed.
    assert completed.owed == ("debt:body", "debt:handler")


def _one_leaf_try_star(tag: str, handler_body: tuple):
    """A try* whose body halts with one ValueError leaf, handled by one arm."""
    from sugar_lift_py_tests.ir import atomic, str_const
    from sugar_lift_py_tests.sugar.try_star_sugar import TryStarSugar

    ve_typed, ve_id = _synthetic_class("ValueError")
    leaf = RaiseEffect(
        exception_name="ValueError",
        occurrence=AuthenticatedRaiseLocus.of(f"leaf:ve:{tag}"),
        exception_type_coordinate=ve_id,
        exception_type_mro=(ve_id,),
        raised_value=ve_typed,
    )
    group = GroupedRaiseEffect(
        f"group:root:{tag}",
        "g",
        (leaf,),
        occurrence=AuthenticatedRaiseLocus.of(f"group:root:{tag}"),
    )
    body_atom = atomic("body.guard", [str_const(tag)])
    site = SimpleNamespace(
        filename=f"{tag}.py",
        line=1,
        col=0,
        unit=SimpleNamespace(source="try-star"),
    )
    sugar = TryStarSugar(
        body=(_Fixed(lambda _c: ExitSet((Halted(body_atom, group, None),))),),
        handlers=(
            (
                (_Fixed(lambda _c: ExitSet.completed(ve_typed)),),
                handler_body(leaf),
                f"slot-ve-{tag}",
            ),
        ),
        site=site,
    )
    return sugar, leaf


def test_a_reraising_handler_yields_only_the_halt() -> None:
    # The body's only face is handled by a handler that re-raises the matched
    # leaf: a raise is never a completion, so the try* answers the halt alone.
    sugar, leaf = _one_leaf_try_star(
        "reraise_7825",
        lambda leaf: (
            _Fixed(lambda _c: ExitSet((Halted(true_guard(), leaf, None),))),
        ),
    )
    result = sugar.desugar(ReduceContext.root(owner="reraise_7825"))

    assert [type(arm) for arm in result.exits] == [Halted], result.exits
    (halt,) = result.exits
    assert isinstance(halt.effect, GroupedRaiseEffect), halt.effect
    assert [child.occurrence_id for child in halt.effect.children] == [
        leaf.occurrence_id
    ]
    assert "body.guard" in str(halt.guard), halt.guard


def test_a_try_star_with_no_reachable_arm_yields_no_completion() -> None:
    # The handler's only arm is unsatisfiable, so no path leaves the handlers.
    # The try* answers exactly what ``sequence`` composed (nothing), never an
    # invented completion.
    from sugar_lift_py_tests.outcome.exit_set import false_guard

    sugar, _leaf = _one_leaf_try_star(
        "unreachable_7825",
        lambda _leaf: (
            _Fixed(
                lambda c: ExitSet(
                    (
                        Completed(
                            false_guard(),
                            _ReducedBlock(
                                entries=(),
                                can_fall_through=True,
                                fall_through=(),
                                context=c,
                            ),
                        ),
                    )
                )
            ),
        ),
    )
    result = sugar.desugar(ReduceContext.root(owner="unreachable_7825"))

    assert not any(isinstance(arm, Completed) for arm in result.exits), result.exits
    assert result.exits == (), result.exits
