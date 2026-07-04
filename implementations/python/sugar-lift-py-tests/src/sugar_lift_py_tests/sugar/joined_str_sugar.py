from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.floor import StringValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import Term, ctor, num, str_const
from sugar_lift_py_tests.operations import MethodCallOperation, StrCoercionOperation
from sugar_lift_py_tests.operations.perform_operation import perform_operation
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import (
    SugarWitnessPair,
    WitnessSource,
)
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class _LiteralPart:
    text: str


@dataclass(frozen=True)
class _FormattedPart:
    value: SugarBody | None
    conversion: int
    spec: str
    dynamic_reason: str | None = None


JoinedStrPart = _LiteralPart | _FormattedPart


@dataclass(frozen=True)
class JoinedStrSugar(Sugar, role=SugarRole.TERM):
    parts: tuple[JoinedStrPart, ...]
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "JoinedStr"

    @classmethod
    def witnesses(cls) -> SugarWitnessPair:
        return SugarWitnessPair(
            name="joined_str_literal_return",
            owner_sugar=cls.__name__,
            family="python-formatted-string-literal",
            truthful=WitnessSource(
                source=(
                    "def A():\n"
                    "    return f'numpy-totality'\n"
                    "\n"
                    "def test_a():\n"
                    "    assert A() == 'numpy-totality'\n"
                ),
                expected="sat",
            ),
            lying=WitnessSource(
                source=(
                    "def A():\n"
                    "    return f'numpy-totality'\n"
                    "\n"
                    "def test_a():\n"
                    "    assert A() == 'wrong-totality'\n"
                ),
                expected="unsat",
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> "JoinedStrSugar":
        if not cls.owns(site):
            raise TypeError("JoinedStrSugar claim built a non-JoinedStr")
        parts: list[JoinedStrPart] = []
        for part in site.joined_str_values():
            if part.observed == "PrimitiveLiteral":
                value = part.literal_value()
                if isinstance(value, str):
                    parts.append(_LiteralPart(value))
                    continue
                parts.append(
                    _FormattedPart(
                        value=None,
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
                        conversion=-1,
                        spec="",
                        dynamic_reason=(
                            f"f-string part `{part.observed}` at {part.blame} "
                            "is not literal text or a formatted field"
                        ),
                    )
                )
                continue
            value = part.formatted_value_value()
            spec = part.formatted_value_format_spec_static_text()
            if part.formatted_value_has_format_spec() and spec is None:
                parts.append(
                    _FormattedPart(
                        value=None,
                        conversion=part.formatted_value_conversion(),
                        spec="",
                        dynamic_reason=(
                            "formatted string literal has a dynamic format spec; "
                            "Python evaluates format specs at runtime"
                        ),
                    )
                )
                continue
            parts.append(
                _FormattedPart(
                    value=ctx.build_body(value, SugarRole.TERM),
                    conversion=part.formatted_value_conversion(),
                    spec=spec or "",
                )
            )
        return cls(parts=tuple(parts), blame=site.blame)

    def desugar(self, ctx) -> Outcome:
        pieces: list[str] = []
        symbolic_parts: list[Term] = []
        for part in self.parts:
            if isinstance(part, _LiteralPart):
                pieces.append(part.text)
                symbolic_parts.append(str_const(part.text))
                continue
            if part.dynamic_reason is not None:
                return _runtime_format_effect(self.blame, part.dynamic_reason)
            if part.value is None:
                return _runtime_format_effect(
                    self.blame,
                    "formatted string literal field has no reducible value",
                )
            value_outcome = part.value.reduce(ctx)
            if isinstance(value_outcome, Incomplete):
                return value_outcome
            value = complete_value(value_outcome, owner="JoinedStrSugar field")
            if part.conversion == ord("s"):
                conversion = perform_operation(
                    owner="JoinedStrSugar",
                    blame=self.blame,
                    receiver=value,
                    operation=StrCoercionOperation(
                        owner="JoinedStrSugar",
                        blame=self.blame,
                    ),
                    ctx=ctx,
                )
                if isinstance(conversion, Incomplete):
                    return conversion
                value = complete_value(conversion, owner="JoinedStrSugar !s")
            elif part.conversion in (ord("r"), ord("a")):
                return _runtime_format_effect(
                    self.blame,
                    "formatted string literal uses !r/!a conversion; repr/ascii "
                    "are runtime display hooks",
                )
            elif part.conversion != -1:
                return _runtime_format_effect(
                    self.blame,
                    f"formatted string literal uses unknown conversion {part.conversion}",
                )
            if isinstance(value, SymbolicValue):
                symbolic_parts.append(
                    ctor(
                        "py.format",
                        [value.term, str_const(part.spec), num(part.conversion)],
                    )
                )
                continue
            if not isinstance(value, (StringValue, TermValue)):
                return _runtime_format_effect(
                    self.blame,
                    f"formatted string literal field reduced to {type(value).__name__}; "
                    "__format__ for that floor is runtime/opaque here",
                )
            formatted = perform_operation(
                owner="JoinedStrSugar",
                blame=self.blame,
                receiver=value,
                operation=MethodCallOperation(
                    name="__format__",
                    arguments=(StringValue(part.spec),),
                    owner="JoinedStrSugar",
                    blame=self.blame,
                ),
                ctx=ctx,
            )
            if isinstance(formatted, Incomplete):
                return formatted
            formatted_value = complete_value(formatted, owner="JoinedStrSugar format")
            if not isinstance(formatted_value, StringValue):
                return _runtime_format_effect(
                    self.blame,
                    f"__format__ returned {type(formatted_value).__name__}, not StringValue",
                )
            pieces.append(formatted_value.value)
            symbolic_parts.append(str_const(formatted_value.value))
        if len(pieces) == len(symbolic_parts):
            return Complete(StringValue("".join(pieces)))
        return Complete(SymbolicValue(ctor("py.fstring", symbolic_parts)))


def _runtime_format_effect(blame: str, detail: str) -> Incomplete:
    return Incomplete(
        RuntimeEffect(
            "formatted string literal runtime boundary: "
            f"{detail}. Python f-strings evaluate formatted fields and call "
            "__format__ at runtime; keep this as a typed red effect until a "
            "narrower vendor-cited reduction owns the field shape. "
            f"blame={blame}"
        )
    )
