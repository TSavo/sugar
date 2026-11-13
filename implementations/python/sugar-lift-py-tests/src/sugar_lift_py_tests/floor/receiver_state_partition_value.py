from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class ReceiverStatePartitionValue(FloorValue):
    """Constructor exits before one unconditional receiver state exists."""

    exits: object

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, formula_term, str_const
        from sugar_lift_py_tests.outcome import Completed, Halted

        faces = []
        for face in self.exits.exits:
            if isinstance(face, Completed):
                payload = face.value.to_term(owner=owner)
                kind = "completed"
            elif isinstance(face, Halted):
                from sugar_lift_py_tests.effect import RaiseEffect
                from sugar_lift_py_tests.effect.raise_effect import (
                    UndeterminedRaiseEffect,
                )

                if isinstance(face.effect, RaiseEffect):
                    from sugar_lift_py_tests.floor.exceptional_exit_term import (
                        _exceptional_exit_term,
                    )

                    payload = _exceptional_exit_term(face.effect)
                elif isinstance(face.effect, UndeterminedRaiseEffect):
                    # A may-raise operation's halt: the subject is the one
                    # exception object it threw, never a named class.
                    payload = _undetermined_raise_term(face.effect, owner=owner)
                else:
                    payload = face.effect.to_term(owner=owner)
                kind = "halted"
            else:  # pragma: no cover - ExitSet is closed over these two faces.
                # Missing arm over ExitSet faces: name the species and the door.
                from sugar_lift_py_tests.gap.info import GapKind
                from sugar_lift_py_tests.gap.panic import construction_panic_gap

                construction_panic_gap(
                    owner="ReceiverStatePartitionValue.to_term",
                    blame="receiver-state-partition",
                    observed=(
                        f"ExitSet face species {type(face).__name__} has no "
                        f"to_term arm (only Completed and Halted are written)"
                    ),
                    requested="Completed | Halted face from ExitSet",
                    fix=(
                        f"write to_term arm for {type(face).__name__} or stop "
                        f"emitting it into receiver-state partitions; do not "
                        f"raise bare TypeError with only the type name"
                    ),
                    gap_kind=GapKind.FLOOR,
                )
            faces.append(
                ctor(
                    "python:receiver-state-face",
                    [str_const(kind), formula_term(face.guard), payload],
                    symbol_kind="coordinate",
                )
            )
        return ctor(
            "python:receiver-state-partition",
            faces,
            symbol_kind="coordinate",
        )

    def constructor_faces(self):
        """``(halts, completed)`` of this construction, nested partitions flattened.

        Each nested face's guard is conjoined with its enclosing completed
        face's guard, so a flattened face holds exactly where Python reaches
        it. ``halts`` are the faces where construction itself raised (the With
        never enters); ``completed`` are the receiver leaves. Returns ``None``
        if any halt carries no typed effect: such a face cannot leave a With
        as itself, so no consumer may seal over it.
        """
        from sugar_lift_py_tests.outcome import Completed, Halted
        from sugar_lift_py_tests.outcome.exit_set import _and_guards
        from dataclasses import replace

        halts = []
        completed = []

        def walk(partition, outer):
            for face in partition.exits.exits:
                guard = face.guard if outer is None else _and_guards(outer, face.guard)
                if isinstance(face, Completed):
                    if isinstance(face.value, ReceiverStatePartitionValue):
                        if not walk(face.value, guard):
                            return False
                        continue
                    completed.append(replace(face, guard=guard))
                    continue
                if not isinstance(face, Halted) or face.effect is None:
                    return False
                halts.append(replace(face, guard=guard))
            return True

        if not walk(self, None):
            return None
        return tuple(halts), tuple(completed)

    def project_operation_receiver_outcome(self, ctx: object, *, owner: str):
        """An operation on a constructed object runs on each receiver it can be.

        Construction either raised (the operation never runs; that face
        leaves as itself) or completed with one receiver state per face.  The
        operation sequences over exactly those faces, flattened under their
        guards.  A halt with no typed effect cannot leave as itself, so it
        stays named-loud rather than being dropped.
        """
        del ctx
        from sugar_lift_py_tests.outcome.exit_set import ExitSet
        from sugar_source_tree.panic import SugarNotWritten

        faces = self.constructor_faces()
        if faces is None:
            raise SugarNotWritten(
                blame="receiver-state-partition",
                owner=owner,
                observed="constructor halt with no typed effect",
                requested="every construction face completed or halted with an effect",
                fix="carry the constructor halt's effect into the receiver partition",
            )
        halts, completed = faces
        return ExitSet((*halts, *completed))

    @property
    def identity(self) -> str:
        from sugar_lift_py_tests.ir import _term_content_cid

        return _term_content_cid(
            self.to_term(owner="ReceiverStatePartitionValue.identity")
        )


def _undetermined_raise_term(effect, *, owner: str):
    """Name an undetermined halt by the exception object it threw."""
    from sugar_lift_py_tests.ir import ctor

    subject = effect.exception_value
    if subject is None:
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            blame=getattr(effect, "blame", None) or owner,
            owner="ReceiverStatePartitionValue.to_term",
            observed="undetermined halt with no exception subject",
            requested="an UndeterminedRaiseEffect keyed on its occurrence",
            fix="carry the occurrence so the thrown object can be named",
        )
    return ctor(
        "python:undetermined-raise",
        [subject.to_term(owner=owner)],
        symbol_kind="coordinate",
    )
