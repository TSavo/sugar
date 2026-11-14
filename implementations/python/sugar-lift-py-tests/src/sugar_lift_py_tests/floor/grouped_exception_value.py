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
        def part(effect):
            if effect is None:
                return NoneValue()
            return GroupedExceptionValue(effect, site)

        # One completed arm per split, guarded by the retained type tests it
        # holds under (each with its face): a decided tree is one arm.
        arms = []
        for matched, residual, conditions in _split(self.effect, arguments[0], site):
            arm = ExitSet.completed(TupleValue((part(matched), part(residual))))
            for formula, face in conditions:
                arm = arm.guarded(formula, face)
            arms.append(arm)
        return ExitSet(()).union(*arms)


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


def _split(effect, condition, site) -> tuple:
    """CPython ``exceptiongroup_split_recursive`` over an authenticated tree:
    every ``(matched, residual, conditions)`` split, an empty part ``None``.

    The condition is checked against the group itself first, then each
    nested group and leaf, each asked of the one matcher ``except`` asks
    (``match_options`` over ``matches_raise_effect``).  A decided verdict is
    one face; a retained one (an undetermined leaf, an import-path class, a
    group whose class its construction left undecided, tested over the
    group instance itself) is the two-way split it owns, matched under the
    obligation and residual under its complement, so a tree splits into
    every combination of its retained tests.  What an undecided group's
    construction owes rides on the path that built it
    (``ExitSet.two_faced``), beneath every split.  Nothing is refused,
    decided by guess or dropped."""
    from sugar_lift_py_tests.effect import GroupedRaiseEffect
    from sugar_lift_py_tests.effect.grouped_raise_effect import match_options

    splits = []
    for matched, _residual, held in match_options(
        effect, condition, site, question="exception-group.split"
    ):
        if matched:
            splits.append((effect, None, held))
            continue
        if not isinstance(effect, GroupedRaiseEffect):
            splits.append((None, effect, held))
            continue
        parts = [((), (), held)]
        for child in effect.children:
            parts = [
                (
                    kept + ((child_match,) if child_match is not None else ()),
                    rest + ((child_rest,) if child_rest is not None else ()),
                    conditions + child_conditions,
                )
                for kept, rest, conditions in parts
                for child_match, child_rest, child_conditions in _split(
                    child, condition, site
                )
            ]
        splits.extend(
            (
                effect.derive(kept) if kept else None,
                effect.derive(rest) if rest else None,
                conditions,
            )
            for kept, rest, conditions in parts
        )
    return tuple(splits)


def _topology(effect) -> str:
    from sugar_lift_py_tests.effect import GroupedRaiseEffect

    parts = []
    for child in effect.children:
        if isinstance(child, GroupedRaiseEffect):
            parts.append(f"[{_topology(child)}]")
        else:
            parts.append(str(child.occurrence))
    return ",".join(parts)
