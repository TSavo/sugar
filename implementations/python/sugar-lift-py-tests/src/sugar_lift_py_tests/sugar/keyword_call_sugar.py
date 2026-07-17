from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
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
        return _call_pair(
            name="keyword_call_return",
            owner_sugar="KeywordCallSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
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
                ImportAliasValue,
            )
            from sugar_lift_py_tests.ir import ctor, str_const

            # Exact exception constructors with kwargs still construct
            # ExceptionValue so RaiseSugar can route them — same door as
            # CallSugar for positional exception calls. CallSiteValue alone is
            # not reclassified by spelling at raise time.
            if self.receiver is None:
                bound = ctx.temporal.value_if_bound(self.target_name)
                if isinstance(bound, ImportAliasValue) and isinstance(
                    bound.resolved_value, ExceptionClassValue
                ):
                    bound = bound.resolved_value
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

            # term: call:name(pos..., kw:k=v, ...)
            term_args = [value.to_term(owner=str(self.site)) for value in pos_values]
            for name, value in kw_pairs:
                term_args.append(
                    ctor("kw", [str_const(name), value.to_term(owner=str(self.site))])
                )
            return Complete(
                CallSiteValue(
                    target_name=self.target_name,
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
