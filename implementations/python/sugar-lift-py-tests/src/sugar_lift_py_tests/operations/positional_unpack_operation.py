"""Positional UNPACK roster — members by source-leaf order, no lexical keys.

Sibling of ``SequenceProjectionOperation`` (name-keyed ScopeRebinds).  Store
and mixed unpack need authenticated members in **source leaf order** without
fabricating string binding identities for non-name targets.

Same floor door: ``project_sequence_with``.  Same arity / opaque laws.
Star middle is a ``ListValue`` in the roster at the star leaf position.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass(frozen=True)
class UnpackMemberRoster:
    """Authenticated finite UNPACK result: one member per source target leaf.

    Star positions hold ``ListValue`` of the middle slice.  No string keys —
    consumers zip with typed projection targets by position.
    """

    members: tuple  # FloorValue per leaf, source order


@dataclass(frozen=True)
class PositionalUnpackOperation:
    """UNPACK demand that returns ``UnpackMemberRoster`` (positional).

    ``fixed_prefix`` / ``fixed_suffix`` count fixed leaves around an optional
    star.  ``has_star`` selects UNPACK_EX vs UNPACK_SEQUENCE cardinality.
    """

    method_name: ClassVar[str] = "project_sequence_with"

    fixed_prefix: int
    fixed_suffix: int
    has_star: bool
    owner: str
    blame: object

    def __post_init__(self) -> None:
        if self.fixed_prefix < 0 or self.fixed_suffix < 0:
            raise ValueError("fixed_prefix/fixed_suffix must be non-negative")
        if not self.has_star and self.fixed_suffix:
            raise ValueError("fixed_suffix requires has_star")

    @property
    def arity(self) -> int:
        return self.fixed_prefix + self.fixed_suffix

    @property
    def is_starred(self) -> bool:
        return self.has_star

    def submit(self, value: Any, ctx: Any) -> Any:
        return value.project_sequence_with(self, ctx)

    def project_tuple(self, value: Any, ctx: Any) -> Any:
        del ctx
        return self._authenticated_members(value, value.items, "tuple")

    def project_array(self, value: Any, ctx: Any) -> Any:
        del ctx
        return self._authenticated_members(value, value.items, "array")

    def project_comprehension(self, value: Any, ctx: Any) -> Any:
        del ctx
        if value.finite_elements is None:
            return self._runtime_cardinality(value)
        return self._authenticated_members(
            value, value.finite_elements, "comprehension"
        )

    def project_symbolic(self, value: Any, ctx: Any) -> Any:
        del ctx
        return self._runtime_cardinality(value)

    def project_object(self, value: Any, ctx: Any) -> Any:
        del ctx
        return self._runtime_cardinality(value)

    def _authenticated_members(self, value: Any, members: tuple, display: str) -> Any:
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.outcome import Complete

        if not self.has_star:
            if len(members) != self.arity:
                return self._arity_mismatch_exit(value, len(members), display)
            return Complete(UnpackMemberRoster(members))

        fixed = self.arity
        if len(members) < fixed:
            return self._arity_mismatch_exit(value, len(members), display)
        pre_n = self.fixed_prefix
        suf_n = self.fixed_suffix
        prefix_vals = members[:pre_n]
        if suf_n:
            mid_vals = members[pre_n : len(members) - suf_n]
            suffix_vals = members[len(members) - suf_n :]
        else:
            mid_vals = members[pre_n:]
            suffix_vals = ()
        roster = (
            *prefix_vals,
            ListValue(tuple(mid_vals)),
            *suffix_vals,
        )
        return Complete(UnpackMemberRoster(roster))

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
        if not self.has_star:
            demand = f"exactly {self.arity} members for positional targets"
        else:
            demand = (
                f"at least {self.arity} members for starred positional targets "
                f"(prefix={self.fixed_prefix}, suffix={self.fixed_suffix})"
            )
        return Incomplete(
            SequenceUnpackRuntimeEffect(
                "sequence unpack runtime boundary: unpack demands "
                f"{demand} but the right-hand side "
                "carries no authenticated cardinality -- iteration count "
                "belongs to Python's runtime __iter__; "
                f"arity={self.arity} starred={self.has_star} "
                f"site={self.blame}",
                **runtime_effect_evidence_from_terms(operation, operation, self.blame),
            )
        )

    def _arity_mismatch_exit(self, value: Any, members: int, display: str) -> Any:
        """Named ValueError for decidable too-few / too-many (same door as name unpack)."""
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
