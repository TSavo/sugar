from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Verdict = Literal["sat", "unsat"]


@dataclass(frozen=True)
class WitnessSource:
    source: str
    expected: Verdict


@dataclass(frozen=True)
class SugarWitnessPair:
    """One production witness pair for a verdict-bearing sugar."""

    name: str
    owner_sugar: str
    family: str
    truthful: WitnessSource
    lying: WitnessSource


@dataclass(frozen=True)
class TypedRedEffectExpectation:
    effect_class: str
    reason_needle: str
    blame_needle: str


@dataclass(frozen=True)
class EffectWitnessSource:
    source: str
    expectation: TypedRedEffectExpectation
    expected_match: bool
    function_name: str = "A"


@dataclass(frozen=True)
class SugarRedEffectWitnessPair:
    """One production witness pair for a lawful typed-red sugar."""

    name: str
    owner_sugar: str
    family: str
    truthful: EffectWitnessSource
    lying: EffectWitnessSource


@dataclass(frozen=True)
class NotVerdictBearing:
    """A non-FOL opt-out must be justified by a marked floor type."""

    sugar_name: str
    floor_name: str
    reason: str


SugarWitnesses = (
    SugarWitnessPair
    | SugarRedEffectWitnessPair
    | tuple[SugarWitnessPair, ...]
    | NotVerdictBearing
    | tuple[SugarWitnessPair | SugarRedEffectWitnessPair | NotVerdictBearing, ...]
)


def _call_pair(
    *,
    name: str,
    owner_sugar: str,
    truthful: str,
    lying: str,
    family: str = "literal-call",
) -> SugarWitnessPair:
    return SugarWitnessPair(
        name=name,
        owner_sugar=owner_sugar,
        family=family,
        truthful=WitnessSource(source=truthful, expected="sat"),
        lying=WitnessSource(source=lying, expected="unsat"),
    )

def _call_return_pair(
    *,
    name: str,
    owner_sugar: str,
    body: str,
    truthful: str,
    lying: str,
    prefix: str = "",
) -> SugarWitnessPair:
    base = prefix + f"def A(z):\n    return {body}\n\n"
    return _call_pair(
        name=name,
        owner_sugar=owner_sugar,
        truthful=base + f"def test_a():\n    assert A(5) == {truthful}\n",
        lying=base + f"def test_a():\n    assert A(5) == {lying}\n",
        family="literal-call",
    )

def _boolop_wrapped_pair(
    *,
    name: str,
    owner_sugar: str,
    truthful: str,
    lying: str,
    prefix: str = "",
) -> SugarWitnessPair:
    return _call_pair(
        name=name,
        owner_sugar=owner_sugar,
        truthful=prefix + f"def test_a():\n    assert {truthful}\n",
        lying=prefix + f"def test_a():\n    assert {lying}\n",
        family="assertion",
    )

def inert_statement_return_witness(
    *,
    name: str,
    owner_sugar: str,
    statement: str,
    prefix: str = "",
) -> SugarWitnessPair:
    body = "".join(f"    {line}\n" for line in statement.splitlines())
    source = prefix + f"def A(z):\n{body}    return z\n\n"
    return _call_pair(
        name=name,
        owner_sugar=owner_sugar,
        truthful=source + "def test_a():\n    assert A(1) == 1\n",
        lying=source + "def test_a():\n    assert A(1) == 2\n",
    )

def typed_red_effect_witness(
    *,
    name: str,
    owner_sugar: str,
    source: str,
    effect_class: str,
    reason_needle: str,
    blame_needle: str,
    wrong_reason_needle: str,
) -> SugarRedEffectWitnessPair:
    return SugarRedEffectWitnessPair(
        name=name,
        owner_sugar=owner_sugar,
        family="typed-red-effect",
        truthful=EffectWitnessSource(
            source=source,
            expectation=TypedRedEffectExpectation(
                effect_class=effect_class,
                reason_needle=reason_needle,
                blame_needle=blame_needle,
            ),
            expected_match=True,
        ),
        lying=EffectWitnessSource(
            source=source,
            expectation=TypedRedEffectExpectation(
                effect_class=effect_class,
                reason_needle=wrong_reason_needle,
                blame_needle=blame_needle,
            ),
            expected_match=False,
        ),
    )

def ord_byte_return_witness(*, owner_sugar: str) -> SugarWitnessPair:
    source = "def A(s):\n" "    return ord(s[0])\n" "\n"
    return _call_pair(
        name="ord_byte_return",
        owner_sugar=owner_sugar,
        truthful=source + "def test_a():\n    assert A('x') == 120\n",
        lying=source + "def test_a():\n    assert A('x') == 121\n",
    )

def collection_len_return_witness(
    *,
    name: str,
    owner_sugar: str,
    expression: str,
    truthful: int,
    lying: int,
) -> SugarWitnessPair:
    source = f"def A():\n    return len({expression})\n\n"
    return _call_pair(
        name=name,
        owner_sugar=owner_sugar,
        truthful=source + f"def test_a():\n    assert A() == {truthful}\n",
        lying=source + f"def test_a():\n    assert A() == {lying}\n",
    )
