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

                if isinstance(face.effect, RaiseEffect):
                    from sugar_lift_py_tests.floor.raise_value import (
                        _exceptional_exit_term,
                    )

                    payload = _exceptional_exit_term(face.effect)
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

    @property
    def identity(self) -> str:
        from sugar_lift_py_tests.ir import _term_content_cid

        return _term_content_cid(
            self.to_term(owner="ReceiverStatePartitionValue.identity")
        )
