"""An ``except`` arm whose type is an expression, read when a raise reaches it.

``except tuple(err_types_to_retry_with_anon):`` (pandas.io.common
``_get_filepath_or_buffer``) names no class lexically.  CPython evaluates the
handler expression only when an exception reaches that arm, in arm order
(Python/compile.c ``compiler_try_except``: the type is loaded after the
exception is pushed), then matches with ``PyErr_GivenExceptionMatches``: a
tuple matches when any member does, an empty tuple matches nothing.

The arm is therefore the expression's Sugar, desugared in the routing context
of each raise, every face of it carried: a halt of the expression is the
``try``'s halt where the raise reached the arm.  A completed face is admitted
only when its value's meaning is closed: an exception class with an
authenticated identity, or a tuple of them (possibly empty).  Anything else --
a non-class member (CPython's ``TypeError: catching classes that do not
inherit from BaseException is not allowed``), a value nobody testified to --
stays loud.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)


@dataclass(frozen=True)
class ComputedExceptionTypeSugar(ConstructedTermSugar):
    value: ConstructedTermSugar
    site: object = dataclass_field(compare=False, default=None)

    def __post_init__(self) -> None:
        require_constructed_term_sugar(
            self.value, owner="ComputedExceptionTypeSugar.value"
        )

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import _assertion_pair

        # The arm's type is a name bound to a value (``excs``), read when the
        # raise reaches the arm: the tuple holds ``ValueError``, so the arm
        # matches and binds `z`.
        return _assertion_pair(
            name="computed_exception_type",
            owner_sugar="ComputedExceptionTypeSugar",
            statements=(
                "z = 5\n"
                "excs = (KeyError, ValueError)\n"
                "try:\n"
                "    raise ValueError\n"
                "except excs:\n"
                "    z = 6"
            ),
            truthful="z == 6",
            lying="z == 5",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:computed-exception-type",
            (self.occurrence_term(owner=owner), self.value.to_term(owner=owner)),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx=None):
        """Every face of the handler expression: a halted face is the
        expression's own raise (the ``try`` halts there, ``TrySugar``'s
        router); each completed face must hold an exception class, or a tuple
        of them, else it is refused by name.  Anything but exits is refused by
        name (``_require_exit_set``)."""
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.outcome.exit_set import _require_exit_set
        from sugar_source_tree.panic import SugarNotWritten

        outcome = _require_exit_set(
            self.value.desugar(ctx), owner="ComputedExceptionTypeSugar.desugar"
        )

        def closed(value):
            members = value.elements if type(value) is TupleValue else (value,)
            for member in members:
                reader = getattr(member, "exception_type_identity", None)
                if reader is None or reader() is None:
                    raise SugarNotWritten(
                        blame=self.site,
                        owner="ComputedExceptionTypeSugar.desugar",
                        observed=(
                            "computed except type member without authenticated "
                            f"exception identity: {type(member).__name__}"
                        ),
                        requested="exception classes, or a tuple of them",
                        fix=(
                            "keep the arm loud; CPython raises TypeError for a "
                            "non-class"
                        ),
                    )
            return ExitSet.completed(value)

        return outcome.and_then(closed)
