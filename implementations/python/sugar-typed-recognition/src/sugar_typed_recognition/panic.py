"""RecognitionPanic: the loud arm of recognition's two-arm match.

Resolution has exactly two outcomes: ONE claim, or this panic. There is no
third arm — no "pick the first candidate", no permissive fallback, no
default claim, no quiet ``False``, no bare ``None`` gap sentinel.

Three MISSING shapes, all panics, all loud:

* ``GAP`` — no claim owns this (node type, operand types) combination.
* ``AMBIGUOUS`` — two or more claims own it. This is the SOUNDNESS
  guarantee, not an incidental error path: if two claims both own a
  combination, the catalog does not describe a function, and any answer it
  returns is arbitrary. Picking the first would make the arbitrariness
  silent. (Today's ``factory/build.py:_raise_ambiguous_candidates`` is the
  same event, reached only after a ``comes_before`` precedence walk failed
  to break the tie; here there is no precedence walk to fail — overlap IS
  the defect. See the module docstring of ``catalog.py``.)
* ``MISSING_OPERAND_TYPE`` — a child arrived that cannot answer its own
  type. ``owns`` is never asked in this case, because a claim returning
  ``False`` because it could not interrogate an operand is indistinguishable
  from a claim returning ``False`` because the operand did not match. The
  first is a hole in the membrane; the second is a correct answer. They must
  never share an encoding.

Modeled on the membrane's ``MembranePanic`` (same four-field shape: owner,
observed, requested, fix) but a distinct type, because a recognition MISSING
and a construction MISSING have different owners and different fixes.
"""

from __future__ import annotations

from enum import Enum
from typing import NoReturn


class RecognitionArm(Enum):
    """The named MISSING shapes. Not a severity — every arm halts."""

    GAP = "gap"
    AMBIGUOUS = "ambiguous"
    MISSING_OPERAND_TYPE = "missing-operand-type"


class RecognitionPanic(Exception):
    """A recognition MISSING surfacing loudly. Never caught to continue."""

    def __init__(
        self,
        arm: RecognitionArm,
        owner: str,
        observed: str,
        requested: str,
        fix: str,
    ) -> None:
        super().__init__(arm, owner, observed, requested, fix)
        self.arm = arm
        self.owner = owner
        self.observed = observed
        self.requested = requested
        self.fix = fix

    def __str__(self) -> str:  # pragma: no cover - formatting only
        return (
            f"RECOGNITION PANIC [{self.arm.value}] ({self.owner})\n"
            f"  observed:  {self.observed}\n"
            f"  requested: {self.requested}\n"
            f"  fix:       {self.fix}"
        )


def recognition_panic(
    arm: RecognitionArm, owner: str, observed: str, requested: str, fix: str
) -> NoReturn:
    raise RecognitionPanic(
        arm=arm, owner=owner, observed=observed, requested=requested, fix=fix
    )
