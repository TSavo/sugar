from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import atomic, ctor, not_, or_, str_const
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class LoopBindingRefSugar(Sugar):
    target_cid: str
    binding_coordinate_cid: str
    completion_kind: str
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return Complete(
            SymbolicValue(
                ctor(
                    "python:loop.post_binding",
                    [
                        str_const(self.target_cid),
                        str_const(self.binding_coordinate_cid),
                        str_const(self.completion_kind),
                    ],
                    symbol_kind="coordinate",
                )
            )
        )


@dataclass(frozen=True)
class LoopRecurrenceSugar(Sugar):
    target_cid: str
    loop_construction_cid: str
    binding_coordinate_cids: tuple[str, ...]
    outward_faces: tuple[object, ...]
    construction: object = field(compare=False)
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.floor import InvValue
        from sugar_lift_py_tests.floor.block_value import BlockValue

        recurrences = []
        for coordinate_cid in self.binding_coordinate_cids:
            h = ctor(
                "python:loop.recurrence",
                [str_const(self.target_cid), str_const(coordinate_cid)],
                symbol_kind="coordinate",
            )
            step = ctor(
                "python:loop.step",
                [h, str_const(self.loop_construction_cid)],
                symbol_kind="coordinate",
            )
            recurrences.append(InvValue(atomic("=", [h, step]), self.site))
        recurrence = BlockValue(tuple(recurrences), can_fall_through=True)
        if not self.outward_faces:
            return Complete(recurrence)

        from sugar_lift_py_tests.floor import ReturnValue
        from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted, Incomplete

        halted_guards = [face.guard for face in self.outward_faces]
        completed_guard = not_(
            halted_guards[0] if len(halted_guards) == 1 else or_(halted_guards)
        )
        exits = [Completed(completed_guard, recurrence)]
        for face in self.outward_faces:
            outcome = face.statement_sugar.desugar(ctx)
            if isinstance(outcome, Complete) and isinstance(outcome.value, ReturnValue):
                exits.append(
                    Completed(
                        face.guard,
                        BlockValue((outcome.value,), can_fall_through=False),
                    )
                )
            elif isinstance(outcome, Incomplete):
                exits.append(Halted(face.guard, outcome.effect, recurrence))
            else:
                from sugar_source_tree.binding_state import BindingStateWireGap

                raise BindingStateWireGap(
                    "loop outward face did not construct return or raise testimony"
                )
        return ExitSet(tuple(exits)).normalize()
