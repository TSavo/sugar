from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class KeywordCallSugar(
    Sugar, role=SugarRole.TERM, comes_before=("CallSugar", "MethodCallSugar")
):
    """A call with keyword arguments: ``f(a=1)`` or ``recv.m(a=1)``.

    Deeper floors: CallSugar/MethodCallSugar leave keywords as loud gaps; many
    vendor tests use ``Signer(secret_key=...)`` / ``unsign(..., max_age=10)``.
    This sugar owns keyword calls, including ``**kwargs`` expansion, and reduces to a
    CallSiteValue coordinate whose term is
    ``call:f(pos..., kw:name=val, ...)`` — still a coordinate, not a fold.

    Comes before CallSugar and MethodCallSugar so keyword shapes are not
    left unowned.
    """

    target_name: str
    import_target: str | None
    receiver: SugarBody | None
    args: tuple[SugarBody, ...]
    kwargs: tuple[tuple[str, SugarBody], ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Call":
            return False
        if not site.call_has_keywords():
            return False
        # Need a plain name or attribute receiver method.
        if site.call_receiver() is None:
            return site.call_target_name() is not None
        return site.call_target_name() is not None

    @classmethod
    def new(cls, site, ctx) -> "KeywordCallSugar":
        receiver_site = site.call_receiver()
        receiver = (
            ctx.build_body(receiver_site, SugarRole.TERM)
            if receiver_site is not None
            else None
        )
        kwargs = tuple(
            (
                kw.keyword_arg_name() or "**",
                ctx.build_body(kw.keyword_value(), SugarRole.TERM),
            )
            for kw in site.call_keywords()
        )
        return cls(
            target_name=site.call_target_name(),
            import_target=site.call_import_target_name(
                ctx.import_aliases, ctx.from_imports
            ),
            receiver=receiver,
            args=tuple(ctx.build_body(arg, SugarRole.TERM) for arg in site.call_args()),
            kwargs=kwargs,
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def B(w, n=0):\n"
            "    return w\n"
            "def A(z):\n"
            "    y = B(z, n=1)\n"
            "    return y\n"
            "\n"
        )
        starred = (
            "def A():\n"
            "    def inner(*args, **options):\n"
            "        return args[1]\n"
            "    return inner(*(4, 5), flag=6)\n"
            "\n"
        )
        partial = (
            "import functools\n"
            "\n"
            "def A(z):\n"
            "    def add(left, right):\n"
            "        return left + right\n"
            "    plus_one = functools.partial(add, right=1)\n"
            "    return z\n"
            "\n"
        )
        return (
            _call_pair(
                name="keyword_call_return",
                owner_sugar="KeywordCallSugar",
                truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
                lying=prefix + "def test_a():\n    assert A(5) == 6\n",
            ),
            _call_pair(
                name="keyword_call_constructed_starred_return",
                owner_sugar="KeywordCallSugar",
                truthful=starred + "def test_a():\n    assert A() == 5\n",
                lying=starred + "def test_a():\n    assert A() == 6\n",
                family="constructed-starred-keyword-call",
            ),
            _call_pair(
                name="keyword_call_functools_partial_return",
                owner_sugar="KeywordCallSugar",
                truthful=partial + "def test_a():\n    assert A(4) == 4\n",
                lying=partial + "def test_a():\n    assert A(4) == 5\n",
                family="functools-partial-callsite-body",
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce receiver (if any), then pos args, then kw values; result is
        # the keyword-aware callsite coordinate.
        if self.receiver is not None:
            return self.receiver.reduce(ctx).and_then(
                lambda recv: self._collect_args(self.args, (recv,), ctx)
            )
        return self._collect_args(self.args, (), ctx)

    def _collect_args(
        self, remaining: tuple, accumulated: tuple, ctx: object
    ) -> Outcome:
        if remaining:
            head, *rest = remaining
            return head.reduce(ctx).and_then(
                lambda value: self._collect_args(
                    tuple(rest), (*accumulated, value), ctx
                )
            )
        return self._collect_kwargs(self.kwargs, accumulated, (), ctx)

    def _collect_kwargs(
        self,
        remaining: tuple[tuple[str, SugarBody], ...],
        pos_values: tuple,
        kw_pairs: tuple,
        ctx: object,
    ) -> Outcome:
        if not remaining:
            from sugar_lift_py_tests.floor import (
                BuiltinExceptionClassValue,
                CallSiteValue,
                ExceptionClassValue,
                ExceptionValue,
                FunctionCallable,
                ImportAliasValue,
            )
            from sugar_lift_py_tests.ir import ctor, str_const
            from sugar_lift_py_tests.sugar.method_call_sugar import (
                _static_exit_suppression_contract,
            )

            from sugar_lift_py_tests.recognition.native_shape import (
                NativeShape,
                recognize_native_call,
            )

            if recognize_native_call(
                self.import_target
            ) is NativeShape.OPTION_REGISTER and (
                registration_values := pos_values[1:]
            ):
                from sugar_lift_py_tests.floor import FunctionCallable, StringValue
                from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind

                callback = next(
                    (value for name, value in kw_pairs if name == "cb"), None
                )
                if isinstance(registration_values[0], StringValue) and isinstance(
                    callback, FunctionCallable
                ):
                    return Complete(
                        ScopeRebind(
                            _pandas_option_callback_binding(
                                registration_values[0].value
                            ),
                            callback,
                        )
                    )
                if callback is not None:
                    from sugar_lift_py_tests.factory.factory_gap import (
                        factory_panic_gap,
                    )

                    factory_panic_gap(
                        owner="pandas.option_callback",
                        blame=str(self.site),
                        observed=(
                            f"key={type(registration_values[0]).__name__} "
                            f"callback={type(callback).__name__}"
                        ),
                        requested="exact local callback registration",
                        fix=(
                            "construct a static string option key and local "
                            "FunctionCallable callback or panic loudly"
                        ),
                    )

            partial_receiver = pos_values[0] if self.receiver is not None else None
            if (
                self.target_name == "partial"
                and isinstance(partial_receiver, ImportAliasValue)
                and partial_receiver.import_target == "functools"
                and pos_values[1:]
            ):
                from sugar_lift_py_tests.floor import (
                    CallSiteValue,
                    PartialFunctionCallable,
                )

                target, *bound_positional = pos_values[1:]
                if isinstance(target, ImportAliasValue):
                    target = target.resolve_value()
                elif (
                    isinstance(target, CallSiteValue)
                    and len(target.arg_values) == 1
                    and isinstance(target.arg_values[0], ImportAliasValue)
                    and target.arg_values[0].import_target
                ):
                    from sugar_lift_py_tests.sugar.install_source_dig import (
                        resolve_install_source_value,
                    )

                    target = resolve_install_source_value(
                        (
                            f"{target.arg_values[0].import_target}."
                            f"{target.target_name}"
                        ),
                        ctx,
                    )
                if isinstance(target, FunctionCallable):
                    return Complete(
                        PartialFunctionCallable(
                            name=f"partial({target.name})",
                            target=target,
                            bound_positional=tuple(bound_positional),
                            bound_keyword_names=tuple(name for name, _ in kw_pairs),
                            bound_keyword_values=tuple(value for _, value in kw_pairs),
                        )
                    )

            # Exact exception constructors with kwargs still construct
            # ExceptionValue so RaiseSugar can route them — same door as
            # CallSugar for positional exception calls. CallSiteValue alone is
            # not reclassified by spelling at raise time.
            if self.receiver is None:
                bound = ctx.temporal.value_if_bound(self.target_name)
                if isinstance(bound, ImportAliasValue):
                    resolved_bound = bound.resolve_value()
                    if isinstance(resolved_bound, ExceptionClassValue):
                        bound = resolved_bound
                if type(bound) in (BuiltinExceptionClassValue, ExceptionClassValue):
                    # Positional args first; keyword values follow in source
                    # order. Names ride on the call coordinate via parameters
                    # only when this path falls through to CallSiteValue.
                    return Complete(
                        ExceptionValue(
                            exception_name=bound.name,
                            arguments=(*pos_values, *(value for _, value in kw_pairs)),
                            site=self.site,
                        )
                    )
                if isinstance(bound, ImportAliasValue):
                    resolved_bound = bound.resolve_value()
                    if isinstance(resolved_bound, FunctionCallable):
                        bound = resolved_bound
                # term: call:name(pos..., kw:k=v, ...) — keyword spelling is the
                # source coordinate even when dig binds defaults under the body.
                term_args = [
                    value.to_term(owner=str(self.site)) for value in pos_values
                ]
                for name, value in kw_pairs:
                    term_args.append(
                        ctor(
                            "kw",
                            [str_const(name), value.to_term(owner=str(self.site))],
                        )
                    )
                keyword_term = ctor(
                    f"call:{self.target_name}",
                    term_args,
                    symbol_kind="contract-target",
                )
                if isinstance(bound, FunctionCallable):
                    # Bind pos + kwargs + defaults and attach dig body so
                    # Derived EUF residue can pin ground posts (#4387
                    # keyword_call_return). Do not soft-refuse — unbindable
                    # signatures stay loud at FunctionCallable.callsite.
                    from sugar_lift_py_tests.sugar.call_sugar import (
                        _expand_function_positional_args,
                    )

                    bound_pos_values = _expand_function_positional_args(
                        pos_values, site=self.site
                    )
                    if isinstance(bound_pos_values, Incomplete):
                        return bound_pos_values
                    return bound.callsite(
                        (*bound_pos_values, *(value for _, value in kw_pairs)),
                        tuple(name for name, _ in kw_pairs),
                        self.site,
                        source_arg_values=pos_values,
                        term=keyword_term,
                    )

            # Opaque / method-receiver keyword coordinate when no bound callable.
            term_args = [value.to_term(owner=str(self.site)) for value in pos_values]
            for name, value in kw_pairs:
                term_args.append(
                    ctor("kw", [str_const(name), value.to_term(owner=str(self.site))])
                )
            return Complete(
                CallSiteValue(
                    target_name=self.import_target or self.target_name,
                    arg_values=pos_values,
                    parameters=tuple(n for n, _ in kw_pairs),
                    term=ctor(
                        f"call:{self.target_name}",
                        term_args,
                        symbol_kind=(
                            "method-coordinate"
                            if self.receiver is not None
                            else "coordinate"
                        ),
                    ),
                    body=None,
                    site=self.site,
                    exit_suppression=(
                        _static_exit_suppression_contract(
                            self.import_target, (*pos_values, *(v for _, v in kw_pairs))
                        )
                        if self.import_target is not None
                        else None
                    ),
                )
            )
        (name, body), *rest = remaining
        return body.reduce(ctx).and_then(
            lambda value: self._collect_kwargs(
                tuple(rest), pos_values, (*kw_pairs, (name, value)), ctx
            )
        )

    def walk_children(self):
        kids = []
        if self.receiver is not None:
            kids.append(self.receiver)
        kids.extend(self.args)
        kids.extend(body for _, body in self.kwargs)
        return tuple(kids)


def _pandas_option_callback_binding(key: str) -> str:
    return f"__sugar_pandas_option_callback__:{key}"
