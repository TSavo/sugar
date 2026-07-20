"""MembranePanic: the loud arm of the membrane's two-arm match.

Every question the membrane answers has exactly two outcomes: a resolved,
Typed answer, or this panic. There is no third arm — no permissive fallback,
no default case, no quiet ``False``, no bare ``None`` refusal. A MISSING
(a backend shape with no membrane class, a node the provider cannot
position, an intern collision) becomes a ``MembranePanic`` that names the
owner, what was observed, what was requested, and how to fix it.

Modeled on ``factory_panic_gap`` (sugar_lift_py_tests.factory.factory_gap),
but standalone: this package deliberately imports nothing from the existing
tree (#5940 builds the membrane in isolation).
"""

from __future__ import annotations


class MembranePanic(Exception):
    """A membrane MISSING surfacing loudly. Never caught to continue."""

    def __init__(self, owner: str, observed: str, requested: str, fix: str) -> None:
        super().__init__(owner, observed, requested, fix)
        self.owner = owner
        self.observed = observed
        self.requested = requested
        self.fix = fix

    def __str__(self) -> str:  # pragma: no cover - formatting only
        return (
            f"MEMBRANE PANIC [{self.owner}]\n"
            f"  observed:  {self.observed}\n"
            f"  requested: {self.requested}\n"
            f"  fix:       {self.fix}"
        )


def membrane_panic(owner: str, observed: str, requested: str, fix: str) -> "MembranePanic":
    raise MembranePanic(owner=owner, observed=observed, requested=requested, fix=fix)
