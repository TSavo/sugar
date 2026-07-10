from __future__ import annotations

from dataclasses import dataclass
import math
from typing import TYPE_CHECKING, NoReturn

from .floor_value import FloorValue

if TYPE_CHECKING:
    from sugar_lift_py_tests.context import FactoryBuildContext
    from sugar_lift_py_tests.operations.method_call_operation import (
        MethodCallOperation,
    )
    from sugar_lift_py_tests.outcome import Outcome


@dataclass(frozen=True)
class StringValue(FloorValue):
    value: str

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import str_const

        return str_const(self.value)

    def add(self, other, blame):
        # A string's addition IS concatenation: two strings fold to their join.
        # Anything else falls to the honest addition-floor gap.
        if type(other) is StringValue:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(StringValue(self.value + other.value))
        return super().add(other, blame)

    def project_callsite_with(self, operation, ctx):
        return operation.project_literal(self, ctx)

    def call_method_with(
        self, operation: MethodCallOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        if operation.name == "__int__" and not operation.arguments:
            from sugar_lift_py_tests.floor.term_value import TermValue
            from sugar_lift_py_tests.outcome import Complete

            return Complete(TermValue(int(self.value)))
        if operation.name == "__float__" and not operation.arguments:
            from sugar_lift_py_tests.effect import RuntimeEffect
            from sugar_lift_py_tests.floor.term_value import TermValue
            from sugar_lift_py_tests.outcome import Complete, Incomplete

            try:
                parsed = float(self.value)
            except ValueError:
                return Incomplete(
                    RuntimeEffect(
                        "string float conversion runtime boundary: "
                        "crime=StringValue.__float__ cannot parse a static string; "
                        "owner=StringValue; "
                        f"shape=value `{self.value}`; "
                        "replacement=keep this as typed red because Python raises "
                        "ValueError at runtime; "
                        f"blame={operation.blame}"
                    )
                )
            if not math.isfinite(parsed):
                return Incomplete(
                    RuntimeEffect(
                        "string float conversion runtime boundary: "
                        "crime=StringValue.__float__ parsed a non-finite float; "
                        "owner=StringValue; "
                        f"shape=value `{self.value}`; "
                        "replacement=add a cited non-finite numeric floor before "
                        "treating NaN/Infinity as proof-bearing; "
                        f"blame={operation.blame}"
                    )
                )
            if not parsed.is_integer():
                return Incomplete(
                    RuntimeEffect(
                        "string float conversion runtime boundary: "
                        "crime=StringValue.__float__ parsed a non-integral Real; "
                        "owner=StringValue; "
                        f"shape=value `{self.value}`; "
                        "replacement=add a deterministic Real-return floor before "
                        "treating this as proof-bearing; "
                        f"blame={operation.blame}"
                    )
                )
            return Complete(TermValue(parsed))
        if operation.name == "format":
            from sugar_lift_py_tests.effect import RuntimeEffect
            from sugar_lift_py_tests.floor.term_value import TermValue
            from sugar_lift_py_tests.outcome import Complete, Incomplete

            args: list[str | int | float] = []
            for arg in operation.arguments:
                if isinstance(arg, StringValue):
                    args.append(arg.value)
                elif isinstance(arg, TermValue):
                    args.append(arg.value)
                else:
                    return Incomplete(
                        RuntimeEffect(
                            "string format runtime boundary: "
                            "crime=StringValue.format argument is not a static "
                            "string/numeric floor; "
                            "owner=StringValue; "
                            f"shape={type(arg).__name__}; "
                            "replacement=add a cited str.format floor for this "
                            "argument type or keep the method call as typed red; "
                            f"blame={operation.blame}"
                        )
                    )
            try:
                return Complete(StringValue(self.value.format(*args)))
            except (IndexError, KeyError, ValueError) as exc:
                return Incomplete(
                    RuntimeEffect(
                        "string format runtime boundary: "
                        "crime=StringValue.format raised while applying a static "
                        "format string; "
                        "owner=StringValue; "
                        f"shape={type(exc).__name__}; "
                        "replacement=prove a narrower format-string floor or keep "
                        "the method call as typed red; "
                        f"blame={operation.blame}"
                    )
                )
        if operation.name == "__format__" and len(operation.arguments) == 1:
            from sugar_lift_py_tests.outcome import Complete

            spec = operation.arguments[0]
            if isinstance(spec, StringValue):
                return Complete(StringValue(format(self.value, spec.value)))
        # Pure str methods: fold when args are static floors; otherwise mint
        # call:<m>(self, …) with computed=None (joinable coordinate, never
        # fabricate a result). Missing floor totalizer — not a missing AST
        # recognizer (CallSugar already selects MethodCallStrategy).
        folded = _fold_string_method(self, operation)
        if folded is not None:
            return folded
        _call_method_gap(
            owner=operation.owner,
            blame=operation.blame,
            observed=f"StringValue.{operation.name}",
            requested="string builtin method floor",
            fix=f"add StringValue method floor for `{operation.name}`",
        )

    def contains_with(self, operation, ctx):
        return operation.contains_string(self, ctx)

    def subscript_with(self, operation, ctx):
        return operation.subscript_string(self, ctx)

    def str_with(self, operation, ctx):
        return operation.str_string(self, ctx)

    def format_value_with(self, operation, ctx):
        return operation.format_string(self, ctx)

    def binary_operator_with(self, operation, ctx):
        return operation.binary_string(self, ctx)


def _fold_string_method(receiver: StringValue, operation: MethodCallOperation):
    """Fold join/strip/split/splitlines (and strip family) or mint an opaque coordinate.

    Returns an Outcome when this method is owned, else None so the caller can
    FactoryGap for unrelated names.
    """
    from sugar_lift_py_tests.floor.array_literal import ArrayLiteral
    from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.outcome import Complete

    name = operation.name
    args = operation.arguments

    def opaque_coordinate() -> Complete:
        return Complete(
            OpaqueOpCallsite(
                callee=name,
                arg=receiver,
                computed=None,
                extra_args=tuple(args),
            )
        )

    if name in {"strip", "lstrip", "rstrip"}:
        if len(args) == 0:
            return Complete(StringValue(getattr(receiver.value, name)()))
        if len(args) == 1:
            chars = args[0]
            if isinstance(chars, StringValue):
                return Complete(StringValue(getattr(receiver.value, name)(chars.value)))
            # Opaque / symbolic chars: mint call:strip(self, chars), never invent.
            return opaque_coordinate()
        return None

    if name == "join" and len(args) == 1:
        iterable = args[0]
        parts = _static_str_parts(iterable)
        if parts is not None:
            return Complete(StringValue(receiver.value.join(parts)))
        # Opaque iterable (vendor columns, symbolic seq): coordinate only.
        return opaque_coordinate()

    if name == "split":
        if len(args) == 0:
            return Complete(
                ArrayLiteral(
                    tuple(StringValue(part) for part in receiver.value.split())
                )
            )
        if len(args) == 1:
            sep = args[0]
            if isinstance(sep, StringValue):
                return Complete(
                    ArrayLiteral(
                        tuple(
                            StringValue(part)
                            for part in receiver.value.split(sep.value)
                        )
                    )
                )
            if _is_none_floor(sep):
                return Complete(
                    ArrayLiteral(
                        tuple(StringValue(part) for part in receiver.value.split(None))
                    )
                )
            return opaque_coordinate()
        if len(args) == 2:
            sep, maxsplit = args
            if isinstance(maxsplit, TermValue) and type(maxsplit.value) is int:
                max_n = int(maxsplit.value)
                if isinstance(sep, StringValue):
                    return Complete(
                        ArrayLiteral(
                            tuple(
                                StringValue(part)
                                for part in receiver.value.split(sep.value, max_n)
                            )
                        )
                    )
                if _is_none_floor(sep):
                    return Complete(
                        ArrayLiteral(
                            tuple(
                                StringValue(part)
                                for part in receiver.value.split(None, max_n)
                            )
                        )
                    )
            return opaque_coordinate()
        return None

    if name == "splitlines":
        # str.splitlines([keepends]) — fold when keepends is static bool/0/1;
        # opaque keepends → coordinate only (never invent line breaks).
        if len(args) == 0:
            return Complete(
                ArrayLiteral(
                    tuple(
                        StringValue(part) for part in receiver.value.splitlines()
                    )
                )
            )
        if len(args) == 1:
            keep = args[0]
            if isinstance(keep):
                return Complete(
                    ArrayLiteral(
                        tuple(
                            StringValue(part)
                            for part in receiver.value.splitlines(keep.value)
                        )
                    )
                )
            if isinstance(keep, TermValue) and type(keep.value) is int:
                return Complete(
                    ArrayLiteral(
                        tuple(
                            StringValue(part)
                            for part in receiver.value.splitlines(bool(keep.value))
                        )
                    )
                )
            return opaque_coordinate()
        return None

    return None


def _static_str_parts(iterable) -> list[str] | None:
    """Extract a fully-static list of strings from a join iterable, or None."""
    from sugar_lift_py_tests.floor.array_literal import ArrayLiteral
    from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue

    if isinstance(iterable, StringValue):
        # str.join over a string iterates characters.
        return list(iterable.value)
    if isinstance(iterable, (ArrayLiteral, TupleLiteralValue)):
        parts: list[str] = []
        for item in iterable.items:
            if not isinstance(item, StringValue):
                return None
            parts.append(item.value)
        return parts
    return None


def _is_none_floor(value) -> bool:
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.ir import _Ctor

    if not isinstance(value, SymbolicValue):
        return False
    term = value.term
    return isinstance(term, _Ctor) and term.name == "None" and not term.args


def _call_method_gap(
    *,
    owner: str,
    blame: str,
    observed: str,
    requested: str,
    fix: str,
) -> NoReturn:
    from sugar_lift_py_tests.factory import (
        FactoryAuditRow, factory_panic,
        FactoryGapInfo,
        GapKind,
        GapLocus,
    )

    info = FactoryGapInfo(
        owner=owner,
        blame=blame,
        observed=observed,
        requested=requested,
        fix=fix,
        gap_kind=GapKind.FLOOR,
        gap_locus=GapLocus.CONSTRUCTION,
    )
    factory_panic(
        info,
        FactoryAuditRow(
            role=requested,
            status="floor-gap",
            observed=observed,
            blame=blame,
            selected=None,
            candidates=[],
            message=info.message,
        ),
    )
