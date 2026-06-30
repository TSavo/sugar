from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.factory.sugar_constructors import build_assign_sugar
from sugar_lift_py_tests.floor import BoundVar
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AssignSugar:
    """A `name = <rhs>` statement. Its child is the RHS expression -- built by the
    factory at the TERM role and handed in. Desugaring does NOT reduce the rhs; it
    yields a BoundVar that ALIASES the name to the rhs SOURCE. The block threads it as
    a let, a reference recomposes it, and a later pass can recover the original
    expression (`let x = y()` keeps `y()`)."""

    name: str
    value: SugarBody

    def desugar(self, ctx) -> Outcome:
        del ctx  # the rhs is preserved as source, not reduced here
        return Complete(BoundVar(self.name, self.value))


def _owns(site) -> bool:
    return (
        site.observed == "Assign"
        and site.assign_target_name() is not None
    )


ASSIGN_CLAIM = SugarClaim(
    name="AssignSugar",
    role=SugarRole.STATEMENT,
    owns=_owns,
    build=build_assign_sugar,
)
