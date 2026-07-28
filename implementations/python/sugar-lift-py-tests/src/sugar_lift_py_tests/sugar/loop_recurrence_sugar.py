from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import atomic, ctor, not_, or_, str_const
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar, Sugar


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
class LoopRecurrenceSugar(ConstructedTermSugar):
    target_cid: str
    loop_construction_cid: str
    binding_coordinate_cids: tuple[str, ...]
    outward_faces: tuple[object, ...]
    construction: object = field(compare=False)
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def to_term(self, *, owner: str):
        """Project the authenticated loop construction as one canonical term."""
        from sugar_lift_py_tests.loop_construction import (
            LoopWireError,
            decode_loop_construction_v1,
        )

        construction = decode_loop_construction_v1(self.construction.wire_graph())
        if construction.loop_construction_cid != self.loop_construction_cid:
            raise LoopWireError("loop recurrence construction CID mismatch")
        if construction.target.target_cid != self.target_cid:
            raise LoopWireError("loop recurrence target CID mismatch")

        root = construction.wire_graph()["root"]
        outward_face_cids = tuple(root["outwardHaltedFaceCids"])
        if len(outward_face_cids) != len(self.outward_faces):
            raise LoopWireError("loop recurrence outward-face testimony mismatch")
        coordinates = (*self.binding_coordinate_cids, *outward_face_cids)
        if any(
            not isinstance(cid, str) or not cid.startswith("blake3-512:")
            for cid in coordinates
        ):
            raise LoopWireError("loop recurrence testimony must be content-addressed")

        return ctor(
            "python:loop-recurrence-construction",
            (
                str_const(self.target_cid),
                str_const(self.loop_construction_cid),
                self.occurrence_term(owner=owner),
                ctor(
                    "python:loop-binding-coordinates",
                    tuple(str_const(cid) for cid in self.binding_coordinate_cids),
                    symbol_kind="coordinate",
                ),
                ctor(
                    "python:loop-outward-face-testimony",
                    tuple(str_const(cid) for cid in outward_face_cids),
                    symbol_kind="coordinate",
                ),
            ),
            symbol_kind="coordinate",
        )

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
                exits.append(Halted(face.guard, outcome.effect, face.state))
            else:
                # The face reduced to something richer than one return value or
                # one effect: a return whose expression PARTITIONS (`return
                # d.setdefault(k, v)`), a guarded return, or a return that owes a
                # parameter contract (`return p[0]`). None of those is a missing
                # wire -- each is a partition the face contributes under its own
                # guard, which is what `BindingStateWireGap: loop outward face did
                # not construct return or raise testimony` was refusing to state.
                from sugar_lift_py_tests.floor.single_outcome_law import (
                    pending_demand,
                )
                from sugar_lift_py_tests.outcome.exit_set import outcome_to_exitset

                # A pending demand's home is a block entry, and this face builds
                # exactly one: it rides beside the return in the same record.
                pending, plain = pending_demand(outcome, face.guard)
                for exit_ in outcome_to_exitset(plain).guarded(face.guard).exits:
                    if isinstance(exit_, Halted):
                        exits.append(Halted(exit_.guard, exit_.effect, face.state))
                    else:
                        entries = (exit_.value,) if pending is None else (
                            pending,
                            exit_.value,
                        )
                        exits.append(
                            Completed(
                                exit_.guard,
                                BlockValue(entries, can_fall_through=False),
                            )
                        )
        return ExitSet(tuple(exits)).normalize()
