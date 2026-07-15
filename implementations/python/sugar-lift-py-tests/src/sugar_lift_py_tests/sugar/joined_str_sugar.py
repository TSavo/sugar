from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class _LiteralPart:
    text: str


@dataclass(frozen=True)
class _FormattedPart:
    value: SugarBody | None
    dynamic_spec: SugarBody | None
    conversion: int
    spec: str
    # When set, this part cannot lift statically -- desugar is a typed red.
    dynamic_reason: str | None = None


_JoinedPart = _LiteralPart | _FormattedPart


@dataclass(frozen=True)
class JoinedStrSugar(Sugar, role=SugarRole.TERM):
    """An f-string `f\"{a}b{c}\"` -- concatenation of every part.

    LAW (symbolic_term JoinedStr): the whole is py.fstring([...parts...]).
    Each FormattedValue is py.format(value, spec, conversion). Literal
    segments are str_const. Fold to StringValue when every part is ground;
    otherwise emit the coordinate. Every part is carried -- never dropped.
    Dynamic format specs are a typed runtime boundary (loud), not silent drop.
    """

    parts: tuple[_JoinedPart, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "JoinedStr"

    @classmethod
    def new(cls, site, ctx) -> "JoinedStrSugar":
        # Factory-build each FormattedValue inner expr; literal text is data.
        parts: list[_JoinedPart] = []
        for part in site.joined_str_values():
            if part.observed in {"PrimitiveLiteral", "Constant"}:
                value = part.literal_value()
                if type(value) is str:
                    parts.append(_LiteralPart(value))
                    continue
                parts.append(
                    _FormattedPart(
                        value=None,
                        dynamic_spec=None,
                        conversion=-1,
                        spec="",
                        dynamic_reason=(
                            f"f-string literal segment at {part.blame} was "
                            f"{type(value).__name__}, not literal text"
                        ),
                    )
                )
                continue
            if part.observed != "FormattedValue":
                parts.append(
                    _FormattedPart(
                        value=None,
                        dynamic_spec=None,
                        conversion=-1,
                        spec="",
                        dynamic_reason=(
                            f"f-string part `{part.observed}` at {part.blame} "
                            "is not literal text or a formatted field"
                        ),
                    )
                )
                continue
            if part.formatted_value_has_format_spec():
                spec = part.formatted_value_format_spec_static_text()
                if spec is None:
                    # Dynamic format_spec -- carry the fact loudly, do not drop.
                    parts.append(
                        _FormattedPart(
                            value=ctx.build_body(
                                part.formatted_value_value(), SugarRole.TERM
                            ),
                            dynamic_spec=ctx.build_body(
                                part.formatted_value_format_spec(), SugarRole.TERM
                            ),
                            conversion=part.formatted_value_conversion(),
                            spec="",
                            dynamic_reason=(
                                "formatted string literal has a dynamic format "
                                "spec; Python evaluates format specs at runtime"
                            ),
                        )
                    )
                    continue
            else:
                spec = ""
            parts.append(
                _FormattedPart(
                    value=ctx.build_body(part.formatted_value_value(), SugarRole.TERM),
                    dynamic_spec=None,
                    conversion=part.formatted_value_conversion(),
                    spec=spec,
                )
            )
        return cls(parts=tuple(parts), site=site)

    @classmethod
    def witnesses(cls):
        # Pure-literal f-string folds to the concrete string face.
        prefix = "def A():\n" "    return f'numpy-totality'\n" "\n"
        return _call_pair(
            name="joined_str_literal_return",
            owner_sugar="JoinedStrSugar",
            family="python-formatted-string-literal",
            truthful=prefix + "def test_a():\n    assert A() == 'numpy-totality'\n",
            lying=prefix + "def test_a():\n    assert A() == 'wrong-totality'\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self._collect(0, (), ctx)

    def _collect(self, index: int, accumulated: tuple, ctx: object) -> Outcome:
        if index == len(self.parts):
            return self._finish(accumulated)
        part = self.parts[index]
        if type(part) is _LiteralPart:
            from sugar_lift_py_tests.floor import StringValue

            return self._collect(index + 1, (*accumulated, StringValue(part.text)), ctx)
        if part.dynamic_reason is not None:
            if part.value is None or part.dynamic_spec is None:
                from sugar_lift_py_tests.factory import factory_panic_gap

                factory_panic_gap(
                    owner="JoinedStrSugar",
                    blame=str(self.site),
                    observed="FormattedValue",
                    requested="term",
                    fix=part.dynamic_reason,
                )
            return part.value.reduce(ctx).and_then(
                lambda value: part.dynamic_spec.reduce(ctx).and_then(
                    lambda spec: _runtime_format_effect(
                        self.site,
                        part.dynamic_reason,
                        value,
                        spec,
                        part.conversion,
                    )
                )
            )
        if part.value is None:
            from sugar_lift_py_tests.factory import factory_panic_gap

            factory_panic_gap(
                owner="JoinedStrSugar",
                blame=str(self.site),
                observed="FormattedValue",
                requested="term",
                fix="formatted string literal field has no reducible value",
            )
        return part.value.reduce(ctx).and_then(
            lambda value: self._after_formatted(value, part, index, accumulated, ctx)
        )

    def _after_formatted(
        self, value, part: _FormattedPart, index: int, accumulated: tuple, ctx
    ) -> Outcome:
        ground = _try_ground_format(value, part.conversion, part.spec, self.site)
        if ground is not None:
            from sugar_lift_py_tests.floor import StringValue

            return self._collect(index + 1, (*accumulated, StringValue(ground)), ctx)
        # Symbolic (or non-foldable ground): py.format coordinate.
        from sugar_lift_py_tests.floor import SymbolicValue
        from sugar_lift_py_tests.ir import ctor, num, str_const

        term = ctor(
            "py.format",
            [
                value.to_term(owner=str(self.site)),
                str_const(part.spec),
                num(part.conversion),
            ],
        )
        return self._collect(index + 1, (*accumulated, SymbolicValue(term)), ctx)

    def _finish(self, accumulated: tuple) -> Outcome:
        from sugar_lift_py_tests.floor import StringValue, SymbolicValue
        from sugar_lift_py_tests.ir import ctor

        if not accumulated:
            return Complete(StringValue(""))
        if all(type(piece) is StringValue for piece in accumulated):
            return Complete(StringValue("".join(piece.value for piece in accumulated)))
        terms = [piece.to_term(owner=str(self.site)) for piece in accumulated]
        return Complete(SymbolicValue(ctor("py.fstring", terms)))

    def walk_children(self):
        return tuple(
            part.value
            for part in self.parts
            if type(part) is _FormattedPart and part.value is not None
        )


def _try_ground_format(value, conversion: int, spec: str, site) -> str | None:
    """Fold a concrete field via Python format; None => emit coordinate."""
    from sugar_lift_py_tests.floor import StringValue, TermValue

    if type(value) is StringValue:
        obj: object = value.value
    elif type(value) is TermValue:
        obj = value.value
    else:
        return None
    if conversion == ord("s"):
        obj = str(obj)
    elif conversion == ord("r"):
        obj = repr(obj)
    elif conversion == ord("a"):
        obj = ascii(obj)
    elif conversion != -1:
        return None
    try:
        return format(obj, spec)
    except (TypeError, ValueError):
        del site
        return None


def _runtime_format_effect(
    site, reason: str, value, spec, conversion: int
) -> Incomplete:
    blame = str(site)
    from sugar_lift_py_tests.effect import (
        DynamicFormatRuntimeEffect,
        RuntimeEffectWitness,
    )
    from sugar_lift_py_tests.ir import ctor, num

    operand = ctor(
        "py.format.arguments",
        [
            value.to_term(owner=blame),
            spec.to_term(owner=blame),
            num(conversion),
        ],
    )

    return Incomplete(
        DynamicFormatRuntimeEffect(
            "formatted string runtime boundary: "
            f"{reason}; keep as typed red until a narrower floor owns this "
            f"shape. blame={blame}",
            witness=RuntimeEffectWitness(
                operation=ctor("py.format.dynamic_spec", [operand]),
                operand=operand,
                site=site,
            ),
        )
    )
