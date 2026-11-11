"""The body of a method its class bound but did not construct (#7664)."""

from __future__ import annotations

from sugar_source_tree.panic import SugarNotWritten

from sugar_lift_py_tests.sugar.sugar_base import Sugar


class DeferredMethodBodySugar(Sugar):
    """The body of a method its class bound but did not construct.

    Running it is the first time anything needs it, and nothing here
    constructed it, so running it refuses by name.  It never completes and
    never raises a guessed exception.
    """

    __slots__ = ("method",)

    def __init__(self, method) -> None:
        self.method = method

    def __eq__(self, other):
        return (
            type(other) is DeferredMethodBodySugar
            and other.method.definition_fragment_cid
            == self.method.definition_fragment_cid
        )

    def __hash__(self):
        return hash(("DeferredMethodBodySugar", self.method.definition_fragment_cid))

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="ObjectMethodValue",
            reason="a bound, unconstructed method body only ever refuses",
        )

    def desugar(self, ctx: object = None):
        del ctx
        raise SugarNotWritten(
            blame=self.method.definition.fragment,
            owner="DeferredMethodBodySugar.desugar",
            observed=(
                f"method {self.method.name} is bound by its class but its body "
                "was not constructed on this path"
            ),
            requested="the method's constructed source frame at its call site",
            fix="construct the method where it is run, or keep the call loud",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        del owner
        return ctor(
            "python:deferred-method-body",
            (str_const(self.method.definition_fragment_cid),),
        )
