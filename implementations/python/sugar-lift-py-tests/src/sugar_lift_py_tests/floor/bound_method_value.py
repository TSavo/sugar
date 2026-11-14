from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class BoundMethodValue(FloorValue):
    """``receiver.name`` read as a value: a method bound to one receiver.

    Python's attribute read of a function defined on the receiver's class
    yields what its descriptor binds (a bound method; for a ``staticmethod``
    the bare function, for a ``classmethod`` a method bound to the class);
    calling it is ``receiver.name(*args, **kwargs)``, whose implicit first
    actual the one method door reads off the descriptor kind
    (``object_value.implicit_arguments``).
    This Floor carries exactly that pair and nothing else, so every call of
    it dispatches through the receiver's own ``call_method_value`` (the class
    side of the lookup that answered it; ``o.m(...)`` on a source instance is
    the attribute read answering this value, then this call), and any other
    use of the value (truthiness, comparison, further attributes) stays a
    FloorValue panic.
    """

    receiver: object
    name: str

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
        return self.receiver.call_method_value(
            self.name,
            positional,
            owner=type(self).__name__,
            blame=operation.site,
            ctx=ctx,
            keywords=keywords,
        )
