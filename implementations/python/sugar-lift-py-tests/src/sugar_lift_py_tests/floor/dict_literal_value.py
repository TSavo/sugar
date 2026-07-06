from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.ir import Term, ctor, eq

from .floor_value import FloorValue
from .term_value import TermValue


@dataclass(frozen=True)
class DictLiteralValue(FloorValue):
    """A structural Python dict literal term.

    Dict literals are useful evidence payloads and call arguments, but the current
    production solver path does not give dict constructor equality an independent
    verdict witness. The floor is therefore a typed non-FOL support carrier, while
    still projecting to a term for enclosing claims.
    """

    non_fol_support = True

    entries: tuple[tuple[Term, Term], ...]

    def to_term(self, *, owner: str) -> Term:
        del owner
        return ctor(
            "python:dict",
            [ctor("python:dict_entry", [key, value]) for key, value in self.entries],
        )

    def call_method_with(self, operation: Any, ctx: object) -> Any:
        del ctx
        if operation.name == "__len__" and not operation.arguments:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(TermValue(len(self.entries)))
        return _call_method_effect(
            blame=operation.blame,
            observed=f"DictLiteralValue.{operation.name}",
        )

    def project_callsite_with(self, operation: Any, ctx: object):
        del ctx
        return eq(operation.call_term(), self.to_term(owner=operation.owner))


def _call_method_effect(
    *,
    blame: str,
    observed: str,
):
    from sugar_lift_py_tests.outcome import Incomplete

    return Incomplete(
        RuntimeEffect(
            "dict builtin method runtime boundary: "
            f"{observed} has no reduced floor semantics in this tranche. "
            "Python dictionary method results can expose runtime view/mutation "
            "semantics; keep as typed red until a narrower vendor-cited "
            f"reduction owns the shape. blame={blame}"
        )
    )
