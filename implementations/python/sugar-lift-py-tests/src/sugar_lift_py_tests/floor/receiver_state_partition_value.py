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
                payload = face.effect.to_term(owner=owner)
                kind = "halted"
            else:  # pragma: no cover - ExitSet is closed over these two faces.
                raise TypeError(type(face).__name__)
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
