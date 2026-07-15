from __future__ import annotations

import builtins

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.sugar.install_source_dig import (
    module_sibling_function_nodes as _module_sibling_function_nodes,
    resolve_install_source_funcdef as _resolve_install_source_funcdef,
)


def _expand_function_positional_args(arg_values: tuple, *, site: object) -> tuple:
    """Expand only structurally known finite ``*`` operands for a bound function.

    ``StarredSugar`` preserves the source spelling as a ``CallSiteValue``. This
    binder view unwraps constructed tuple/list floors without changing that
    source value, so the call coordinate remains keyed by what the caller wrote.
    """
    from sugar_lift_py_tests.factory import factory_panic_gap
    from sugar_lift_py_tests.factory.factory_gap_info import GapKind, GapLocus
    from sugar_lift_py_tests.floor import CallSiteValue, ListValue, TupleValue

    expanded = []
    for value in arg_values:
        if not (isinstance(value, CallSiteValue) and value.target_name == "*"):
            expanded.append(value)
            continue

        operand = value.arg_values[0]
        if type(operand) in (TupleValue, ListValue):
            expanded.extend(operand.elements)
            continue

        factory_panic_gap(
            owner="CallSugar",
            blame=site,
            observed=type(operand).__name__,
            requested=(
                "expand a constructed finite positional sequence at a starred "
                "call argument"
            ),
            fix=(
                "construct a TupleValue/ListValue before starred positional "
                "binding; keep symbolic, mapping, and non-iterable expansion loud"
            ),
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
    return tuple(expanded)


@dataclass(frozen=True)
class CallSugar(Sugar, role=SugarRole.TERM):
    """A plain-name call `f(<args>)` / `f(<args>, k=v)`.

    A call is a COORDINATE into the vendor universe: reduce the arguments
    (positional then keyword VALUES in source order), and the result is the
    callsite -- a CallSiteValue whose term IS `call:f(<arg terms>)`. Keyword
    names ride in `parameters` (not dropped). The lift does not derive f
    (dig the universe when body resolves; else coordinate only). Method receivers
    stay MethodCallSugar's; ``**kwargs`` / ``*args`` ride coordinates (not dropped).
    Body dig: install_source_dig.resolve_call_funcdef + build_dig_body."""

    target_name: str
    args: tuple[SugarBody, ...]
    # Keyword names in source order for the trailing keyword value slots of
    # `args` (empty when the call is positional-only).
    keyword_names: tuple[str, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        # Plain-name calls (positional and/or keyword). abs is a closed builtin
        # partition: KeywordCallSugar owns keyword-bearing shapes,
        # ConstructorCallSugar owns class-spelled coordinates, and AbsCallSugar
        # owns its numeric shape. Malformed abs calls
        # stay loud instead of becoming arbitrary call coordinates. os.exit stays
        # OsSugar's (it has a receiver).
        return (
            site.observed == "Call"
            and site.call_receiver() is None
            and site.call_target_name() is not None
            and site.call_target_name() != "abs"
            and not site.call_has_keywords()
            and not site.call_target_name()[:1].isupper()
            # *args / **kwargs ride as coordinates (StarredSugar / ** param)
        )

    @classmethod
    def new(cls, site, ctx) -> "CallSugar":
        # Arguments and keyword VALUES are factory-built (audited), never reduced here.
        positional = tuple(
            ctx.build_body(arg, SugarRole.TERM) for arg in site.call_args()
        )
        keyword_names: list[str] = []
        keyword_bodies: list[SugarBody] = []
        for kw in site.call_keywords():
            name = kw.keyword_arg_name()
            # **kwargs expansion: parameter name is "**" (not dropped).
            keyword_names.append(name if name is not None else "**")
            keyword_bodies.append(ctx.build_body(kw.keyword_value(), SugarRole.TERM))
        return cls(
            target_name=site.call_target_name(),
            args=(*positional, *keyword_bodies),
            keyword_names=tuple(keyword_names),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Keyword-call return face: B is reached as B(w=z) so the keyword value
        # rides the call coordinate. Truthful/lying twins discriminate on the
        # enclosing assert face.
        prefix = (
            "def B(w):\n"
            "    return w\n"
            "\n"
            "def A(z):\n"
            "    y = B(w=z)\n"
            "    return y\n"
            "\n"
        )
        return _call_pair(
            name="call_return",
            owner_sugar="CallSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce each argument (positional then keyword values), and the
        # result is the callsite coordinate.
        return self._collect(self.args, (), ctx)

    def _collect(self, remaining: tuple, accumulated: tuple, ctx: object) -> Outcome:
        if not remaining:
            from sugar_lift_py_tests.floor import (
                BuiltinExceptionClassValue,
                CallSiteValue,
                ExceptionValue,
                FunctionCallable,
                NativeCallableValue,
            )
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.sugar.install_source_dig import (
                build_dig_body,
                bind_positional_defaults,
                resolve_call_funcdef,
            )

            bound = ctx.temporal.value_if_bound(self.target_name)
            from sugar_lift_py_tests.floor import ImportAliasValue

            if isinstance(bound, ImportAliasValue):
                if isinstance(bound.resolved_value, FunctionCallable):
                    bound = bound.resolved_value
                elif isinstance(bound.resolved_value, NativeCallableValue):
                    native = bound.resolved_value
                    return Complete(
                        CallSiteValue(
                            target_name=native.qualified_name,
                            arg_values=accumulated,
                            parameters=self.keyword_names,
                            term=ctor(
                                f"call:{native.qualified_name}",
                                [
                                    value.to_term(owner=str(self.site))
                                    for value in accumulated
                                ],
                                symbol_kind="contract-target",
                            ),
                            body=None,
                            site=self.site,
                        )
                    )
                else:
                    from sugar_lift_py_tests.factory import factory_panic_gap
                    from sugar_lift_py_tests.factory.factory_gap_info import (
                        GapKind,
                        GapLocus,
                    )

                    factory_panic_gap(
                        owner="CallSugar",
                        blame=self.site,
                        observed=bound.import_target or bound.name,
                        requested="resolve an exact installed-source FunctionDef for a called import alias",
                        fix="install one source-qualified function definition or keep the call opaque outside CallSugar",
                        gap_kind=GapKind.FLOOR,
                        gap_locus=GapLocus.CONSTRUCTION,
                    )
            if isinstance(bound, FunctionCallable):
                return bound.callsite(
                    _expand_function_positional_args(accumulated, site=self.site),
                    self.keyword_names,
                    self.site,
                    source_arg_values=accumulated,
                )

            if type(bound) is BuiltinExceptionClassValue:
                return Complete(
                    ExceptionValue(
                        exception_name=bound.name,
                        arguments=accumulated,
                        site=self.site,
                    )
                )

            # Install-source / same-module body dig: attach factory-built body
            # when resolve succeeds. body=None remains lawful coordinate-only.
            fn = resolve_call_funcdef(self.target_name, ctx)
            body = build_dig_body(fn, ctx) if fn is not None else None
            if body is None:
                return Complete(
                    CallSiteValue(
                        target_name=self.target_name,
                        arg_values=accumulated,
                        parameters=self.keyword_names,
                        term=ctor(
                            f"call:{self.target_name}",
                            [
                                value.to_term(owner=str(self.site))
                                for value in accumulated
                            ],
                            symbol_kind=(
                                "builtin"
                                if hasattr(builtins, self.target_name)
                                else "coordinate"
                            ),
                        ),
                        body=body,
                        site=self.site,
                    )
                )

            source_term = ctor(
                f"call:{self.target_name}",
                [value.to_term(owner=str(self.site)) for value in accumulated],
                symbol_kind="contract-target",
            )
            return bind_positional_defaults(fn, accumulated, ctx).and_then(
                lambda binding: Complete(
                    CallSiteValue(
                        target_name=self.target_name,
                        arg_values=binding[1],
                        parameters=binding[0],
                        term=source_term,
                        body=body,
                        site=self.site,
                    )
                )
            )
        head, *rest = remaining
        return head.reduce(ctx).and_then(
            lambda value: self._collect(tuple(rest), (*accumulated, value), ctx)
        )

    def walk_children(self):
        return self.args
