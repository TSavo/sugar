from __future__ import annotations

from dataclasses import dataclass

from .panic_record import PanicRecord


PANIC_AXES = (
    "numpy_sugar_panics",
    "numpy_floor_panics",
    "pandas_sugar_panics",
    "pandas_floor_panics",
    "unexpected_panics",
)


@dataclass(frozen=True)
class PanicVector:
    values: dict[str, int]

    @classmethod
    def from_records(cls, records: list[PanicRecord]) -> "PanicVector":
        values = {axis: 0 for axis in PANIC_AXES}
        for record in records:
            if record.kind == "unexpected":
                values["unexpected_panics"] += 1
                continue
            if record.target not in {"numpy", "pandas"}:
                values["unexpected_panics"] += 1
                continue
            values[f"{record.target}_{record.kind}_panics"] += 1
        return cls(values)

    @property
    def is_zero(self) -> bool:
        return all(value == 0 for value in self.values.values())
