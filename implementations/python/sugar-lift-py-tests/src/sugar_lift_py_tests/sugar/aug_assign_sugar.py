from __future__ import annotations

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.sugar.sugar_base import Sugar


class AugAssignSugar(Sugar, role=SugarRole.STATEMENT):
    """`x += v` is sugar for `x = x + v`.

    A pure recognizer that owns NO operator knowledge. It rewrites to an AssignSugar over
    the synthesized `x <op> v` binop (`aug_assign_binop` on the gateway) and hands that
    downstream through the factory. So the operator dispatches to its own binop sugar
    (Add -> BinOpSugar) -- or, when that binop does not exist yet (Sub, Mult, ...), the
    factory panics naming the gap. That panic is the CORRECT behavior: `-=` is not
    silently wrong, it is loudly unwritten.

    It reuses AssignSugar's bind (which closes over its definition scope, so the rebind
    reads the old x) and the binop's add. It re-implements neither, which is exactly why
    it stays three lines: `+=`, and every other augmented op, for free once its binop
    lands.
    """

    @classmethod
    def owns(cls, fragment) -> bool:
        return (
            fragment.observed == "AugAssign"
            and fragment.aug_assign_target().observed == "Name"
        )

    @classmethod
    def build(cls, fragment, ctx):
        # Rewrite to a plain assign of the synthesized binop -- never instantiated as an
        # AugAssignSugar; the downstream AssignSugar + binop sugar do all the work.
        from sugar_lift_py_tests.sugar.assign_sugar import AssignSugar

        return AssignSugar(
            name=fragment.aug_assign_target().name_id(),
            value=ctx.build_body(fragment.aug_assign_binop(), SugarRole.TERM),
        )
