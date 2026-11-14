"""Positional UNPACK roster — members by source-leaf order, no lexical keys.

Sibling of ``SequenceProjectionOperation`` (name-keyed ScopeRebinds).  Store
and mixed unpack need authenticated members in **source leaf order** without
fabricating string binding identities for non-name targets.

Same floor door: ``project_sequence_with``.  Same arity / opaque laws.
Star middle is a ``ListValue`` in the roster at the star leaf position.

Successful rosters carry the authenticated unpack **occurrence** and
**demand_cid** (content address of site + arity layout) so consumers can
testify which source unpack produced the members.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass(frozen=True)
class UnpackMemberRoster:
    """Authenticated finite UNPACK result: one member per source target leaf.

    Star positions hold ``ListValue`` of the middle slice.  No string keys —
    consumers zip with typed projection targets by position.

    ``occurrence`` and ``demand_cid`` are the unpack operation's authority:
    which source unpack demand produced these members.  A roster of bare
    members without them is unconstructable.
    """

    members: tuple  # FloorValue per leaf, source order
    occurrence: object  # authenticated source fragment (operation blame)
    demand_cid: str  # content address of unpack demand (site + arity)

    @property
    def site(self) -> object:
        """The source locus of this demand (recorded under ``blame``).

        Consumers that reduce this operation over an undecided receiver -- an
        ImportMemberValue under an enrolled stdlib body -- read
        ``operation.site``. Sibling operations that lacked it raised
        AttributeError and voided the file (see SubscriptOperation.site).
        """
        return self.blame

    def __post_init__(self) -> None:
        if not isinstance(self.demand_cid, str) or not self.demand_cid:
            raise ValueError(
                "UnpackMemberRoster requires a nonempty demand_cid from the "
                "positional unpack operation"
            )
        if self.occurrence is None:
            raise ValueError(
                "UnpackMemberRoster requires an authenticated unpack occurrence"
            )


@dataclass(frozen=True)
class PositionalUnpackOperation:
    """UNPACK demand that returns ``UnpackMemberRoster`` (positional).

    ``fixed_prefix`` / ``fixed_suffix`` count fixed leaves around an optional
    star.  ``has_star`` selects UNPACK_EX vs UNPACK_SEQUENCE cardinality.

    ``guarded_symbolic``: a value with no authenticated cardinality (a
    symbolic term, an object) answers both faces of its runtime unpack
    (``_runtime_faces``) rather than the halt alone: the roster of each
    position's projection (``python:unpack.project(term, index, arity)``)
    under the unpack's completes atom, and the same runtime-cardinality halt
    under its complement.  A live loop's symbolic item asks for it
    (``LoopRecurrenceSugar._enter_symbolic_item``): the recurrence carries
    the halt as its own arm and reads the leaves from the completed one.
    """

    method_name: ClassVar[str] = "project_sequence_with"

    fixed_prefix: int
    fixed_suffix: int
    has_star: bool
    owner: str
    blame: object
    guarded_symbolic: bool = False

    def __post_init__(self) -> None:
        if self.fixed_prefix < 0 or self.fixed_suffix < 0:
            raise ValueError("fixed_prefix/fixed_suffix must be non-negative")
        if not self.has_star and self.fixed_suffix:
            raise ValueError("fixed_suffix requires has_star")
        if self.guarded_symbolic and self.has_star:
            raise ValueError(
                "guarded_symbolic has no member to project for a star: a "
                "starred runtime unpack answers its halt alone"
            )

    @property
    def arity(self) -> int:
        return self.fixed_prefix + self.fixed_suffix

    @property
    def is_starred(self) -> bool:
        return self.has_star

    def demand_cid(self) -> str:
        """Content address of this unpack demand (site + arity layout)."""
        from sugar_lift_py_tests.caller_parameter_contract import (
            _cid,
            source_coordinate,
        )

        try:
            source_node = source_coordinate(self.blame)
            source_wire = source_node.wire()
        except (AttributeError, TypeError) as exc:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner=f"{self.owner}.demand_cid",
                blame=self.blame,
                observed=f"{type(self.blame).__name__} cannot source-coordinate",
                requested="authenticated source fragment for positional unpack",
                fix=(
                    "thread the statement fragment as PositionalUnpackOperation.blame "
                    f"(cause={exc})"
                ),
            )
        preimage = {
            "kind": "positional-unpack-demand",
            "schemaVersion": "1",
            "owner": self.owner,
            "sourceNode": source_wire,
            "fixedPrefix": self.fixed_prefix,
            "fixedSuffix": self.fixed_suffix,
            "hasStar": self.has_star,
            "arity": self.arity,
        }
        return _cid(preimage)

    def mint_roster(self, members: tuple) -> UnpackMemberRoster:
        """Seal members under this operation's occurrence and demand_cid."""
        return UnpackMemberRoster(
            members=members,
            occurrence=self.blame,
            demand_cid=self.demand_cid(),
        )

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
        from sugar_lift_py_tests.outcome import ExitSet

        if not self.has_star:
            if len(members) != self.arity:
                return self._arity_mismatch_exit(value, len(members), display)
            return ExitSet.completed(self.mint_roster(members))

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
        return ExitSet.completed(self.mint_roster(roster))

    def _runtime_cardinality(self, value: Any) -> Any:
        from sugar_lift_py_tests.outcome import ExitSet

        if self.guarded_symbolic:
            return self._runtime_faces(value)
        _term, _operation, effect = self._runtime_halt(value)
        return ExitSet.halted(effect)

    def _runtime_faces(self, value: Any) -> Any:
        """Both faces of a runtime-cardinality unpack (``guarded_symbolic``).

        It completes, under ``python:unpack.completes`` of the demand's
        ``python:unpack.destructure(term, arity)`` coordinate, with the roster
        of each position's projection (``python:unpack.project(term, index,
        arity)``, the coordinate a comprehension's symbolic destructure reads:
        ``comprehension_sugar._projection``); and halts with the runtime
        cardinality effect (``_runtime_halt``: too few, too many, not
        iterable) under the complement.  No member is assumed: each is its
        position's projection, readable only on the completed face."""
        from sugar_lift_py_tests.floor import SymbolicValue
        from sugar_lift_py_tests.ir import atomic, ctor, num
        from sugar_lift_py_tests.outcome import ExitSet

        term, operation, effect = self._runtime_halt(value)
        members = tuple(
            SymbolicValue(
                ctor(
                    "python:unpack.project",
                    [term, num(index), num(self.arity)],
                    symbol_kind="coordinate",
                )
            )
            for index in range(self.arity)
        )
        return ExitSet.two_faced(
            self.mint_roster(members),
            effect,
            guard=atomic("python:unpack.completes", [operation]),
        )

    def _runtime_halt(self, value: Any) -> tuple:
        """``(term, demand coordinate, effect)``: the runtime-cardinality halt
        of unpacking ``value``, which carries no authenticated cardinality."""
        from sugar_lift_py_tests.effect import (
            SequenceUnpackRuntimeEffect,
            runtime_effect_evidence_from_terms,
        )
        from sugar_lift_py_tests.ir import ctor, num

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
        effect = SequenceUnpackRuntimeEffect(
            "sequence unpack runtime boundary: unpack demands "
            f"{demand} but the right-hand side "
            "carries no authenticated cardinality -- iteration count "
            "belongs to Python's runtime __iter__; "
            f"arity={self.arity} starred={self.has_star} "
            f"site={self.blame}",
            **runtime_effect_evidence_from_terms(operation, operation, self.blame),
        )
        return term, operation, effect

    def _arity_mismatch_exit(self, value: Any, members: int, display: str) -> Any:
        """Named ValueError for decidable too-few / too-many (same door as name unpack)."""
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus
        from sugar_lift_py_tests.gap.panic import construction_panic

        relation = "not enough" if members < self.arity else "too many"
        observed = (
            f"{type(value).__name__} of {members} members unpacked into "
            f"{self.arity} fixed targets ({relation} values)"
        )
        if hasattr(self.blame, "filename") and hasattr(self.blame, "line"):
            return ground_exceptional_exit(
                exception_name="ValueError",
                site=self.blame,
                owner=f"{self.owner}.arity_mismatch",
            )
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
