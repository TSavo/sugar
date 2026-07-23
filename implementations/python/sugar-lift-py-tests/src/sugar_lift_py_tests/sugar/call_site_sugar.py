from __future__ import annotations

import builtins
from dataclasses import dataclass, field as dataclass_field
from typing import Any

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class CallSiteSugar(Sugar):
    """`<name>(<args>)` -> a call-site coordinate: THE DIG CUE.

    Reduce each argument, then stand as a CallSiteValue whose term is the bridge
    coordinate `call:<name>(<arg terms>)`. That coordinate is the cue: an assert
    that consumes it carries it into the InvValue's operand_callsites, which
    projects the callEdge -- and a cue is the signal that this call warrants a
    dig (reduce the callee into its universe; its call sites cue further digs).

    The dig itself is NOT done here (`body=None`). Digging is cued, not eager:
    an assertion cues digs, and digs cue digs, so the recursion is driven by the
    cueing mechanism (the enumeration), not by inlining the callee at every call.

    Meaning-only, node-constructed. Plain positional calls to a named callee;
    method/attribute/computed callees and keyword args stay gaps (the tree node
    guards them).
    """

    target_name: str
    args: tuple  # the argument sugars, in source order
    site: object = dataclass_field(compare=False)
    keywords: tuple = ()  # (name, sugar) pairs, in source order
    contract_ref: Any = dataclass_field(default=None, compare=False)
    contract_resolution_gap: str | None = dataclass_field(default=None, compare=False)
    exception_type_coordinate: Any = dataclass_field(default=None, compare=False)
    exception_type_mro: tuple | None = dataclass_field(default=None, compare=False)
    source_call_frame: Any = dataclass_field(default=None, compare=False)

    @classmethod
    def witnesses(cls):
        # A user callee's returned value is asserted through the call site: the
        # truthful twin asserts the dug value, the lying twin another -- the pair
        # proves the lift discriminates on what the call computes.
        prefix = "def A(z):\n    return z\n\n"
        return _call_pair(
            name="call_site_return",
            owner_sugar="CallSiteSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        if self.contract_resolution_gap is not None:
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                owner="CallSiteSugar.desugar",
                observed=self.contract_resolution_gap,
                requested="authenticated resolved-call contract reference",
                fix="publish and resolve the imported target contract or keep the call loud",
            )
        return self._collect(self.args, (), ctx)

    def _collect(self, remaining: tuple, accumulated: tuple, ctx: object) -> Outcome:
        if remaining:
            head, *rest = remaining
            return head.desugar(ctx).and_then(
                lambda value: self._collect(tuple(rest), accumulated + (value,), ctx)
            )
        return self._collect_kwargs(self.keywords, (), accumulated, ctx)

    def _collect_kwargs(
        self, remaining: tuple, kw_values: tuple, positional: tuple, ctx: object
    ) -> Outcome:
        if remaining:
            (name, sugar), *rest = remaining
            return sugar.desugar(ctx).and_then(
                lambda value: self._collect_kwargs(
                    tuple(rest), kw_values + ((name, value),), positional, ctx
                )
            )
        if ctx is not None:
            from sugar_lift_py_tests.callable_application import CallableApplication
            from sugar_lift_py_tests.floor import BuiltinSemanticCallable

            receiver = ctx.temporal.value_for(self.target_name)
            if isinstance(receiver, BuiltinSemanticCallable):
                return receiver.callable_application_with(
                    CallableApplication(
                        positional + tuple(value for _, value in kw_values),
                        tuple(name for name, _ in kw_values),
                        self.site,
                    ),
                    ctx,
                )
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor, str_const

        owner = str(self.site)
        kwarg_terms = [
            ctor("py.kwarg", [str_const(name), value.to_term(owner=owner)])
            for name, value in kw_values
        ]
        term = ctor(
            f"call:{self.target_name}",
            [value.to_term(owner=owner) for value in positional] + kwarg_terms,
            symbol_kind=(
                "builtin" if hasattr(builtins, self.target_name) else "coordinate"
            ),
        )
        if self.contract_ref is not None:
            return self._collect_bridged(positional)
        source_body = None
        source_frame_cid = None
        if self.source_call_frame is not None:
            from sugar_lift_py_tests.source_call_frame import SourceVisibleCallFrameV1
            from sugar_source_tree.panic import SugarNotWritten

            if not isinstance(self.source_call_frame, SourceVisibleCallFrameV1):
                raise SugarNotWritten(
                    owner="CallSiteSugar.desugar",
                    observed=type(self.source_call_frame).__name__,
                    requested="a closed SourceCallFrameV1 variant",
                    fix="construct a typed source frame or keep the call loud",
                )
            from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

            try:
                positional = self.source_call_frame.bind_actuals(
                    positional, kw_values, ctx
                )
            except SourceCallBindingGap as exc:
                raise SugarNotWritten(
                    owner="CallSiteSugar.desugar",
                    observed=str(exc),
                    requested="actuals matching the authenticated source signature",
                    fix="supply a real actual/default/variadic occurrence or keep loud",
                ) from exc
            source_body = self.source_call_frame.body
            source_frame_cid = self.source_call_frame.frame_cid
            # bind_actuals returned the complete formal-ordered tuple,
            # including keyword/default actuals. They must not be appended a
            # second time below.
            kw_values = ()
        return Complete(
            CallSiteValue(
                target_name=self.target_name,
                arg_values=positional + tuple(value for _, value in kw_values),
                parameters=(
                    self.source_call_frame.parameters
                    if self.source_call_frame is not None
                    else ()
                ),
                term=term,
                body=source_body,
                keyword_names=tuple(name for name, _ in kw_values),
                site=self.site,
                exception_type_coordinate=self.exception_type_coordinate,
                exception_type_mro=self.exception_type_mro,
                source_call_frame_cid=source_frame_cid,
                formal_coordinate_cids=(),
            )
        )

    def _collect_bridged(self, positional: tuple) -> Outcome:
        from sugar_lift_py_tests.floor.bridged_contract_value import (
            BridgedContractValue,
        )
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import _Ctor, _free_vars_in_term, subst_var_in_term
        from sugar_lift_py_tests.outcome import Complete
        from sugar_source_tree.panic import SugarNotWritten

        reference = self.contract_ref
        if len(reference.formals) != len(positional):
            raise SugarNotWritten(
                owner="CallSiteSugar.desugar",
                observed="signature mismatch",
                requested="actual arguments matching the authenticated import signature",
                fix="correct the call signature or keep the call loud",
            )
        term = reference.return_term
        if term is None:
            raise SugarNotWritten(
                owner="CallSiteSugar.desugar",
                observed="authenticated contract has no exact return equality",
                requested="exact structural return testimony",
                fix="strengthen the contract or keep the imported value loud",
            )
        if not _free_vars_in_term(term) <= set(reference.formals):
            raise SugarNotWritten(
                owner="CallSiteSugar.desugar",
                observed="authenticated structural return contains an unbound projection",
                requested="return variables authenticated by the target formal list",
                fix="reject the stale or lying contract reference",
            )
        for formal, actual in zip(reference.formals, positional):
            term = subst_var_in_term(term, formal, actual.to_term(owner=str(self.site)))
        if not isinstance(term, _Ctor) or term.name not in {
            "tuple",
            "python:tuple",
            "python:list",
        }:
            raise SugarNotWritten(
                owner="CallSiteSugar.desugar",
                observed="authenticated contract has no exact structural return",
                requested="structural return term carried by the target contract",
                fix="strengthen the target contract or keep the imported value loud",
            )
        callsite = CallSiteValue(
            target_name=self.target_name,
            arg_values=positional,
            parameters=reference.formals,
            term=term,
            body=None,
            site=self.site,
            target_contract_cid=reference.contract_cid,
            authenticated_target_symbol=reference.bridge_source_symbol,
        )
        return Complete(
            BridgedContractValue(
                term, reference.contract_cid, reference.member_cid, callsite
            )
        )
