from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.ir import (
    _ConstBool,
    _ConstInt,
    _ConstStr,
    _Ctor,
    Term,
    ctor,
    eq,
)

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

    entries: tuple[tuple[Term, Term], ...]

    def contribution(self):
        # Typed non-FOL support carrier: absorbed in a block record.
        return ()

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

            # Bare folded count; BuiltinCallSugar wrap re-attaches call:len.
            return Complete(TermValue(len(self.entries)))
        return _call_method_effect(
            blame=operation.blame,
            observed=f"DictLiteralValue.{operation.name}",
        )

    def subscript_with(self, operation: Any, ctx: object) -> Any:
        from sugar_lift_py_tests.floor.call_site_value import force_floor
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

        key_floor = force_floor(
            operation.index,
            ctx,
            owner=f"{operation.owner} dict key",
        )
        key_term = floor_to_term(key_floor, owner=f"{operation.owner} dict key")
        for stored_key, stored_value in self.entries:
            if stored_key == key_term:
                return Complete(_term_to_floor(stored_value))
        return _subscript_effect(
            blame=operation.blame,
            observed="DictLiteralValue[missing-key]",
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


def _subscript_effect(
    *,
    blame: str,
    observed: str,
):
    from sugar_lift_py_tests.outcome import Incomplete

    return Incomplete(
        RuntimeEffect(
            "dict subscript runtime boundary: "
            f"{observed} has no statically matching entry. Python dictionary "
            "lookup can raise KeyError or depend on runtime __hash__/__eq__; "
            "keep as typed red until a narrower vendor-cited reduction owns "
            f"the shape. blame={blame}"
        )
    )


def _term_to_floor(term: Term) -> FloorValue:
    if isinstance(term, _ConstInt):
        return TermValue(term.value)
    if isinstance(term, _ConstStr):
        from .string_value import StringValue

        return StringValue(term.value)
    if isinstance(term, _Ctor) and term.name == "python:dict":
        entries: list[tuple[Term, Term]] = []
        for entry in term.args:
            if not (
                isinstance(entry, _Ctor)
                and entry.name == "python:dict_entry"
                and len(entry.args) == 2
            ):
                break
            entries.append((entry.args[0], entry.args[1]))
        else:
            return DictLiteralValue(tuple(entries))
    from .symbolic_value import SymbolicValue

    return SymbolicValue(term)
