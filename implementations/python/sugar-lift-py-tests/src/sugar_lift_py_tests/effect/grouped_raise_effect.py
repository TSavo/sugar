from __future__ import annotations

from dataclasses import dataclass

from .raise_effect import RaiseEffect


@dataclass(frozen=True)
class GroupedRaisePartition:
    matched: "GroupedRaiseEffect"
    residual: "GroupedRaiseEffect"


@dataclass(frozen=True)
class GroupedRaiseEffect:
    """One immutable exception-group tree; leaves retain RaiseEffect identity."""

    group_identity: str
    message: object
    children: tuple[RaiseEffect | "GroupedRaiseEffect", ...]
    occurrence: str | None = None

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
        self, children: tuple[RaiseEffect | "GroupedRaiseEffect", ...]
    ) -> "GroupedRaiseEffect":
        return GroupedRaiseEffect(
            self.group_identity,
            self.message,
            children,
            occurrence=self.occurrence,
        )


def _leaf_matches(effect: RaiseEffect, expected, site) -> bool:
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
    from sugar_source_tree.panic import SugarNotWritten

    raised = effect.raised_value
    operation = getattr(raised, "test_python_subtype", None)
    if operation is None and effect.exception_type_coordinate is not None:
        from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
            AuthenticatedExceptionTypeValue,
        )

        raised = AuthenticatedExceptionTypeValue(
            raised,
            effect.exception_type_coordinate,
            effect.exception_type_mro,
        )
        operation = raised.test_python_subtype
    if operation is None:
        raise SugarNotWritten(
            owner="GroupedRaiseEffect.partition",
            observed="group leaf lacks an authenticated subtype floor",
            requested="RaiseEffect leaf with authenticated exception type testimony",
            fix="construct every group leaf through the ordinary exception floor",
        )
    outcome = operation(expected, site)
    if not isinstance(outcome, Complete):
        raise SugarNotWritten(
            owner="GroupedRaiseEffect.partition",
            observed="symbolic subtype partition",
            requested="closed true/false subtype partition for group topology",
            fix="keep symbolic group partition typed loud",
        )
    if isinstance(outcome.value, TrueBoolLiteralSugar):
        return True
    if isinstance(outcome.value, FalseBoolLiteralSugar):
        return False
    raise SugarNotWritten(
        owner="GroupedRaiseEffect.partition",
        observed=type(outcome.value).__name__,
        requested="closed boolean subtype partition",
        fix="keep unsupported subtype results typed loud",
    )
