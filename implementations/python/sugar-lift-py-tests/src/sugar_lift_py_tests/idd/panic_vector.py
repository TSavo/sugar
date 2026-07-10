from __future__ import annotations

from dataclasses import dataclass

from .panic_record import PanicRecord

PANIC_AXES = (
    "numpy_sugar_panics",
    "numpy_floor_panics",
    "pandas_sugar_panics",
    "pandas_floor_panics",
    "statistics_sugar_panics",
    "statistics_floor_panics",
    "unexpected_panics",
)

# Named package axes that own sugar/floor buckets. Anything else is unexpected.
_PACKAGE_AXES = frozenset({"numpy", "pandas", "statistics"})


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
            target = _axis_target(record.target)
            if target not in _PACKAGE_AXES:
                values["unexpected_panics"] += 1
                continue
            # sugar / floor only — other kinds fall into unexpected.
            axis = f"{target}_{record.kind}_panics"
            if axis not in values:
                values["unexpected_panics"] += 1
                continue
            values[axis] += 1
        return cls(values)

    @property
    def is_zero(self) -> bool:
        return all(value == 0 for value in self.values.values())


def _axis_target(target: str) -> str:
    if target.endswith("-all"):
        return target[: -len("-all")]
    return target
