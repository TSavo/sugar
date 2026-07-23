from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Term


@dataclass(frozen=True)
class RaiseEffect:
    exception_name: str | None = None
    blame: str | None = None
    source_sha256: str | None = None
    exception_type_coordinate: Term | None = None
    exception_type_mro: tuple[Term, ...] | None = None
    # Deterministic occurrence of THIS raise site (file:line:col). Distinct from
    # type name: two raise ValueError at different loci have different
    # occurrences. Never used as a fabricated "instance identity" from type alone.
    occurrence: str | None = None
    # The value built from ``raise <exc>``.  A Name is a coordinate pointing
    # at the existing binding; a constructor call is its ordinary callsite.
    # Some runtime-generated RaiseEffects have no source exception child.
    raised_value: object | None = None
    # The constructed expression after an explicit ``from``. Host ``None``
    # means the clause was absent; explicit Python ``None`` is a NoneValue.
    cause_value: object | None = None

    @property
    def occurrence_id(self) -> str | None:
        """Stable raise-effect occurrence coordinate, if known."""
        return self.occurrence if self.occurrence is not None else self.blame

    @property
    def reason(self) -> str:
        name = self.exception_name or (
            repr(self.exception_type_coordinate)
            if self.exception_type_coordinate is not None
            else "unknown exception"
        )
        locus = f" at {self.blame}" if self.blame is not None else ""
        return (
            f"raise {name}{locus}: a Python raise effect that exits the current "
            "block and may be routed by a matching TrySugar handler"
        )
