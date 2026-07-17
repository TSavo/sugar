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

    def call_scope_updates(self, arg_values, ctx, site):
        """Replay a straight-line local callback and return its caller rebinds."""
        from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap
        from sugar_lift_py_tests.floor.call_site_value import (
            CallSiteValue,
            _ctx_with_curried_args,
        )
        from sugar_lift_py_tests.outcome import complete_value, Complete
        from sugar_lift_py_tests.sugar.install_source_dig import ContextualizedDigBody
        from sugar_lift_py_tests.sugar_body import SugarBody

        callsite = complete_value(
            self.callsite(arg_values, (), site),
            owner="FunctionCallable.call_scope_updates",
        )
        if not isinstance(callsite, CallSiteValue):
            factory_panic_gap(
                owner="FunctionCallable",
                blame=str(site),
                observed=type(callsite).__name__,
                requested="callback CallSiteValue",
                fix="construct the callback callsite or panic loudly",
            )
        body = callsite.body
        if not isinstance(body, SugarBody) or not isinstance(
            body.sugar, ContextualizedDigBody
        ):
            factory_panic_gap(
                owner="FunctionCallable",
                blame=str(site),
                observed=type(body).__name__,
                requested="straight-line callback scope updates",
                fix="carry a contextualized local callback body or panic loudly",
            )
        curried = _ctx_with_curried_args(ctx, callsite.parameters, callsite.arg_values)
        final_ctx = body.sugar.scope_after(curried)
        caller_names = tuple(binding.name for binding in ctx.temporal.bindings)
        updates = tuple(
            (name, final_ctx.temporal.value_for(name))
            for name in caller_names
            if final_ctx.temporal.value_for(name) != ctx.temporal.value_for(name)
        )
        from .scope_rebind import ScopeRebinds

        return Complete(ScopeRebinds(updates))

    def callsite(
        self,
        arg_values,
        keyword_names,
        site,
        *,
        source_arg_values=None,
        term=None,
    ):
        from sugar_lift_py_tests.factory import factory_panic_gap
        from sugar_lift_py_tests.factory.factory_gap_info import GapKind, GapLocus
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        if source_arg_values is None:
            source_arg_values = arg_values

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
        # CallSugar / KeywordCallSugar trail keyword values after positionals and
        # list their names in keyword_names (source order). Empty keyword_names is
        # the pure-positional path.
        n_keywords = len(keyword_names)
        if n_keywords:
            if n_keywords > len(arg_values):
                factory_panic_gap(
                    owner="FunctionCallable",
                    blame=str(site),
                    observed=(len(arg_values), keyword_names),
                    requested="keyword values aligned with keyword_names",
                    fix="pass positional then keyword values in source order",
                    gap_kind=GapKind.FLOOR,
                    gap_locus=GapLocus.CONSTRUCTION,
                )
            positional_supplied = arg_values[: len(arg_values) - n_keywords]
            keyword_map = {
                name: value
                for name, value in zip(
                    keyword_names, arg_values[len(arg_values) - n_keywords :]
                )
            }
        else:
            positional_supplied = arg_values
            keyword_map = {}

        keyword_expansions = tuple(
            value
            for name, value in zip(
                keyword_names, arg_values[len(arg_values) - n_keywords :]
            )
            if name == "**"
        )
        keyword_map.pop("**", None)
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
        has_var_keyword = "var-keyword" in self.parameter_kinds
        from .dict_value import DictValue
        from .symbolic_value import SymbolicValue

        keyword_expansion = (
            keyword_expansions[0] if len(keyword_expansions) == 1 else None
        )
        binds_keyword_expansion_exactly = (
            keyword_names == ("**",)
            and self.parameter_kinds
            and self.parameter_kinds[-1] == "var-keyword"
            and all(
                kind in {"positional", "positional-only"}
                for kind in self.parameter_kinds[:-1]
            )
            and len(positional_supplied) == fixed_positional_count
            and (
                type(keyword_expansion) in (DictValue, SymbolicValue)
                or (
                    type(keyword_expansion) is CallSiteValue
                    and keyword_expansion.body is None
                )
            )
        )
        # A single mapping expansion binds exactly to a callee-owned **kwargs
        # formal. A body-less callsite remains an opaque mapping coordinate
        # under the source ``**`` contract; a body-bearing peer must be dug
        # instead. Other expansion shapes remain loud: do not invent keys or
        # confuse missing binder machinery with runtime dependence.
        if (
            keyword_expansions
            and not binds_keyword_expansion_exactly
            or any(
                isinstance(value, CallSiteValue) and value.target_name == "*"
                for value in positional_supplied
            )
        ):
            bound_values = None
        elif not supported_signature:
            bound_values = None
        else:
            from .string_value import StringValue
            from .tuple_value import TupleValue

            bound_list: list[FloorValue] = []
            pos_iter = iter(positional_supplied)
            # positional_defaults align with the trailing fixed positionals that
            # have defaults: index 0 is the first defaulted fixed param.
            default_start = fixed_positional_count - len(self.positional_defaults)
            keyword_only_defaults_by_name: dict[str, FloorValue] = {}
            keyword_only_names = [
                name
                for name, kind in zip(self.parameters, self.parameter_kinds)
                if kind == "keyword-only"
            ]
            if len(self.keyword_only_defaults) == keyword_only_count:
                for name, default in zip(
                    keyword_only_names, self.keyword_only_defaults
                ):
                    if default is not None:
                        keyword_only_defaults_by_name[name] = default
            remaining_keywords = dict(keyword_map)
            binding_ok = True
            fixed_seen = 0
            for name, kind in zip(self.parameters, self.parameter_kinds):
                if kind in {"positional", "positional-only"}:
                    if name in remaining_keywords:
                        bound_list.append(remaining_keywords.pop(name))
                        fixed_seen += 1
                        continue
                    try:
                        bound_list.append(next(pos_iter))
                        fixed_seen += 1
                    except StopIteration:
                        default_index = fixed_seen - default_start
                        if 0 <= default_index < len(self.positional_defaults):
                            bound_list.append(self.positional_defaults[default_index])
                            fixed_seen += 1
                        else:
                            binding_ok = False
                            break
                elif kind == "var-positional":
                    bound_list.append(TupleValue(tuple(pos_iter)))
                elif kind == "keyword-only":
                    if name in remaining_keywords:
                        bound_list.append(remaining_keywords.pop(name))
                    elif name in keyword_only_defaults_by_name:
                        bound_list.append(keyword_only_defaults_by_name[name])
                    else:
                        binding_ok = False
                        break
                elif kind == "var-keyword":
                    if keyword_expansion is not None:
                        bound_list.append(keyword_expansion)
                    else:
                        bound_list.append(
                            DictValue(
                                tuple(
                                    (StringValue(key), value)
                                    for key, value in remaining_keywords.items()
                                )
                            )
                            if remaining_keywords
                            else DictValue(())
                        )
                    remaining_keywords.clear()
            # Leftover positionals only lawful with *args.
            try:
                next(pos_iter)
                leftover_pos = True
            except StopIteration:
                leftover_pos = False
            if leftover_pos and not has_var_positional:
                binding_ok = False
            if remaining_keywords and not has_var_keyword:
                binding_ok = False
            # Pure-positional path still requires keyword-only defaults complete
            # when the signature has keyword-only params and none were supplied.
            if (
                binding_ok
                and not keyword_names
                and keyword_only_count
                and len(keyword_only_defaults_by_name) != keyword_only_count
            ):
                binding_ok = False
            bound_values = tuple(bound_list) if binding_ok else None
        if bound_values is None:
            factory_panic_gap(
                owner="FunctionCallable",
                blame=str(site),
                observed=(self.parameter_kinds, keyword_names),
                requested="bind call arguments to a function signature",
                fix="write the callable argument-binding floor for this signature",
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
        if term is None:
            term = ctor(
                f"call:{self.name}",
                [value.to_term(owner=str(site)) for value in source_arg_values],
                symbol_kind="contract-target",
            )
        return Complete(
            CallSiteValue(
                target_name=self.name,
                arg_values=bound_values,
                parameters=self.parameters,
                term=term,
                body=self.body,
                site=site,
            )
        )
