"""The exception an undetermined raise threw: real, opaque, keyed on its occurrence.

An ``UndeterminedRaiseEffect`` from a may-raise call (a C call, an unprojected
source call, an imported source-class construction, an opaque subscript) says
"this operation may leave by raising SOMETHING". That something is a Python
exception object. Nothing testified to its class or fields, but it exists, it
is exactly one object, and it is the object an ``except`` clause tests and an
``as`` name binds.

This value IS that object -- the subject of the handler's type test -- not a
substitute for it. Its term is ``python:undetermined_exception(occurrence,
producer)``: a function symbol whose denotation is the exception raised by
that occurrence of that producer. It is NOT the occurrence coordinate: the
coordinate (``file:line:col``) designates where the operation is written and
``adt.is_python_type(<coordinate>, T)`` is a predicate about a source span.
Here the coordinate is only the key that tells two raised objects apart, the
same way ``python:c_extension.call_completes`` keys an opaque completion on
its call site.

Every projection stays opaque or refuses through the ``FloorValue`` defaults:
its type, ``args``, message, and ``__cause__`` are not invented.
"""

from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class UndeterminedExceptionValue(FloorValue):
    """The one exception object an undetermined raise occurrence threw."""

    occurrence: str
    producer: str | None = None

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        del owner
        return ctor(
            "python:undetermined_exception",
            (str_const(self.occurrence), str_const(self.producer or "")),
        )

    def denotes_value(self) -> bool:
        """This floor value denotes one Python exception object."""
        return True

    def runtime_type_is_decided(self) -> bool:
        # Its class is exactly what nobody testified to.
        return False
