"""An ``except`` arm whose type is an expression, read when a raise reaches it.

``except tuple(err_types_to_retry_with_anon):`` (pandas.io.common
``_get_filepath_or_buffer``) names no class lexically.  CPython evaluates the
handler expression only when an exception reaches that arm, in arm order
(Python/compile.c ``compiler_try_except``: the type is loaded after the
exception is pushed), then matches with ``PyErr_GivenExceptionMatches``: a
tuple matches when any member does, an empty tuple matches nothing.

The arm is therefore the expression's Sugar, desugared in the routing context
of each raise.  Only a value whose meaning is closed is admitted: an exception
class with an authenticated identity, or a tuple of them (possibly empty).
Anything else -- an expression that may itself raise, a non-class member
(CPython's ``TypeError: catching classes that do not inherit from
BaseException is not allowed``), a value nobody testified to -- stays loud.
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
        from sugar_lift_py_tests.sugar.witnesses import _call_pair

        return _call_pair(
            name="computed_exception_type",
            owner_sugar="ComputedExceptionTypeSugar",
            truthful="def f(x):\n    return x\n",
            lying="def f(x):\n    return 0\n",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:computed-exception-type",
            (self.occurrence_term(owner=owner), self.value.to_term(owner=owner)),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.outcome import Complete
        from sugar_source_tree.panic import SugarNotWritten

        outcome = self.value.desugar(ctx)
        if not isinstance(outcome, Complete):
            raise SugarNotWritten(
                blame=self.site,
                owner="ComputedExceptionTypeSugar.desugar",
                observed="computed except type may not complete",
                requested="an except expression that completes",
                fix="model the handler expression's own raise, or keep it loud",
            )
        value = outcome.value
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
                    fix="keep the arm loud; CPython raises TypeError for a non-class",
                )
        return outcome
