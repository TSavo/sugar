"""A method call `<receiver>.<name>(<args>)` -- the attribute callee.

The pandas census's largest family (15,638 sites, 61% of the frontier), and it
is a COMPOSITION, not a new mechanism: the receiver reduces like any value (the
`py.getattr` discipline), and the call stands as the method coordinate
`call:<name>(receiver, args)` with `symbol_kind="method-coordinate"` -- the same
vocabulary `__format__`/`__getitem__` already use. The receiver rides as
`runtime_dispatch_receiver` on the CallSiteValue: the field that exists for
exactly this ("the receiver whose runtime type selects a method body"), so a
future type-aware dig can resolve the body; today the coordinate is honest EUF,
decidable where an equality consumes it.

Keyword arguments stay loud (the tree node guards them), as on plain calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class MethodCallSugar(ConstructedTermSugar):
    receiver: ConstructedTermSugar
    name: str
    args: tuple[ConstructedTermSugar, ...]
    site: object = dataclass_field(compare=False)
    keywords: tuple[tuple[str, ConstructedTermSugar], ...] = ()
    source_call_frame: object = dataclass_field(default=None, compare=False)
    # Exception construction only: when Raise authenticates an Attribute
    # exception-class path, the resulting CallSiteValue carries that identity.
    exception_type_coordinate: object = dataclass_field(default=None, compare=False)
    exception_type_mro: tuple | None = dataclass_field(default=None, compare=False)
    native_definition_coordinate: object = dataclass_field(default=None, compare=False)

    def __post_init__(self) -> None:
        require_constructed_term_sugar(self.receiver, owner="MethodCallSugar.receiver")
        for argument in self.args:
            require_constructed_term_sugar(argument, owner="MethodCallSugar.args")
        for _name, argument in self.keywords:
            require_constructed_term_sugar(argument, owner="MethodCallSugar.keywords")

    @classmethod
    def witnesses(cls):
        # int.bit_length is a real method with a decidable shape: the pair rides
        # the coordinate's identity against a contradicting asserted value.
        prefix = "def A(z):\n    return z.bit_length()\n\n"
        return _call_pair(
            name="method_call_return",
            owner_sugar="MethodCallSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 3\n",
            lying=prefix + "def test_a():\n    assert A(5) == 4\n",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        authority = []
        if self.source_call_frame is not None:
            authority.append(str_const(self.source_call_frame.frame_cid))
        if self.exception_type_coordinate is not None:
            authority.append(str_const(self.exception_type_coordinate.cid))
        if self.native_definition_coordinate is not None:
            authority.append(str_const(self.native_definition_coordinate.cid))
        return ctor(
            "python:method-call-construction",
            (
                self.occurrence_term(owner=owner),
                self.receiver.to_term(owner=owner),
                str_const(self.name),
                ctor(
                    "python:positional-arguments",
                    tuple(argument.to_term(owner=owner) for argument in self.args),
                ),
                ctor(
                    "python:keyword-arguments",
                    tuple(
                        ctor(
                            "python:keyword-argument",
                            (str_const(name), argument.to_term(owner=owner)),
                        )
                        for name, argument in self.keywords
                    ),
                ),
                ctor(
                    "python:definition-authority",
                    tuple(authority),
                    symbol_kind="coordinate",
                ),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.outcome.exit_set import factored_operand

        # The RECEIVER is the prefix of the whole argument fold, so its arm
        # count is the base of the exponent every argument raises (#6324).
        return factored_operand(self.receiver.desugar(ctx)).and_then(
            lambda receiver: self._collect(
                receiver.project_operation_receiver(
                    ctx, owner="MethodCallSugar receiver"
                ),
                self.args,
                (),
                ctx,
            )
        )

    def _collect(self, receiver, remaining: tuple, accumulated: tuple, ctx) -> Outcome:
        from sugar_lift_py_tests.outcome.exit_set import factored_operand

        if remaining:
            head, *rest = remaining
            # One completed arm per argument (#6324): `and_then` is
            # `ExitSet.sequence`, so an unfactored partitioning argument
            # multiplies the accumulated tuple by its arm count, and k
            # arguments distribute into m ** k arms.
            return factored_operand(head.desugar(ctx)).and_then(
                lambda value: self._collect(
                    receiver,
                    tuple(rest),
                    accumulated
                    + (
                        value.project_operation_receiver(
                            ctx, owner="MethodCallSugar positional actual"
                        ),
                    ),
                    ctx,
                )
            )
        return self._collect_kwargs(receiver, self.keywords, (), accumulated, ctx)

    def _collect_kwargs(
        self, receiver, remaining: tuple, kw_values: tuple, positional: tuple, ctx
    ) -> Outcome:
        from sugar_lift_py_tests.outcome.exit_set import factored_operand

        if remaining:
            (name, sugar), *rest = remaining
            # Same law as the positional fold (#6324).
            return factored_operand(sugar.desugar(ctx)).and_then(
                lambda value: self._collect_kwargs(
                    receiver,
                    tuple(rest),
                    kw_values
                    + (
                        (
                            name,
                            value.project_operation_receiver(
                                ctx, owner="MethodCallSugar keyword actual"
                            ),
                        ),
                    ),
                    positional,
                    ctx,
                )
            )
        call_method_value = getattr(receiver, "call_method_value", None)
        supports_closed_method = getattr(receiver, "supports_closed_method", None)
        if callable(call_method_value) and (
            not callable(supports_closed_method) or supports_closed_method(self.name)
        ):
            return call_method_value(
                self.name,
                positional,
                owner="MethodCallSugar",
                blame=self.site,
                ctx=ctx,
                keywords=kw_values,
                required_frame=self.source_call_frame,
            )
        if self.source_call_frame is not None:
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                blame=self.site,
                owner="MethodCallSugar._collect_kwargs",
                observed=type(receiver).__name__,
                requested="authenticated constructed receiver matching the method frame",
                fix="preserve receiver identity or keep authenticated dispatch loud",
            )
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor, str_const

        owner = str(self.site)
        kwarg_terms = [
            ctor("py.kwarg", [str_const(name), value.to_term(owner=owner)])
            for name, value in kw_values
        ]
        term = ctor(
            f"call:{self.name}",
            [receiver.to_term(owner=owner)]
            + [value.to_term(owner=owner) for value in positional]
            + kwarg_terms,
            symbol_kind="method-coordinate",
        )
        return Complete(
            CallSiteValue(
                target_name=self.name,
                arg_values=(receiver, *positional, *(v for _, v in kw_values)),
                parameters=(),
                term=term,
                body=None,
                site=self.site,
                runtime_dispatch_receiver=receiver,
                exception_type_coordinate=self.exception_type_coordinate,
                exception_type_mro=self.exception_type_mro,
            )
        )
