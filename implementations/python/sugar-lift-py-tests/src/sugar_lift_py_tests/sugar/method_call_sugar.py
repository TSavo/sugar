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
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)
from sugar_lift_py_tests.sugar.witnesses import _assertion_pair


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
    # The module the call stands in: what a dispatched call on a parameter
    # reads the names its fields may be stored under off
    # (``receiver_dispatch.dispatch_on_receiver``, #7757 step 8).  A lookup
    # aid, never testimony: the call is testified by its receiver, name,
    # arguments and site.  Walking it would walk the unit's memos (a
    # ``PosixPath`` in ``_lexical_import_pass_key_memo``) and refuse.
    unit: object = dataclass_field(
        default=None, compare=False, repr=False, metadata={"testimony": "lookup"}
    )

    def __post_init__(self) -> None:
        require_constructed_term_sugar(self.receiver, owner="MethodCallSugar.receiver")
        for argument in self.args:
            require_constructed_term_sugar(argument, owner="MethodCallSugar.args")
        for _name, argument in self.keywords:
            require_constructed_term_sugar(argument, owner="MethodCallSugar.keywords")

    @classmethod
    def witnesses(cls):
        # `C.m()` calls a same-file method on a receiver whose class is
        # decided (the class value itself, `receiver_class_decided`): its
        # coordinate and an edge to `m`'s join symbol, decided at prove by
        # `m`'s contract (#8726, #8738).  The subject was `(5).bit_length()`,
        # a builtin `int` method the lifter does not state, which left both
        # halves open.
        return _assertion_pair(
            name="method_call_return",
            owner_sugar="MethodCallSugar",
            prefix="class C:\n    def m():\n        return 3\n\n\n",
            statements="",
            truthful="C.m() == 3",
            lying="C.m() == 4",
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

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            written_by,
        )
        from sugar_lift_py_tests.outcome.exit_set import factored_operand

        # The RECEIVER is the prefix of the whole argument fold, so its arm
        # count is the base of the exponent every argument raises (#6324).
        # It is an operand: a walrus in it binds once, through the one door,
        # and the arguments are evaluated with its writes applied
        # (``written_by``), inside its door, which lays its stores in their
        # halts; an argument's halt is recorded where it was evaluated,
        # after every earlier operand's writes (``inside``,
        # ``evaluated_after``).
        return factored_operand(self.receiver.desugar(ctx)).and_then(
            lambda receiver: consume_operands(
                lambda presented: self._collect(
                    presented.project_operation_receiver(
                        ctx, owner="MethodCallSugar receiver"
                    ),
                    self.args,
                    (),
                    written_by(receiver, ctx),
                    (receiver,),
                ),
                receiver,
            )
        )

    def _collect(
        self, receiver, remaining: tuple, accumulated: tuple, ctx, inside=()
    ) -> ExitSet:
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            evaluated_after,
            written_by,
        )
        from sugar_lift_py_tests.outcome.exit_set import factored_operand

        if remaining:
            head, *rest = remaining
            # One completed arm per argument (#6324): through
            # `ExitSet.and_then`, an unfactored partitioning argument
            # multiplies the accumulated tuple by its arm count, and k
            # arguments distribute into m ** k arms.
            # The actual is an operand: a walrus in it binds once, through
            # the one operand door (``consume_operands``), and the later
            # actuals are evaluated with its writes applied (``written_by``).
            return factored_operand(
                evaluated_after((), head, ctx, inside=inside)
            ).and_then(
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
                        written_by(value, ctx),
                        (*inside, value),
                    ),
                    value,
                )
            )
        return self._collect_kwargs(
            receiver, self.keywords, (), accumulated, ctx, inside
        )

    def _collect_kwargs(
        self,
        receiver,
        remaining: tuple,
        kw_values: tuple,
        positional: tuple,
        ctx,
        inside=(),
    ) -> ExitSet:
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            evaluated_after,
            written_by,
        )
        from sugar_lift_py_tests.outcome.exit_set import factored_operand

        if remaining:
            (name, sugar), *rest = remaining
            # Same law and order as the positional fold (#6324).
            return factored_operand(
                evaluated_after((), sugar, ctx, inside=inside)
            ).and_then(
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
                        written_by(value, ctx),
                        (*inside, value),
                    ),
                    value,
                )
            )
        from sugar_lift_py_tests.floor.call_site_value import bind_after_call

        # The method call's completed face carries its record under this
        # call's key, as a call by name's does (``CallSiteSugar.
        # _collect_kwargs``): what a same-file method's contract names of
        # what it was handed, and, for a call no contract here states, every
        # module global it may reach (#7757 H7).
        return bind_after_call(
            dispatch_method_call(
                self.name,
                receiver,
                positional,
                kw_values,
                self.site,
                ctx,
                source_call_frame=self.source_call_frame,
                exception_type_coordinate=self.exception_type_coordinate,
                exception_type_mro=self.exception_type_mro,
                unit=self.unit,
            ),
            self.site,
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
    unit=None,
):
    """``receiver.name(*positional, **kw_values)`` selected by the receiver.

    A ground ``list``/``tuple``/``dict`` receiver whose value says its
    contents are the object's contents at this call
    (``object_identity.contents_current``), with ground arguments, calling a
    method that does not change it, is decided by the cited fold alone
    (``container_method_cited_fold``, #7757).  The receiver of an
    ``__init__``'s own contract whose class is an input of that contract is
    the dispatched edge over the input (``receiver_dispatch.
    dispatch_on_receiver``, #7757 step 8).  Any other source-class instance
    is ``o.m`` read through the one attribute lookup, then that value called
    (``_source_instance_method_call``).  Otherwise a floor of the
    receiver answers first (a closed builtin method).  When none does, a
    receiver whose class is a class input here (a formal of the function
    whose own proof this is) or a same-file class's call result is the
    dispatched edge (``dispatch_on_receiver``).  A built-in container whose
    method no floor decided is two-faced under its own atom
    (``_container_method_call``), and any other receiver -- a formal whose
    class is no input, a call's result, a builtin scalar -- is the one
    unanswered call, two-faced and owed (#7585).  No call waits for a
    caller's actual: a formal receiver or operand is never deferred (#7757
    NEW-1; the ``method_call`` carrier, which production discharged with no
    actuals into the same owed ``undecided`` member, is deleted)."""
    if not kw_values and source_call_frame is None:
        from sugar_lift_py_tests.source_call_resolution import (
            cited_container_method,
            container_method_cited_fold,
        )

        if cited_container_method(receiver, name):
            folded = container_method_cited_fold(
                receiver,
                name,
                tuple(positional),
                site,
                callsite=_method_callsite(
                    name,
                    receiver,
                    positional,
                    kw_values,
                    site,
                    exception_type_coordinate,
                    exception_type_mro,
                ),
            )
            if folded is not None:
                return folded
    from sugar_lift_py_tests.floor.object_value import ObjectValue

    if isinstance(receiver, ObjectValue):
        if exception_type_coordinate is None:
            # ``self`` in an ``__init__``'s own contract whose class is an
            # input of that contract: the dispatched edge over the input,
            # bound at prove by the caller (``super().__init__()``, a class's
            # constructor), never looked up on the initializer's own class
            # (#7757 step 8).
            from sugar_lift_py_tests.receiver_dispatch import dispatch_on_receiver

            dispatched = dispatch_on_receiver(
                name, receiver, positional, kw_values, site, unit=unit
            )
            if dispatched is not None:
                return dispatched
        return _source_instance_method_call(
            name,
            receiver,
            positional,
            kw_values,
            site,
            ctx,
            source_call_frame=source_call_frame,
            exception_type_coordinate=exception_type_coordinate,
            exception_type_mro=exception_type_mro,
        )
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
    callsite = _method_callsite(
        name,
        receiver,
        positional,
        kw_values,
        site,
        exception_type_coordinate,
        exception_type_mro,
    )
    if exception_type_coordinate is None:
        # A receiver whose class is a class input here (a parameter of the
        # function whose own proof this is), or a same-file class's bare
        # instance: the dispatched edge, resolved at prove where a read binds
        # the class (#7757 step 8).
        from sugar_lift_py_tests.receiver_dispatch import dispatch_on_receiver

        dispatched = dispatch_on_receiver(
            name, receiver, positional, kw_values, site, unit=unit
        )
        if dispatched is not None:
            return dispatched
    from sugar_lift_py_tests.floor import builtin_container_method as law

    kind = law.container_kind(receiver)
    if kind is not None:
        return _container_method_call(
            kind, name, receiver, positional, kw_values, site, ctx
        )
    # No floor of the receiver answered the method and no class input
    # dispatches it: what runs was not looked at.  A formal whose class is no
    # input lands here too: nothing would ever bind its class, so a
    # ``call:dispatch:`` over it, or a carrier waiting for its actual, would
    # be this same owed debt written a second way (#7757 NEW-1, #8960
    # decision 1).  A method call is the plain
    # call with the receiver bound first, so this is the plain call to a
    # callee the lifter does not have, with its two faces (#7585, #7756).
    # With or without a site it is never a completion (#7757: a halt is never
    # dropped); a call with no source coordinate is refused by name where its
    # occurrence is spelled.
    from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

    return UnknownCalleeCallV1(name).faces(callsite, site)


def _source_instance_method_call(
    name,
    receiver,
    positional,
    kw_values,
    site,
    ctx,
    *,
    source_call_frame,
    exception_type_coordinate,
    exception_type_mro,
):
    """``o.m(*positional, **kw_values)`` on a source-class instance: one
    attribute read, then one call.

    CPython evaluates ``o.m(...)`` as ``o.m`` read by the generic lookup
    (``object.__getattribute__``: a class data descriptor, else the instance
    ``__dict__``, else the class), then the value it answers called.  So the
    callee is looked up only through the one attribute lookup
    (``ObjectValue.attribute``), never a method selected beside it, and the
    value it answers is applied by the one routine (``apply_callee``):

    - where no recorded field and no class-field value answers ``o.m`` --
      a ``def`` the class wrote, of any kind, or no member at all -- the
      call is the one dispatched call
      (``ObjectValue.dispatched_method_call``): prove's one walk of the
      order decides the member, its binding and the lookup's raise (#7757
      L3); the lift never reads the ``def`` to classify it;
    - a function the class namespace holds as a field is a
      ``BoundMethodValue`` (``function.__get__`` binds the receiver), called
      as the one dispatched call (``ObjectValue.call_member``);
    - an instance field that shadows the method is that field's value
      called (``self.m = lambda: 1`` -> ``o.m()`` is ``1``);
    - on an instance whose fields are not current (it arrived by binding,
      ``object_identity.contents_current``) every name but a class data
      descriptor is the undecided read: its member is no callee anything
      here resolved, so the call is the one unanswered call
      (``UnknownCalleeCallV1``) under it, two-faced and owed.

    A frame the call form authenticated (``source_call_frame``) selects the
    method's frame only when the lookup answered that method."""
    from sugar_lift_py_tests.floor.bound_method_value import BoundMethodValue
    from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1
    from sugar_lift_py_tests.sugar.computed_call_sugar import apply_callee

    def unanswered():
        return UnknownCalleeCallV1(name).faces(
            _method_callsite(
                name,
                receiver,
                positional,
                kw_values,
                site,
                exception_type_coordinate,
                exception_type_mro,
            ),
            site,
        )

    def call(callee):
        if (
            source_call_frame is not None
            and type(callee) is BoundMethodValue
            and callee.receiver is receiver
        ):
            # The member the attribute read selected, bound with the frame
            # the call form authenticated: never selected again by name.
            return callee.call_with(
                positional,
                kw_values,
                owner="MethodCallSugar",
                site=site,
                ctx=ctx,
                required_frame=source_call_frame,
            )
        return apply_callee(callee, positional, kw_values, site, ctx, unanswered)

    # No recorded field and no class-field value answers ``o.m``: the call
    # is the one dispatched call itself, whose member prove's one walk of
    # the order decides (``ObjectValue.dispatched_method_call``, #7757 L3),
    # never ``o.m`` read as a member the lift classified and then called.
    direct = receiver.dispatched_method_call(name, positional, kw_values, site)
    if direct is not None:
        return direct
    return receiver.attribute(name, site, ctx).and_then(call)


def _method_callsite(
    name,
    receiver,
    positional,
    kw_values,
    site,
    exception_type_coordinate,
    exception_type_mro,
):
    """The method coordinate ``call:<name>(receiver, args)`` of this call."""
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.floor.object_identity import call_operand_terms
    from sugar_lift_py_tests.ir import ctor

    owner = str(site)
    # The receiver and each actual as the call finds it (``identity_term``).
    term = ctor(
        call_symbol(name),
        call_operand_terms((receiver, *positional), kw_values, site, owner=owner),
        symbol_kind="method-coordinate",
    )
    return CallSiteValue(
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


def _container_method_call(kind, name, receiver, positional, kw_values, site, ctx):
    """A built-in container's method that no floor of the receiver answered.

    Its contents were not decided current at this call (the value arrived
    by binding: a helper's formal bound to the caller's actual), or the
    method or an argument is not one the cited fold reads: code this frame
    does not see may have changed the object without rebinding the name.  The
    container law (#7603) decides only what does not read the contents
    (``CONTENTS_FREE_METHODS``); every other call is two-faced under its
    ``python:builtin_method`` atom.  The receiver's post-state is the
    statement's or the caller's to apply."""
    from sugar_lift_py_tests.floor import builtin_container_method as law
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_lift_py_tests.sugar.builtin_container_call_sugar import _opaque_pair

    decided = None
    if not kw_values and name in law.CONTENTS_FREE_METHODS.get(kind, ()):
        decided = law.apply(kind, name, receiver, tuple(positional), site, ctx)
    if decided is None:
        decided = _opaque_pair(kind, name, site)

    def result(pair):
        if type(pair) is TupleValue and len(pair.elements) == 2:
            return ExitSet.completed(pair.elements[1])
        return ExitSet.completed(pair)

    return decided.and_then(result)
