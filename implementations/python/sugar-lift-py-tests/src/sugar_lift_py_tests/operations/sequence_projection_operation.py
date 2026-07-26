"""The sequence-projection operation: what ``a, b = <rhs>`` demands of one
reduced RHS value.

Python's unpacking assignment is ITERABLE unpacking, not subscription, and it
is not a sequence of independent stores.  ``UNPACK_SEQUENCE`` materializes the
right-hand side and demands EXACTLY the arity the target spells; only then does
it bind, left to right.  So the whole statement has exactly two outcomes:

    Unpack(value, arity)
        the value yields exactly `arity` members -> Completed(names bound to
                                                             those members)
        it yields any other count, or is not iterable
                                             -> Halted(unpack effect, nothing
                                                       bound)

Which one happens is decided by the RHS.  That decision is the whole content of
the operation, and it splits on ONE question: does the reduced value carry
authenticated finite members?

- It does (a list/tuple/array literal floor value): the count is lift-time
  decidable.  Matching arity binds each name to the member ALREADY IN HAND --
  never a fabricated element.  A mismatch is a decidable ``ValueError`` whose
  exact exceptional exit has no floor value yet, so it stays a loud
  construction gap rather than a guessed exit.

- It does not (a symbolic term, an object, an opaque call coordinate): the
  cardinality is known only at runtime.  There is no lift-time evidence naming
  either the count or the exception type, so the arity demand is retained as
  the typed ``SequenceUnpackRuntimeEffect`` carrying the exact
  ``python:unpack.destructure(term, arity)`` obligation -- the same coordinate
  family the comprehension destructure already states
  (``sugar/comprehension_sugar.py::_guard_destructure``).  Assuming the count
  matched would be the one forbidden move.

Anything else reaches ``FloorValue.project_sequence_with`` and stays a loud
floor construction gap: an unwritten floor is never a silent success.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass(frozen=True)
class SequenceProjectionOperation:
    """One unpack demand: ``target_names`` positions against one reduced RHS."""

    method_name: ClassVar[str] = "project_sequence_with"

    target_names: tuple[str, ...]
    owner: str
    blame: object

    @property
    def arity(self) -> int:
        return len(self.target_names)

    def submit(self, value: Any, ctx: Any) -> Any:
        """Ask the value what it unpacks to. The value owns the answer."""
        return value.project_sequence_with(self, ctx)

    # -- authenticated finite members: the count is decidable ---------------

    def project_tuple(self, value: Any, ctx: Any) -> Any:
        del ctx
        return self._authenticated_members(value, value.items, "tuple")

    def project_array(self, value: Any, ctx: Any) -> Any:
        del ctx
        return self._authenticated_members(value, value.items, "array")

    def project_comprehension(self, value: Any, ctx: Any) -> Any:
        """A comprehension answers from its own finite testimony, or not at all.

        ``ComprehensionValue.finite_elements`` is the authenticated projection of
        every member of an exact finite iterable, and ``None`` means no such
        testimony exists. ``None`` is NOT an empty sequence and is not a count:
        it routes to the runtime arm, where the cardinality stays owed. Reading
        it as zero members would turn "we do not know" into a decidable arity
        mismatch, which is the same lie in the opposite direction.
        """
        del ctx
        if value.finite_elements is None:
            return self._runtime_cardinality(value)
        return self._authenticated_members(
            value, value.finite_elements, "comprehension"
        )

    # -- runtime cardinality: the count is not decidable -------------------

    def project_symbolic(self, value: Any, ctx: Any) -> Any:
        del ctx
        return self._runtime_cardinality(value)

    def project_object(self, value: Any, ctx: Any) -> Any:
        del ctx
        return self._runtime_cardinality(value)

    # -- the two answers ---------------------------------------------------

    def _authenticated_members(self, value: Any, members: tuple, display: str) -> Any:
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds
        from sugar_lift_py_tests.outcome import Complete

        if len(members) != self.arity:
            self._arity_mismatch_gap(value, len(members), display)
        return Complete(
            ScopeRebinds(tuple(zip(self.target_names, members, strict=True)))
        )

    def _runtime_cardinality(self, value: Any) -> Any:
        from sugar_lift_py_tests.effect import (
            SequenceUnpackRuntimeEffect,
            runtime_effect_evidence_from_terms,
        )
        from sugar_lift_py_tests.ir import ctor, num
        from sugar_lift_py_tests.outcome import Incomplete

        term = value.to_term(owner=f"{self.owner}.value")
        operation = ctor(
            "python:unpack.destructure",
            [term, num(self.arity)],
            symbol_kind="coordinate",
        )
        return Incomplete(
            SequenceUnpackRuntimeEffect(
                "sequence unpack runtime boundary: unpack demands exactly "
                f"{self.arity} members for targets "
                f"({', '.join(self.target_names)}) but the right-hand side "
                "carries no authenticated cardinality -- iteration count "
                "belongs to Python's runtime __iter__; "
                f"arity={self.arity} site={self.blame}",
                **runtime_effect_evidence_from_terms(operation, operation, self.blame),
            )
        )

    def _arity_mismatch_gap(self, value: Any, members: int, display: str) -> None:
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus
        from sugar_lift_py_tests.gap.panic import construction_panic

        relation = "not enough" if members < self.arity else "too many"
        construction_panic(
            ConstructionGap(
                owner=self.owner,
                blame=str(self.blame),
                observed=(
                    f"{type(value).__name__} of {members} members unpacked into "
                    f"{self.arity} targets ({relation} values)"
                ),
                requested=(
                    "ground ValueError exceptional exit for a decidable "
                    f"{display} unpack arity mismatch"
                ),
                fix=(
                    "write more Floor: a ground ValueError exit value so this "
                    "decidable mismatch states its exception instead of "
                    "panicking"
                ),
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
        )
