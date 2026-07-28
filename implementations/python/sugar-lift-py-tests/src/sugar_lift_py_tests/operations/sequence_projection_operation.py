"""The sequence-projection operation: what ``a, b = <rhs>`` (and starred
forms) demand of one reduced RHS value.

Python's unpacking assignment is ITERABLE unpacking, not subscription, and it
is not a sequence of independent stores.  ``UNPACK_SEQUENCE`` / ``UNPACK_EX``
materializes the right-hand side and demands the arity the target spells; only
then does it bind, left to right.  So the whole statement has exactly two
outcomes:

    Unpack(value, pattern)
        the value yields enough members for the pattern
            -> Completed(names bound to those members; star binds a list)
        too few / not iterable / runtime cardinality
            -> Halted(unpack effect or named ValueError, nothing bound)

Which one happens is decided by the RHS.  That decision is the whole content of
the operation, and it splits on ONE question: does the reduced value carry
authenticated finite members?

- It does (a tuple/array/list floor value): the count is lift-time decidable.
  Matching (or starred-sufficient) arity binds each name to the member ALREADY
  IN HAND -- never a fabricated element.  A star target receives a
  ``ListValue`` of the middle slice in source order.  Too few fixed positions
  is a named ``ValueError`` via the ground exit door.

- It does not (a symbolic term, an object, an opaque call coordinate): the
  cardinality is known only at runtime.  There is no lift-time evidence naming
  either the count or the exception type, so the arity demand is retained as
  the typed ``SequenceUnpackRuntimeEffect`` carrying the exact
  ``python:unpack.destructure(term, arity)`` obligation -- the same coordinate
  family the comprehension destructure already states
  (``sugar/comprehension_sugar.py::_guard_destructure``).  Assuming the count
  matched would be the one forbidden move.  Starred opaque patterns keep the
  same law: never complete, never invent a tail.

Anything else reaches ``FloorValue.project_sequence_with`` and stays a loud
floor construction gap: an unwritten floor is never a silent success.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass(frozen=True)
class SequenceProjectionOperation:
    """One unpack demand against one reduced RHS.

    Exact form (no star): ``target_names`` is the full left-to-right roster and
    ``star_name`` is ``None``.  Arity is exact.

    Starred form: ``prefix_names`` then ``*star_name`` then ``suffix_names``.
    ``target_names`` is the flattened fixed roster (prefix + suffix) for
    compatibility; the star is not in that tuple.  Minimum member count is
    ``len(prefix) + len(suffix)``.
    """

    method_name: ClassVar[str] = "project_sequence_with"

    target_names: tuple[str, ...]
    owner: str
    blame: object
    star_name: str | None = None
    prefix_names: tuple[str, ...] = ()
    suffix_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.star_name is None:
            if self.prefix_names or self.suffix_names:
                raise ValueError(
                    "prefix_names/suffix_names require star_name for starred unpack"
                )
            return
        # Starred: target_names is the fixed roster (prefix+suffix) for the
        # obligation's fixed-count half; recompute if the caller only supplied
        # prefix/suffix.
        fixed = (*self.prefix_names, *self.suffix_names)
        if self.target_names and self.target_names != fixed:
            # Allow callers that pass only target_names + star_name + star index
            # via prefix/suffix already set.
            if not self.prefix_names and not self.suffix_names:
                object.__setattr__(self, "prefix_names", self.target_names)
                object.__setattr__(self, "suffix_names", ())
                return
            raise ValueError(
                "target_names must equal prefix_names + suffix_names for starred unpack"
            )
        if not self.target_names:
            object.__setattr__(self, "target_names", fixed)

    @property
    def arity(self) -> int:
        """Exact target count for non-star; fixed (minimum) count for star."""
        if self.star_name is None:
            return len(self.target_names)
        return len(self.prefix_names) + len(self.suffix_names)

    @property
    def is_starred(self) -> bool:
        return self.star_name is not None

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
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds
        from sugar_lift_py_tests.outcome import Complete

        if self.star_name is None:
            if len(members) != self.arity:
                return self._arity_mismatch_exit(value, len(members), display)
            return Complete(
                ScopeRebinds(tuple(zip(self.target_names, members, strict=True)))
            )

        # Starred: need at least the fixed positions; middle may be empty.
        fixed = self.arity
        if len(members) < fixed:
            return self._arity_mismatch_exit(value, len(members), display)
        pre_n = len(self.prefix_names)
        suf_n = len(self.suffix_names)
        prefix_vals = members[:pre_n]
        if suf_n:
            mid_vals = members[pre_n : len(members) - suf_n]
            suffix_vals = members[len(members) - suf_n :]
        else:
            mid_vals = members[pre_n:]
            suffix_vals = ()
        # CPython always binds the starred target to a list, even from a tuple.
        rebinds = (
            *zip(self.prefix_names, prefix_vals, strict=True),
            (self.star_name, ListValue(tuple(mid_vals))),
            *zip(self.suffix_names, suffix_vals, strict=True),
        )
        return Complete(ScopeRebinds(rebinds))

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
        if self.star_name is None:
            roster = ", ".join(self.target_names)
            demand = f"exactly {self.arity} members for targets ({roster})"
        else:
            roster = (
                f"{', '.join(self.prefix_names)}"
                f"{', ' if self.prefix_names else ''}"
                f"*{self.star_name}"
                f"{', ' if self.suffix_names else ''}"
                f"{', '.join(self.suffix_names)}"
            )
            demand = f"at least {self.arity} members for starred targets ({roster})"
        return Incomplete(
            SequenceUnpackRuntimeEffect(
                "sequence unpack runtime boundary: unpack demands "
                f"{demand} but the right-hand side "
                "carries no authenticated cardinality -- iteration count "
                "belongs to Python's runtime __iter__; "
                f"arity={self.arity} starred={self.star_name is not None} "
                f"site={self.blame}",
                **runtime_effect_evidence_from_terms(operation, operation, self.blame),
            )
        )

    def _arity_mismatch_exit(self, value: Any, members: int, display: str) -> Any:
        """Named ValueError for a decidable too-few / too-many unpack.

        Uses the ground exit door when ``blame`` is a re-readable source
        fragment.  Prose / non-fragment blame stays the loud construction gap
        naming the mismatch (existing twin-site instruments).
        """
        from sugar_lift_py_tests.floor import RaiseValue
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus
        from sugar_lift_py_tests.gap.panic import ConstructionPanic, construction_panic
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        relation = "not enough" if members < self.arity else "too many"
        observed = (
            f"{type(value).__name__} of {members} members unpacked into "
            f"{self.arity} fixed targets ({relation} values)"
        )
        # Only fragments (or objects answering the RuntimeEffectSite protocol)
        # may mint a ground exit.  Strings and synthetic loci stay the gap.
        if hasattr(self.blame, "filename") and hasattr(self.blame, "line"):
            try:
                projected = ground_exceptional_exit(
                    exception_name="ValueError",
                    site=self.blame,
                    owner=f"{self.owner}.arity_mismatch",
                )
            except ConstructionPanic:
                projected = None
            else:
                if isinstance(projected, Complete) and isinstance(
                    projected.value, RaiseValue
                ):
                    return Incomplete(projected.value.effect)
                return projected
        construction_panic(
            ConstructionGap(
                owner=self.owner,
                blame=str(self.blame),
                observed=observed,
                requested=(
                    "ground ValueError exceptional exit for a decidable "
                    f"{display} unpack arity mismatch"
                ),
                fix=(
                    "thread a workspace-relative source fragment as blame so "
                    "the ground ValueError exit can cite it"
                ),
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
        )
