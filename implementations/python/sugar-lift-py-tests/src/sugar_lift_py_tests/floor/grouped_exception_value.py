"""The raised ``ExceptionGroup`` instance a With statement hands to ``__exit__``.

The body raised an authenticated ``GroupedRaiseEffect`` tree; this is that same
group object as an exit argument. Only ``split`` is floored, from its
documented algorithm
(https://docs.python.org/3/library/exceptions.html#BaseExceptionGroup.split):
the condition is checked against the group itself first, then nested groups
and leaves; each part is ``derive``-d from the original group, and an empty
part is ``None``. Re-raising the value re-raises the same group tree. Nothing
else about the group is invented: other members stay construction gaps.
"""

from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class GroupedExceptionValue(FloorValue):
    effect: object
    site: object = None

    @property
    def exception_type_coordinate(self):
        return self.effect.exception_type_coordinate

    @property
    def exception_type_mro(self):
        return self.effect.exception_type_mro

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        del owner
        return ctor(
            "python:exception_group.instance",
            (
                str_const(self.effect.occurrence_id),
                str_const(_topology(self.effect)),
            ),
        )

    def is_identical(self, other, site):
        from sugar_lift_py_tests.floor.none_value import NoneValue

        if type(other) is NoneValue:
            # A raised exception instance is never the None singleton.
            from sugar_lift_py_tests.outcome import ExitSet
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )

            return ExitSet.completed(FalseBoolLiteralSugar(site=site))
        return super().is_identical(other, site)

    def attribute(self, name, site, ctx):
        if name == "split":
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(GroupedExceptionSplitMethod(self, site))
        return super().attribute(name, site, ctx)

    def call_method_value(
        self, name, arguments, *, owner, blame, ctx=None, keywords=(), required_frame=None
    ):
        if name == "split" and not keywords:
            return self.split(tuple(arguments), (), blame)
        return super().call_method_value(
            name,
            arguments,
            owner=owner,
            blame=blame,
            ctx=ctx,
            keywords=keywords,
            required_frame=required_frame,
        )

    def split(self, arguments, keyword_names, site):
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_source_tree.panic import SugarNotWritten

        if keyword_names or len(arguments) != 1:
            raise SugarNotWritten(
                blame=site,
                owner="GroupedExceptionValue.split",
                observed=(len(arguments), keyword_names),
                requested="split(condition) with one positional type condition",
                fix="keep predicate-callable and keyword conditions loud",
            )
        matched, residual = _split(self.effect, arguments[0], site)

        def part(effect):
            if effect is None:
                return NoneValue()
            return GroupedExceptionValue(effect, site)

        return ExitSet.completed(TupleValue((part(matched), part(residual))))


@dataclass(frozen=True)
class GroupedExceptionSplitMethod(FloorValue):
    group: GroupedExceptionValue
    site: object = None

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:exception_group.split",
            (self.group.to_term(owner=owner),),
        )

    def callable_application_with(self, operation, ctx):
        del ctx
        return self.group.split(
            tuple(getattr(operation, "arguments", ())),
            getattr(operation, "keyword_names", ()),
            getattr(operation, "blame", None) or self.site,
        )


def _split(effect, condition, site):
    """CPython ``exceptiongroup_split_recursive`` over an authenticated tree."""
    from sugar_lift_py_tests.effect import GroupedRaiseEffect

    if _type_matches(effect, condition, site):
        return effect, None
    matched = []
    residual = []
    for child in effect.children:
        if isinstance(child, GroupedRaiseEffect):
            child_match, child_rest = _split(child, condition, site)
            if child_match is not None:
                matched.append(child_match)
            if child_rest is not None:
                residual.append(child_rest)
        elif _type_matches(child, condition, site):
            matched.append(child)
        else:
            residual.append(child)
    return (
        effect.derive(tuple(matched)) if matched else None,
        effect.derive(tuple(residual)) if residual else None,
    )


def _type_matches(effect, condition, site) -> bool:
    """``isinstance(exc, condition)`` from the raise's own type testimony.

    For a group this is the group's class; for a leaf, the leaf's class. The
    raised-type law decides only builtin exception classes by MRO membership.
    """
    from sugar_lift_py_tests.floor.manager_coordinate import RaisedExitTypeValue
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
    from sugar_source_tree.panic import SugarNotWritten

    if effect.exception_type_coordinate is None or effect.exception_type_mro is None:
        raise SugarNotWritten(
            blame=site,
            owner="GroupedExceptionValue.split",
            observed="group member without authenticated type testimony",
            requested="class identity and MRO from Raise construction",
            fix="construct every group through the builtin group coordinate",
        )
    outcome = RaisedExitTypeValue(
        effect.exception_type_coordinate, effect.exception_type_mro
    ).test_python_subtype(condition, site)
    decided = outcome.completed_value() if isinstance(outcome, ExitSet) else None
    if isinstance(decided, TrueBoolLiteralSugar):
        return True
    if isinstance(decided, FalseBoolLiteralSugar):
        return False
    raise SugarNotWritten(
        blame=site,
        owner="GroupedExceptionValue.split",
        observed=type(outcome if decided is None else decided).__name__,
        requested="closed true/false group-type match",
        fix="keep a symbolic split condition loud",
    )


def _topology(effect) -> str:
    from sugar_lift_py_tests.effect import GroupedRaiseEffect

    parts = []
    for child in effect.children:
        if isinstance(child, GroupedRaiseEffect):
            parts.append(f"[{_topology(child)}]")
        else:
            parts.append(str(child.occurrence))
    return ",".join(parts)
