"""f-strings: `f"pre {value} post"`.

A JoinedStr is the CONCATENATION of its parts -- literal chunks (StringLiteral)
and interpolations (FormattedValue). Ground string parts fold left with `add`.
A mix of a ground string and a named interpolation is ``python:fstring`` over
the part terms: inventing the formatted string is dishonest, and
``str + symbolic`` mints a deferred carrier that cannot travel through If
guards. A FormattedValue projects the Python reference's
opaque ``python:fstring_value(value, conversion, format_spec)`` coordinate.
Conversion and format spec remain typed operands: absence is explicit ``None``
and a present spec is a nested ``python:fstring`` coordinate. The coordinate
carries Python's conversion-then-format meaning without claiming execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)
from sugar_lift_py_tests.sugar.witnesses import _call_pair


def _concatenate_joined_parts(left, right, site, ctx):
    """Name an unground join as an f-string coordinate, without inventing the string.

    Ground string parts still concatenate through ``add``. A mix of a ground
    string and a named interpolation currently mints
    ``NativeOperationExitCarrierV1`` (``StringValue.add(SymbolicValue)``), and
    that carrier cannot join through ``IfSugar.union``. RaisesExc writes
    ``f"DID NOT RAISE {self.expected_exceptions[0].__name__}"`` inside
    ``if len(...) == 1``. Emit ``python:fstring`` over the part terms instead.
    """
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.ir import ctor

    if type(left) is StringValue and type(right) is StringValue:
        return left.add(right, site, ctx)
    return ExitSet.completed(
        CallSiteValue(
            target_name="__add__",
            arg_values=(left, right),
            parameters=(),
            term=ctor(
                "python:fstring",
                [
                    left.to_term(owner="JoinedStrSugar.desugar"),
                    right.to_term(owner="JoinedStrSugar.desugar"),
                ],
                symbol_kind="coordinate",
            ),
            body=None,
            site=site,
            string_concatenation=True,
        )
    )


@dataclass(frozen=True)
class FormattedValueSugar(ConstructedTermSugar):
    """A Python-reference formatted-value coordinate, without execution."""

    value: ConstructedTermSugar
    conversion: str | None
    format_spec: JoinedStrSugar | None
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        require_constructed_term_sugar(self.value, owner="FormattedValueSugar.value")
        if self.format_spec is not None:
            require_constructed_term_sugar(
                self.format_spec, owner="FormattedValueSugar.format_spec"
            )

    @classmethod
    def witnesses(cls):
        return ()

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        conversion = (
            ctor("python:no-fstring-conversion", ())
            if self.conversion is None
            else str_const(self.conversion)
        )
        format_spec = (
            ctor("python:no-format-spec", ())
            if self.format_spec is None
            else self.format_spec.to_term(owner=owner)
        )
        return ctor(
            "python:formatted-value-construction",
            (
                self.occurrence_term(owner=owner),
                self.value.to_term(owner=owner),
                conversion,
                format_spec,
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import ctor, str_const

        conversion_term = (
            ctor("None", []) if self.conversion is None else str_const(self.conversion)
        )

        def build(value, format_spec_term):
            # Ground strings with no conversion/spec are already their display.
            # RaisesExc formats ``f"DID NOT RAISE {type.__name__}"``; folding
            # keeps the diagnostic message a StringValue so fail() can raise
            # instead of panicking at SymbolicValue + SymbolicValue.
            if (
                isinstance(value, StringValue)
                and self.conversion is None
                and self.format_spec is None
            ):
                return ExitSet.completed(value)
            formatted = SymbolicValue(
                ctor(
                    "python:fstring_value",
                    [
                        value.to_term(owner="FormattedValueSugar.value"),
                        conversion_term,
                        format_spec_term,
                    ],
                )
            )
            from sugar_lift_py_tests.source_call_resolution import (
                BuiltinDunderCallV1,
                builtin_typed_value,
            )

            if not builtin_typed_value(value):
                # ``f'{c}'`` runs ``type(c).__format__`` (``!s``/``!r``/``!a``
                # its ``__str__``/``__repr__`` first): not CPython's own when
                # ``c`` is not a decided builtin, so it may raise.
                return BuiltinDunderCallV1("format").faces(formatted, self.site)
            return ExitSet.completed(formatted)

        # `f"{expr!r:{spec}}"` evaluates expr then spec, and EITHER can halt or
        # partition (`f"{d[k] := v}"`). Both thread through `and_then` -- the one
        # door -- so a halt propagates and a partition keeps every arm. Reading `.value` off the outcome assumed one
        # unconditional arm and was the `'ExitSet' has no attribute 'value'`
        # defect here.
        def with_spec(value, spec_ctx):
            if self.format_spec is None:
                return build(value, ctor("None", []))
            return self.format_spec.reference_term(spec_ctx).and_then(
                lambda spec_term: build(value, spec_term)
            )

        # The formatted expression is an operand: a walrus in it
        # (``f"{(x := 5)}"``) binds once, through the one operand door, and
        # the value it presents is what is formatted.  The spec is evaluated
        # after it, with its writes applied (``written_by``).
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            written_by,
        )

        return self.value.desugar(ctx).and_then(
            lambda value: consume_operands(
                lambda presented: with_spec(presented, written_by(value, ctx)),
                value,
            )
        )


@dataclass(frozen=True)
class JoinedStrSugar(ConstructedTermSugar):
    """The whole f-string: concatenate its parts left-to-right via `add`."""

    parts: tuple[ConstructedTermSugar, ...]
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        for part in self.parts:
            require_constructed_term_sugar(part, owner="JoinedStrSugar.parts")

    @classmethod
    def witnesses(cls):
        prefix = 'def A(z):\n    return f"n={z}"\n\n'
        return _call_pair(
            name="fstring_return",
            owner_sugar="JoinedStrSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == '5'\n",
            lying=prefix + "def test_a():\n    assert A(5) == '6'\n",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:joined-string-construction",
            (
                self.occurrence_term(owner=owner),
                ctor(
                    "python:joined-string-parts",
                    tuple(part.to_term(owner=owner) for part in self.parts),
                ),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.outcome.exit_set import factored_operand

        if not self.parts:
            return ExitSet.completed(StringValue(""))
        # Concatenate left-to-right through `and_then`, the one door: a part
        # that halts propagates, a part that PARTITIONS keeps every arm and
        # each arm concatenates under its own guard. `acc.value.add(right.value,
        # ...)` assumed both sides were one unconditional value.
        # One completed arm per part (#6324): concatenation is a k-step fold
        # through `ExitSet.sequence`, so an unfactored partitioning part
        # multiplies the accumulator at every remaining part.
        # The parts are operands of the concatenation: a walrus in one binds
        # once, through the one operand door; the joined value so far carries
        # the binds of the parts before it, so they ride to the end in order,
        # and each part is evaluated with their writes applied
        # (``written_by``: ``f"{(n := 1)}{n}"``).
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            written_by,
        )

        def concatenate(left, right):
            return _concatenate_joined_parts(left, right, self.site, ctx)

        outcome = factored_operand(self.parts[0].desugar(ctx))
        for part in self.parts[1:]:
            outcome = outcome.and_then(
                lambda left, part=part: factored_operand(
                    part.desugar(written_by(left, ctx))
                ).and_then(lambda right: consume_operands(concatenate, left, right))
            )
        return outcome

    def reference_term(self, ctx: object = None) -> ExitSet:
        """Project this JoinedStr as the reference ``python:fstring`` ctor."""
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome.exit_set import factored_operand

        # Same law as `desugar`: every part threads through `and_then`, so a
        # halting or partitioning part is conserved rather than read as `.value`.
        outcome = ExitSet.completed(())
        for part in self.parts:
            outcome = outcome.and_then(
                lambda terms, part=part: factored_operand(part.desugar(ctx)).and_then(
                    lambda value: ExitSet.completed(
                        (
                            *terms,
                            value.to_term(owner="JoinedStrSugar.reference_term"),
                        )
                    )
                )
            )
        return outcome.and_then(
            lambda terms: ExitSet.completed(ctor("python:fstring", list(terms)))
        )
