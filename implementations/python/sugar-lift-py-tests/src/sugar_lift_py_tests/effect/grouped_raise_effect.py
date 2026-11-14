from __future__ import annotations

from dataclasses import dataclass

from .raise_effect import RaiseEffect, UndeterminedRaiseEffect


@dataclass(frozen=True)
class GroupedRaisePartition:
    matched: "GroupedRaiseEffect"
    residual: "GroupedRaiseEffect"


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
    # The builtin group class the Raise construction authenticated by runtime
    # identity (builtins.ExceptionGroup or builtins.BaseExceptionGroup). None
    # when a producer did not supply that testimony; exit inputs then stay loud.
    exception_type_coordinate: object | None = None
    exception_type_mro: tuple | None = None

    @property
    def occurrence_id(self) -> str:
        return self.occurrence or self.group_identity

    @property
    def reason(self) -> str:
        return f"grouped raise {self.group_identity} with {len(self.children)} children"

    def partition(self, expected, site) -> GroupedRaisePartition:
        matched = []
        residual = []
        for child in self.children:
            if isinstance(child, GroupedRaiseEffect):
                split = child.partition(expected, site)
                if split.matched.children:
                    matched.append(split.matched)
                if split.residual.children:
                    residual.append(split.residual)
                continue
            if _leaf_matches(child, expected, site):
                matched.append(child)
            else:
                residual.append(child)
        return GroupedRaisePartition(
            self.derive(tuple(matched)),
            self.derive(tuple(residual)),
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


def _leaf_matches(effect, expected, site) -> bool:
    """Whether ``except* expected`` catches one leaf.

    Asked of the one matcher ``except`` and ``with`` ask
    (``matches_raise_effect``), over the class the leaf's raise read off the
    value its construction made (``RaiseSugar._effect``: the coordinate and
    ancestry on the effect).  A leaf whose class is undetermined, or whose
    match is a real question nothing here decides, is refused by name: the
    partition is a closed split of the group's topology."""
    from sugar_lift_py_tests.authenticated_exception_matching import (
        MatchDecided,
        matches_raise_effect,
    )
    from sugar_source_tree.panic import SugarNotWritten

    verdict = matches_raise_effect(effect, expected)
    if isinstance(verdict, MatchDecided):
        return verdict.value
    raise SugarNotWritten(
        blame=site,
        owner="GroupedRaiseEffect.partition",
        observed="symbolic subtype partition",
        requested="closed true/false subtype partition for group topology",
        fix="keep symbolic group partition typed loud",
    )
