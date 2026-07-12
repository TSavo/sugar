from __future__ import annotations

from dataclasses import dataclass
import math
from typing import TYPE_CHECKING, NoReturn, cast

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

    def python_isinstance(self, type_name: str, type_term, site):
        del type_term
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return Complete(
            TrueBoolLiteralSugar(site=site)
            if type_name == "str"
            else FalseBoolLiteralSugar(site=site)
        )

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import str_const

        return str_const(self.value)

    def truth(self, site):
        # A string's truth is nonempty.
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return Complete(
            TrueBoolLiteralSugar(site=site)
            if self.value
            else FalseBoolLiteralSugar(site=site)
        )

    def less_than(self, other, site):
        # A string stands on the ordering floor: two strings order by Python's
        # lexicographic rule and fold to the True/False literal. Ground
        # cross-type is TypeError -- a named runtime effect, not an emit.
        # Symbolic falls to super() emit.
        if type(other) is StringValue:
            from sugar_lift_py_tests.outcome import Complete
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return Complete(
                TrueBoolLiteralSugar(site=site)
                if self.value < other.value
                else FalseBoolLiteralSugar(site=site)
            )
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.floor.set_value import SetValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue

        if type(other) in (TermValue, NoneValue, ListValue, TupleValue, SetValue):
            from sugar_lift_py_tests.effect import TypeErrorRuntimeEffect
            from sugar_lift_py_tests.outcome import Incomplete

            return Incomplete(
                TypeErrorRuntimeEffect(
                    f"unorderable types runtime boundary: "
                    f"StringValue and {type(other).__name__}; site={site}"
                )
            )
        return super().less_than(other, site)

    def length(self, site):
        # A string knows its length: the count of characters.
        del site
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(TermValue(len(self.value)))

    def subscript(self, index, site):
        # Concrete string + in-range TermValue int folds to the one-char string;
        # out of range is IndexError. Non-concrete index stays py.subscript.
        from sugar_lift_py_tests.floor.slice_value import SliceValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        if type(index) is SliceValue:
            bounds = (index.lower, index.upper, index.step)
            if all(
                bound is None or (type(bound) is TermValue and type(bound.value) is int)
                for bound in bounds
            ):
                lower, upper, step = (
                    cast(int, bound.value) if type(bound) is TermValue else None
                    for bound in bounds
                )
                if step == 0:
                    from sugar_lift_py_tests.factory import factory_panic_gap

                    factory_panic_gap(
                        owner="StringValue.subscript",
                        blame=str(site),
                        observed="slice step 0",
                        requested="ground Python string slice",
                        fix="use a nonzero literal integer step or emit ValueErrorRuntimeEffect",
                    )
                return Complete(StringValue(self.value[slice(lower, upper, step)]))

        if type(index) is TermValue and type(index.value) is int:
            i = index.value
            n = len(self.value)
            if -n <= i < n:
                return Complete(StringValue(self.value[i]))
            from sugar_lift_py_tests.effect import IndexErrorRuntimeEffect

            return Incomplete(
                IndexErrorRuntimeEffect(
                    f"string index out of range runtime boundary: "
                    f"index={i} length={n}; owner=StringValue.subscript site={site}"
                )
            )
        return self.py_subscript_coordinate(index, site)

    def add(self, other, site):
        # A string's addition IS concatenation: two strings fold to their join.
        # Anything else falls to the honest addition-floor gap.
        if type(other) is StringValue:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(StringValue(self.value + other.value))
        return super().add(other, site)

    def modulo(self, other, site):
        """Apply Python's printf-style string formatting floor.

        Ground scalar and tuple operands use the interpreter itself. Symbolic
        operands retain the whole operation as the same ``py.format``
        coordinate used by formatted-string construction. Other floor shapes
        stay on the default loud modulo gap.
        """
        distributed = self._distribute_guarded_modulo(other, site)
        if distributed is not None:
            return distributed

        ground = _ground_percent_operand(other)
        if ground is not _NOT_GROUND:
            from sugar_lift_py_tests.effect import DynamicFormatRuntimeEffect
            from sugar_lift_py_tests.outcome import Complete, Incomplete

            try:
                return Complete(StringValue(self.value % ground))
            except (KeyError, OverflowError, TypeError, ValueError) as exc:
                return Incomplete(
                    DynamicFormatRuntimeEffect(
                        "percent-format runtime boundary: Python rejected a "
                        "ground format application; "
                        f"shape={type(exc).__name__}; site={site}"
                    )
                )

        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.ir import ctor, num, str_const
        from sugar_lift_py_tests.outcome import Complete

        if type(other) in (CallSiteValue, SymbolicValue, TupleValue):
            return Complete(
                SymbolicValue(
                    ctor(
                        "py.format",
                        [
                            other.to_term(owner=str(site)),
                            str_const(self.value),
                            num(-1),
                        ],
                    )
                )
            )
        return super().modulo(other, site)

    def _distribute_guarded_modulo(self, other, site):
        from sugar_lift_py_tests.floor.guarded_value import GuardedValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.outcome import Complete, complete_value

        if isinstance(other, GuardedValue):
            return Complete(
                GuardedValue(
                    other.guard,
                    complete_value(
                        self.modulo(other.when_true, site),
                        owner="StringValue.modulo guarded true",
                    ),
                    complete_value(
                        self.modulo(other.when_false, site),
                        owner="StringValue.modulo guarded false",
                    ),
                )
            )
        if isinstance(other, TupleValue):
            for index, element in enumerate(other.elements):
                if not isinstance(element, GuardedValue):
                    continue

                def branch(value):
                    elements = list(other.elements)
                    elements[index] = value
                    return complete_value(
                        self.modulo(TupleValue(tuple(elements)), site),
                        owner="StringValue.modulo guarded tuple element",
                    )

                return Complete(
                    GuardedValue(
                        element.guard,
                        branch(element.when_true),
                        branch(element.when_false),
                    )
                )
        return None

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


_NOT_GROUND = object()


def _ground_percent_operand(value):
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    if type(value) is StringValue:
        return value.value
    if type(value) is TermValue:
        return value.value
    if type(value) is NoneValue:
        return None
    if type(value) is TupleValue:
        items = tuple(_ground_percent_operand(item) for item in value.elements)
        if all(item is not _NOT_GROUND for item in items):
            return items
    return _NOT_GROUND


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
                    tuple(StringValue(part) for part in receiver.value.splitlines())
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
        FactoryAuditRow,
        factory_panic,
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
