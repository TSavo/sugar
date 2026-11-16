from __future__ import annotations

from dataclasses import dataclass, field

from .floor_value import FloorValue


@dataclass(frozen=True)
class BoundMethodValue(FloorValue):
    """``receiver.name`` read as a value: a method bound to one receiver.

    Python's attribute read of a function in the receiver's class namespace
    yields what its descriptor binds (a bound method; for a ``staticmethod``
    the bare function, for a ``classmethod`` a method bound to the class);
    calling it is ``receiver.name(*args, **kwargs)``: on a source instance
    the one dispatched call over the receiver's class, whose implicit first
    actual prove binds by the kind the class's namespace row states
    (``ObjectValue.call_member``, #7757 step 8).

    ``member`` is what the one class-namespace lookup selected when the read
    was made (``ObjectValue.class_member``): a function the class wrote
    (``ObjectMethodValue``) or a function its namespace holds as a field
    (``LambdaCallable``).  Every call of the value binds that very member
    (``ObjectValue.call_member``), never one selected again by name; ``o.m(...)``
    on a source instance is the attribute read answering this value, then
    this call.  None only for the method a ``super()`` lookup selects
    (``BuiltinSuperMethodValue``), which the receiver answers by name.  Its
    truth is decided (``truth``); any other use of the value (comparison,
    further attributes) stays a FloorValue panic.
    """

    receiver: object
    name: str
    member: object = field(default=None, compare=False)

    def truth(self, site):
        """``bool(o.m)``: a function bound to its receiver is a ``method``,
        whose type binds neither ``__bool__`` nor ``__len__``, so it is
        ``True`` (#7757 H12).  The member a ``super()`` read selects is not
        known to be a function (``super().x`` reads any attribute), so its
        truth is the one undecided truth, both faces owed."""
        from sugar_lift_py_tests.floor.lambda_callable import LambdaCallable

        if isinstance(self.member, LambdaCallable):
            from sugar_lift_py_tests.outcome import ExitSet
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return ExitSet.completed(TrueBoolLiteralSugar(site=site))
        from sugar_lift_py_tests.sugar.bool_op_sugar import _unanswered_truth

        return _unanswered_truth(self, site, owner=f"{type(self).__name__}.truth")

    def callable_application_with(self, operation, ctx):
        keyword_count = len(operation.keyword_names)
        positional = (
            operation.arguments[:-keyword_count]
            if keyword_count
            else operation.arguments
        )
        keywords = (
            tuple(zip(operation.keyword_names, operation.arguments[-keyword_count:]))
            if keyword_count
            else ()
        )
        return self.call_with(
            positional,
            keywords,
            owner=type(self).__name__,
            site=operation.site,
            ctx=ctx,
        )

    def call_with(self, positional, keywords, *, owner, site, ctx, required_frame=None):
        """The call of this bound method: the member it carries, bound to
        its receiver (``ObjectValue.call_member``); a frame the call form
        authenticated (``required_frame``) must be that member's own."""
        if self.member is None:
            framed = {} if required_frame is None else {"required_frame": required_frame}
            return self.receiver.call_method_value(
                self.name,
                tuple(positional),
                owner=owner,
                blame=site,
                ctx=ctx,
                keywords=tuple(keywords),
                **framed,
            )
        return self.receiver.call_member(
            self.name,
            self.member,
            tuple(positional),
            owner=owner,
            blame=site,
            ctx=ctx,
            keywords=tuple(keywords),
            required_frame=required_frame,
        )
