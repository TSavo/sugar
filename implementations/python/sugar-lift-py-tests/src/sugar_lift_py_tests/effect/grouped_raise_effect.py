from __future__ import annotations

from dataclasses import dataclass

from .raise_effect import RaiseEffect, UndeterminedRaiseEffect


@dataclass(frozen=True)
class GroupedRaisePartition:
    """One split of a group by an ``except*`` type: the matched and residual
    subgroups, and the retained type tests it holds under.

    ``conditions`` is one ``(formula, face)`` per leaf whose match the one
    matcher retained (``MatchRetained``): the obligation and its caught face
    where the leaf is matched, its complement and missed face where it is
    residual.  Empty when every leaf's verdict was decided."""

    matched: "GroupedRaiseEffect"
    residual: "GroupedRaiseEffect"
    conditions: tuple = ()


@dataclass(frozen=True)
class GroupedRaiseEffect:
    """One immutable exception-group tree; leaves retain RaiseEffect identity.

    A leaf whose construction carries no class (an unanswered construction,
    ``OSError(e, 'x')``) is an ``UndeterminedRaiseEffect``: undecided, never
    typed by its callee."""

    group_identity: str
    message: object
    children: tuple[RaiseEffect | UndeterminedRaiseEffect | "GroupedRaiseEffect", ...]
    occurrence: str | None = None
    # The builtin group class the group's construction built
    # (builtins.ExceptionGroup or builtins.BaseExceptionGroup), decided by its
    # members (``GroupedRaiseSugar._group``). None when the construction left
    # it undecided (a member nothing here decides).
    exception_type_coordinate: object | None = None
    exception_type_mro: tuple | None = None

    @property
    def occurrence_id(self) -> str:
        return self.occurrence or self.group_identity

    @property
    def reason(self) -> str:
        return f"grouped raise {self.group_identity} with {len(self.children)} children"

    def partition(self, expected, site) -> tuple[GroupedRaisePartition, ...]:
        """Every split of this tree by ``except* expected``, nested topology
        kept: one split when every leaf's verdict is decided.

        A leaf whose match the one matcher retains (an undetermined leaf, an
        import-path class) is the same two-way split ordinary ``except``
        owns for it (``TrySugar._route_one_halt``): matched under the
        obligation, residual under its complement, each carrying its face.
        So a group of n retained leaves splits into every combination of
        them; nothing is refused, decided by guess or dropped."""
        splits: list[tuple[tuple, tuple, tuple]] = [((), (), ())]
        for child in self.children:
            if isinstance(child, GroupedRaiseEffect):
                options = tuple(
                    (
                        (split.matched,) if split.matched.children else (),
                        (split.residual,) if split.residual.children else (),
                        split.conditions,
                    )
                    for split in child.partition(expected, site)
                )
            else:
                options = _leaf_options(child, expected, site)
            splits = [
                (matched + leaf_matched, residual + leaf_residual, held + leaf_held)
                for matched, residual, held in splits
                for leaf_matched, leaf_residual, leaf_held in options
            ]
        return tuple(
            GroupedRaisePartition(self.derive(matched), self.derive(residual), held)
            for matched, residual, held in splits
        )

    def derive(
        self,
        children: tuple[
            RaiseEffect | UndeterminedRaiseEffect | "GroupedRaiseEffect", ...
        ],
    ) -> "GroupedRaiseEffect":
        return GroupedRaiseEffect(
            self.group_identity,
            self.message,
            children,
            occurrence=self.occurrence,
            exception_type_coordinate=self.exception_type_coordinate,
            exception_type_mro=self.exception_type_mro,
        )


def _leaf_options(effect, expected, site) -> tuple:
    """Where ``except* expected`` puts one leaf: ``(matched, residual,
    conditions)`` per face.

    Asked of the one matcher ``except`` and ``with`` ask
    (``matches_raise_effect``), over the class the leaf's raise read off the
    value its construction made (``RaiseSugar._effect``).  A decided verdict
    is one face.  A retained one (``MatchRetained``) is a genuine two-way
    split this partition owns, so it mints the pair of faces
    (``partition``): the leaf matched under the obligation, residual under
    its complement -- the two-faced outcome ordinary ``except`` routes an
    undecided match by, never a refusal."""
    from sugar_lift_py_tests.authenticated_exception_matching import (
        MatchDecided,
        matches_raise_effect,
    )
    from sugar_lift_py_tests.ir import not_
    from sugar_lift_py_tests.outcome.exit_set import partition

    verdict = matches_raise_effect(effect, expected)
    if isinstance(verdict, MatchDecided):
        return (((effect,), (), ()),) if verdict.value else (((), (effect,), ()),)
    caught_face, missed_face = partition(
        ("try-star.except-identity", site, effect.occurrence_id, verdict.obligation)
    )
    return (
        ((effect,), (), ((verdict.obligation, caught_face),)),
        ((), (effect,), ((not_(verdict.obligation), missed_face),)),
    )
