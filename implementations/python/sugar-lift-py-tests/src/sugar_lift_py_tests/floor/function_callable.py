from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace
from typing import Any

from .floor_value import FloorValue
from .term_value import TermValue


@dataclass(frozen=True)
class FunctionCallable(FloorValue):
    name: str
    parameter: str | None = None
    return_name: str | None = None
    parameters: tuple[str, ...] = ()
    parameter_kinds: tuple[str, ...] = ()
    positional_defaults: tuple[FloorValue, ...] = ()
    keyword_only_defaults: tuple[FloorValue | None, ...] = ()
    decorators: tuple[Any, ...] = ()
    body: Any = dataclass_field(default=None, compare=False)

    def to_term(self, *, owner: str):
        """Project the callable as the coordinate bound by its def statement."""
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:function", [str_const(self.name)])

    def apply(self, value: TermValue) -> TermValue:
        if self.return_name != self.parameter:
            raise ValueError(
                f"write more Callable floor for `{self.name}`: return `{self.return_name}`"
            )
        return value

    def extend_scope(self, ctx):
        return replace(ctx, temporal=ctx.temporal.bind_value(self.name, self))

    def guarded(self, formula):
        del formula
        return self

    def callsite(self, arg_values, keyword_names, site):
        from sugar_lift_py_tests.factory import factory_panic_gap
        from sugar_lift_py_tests.factory.factory_gap_info import GapKind, GapLocus
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        if self.body is None:
            factory_panic_gap(
                owner="FunctionCallable",
                blame=str(site),
                observed=self.name,
                requested="call a bound function body",
                fix="bind FunctionCallable with its factory-built body",
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
        supplied_count = len(arg_values)
        fixed_positional_count = sum(
            kind in {"positional", "positional-only"} for kind in self.parameter_kinds
        )
        keyword_only_count = self.parameter_kinds.count("keyword-only")
        supported_signature = all(
            kind
            in {
                "positional",
                "positional-only",
                "var-positional",
                "keyword-only",
                "var-keyword",
            }
            for kind in self.parameter_kinds
        )
        has_var_positional = "var-positional" in self.parameter_kinds
        required_count = fixed_positional_count - len(self.positional_defaults)
        valid_positional_arity = required_count <= supplied_count and (
            has_var_positional or supplied_count <= fixed_positional_count
        )
        keyword_only_values = tuple(
            default for default in self.keyword_only_defaults if default is not None
        )
        aligned_keyword_only_defaults = (
            len(self.keyword_only_defaults) == keyword_only_count
            and len(keyword_only_values) == keyword_only_count
        )
        if (
            supported_signature
            and not keyword_names
            and valid_positional_arity
            and aligned_keyword_only_defaults
        ):
            from .dict_value import DictValue
            from .tuple_value import TupleValue

            supplied_fixed_count = min(supplied_count, fixed_positional_count)
            missing_fixed_count = fixed_positional_count - supplied_fixed_count
            fixed_values = (
                *arg_values[:supplied_fixed_count],
                *self.positional_defaults[
                    len(self.positional_defaults) - missing_fixed_count :
                ],
            )
            positional = iter(fixed_values)
            keyword_only = iter(keyword_only_values)
            surplus = arg_values[fixed_positional_count:]
            bound_values = tuple(
                (
                    next(positional)
                    if kind in {"positional", "positional-only"}
                    else (
                        TupleValue(surplus)
                        if kind == "var-positional"
                        else (
                            next(keyword_only)
                            if kind == "keyword-only"
                            else DictValue(())
                        )
                    )
                )
                for kind in self.parameter_kinds
            )
        else:
            bound_values = None
        if bound_values is None:
            factory_panic_gap(
                owner="FunctionCallable",
                blame=str(site),
                observed=self.parameter_kinds,
                requested="bind call arguments to a function signature",
                fix="write the callable argument-binding floor for this signature",
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
        return Complete(
            CallSiteValue(
                target_name=self.name,
                arg_values=bound_values,
                parameters=self.parameters,
                term=ctor(
                    f"call:{self.name}",
                    [value.to_term(owner=str(site)) for value in arg_values],
                    symbol_kind="contract-target",
                ),
                body=self.body,
                site=site,
            )
        )
