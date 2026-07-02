from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.floor import ObjectValue, SymbolicValue
from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ContextManagerOperation:
    body: SugarBody
    optional_name: str | None = None
    owner: str = "WithSugar"
    blame: str = "<unknown>"

    def __post_init__(self) -> None:
        if not isinstance(self.body, SugarBody):
            raise TypeError("ContextManagerOperation body must be factory-built")

    def context_object(self, receiver: ObjectValue, ctx) -> Outcome:
        entered = _force_dunder(
            receiver,
            "__enter__",
            (),
            ctx,
            owner=f"{self.owner}.__enter__",
            blame=self.blame,
        )
        if isinstance(entered, Incomplete):
            return entered
        body_ctx = ctx
        if self.optional_name is not None:
            body_ctx = ctx.with_temporal(
                ctx.temporal.bind_value(
                    self.optional_name,
                    entered,
                    blame=self.blame,
                )
            )
        body_outcome = self.body.reduce(body_ctx)
        if isinstance(body_outcome, Incomplete):
            return body_outcome
        exited = _force_dunder(
            receiver,
            "__exit__",
            (_none_value(), _none_value(), _none_value()),
            body_ctx,
            owner=f"{self.owner}.__exit__",
            blame=self.blame,
        )
        if isinstance(exited, Incomplete):
            return exited
        return body_outcome


def _force_dunder(
    receiver: ObjectValue,
    name: str,
    arguments: tuple,
    ctx,
    *,
    owner: str,
    blame: str,
):
    value = complete_value(
        receiver.call_method_value(
            name,
            arguments,
            owner=owner,
            blame=blame,
        ),
        owner=owner,
    )
    try:
        return force_floor(value, ctx, owner=owner)
    except TypeError as exc:
        return Incomplete(
            RuntimeEffect(
                f"{owner} reduced to a runtime effect or opaque callsite: {exc}"
            )
        )


def _none_value() -> SymbolicValue:
    return SymbolicValue(ctor("None", []))
