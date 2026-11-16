"""The value a builtin descriptor constructor returns (#7757, A5).

``staticmethod(f)``, ``classmethod(f)`` and ``property(fget)`` -- spelled as
a decorator wherever the ``def`` stands (a class body, a module, a function
body) or as a call -- are answered by the one decorator application
(``nodes.builtin_decorator_application``, a ``descriptor`` step): the
descriptor object wrapping the function.  None of them raises.  A
property's own ``@x.setter`` / ``@x.getter`` / ``@x.deleter`` is the
attribute read of that property (``PropertyAccessorValue``) applied to the
function by the same application: a copy of the property with that one
accessor replaced (``property.setter``, Objects/descrobject.c).

In a class body the descriptor is what the class's namespace binds the name
to; the namespace row states its kind (``python:class_binds``, read through
``ClassDef._method_descriptor_kind``, which asks the same door), and prove
binds a call or read through it by that kind (#8813).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .floor_value import FloorValue

STATICMETHOD = "staticmethod"
CLASSMETHOD = "classmethod"
PROPERTY = "property"

#: ``@x.<accessor>``: the field of the property each accessor replaces.
_PROPERTY_ACCESSORS = {"getter": "function", "setter": "setter", "deleter": "deleter"}

_OWNER = "BuiltinDescriptorValue"


def wraps_without_raising(value) -> bool:
    """Whether a builtin descriptor constructor wraps ``value`` without
    running code that may raise: ``property(f)`` reads ``f.__doc__``
    (``property_init``), and ``staticmethod(f)`` / ``classmethod(f)`` copy
    ``__module__``, ``__name__``, ``__qualname__``, ``__doc__`` and
    ``__dict__`` off ``f`` (``functools_wraps``, Objects/funcobject.c).  A
    function (``LambdaCallable``: a source ``def``'s or lambda's) and a
    builtin descriptor answer each read without raising; any other value's
    read may run code (a ``__getattr__``, a property), so its wrapping is
    not decided here."""
    from sugar_lift_py_tests.floor.lambda_callable import LambdaCallable

    return isinstance(value, (LambdaCallable, BuiltinDescriptorValue))


@dataclass(frozen=True)
class BuiltinDescriptorValue(FloorValue):
    """``staticmethod(function)``, ``classmethod(function)``, or
    ``property(function, setter, deleter)`` (``function`` the getter; an
    accessor no ``@x.setter``/``@x.deleter`` gave is None)."""

    kind: str
    function: object
    setter: object = None
    deleter: object = None

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.ir import ctor

        def part(value):
            return (NoneValue() if value is None else value).to_term(owner=owner)

        parts = [part(self.function)]
        if self.kind == PROPERTY:
            parts += [part(self.setter), part(self.deleter)]
        return ctor(f"python:{self.kind}", parts)

    def callable_application_with(self, operation, ctx):
        """A call of the descriptor object itself.  A ``staticmethod`` is
        callable and calls its function (Python 3.10+): the one routine a
        called value is applied by (``computed_call_sugar.apply_callee``).
        A ``classmethod`` or ``property`` object is not callable: CPython's
        ``TypeError``."""
        if self.kind != STATICMETHOD:
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="TypeError", site=operation.site, owner=_OWNER
            )
        from sugar_lift_py_tests.sugar.computed_call_sugar import (
            apply_callee,
            unanswered_value_call,
        )

        count = len(operation.keyword_names)
        arguments = tuple(operation.arguments)
        positional = arguments[:-count] if count else arguments
        keywords = (
            tuple(zip(operation.keyword_names, arguments[-count:])) if count else ()
        )
        return apply_callee(
            self.function,
            positional,
            keywords,
            operation.site,
            ctx,
            lambda: unanswered_value_call(
                self.function, positional, keywords, operation.site
            ),
            captured=operation.captured,
            call_occurrence=operation.call_occurrence,
        )

    def attribute(self, name, site, ctx):
        """``__func__`` / ``__wrapped__`` of a ``staticmethod`` or
        ``classmethod``: its function.  ``fget`` / ``fset`` / ``fdel`` of a
        property: its accessor, or ``None``; ``getter`` / ``setter`` /
        ``deleter``: the accessor that copies it (``PropertyAccessorValue``).
        Any other attribute is not modelled here: the undecided read, two
        faces, owed (``undecided_attribute``)."""
        del ctx
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.outcome import ExitSet

        if self.kind == PROPERTY:
            held = {"fget": self.function, "fset": self.setter, "fdel": self.deleter}
            if name in held:
                value = held[name]
                return ExitSet.completed(NoneValue() if value is None else value)
            if name in _PROPERTY_ACCESSORS:
                return ExitSet.completed(PropertyAccessorValue(self, name))
        elif name in ("__func__", "__wrapped__"):
            return ExitSet.completed(self.function)
        return self.undecided_attribute(name, site, owner=f"{_OWNER}.attribute")


@dataclass(frozen=True)
class PropertyAccessorValue(FloorValue):
    """``x.setter`` (``getter``, ``deleter``) read off the property ``x``:
    called on one function, a copy of ``x`` with that accessor replaced."""

    prop: BuiltinDescriptorValue
    accessor: str

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:property_accessor",
            [self.prop.to_term(owner=owner), str_const(self.accessor)],
        )

    def callable_application_with(self, operation, ctx):
        """``x.setter(f)``: the property copy (``property_copy``), which
        never raises where every accessor it rebuilds the property from
        wraps without raising (its getter's ``__doc__`` is read again,
        ``wraps_without_raising``); over any other value, the unanswered
        call of this accessor, both faces.  Any other call -- no argument,
        two, a keyword -- is CPython's ``TypeError`` (``setter() takes
        exactly one argument``)."""
        del ctx
        from sugar_lift_py_tests.outcome import ExitSet

        if operation.keyword_names or len(operation.arguments) != 1:
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="TypeError",
                site=operation.site,
                owner=f"{_OWNER}.{self.accessor}",
            )
        (function,) = operation.arguments
        copied = replace(self.prop, **{_PROPERTY_ACCESSORS[self.accessor]: function})
        if not wraps_without_raising(copied.function):
            from sugar_lift_py_tests.sugar.computed_call_sugar import (
                unanswered_value_call,
            )

            return unanswered_value_call(self, (function,), (), operation.site)
        return ExitSet.completed(copied)
