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
    exit_suppression: Any = None
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
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
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
            construction_panic_gap(
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
            construction_panic_gap(
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

    def callable_application_with(self, operation, ctx):
        del ctx
        return self.callsite(
            operation.arguments,
            operation.keyword_names,
            operation.site,
        )

    def callsite(
        self,
        arg_values,
        keyword_names,
        site,
        *,
        source_arg_values=None,
        term=None,
        native_shape=None,
    ):
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.gap.info import GapKind, GapLocus
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete, complete_value

        if source_arg_values is None:
            source_arg_values = arg_values
        if self.decorators:
            decorated = self._apply_decorators(site)
            return decorated.callsite(
                arg_values,
                keyword_names,
                site,
                source_arg_values=source_arg_values,
                term=term,
                native_shape=native_shape,
            )

        if self.body is None:
            construction_panic_gap(
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
                construction_panic_gap(
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
        # Body-bearing ** expansions are diggable floor work: dig the mapping,
        # then re-enter binding as substitution. Opaque / undiggable peers stay
        # loud below (never mint a RuntimeEffect over a diggable callsite).
        if any(_diggable_keyword_expansion(value) for value in keyword_expansions):
            from sugar_lift_py_tests.floor.call_site_value import force_floor

            rewritten = list(arg_values)
            kw_start = len(arg_values) - n_keywords
            for offset, name in enumerate(keyword_names):
                if name != "**":
                    continue
                value = rewritten[kw_start + offset]
                if _diggable_keyword_expansion(value):
                    rewritten[kw_start + offset] = force_floor(
                        value,
                        None,
                        owner="FunctionCallable diggable **kwargs",
                        project_callsite=False,
                    )
            return self.callsite(
                tuple(rewritten),
                keyword_names,
                site,
                source_arg_values=source_arg_values,
                term=term,
            )
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
        from .guarded_value import GuardedValue
        from .string_value import StringValue
        from .symbolic_value import SymbolicValue

        keyword_expansion = (
            keyword_expansions[0] if len(keyword_expansions) == 1 else None
        )
        # One or more constructed DictValue ** expansions merge in source order
        # into the explicit keyword map. Duplicate keys are a static TypeError
        # (Python rejects multiple values for the same keyword). Non-string
        # keys leave the expansion for the exact-** / loud paths below.
        keyword_expansion_collision = False
        if keyword_expansions and all(
            type(expansion) is DictValue for expansion in keyword_expansions
        ):
            expanded_keywords: dict[str, FloorValue] = {}
            merge_ok = True
            for expansion in keyword_expansions:
                for key, value in expansion.entries:
                    if type(key) is not StringValue:
                        merge_ok = False
                        break
                    if key.value in keyword_map or key.value in expanded_keywords:
                        keyword_expansion_collision = True
                        merge_ok = False
                        break
                    expanded_keywords[key.value] = value
                if not merge_ok:
                    break
            else:
                keyword_map.update(expanded_keywords)
                keyword_expansions = ()
                keyword_expansion = None
        if isinstance(keyword_expansion, GuardedValue) and _guarded_dict_value(
            keyword_expansion
        ):
            explicit = DictValue(
                tuple((StringValue(key), value) for key, value in keyword_map.items())
            )
            keyword_expansion = complete_value(
                keyword_expansion.map_from_left("bitwise_or", explicit, site),
                owner="FunctionCallable guarded **kwargs substitution",
            )
            keyword_map.clear()
        binds_keyword_expansion_exactly = (
            not keyword_map
            and len(keyword_expansions) == 1
            and self.parameter_kinds
            and self.parameter_kinds[-1] == "var-keyword"
            and all(
                kind in {"positional", "positional-only"}
                for kind in self.parameter_kinds[:-1]
            )
            and (
                type(keyword_expansion) in (DictValue, GuardedValue, SymbolicValue)
                or (
                    type(keyword_expansion) is CallSiteValue
                    and keyword_expansion.body is None
                )
            )
        )
        # A single mapping expansion binds exactly to a callee-owned **kwargs
        # formal. The ordinary fixed-parameter loop below proves and fills any
        # preceding declared defaults; missing required parameters still fail
        # there. A body-less callsite remains an opaque mapping coordinate
        # under the source ``**`` contract; a body-bearing peer must be dug
        # instead. Other expansion shapes remain loud: do not invent keys or
        # confuse missing binder machinery with runtime dependence.
        binding_failed_decidably = False
        if keyword_expansion_collision:
            bound_values = None
            binding_failed_decidably = True
        elif (
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
            binding_failed_decidably = not binding_ok
            bound_values = tuple(bound_list) if binding_ok else None
        if bound_values is None:
            from sugar_lift_py_tests.effect.runtime_effect import (
                is_lift_time_decidable,
            )

            # Body-bearing callsites are diggable floor work, not runtime
            # dependence: construct-or-panic after dig, never mint an effect.
            diggable_keyword_expansion = (
                type(keyword_expansion) is CallSiteValue
                and keyword_expansion.body is not None
            )
            runtime_keyword_expansion = (
                len(keyword_expansions) == 1
                and keyword_expansion is not None
                and not diggable_keyword_expansion
                and not is_lift_time_decidable(
                    keyword_expansion.to_term(owner="FunctionCallable **kwargs")
                )
            )
            if runtime_keyword_expansion:
                from sugar_lift_py_tests.effect import (
                    runtime_callable_argument_binding,
                )

                return runtime_callable_argument_binding(keyword_expansion, site)
            keyword_bindable_names = {
                name
                for name, kind in zip(self.parameters, self.parameter_kinds)
                if kind in {"positional", "keyword-only"}
            }
            unexpected_keywords = tuple(
                name for name in keyword_map if name not in keyword_bindable_names
            )
            # A completed binding attempt that fails under a supported signature
            # is a static TypeError (missing/extra/unexpected), not an unbuilt
            # floor. Opaque expansions and unsupported machinery stay loud above.
            static_type_error = supported_signature and (
                binding_failed_decidably
                or (
                    not has_var_keyword
                    and "**" not in keyword_names
                    and bool(unexpected_keywords)
                )
            )
            if static_type_error:
                from sugar_lift_py_tests.floor.ground_exit import (
                    ground_exceptional_exit,
                )

                return ground_exceptional_exit(
                    exception_name="TypeError",
                    site=site,
                    owner="FunctionCallable.call",
                )
            construction_panic_gap(
                owner="FunctionCallable",
                blame=str(site),
                observed=(self.parameter_kinds, keyword_names),
                requested="bind call arguments to a function signature",
                fix="write the callable argument-binding floor for this signature",
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
        assert bound_values is not None
        if term is None:
            term = ctor(
                f"call:{self.name}",
                [value.to_term(owner=str(site)) for value in source_arg_values],
                symbol_kind="contract-target",
            )
        body = self.body
        from sugar_lift_py_tests.sugar.install_source_dig import ContextualizedDigBody
        from sugar_lift_py_tests.sugar_body import SugarBody

        if isinstance(body, SugarBody) and isinstance(
            body.sugar, ContextualizedDigBody
        ):
            body = replace(
                body,
                sugar=replace(
                    body.sugar,
                    callable_binding=self,
                    callable_name_is_parameter=self.name in self.parameters,
                ),
            )
        return Complete(
            CallSiteValue(
                target_name=self.name,
                arg_values=bound_values,
                parameters=self.parameters,
                term=term,
                body=body,
                site=site,
                exit_suppression=self.exit_suppression,
                native_shape=native_shape,
            )
        )

    def _apply_decorators(self, site):
        """Apply Python decorators as nested callable substitutions."""
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.floor.call_site_value import (
            CallSiteValue,
            _ctx_with_curried_args,
            _reduce_callsite_body,
            force_floor,
        )
        from sugar_lift_py_tests.outcome import Incomplete, complete_value

        def decorator_value_preserves_implementation(decorator) -> bool:
            # Recognition-era native_shape / decorator_contracts tables are gone.
            # Only the NEP-18 name enrollment below remains (floor, not recognition).
            return False

        current = replace(self, decorators=())
        for decorator in reversed(self.decorators):
            # NEP-18 array_function_dispatch enrollment (floor name set only).
            if decorator_value_preserves_implementation(decorator):
                continue
            if isinstance(decorator, CallSiteValue) and (
                _implementation_preserving_decorator_factory(decorator.target_name)
            ):
                # NEP-18 array-function wrappers (and their partial aliases) are
                # not soft-continue: under default dispatch the public API body
                # is exactly the decorated implementation. Override routing via
                # `__array_function__` stays unmodeled as its own construction.
                # #5152 sugar.enumerate implication fold panics here when the
                # decorator CallSiteValue is body-less (functools.partial of
                # overrides.array_function_dispatch).
                continue
            if isinstance(decorator, CallSiteValue):
                factory_name = decorator.target_name
                if decorator.body is None:
                    construction_panic_gap(
                        owner=f"FunctionCallable decorator factory:{factory_name}",
                        blame=str(site),
                        observed=(
                            f"missing callsite body for decorator factory "
                            f"`{factory_name}`"
                        ),
                        requested=(
                            "decorator callable floor or implementation-preserving "
                            "decorator contract"
                        ),
                        fix=(
                            f"construct a factory-built body for `{factory_name}`, "
                            f"resolve partial/import aliases to the real "
                            f"FunctionCallable, or enroll an implementation-"
                            f"preserving contract when the public API body is "
                            f"exactly the decorated implementation (see "
                            f"array_function_dispatch / functools.wraps via "
                            f"recognition native_shape); never soft-continue "
                            f"implication enumeration"
                        ),
                    )
                decorator = decorator.force_floor(
                    None,
                    owner=f"FunctionCallable decorator factory:{factory_name}",
                    project_callsite=False,
                )
            if not isinstance(decorator, FunctionCallable):
                construction_panic_gap(
                    owner="FunctionCallable",
                    blame=str(site),
                    observed=type(decorator).__name__,
                    requested="decorator callable substitution",
                    fix="construct the decorator callable floor or panic loudly",
                )
            assert isinstance(decorator, FunctionCallable)
            applied = complete_value(
                decorator.callsite((current,), (), site),
                owner="FunctionCallable decorator application",
            )
            if not isinstance(applied, CallSiteValue):
                construction_panic_gap(
                    owner="FunctionCallable",
                    blame=str(site),
                    observed=type(applied).__name__,
                    requested="decorator callsite substitution",
                    fix="construct the decorator callsite or panic loudly",
                )
            assert isinstance(applied, CallSiteValue)
            if applied.body is None:
                construction_panic_gap(
                    owner=f"FunctionCallable decorator application:{applied.target_name}",
                    blame=str(site),
                    observed=(
                        f"missing decorator callsite body for "
                        f"`{applied.target_name}`"
                    ),
                    requested="decorator result substitution",
                    fix=(
                        f"construct the decorator body for `{applied.target_name}` "
                        f"or panic loudly; never soft-continue"
                    ),
                )
            assert applied.body is not None
            result_outcome = _reduce_callsite_body(
                applied.body,
                _ctx_with_curried_args(None, applied.parameters, applied.arg_values),
                blame=applied.target_name,
            )
            if isinstance(result_outcome, Incomplete):
                construction_panic_gap(
                    owner=(
                        "FunctionCallable decorator result:" f"{applied.target_name}"
                    ),
                    blame=str(site),
                    observed=type(result_outcome.effect).__name__,
                    requested="completed decorator result substitution",
                    fix=(
                        "construct the decorator body's runtime-dependent result "
                        "before applying it; never read an incomplete effect as a "
                        "completed callable"
                    ),
                )
            result = complete_value(
                result_outcome,
                owner="FunctionCallable decorator result",
            )
            if (
                isinstance(result, CallSiteValue)
                and result.target_name in {"cast", "typing.cast"}
                and len(result.arg_values) == 2
            ):
                # typing.cast is runtime identity. Its second operand is the
                # exact callable produced by the decorator body.
                current = result.arg_values[1]
            elif (
                isinstance(result, CallSiteValue)
                and _array_function_dispatcher_ctor(result.target_name)
                and len(result.arg_values) == 2
                and isinstance(result.arg_values[1], FunctionCallable)
            ):
                # Digging the real array_function_dispatch body lands on the C
                # `_ArrayFunctionDispatcher(dispatcher, implementation)` ctor.
                # Default-dispatch public API body is the implementation.
                current = result.arg_values[1]
            else:
                current = force_floor(
                    result,
                    None,
                    owner="FunctionCallable decorator result",
                    project_callsite=False,
                )
            if not isinstance(current, FunctionCallable):
                construction_panic_gap(
                    owner="FunctionCallable",
                    blame=str(site),
                    observed=type(current).__name__,
                    requested="decorated callable floor",
                    fix="construct the decorator return callable or panic loudly",
                )
        return current


# Bare names and trailing segments of qualified decorator-factory targets whose
# application leaves the decorated FunctionCallable as the public-API body under
# default dispatch. Enrollment is existence: a new identity-preserving factory
# must land here with a pin, not as a silent continue.
_IMPLEMENTATION_PRESERVING_DECORATOR_FACTORIES = frozenset(
    {
        "array_function_dispatch",
        "array_function_from_dispatcher",
        "array_function_from_c_func_and_dispatcher",
    }
)


def _implementation_preserving_decorator_factory(target_name: str) -> bool:
    bare = target_name.rsplit(".", 1)[-1]
    return bare in _IMPLEMENTATION_PRESERVING_DECORATOR_FACTORIES


def _array_function_dispatcher_ctor(target_name: str) -> bool:
    return target_name.rsplit(".", 1)[-1] == "_ArrayFunctionDispatcher"


def _diggable_keyword_expansion(value) -> bool:
    """True when a ``**`` operand carries a factory-built body that can dig."""
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.sugar.function_body_universe import FunctionBodyUniverse
    from sugar_lift_py_tests.sugar_body import SugarBody

    return type(value) is CallSiteValue and (
        isinstance(value.body, SugarBody)
        or isinstance(value.body, FunctionBodyUniverse)
    )


def _guarded_dict_value(value) -> bool:
    from .dict_value import DictValue
    from .guarded_value import GuardedValue

    if type(value) is DictValue:
        return True
    if not isinstance(value, GuardedValue):
        return False
    return _guarded_dict_value(value.when_true) and _guarded_dict_value(
        value.when_false
    )
