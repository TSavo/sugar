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

from sugar_lift_py_tests.call_symbol import call_symbol
from sugar_lift_py_tests.outcome import ExitSet, Outcome
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
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
        )
        from sugar_lift_py_tests.outcome.exit_set import factored_operand

        # The RECEIVER is the prefix of the whole argument fold, so its arm
        # count is the base of the exponent every argument raises (#6324).
        # It is an operand: a walrus in it binds once, through the one door.
        return factored_operand(self.receiver.desugar(ctx)).and_then(
            lambda receiver: consume_operands(
                lambda presented: self._collect(
                    presented.project_operation_receiver(
                        ctx, owner="MethodCallSugar receiver"
                    ),
                    self.args,
                    (),
                    ctx,
                ),
                receiver,
            )
        )

    def _collect(self, receiver, remaining: tuple, accumulated: tuple, ctx) -> Outcome:
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
        )
        from sugar_lift_py_tests.outcome.exit_set import factored_operand

        if remaining:
            head, *rest = remaining
            # One completed arm per argument (#6324): `and_then` is
            # `ExitSet.sequence`, so an unfactored partitioning argument
            # multiplies the accumulated tuple by its arm count, and k
            # arguments distribute into m ** k arms.
            # The actual is an operand: a walrus in it binds once, through
            # the one operand door (``consume_operands``).
            return factored_operand(head.desugar(ctx)).and_then(
                lambda value: consume_operands(
                    lambda presented: self._collect(
                        receiver,
                        tuple(rest),
                        accumulated
                        + (
                            presented.project_operation_receiver(
                                ctx, owner="MethodCallSugar positional actual"
                            ),
                        ),
                        ctx,
                    ),
                    value,
                )
            )
        return self._collect_kwargs(receiver, self.keywords, (), accumulated, ctx)

    def _collect_kwargs(
        self, receiver, remaining: tuple, kw_values: tuple, positional: tuple, ctx
    ) -> Outcome:
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
        )
        from sugar_lift_py_tests.outcome.exit_set import factored_operand

        if remaining:
            (name, sugar), *rest = remaining
            # Same law as the positional fold (#6324).
            return factored_operand(sugar.desugar(ctx)).and_then(
                lambda value: consume_operands(
                    lambda presented: self._collect_kwargs(
                        receiver,
                        tuple(rest),
                        kw_values
                        + (
                            (
                                name,
                                presented.project_operation_receiver(
                                    ctx, owner="MethodCallSugar keyword actual"
                                ),
                            ),
                        ),
                        positional,
                        ctx,
                    ),
                    value,
                )
            )
        return dispatch_method_call(
            self.name,
            receiver,
            positional,
            kw_values,
            self.site,
            ctx,
            source_call_frame=self.source_call_frame,
            exception_type_coordinate=self.exception_type_coordinate,
            exception_type_mro=self.exception_type_mro,
        )


def dispatch_method_call(
    name,
    receiver,
    positional,
    kw_values,
    site,
    ctx,
    *,
    source_call_frame=None,
    exception_type_coordinate=None,
    exception_type_mro=None,
    may_defer=True,
):
    """``receiver.name(*positional, **kw_values)`` selected by the receiver.

    A floor of the receiver answers first (a source method body, a closed
    builtin method).  When none does and the receiver or an operand is a
    formal, the caller's actual selects the method: the call defers through
    ``NativeOperationExitCarrierV1`` with the ``method_call`` operator, whose
    projector re-runs this dispatch on the resolved actuals.  A built-in
    container whose method no floor decided, and a receiver this frame holds
    (a call's result, a builtin scalar), are two-faced (#7585)."""
    call_method_value = getattr(receiver, "call_method_value", None)
    supports_closed_method = getattr(receiver, "supports_closed_method", None)
    if callable(call_method_value) and (
        not callable(supports_closed_method) or supports_closed_method(name)
    ):
        return call_method_value(
            name,
            positional,
            owner="MethodCallSugar",
            blame=site,
            ctx=ctx,
            keywords=kw_values,
            required_frame=source_call_frame,
        )
    call_named_method = getattr(receiver, "call_named_method", None)
    if callable(call_named_method):
        native = call_named_method(
            name,
            positional,
            owner="MethodCallSugar",
            blame=site,
            ctx=ctx,
            keywords=kw_values,
        )
        if native is not None:
            return native
    if source_call_frame is not None:
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            blame=site,
            owner="MethodCallSugar._collect_kwargs",
            observed=type(receiver).__name__,
            requested="authenticated constructed receiver matching the method frame",
            fix="preserve receiver identity or keep authenticated dispatch loud",
        )
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.ir import ctor, str_const

    owner = str(site)
    kwarg_terms = [
        ctor("py.kwarg", [str_const(key), value.to_term(owner=owner)])
        for key, value in kw_values
    ]
    term = ctor(
        call_symbol(name),
        [receiver.to_term(owner=owner)]
        + [value.to_term(owner=owner) for value in positional]
        + kwarg_terms,
        symbol_kind="method-coordinate",
    )
    callsite = CallSiteValue(
        target_name=name,
        arg_values=(receiver, *positional, *(v for _, v in kw_values)),
        parameters=(),
        term=term,
        body=None,
        site=site,
        runtime_dispatch_receiver=receiver,
        exception_type_coordinate=exception_type_coordinate,
        exception_type_mro=exception_type_mro,
    )
    if site is None:
        return ExitSet.completed(callsite)
    if may_defer:
        deferred = _defer_formal_method_call(name, receiver, positional, kw_values, site)
        if deferred is not None:
            return deferred
    from sugar_lift_py_tests.floor import builtin_container_method as law

    kind = law.container_kind(receiver)
    if kind is not None:
        return _container_method_call(kind, name, receiver, positional, kw_values, site)
    # No floor of the receiver answered the method and no formal defers it
    # to a caller: what runs was not looked at.  A method call is the plain
    # call with the receiver bound first, so this is the plain call to a
    # callee the lifter does not have, with its two faces (#7585, #7756).
    from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

    return UnknownCalleeCallV1(name).faces(callsite, site)


# Cited container methods whose exits and result the law decides from the
# operands alone, never from the receiver's contents.
_CONTENTS_FREE_METHODS = {
    "list": frozenset({"append", "extend", "insert", "clear", "reverse"}),
    "dict": frozenset({"__setitem__", "update", "clear"}),
    "set": frozenset(
        {
            "add",
            "discard",
            "update",
            "clear",
            "difference_update",
            "intersection_update",
            "symmetric_difference_update",
        }
    ),
}


def _container_method_call(kind, name, receiver, positional, kw_values, site):
    """A built-in container's method that no floor of the receiver answered.

    This value reached the call by binding (a helper's formal bound to the
    caller's actual), not through the statement's own mutation path, so its
    contents are not testified as the contents at this call: an earlier call
    in the body may have changed the object without rebinding the name.  The
    container law (#7603) decides only what does not read the contents; every
    other call is two-faced under its ``python:builtin_method`` atom.  The
    receiver's post-state is the statement's or the caller's to apply."""
    from sugar_lift_py_tests.floor import builtin_container_method as law
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_lift_py_tests.sugar.builtin_container_call_sugar import _opaque_pair

    decided = None
    if not kw_values and name in _CONTENTS_FREE_METHODS.get(kind, ()):
        decided = law.apply(kind, name, receiver, tuple(positional), site)
    if decided is None:
        decided = _opaque_pair(kind, name, site)

    def result(pair):
        if type(pair) is TupleValue and len(pair.elements) == 2:
            return ExitSet.completed(pair.elements[1])
        return ExitSet.completed(pair)

    return decided.and_then(result)


def _defer_formal_method_call(name, receiver, positional, kw_values, site):
    """The ``method_call`` carrier when the receiver or an operand is a formal."""
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    operands = (receiver, *positional, *(value for _, value in kw_values))
    coordinates = tuple(getattr(value, "formal_coordinate", None) for value in operands)
    if all(coordinate is None for coordinate in coordinates):
        return None
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    keyword_names = TupleValue(tuple(StringValue(key) for key, _ in kw_values))
    return NativeOperationExitCarrierV1.mint(
        site=site,
        operator="method_call",
        operands=(receiver, StringValue(name), keyword_names, *operands[1:]),
        coordinates=(coordinates[0], None, None, *coordinates[1:]),
    )
