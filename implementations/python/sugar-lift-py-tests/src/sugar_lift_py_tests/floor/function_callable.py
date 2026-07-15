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
        simple = all(
            kind in {"positional", "positional-only"} for kind in self.parameter_kinds
        )
        supplied_count = len(arg_values)
        if simple:
            required_count = len(self.parameters) - len(self.positional_defaults)
            valid_positional_arity = required_count <= supplied_count <= len(
                self.parameters
            )
            if not keyword_names and valid_positional_arity:
                missing_count = len(self.parameters) - supplied_count
                bound_values = (
                    *arg_values,
                    *self.positional_defaults[
                        len(self.positional_defaults) - missing_count :
                    ],
                )
            else:
                bound_values = None
        else:
            fixed_positional_count = sum(
                kind in {"positional", "positional-only"}
                for kind in self.parameter_kinds
            )
            empty_variadic_signature = (
                any(
                    kind in {"var-positional", "var-keyword"}
                    for kind in self.parameter_kinds
                )
                and all(
                    kind
                    in {
                        "positional",
                        "positional-only",
                        "var-positional",
                        "var-keyword",
                    }
                    for kind in self.parameter_kinds
                )
            )
            if (
                empty_variadic_signature
                and not keyword_names
                and supplied_count == fixed_positional_count
            ):
                from .dict_value import DictValue
                from .tuple_value import TupleValue

                positional = iter(arg_values)
                bound_values = tuple(
                    next(positional)
                    if kind in {"positional", "positional-only"}
                    else TupleValue(())
                    if kind == "var-positional"
                    else DictValue(())
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
