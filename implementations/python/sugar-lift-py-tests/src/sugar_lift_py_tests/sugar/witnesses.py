from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Verdict = Literal["sat", "unsat", "unwitnessed"]


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
class SugarUnwitnessedPair:
    """A lawful epistemic-red pair: neither arm may be guessed."""

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
    | SugarUnwitnessedPair
    | SugarRedEffectWitnessPair
    | tuple[SugarWitnessPair, ...]
    | NotVerdictBearing
    | tuple[
        SugarWitnessPair
        | SugarUnwitnessedPair
        | SugarRedEffectWitnessPair
        | NotVerdictBearing,
        ...,
    ]
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


def _test_source(prefix: str, statements: str, claim: str) -> str:
    """``test_a`` running ``statements`` and asserting ``claim`` in its own
    body.  The sugar a pair witnesses is stated here, over a local or a
    literal, never through a same-file helper the test calls: a same-file
    call is a coordinate joined at prove (#7757), so a pair built on a
    helper call would witness the join instead of its sugar."""
    body = "".join(f"    {line}\n" for line in statements.splitlines())
    return prefix + "def test_a():\n" + body + f"    assert {claim}\n"


def _assertion_pair(
    *,
    name: str,
    owner_sugar: str,
    statements: str,
    truthful: str,
    lying: str,
    prefix: str = "",
) -> SugarWitnessPair:
    """A pair whose test runs ``statements`` and asserts ``truthful`` /
    ``lying`` (``_test_source``)."""
    return _call_pair(
        name=name,
        owner_sugar=owner_sugar,
        truthful=_test_source(prefix, statements, truthful),
        lying=_test_source(prefix, statements, lying),
        family="assertion",
    )


def _expression_pair(
    *,
    name: str,
    owner_sugar: str,
    body: str,
    truthful: str,
    lying: str,
    prefix: str = "",
) -> SugarWitnessPair:
    """``body`` asserted equal to ``truthful`` / ``lying`` in the test, over
    the local ``z = 5``."""
    return _assertion_pair(
        name=name,
        owner_sugar=owner_sugar,
        statements="z = 5",
        truthful=f"({body}) == {truthful}",
        lying=f"({body}) == {lying}",
        prefix=prefix,
    )


def _unwitnessed_expression_pair(
    *,
    name: str,
    owner_sugar: str,
    body: str,
    truthful: str,
    lying: str,
    prefix: str = "",
) -> SugarUnwitnessedPair:
    return SugarUnwitnessedPair(
        name=name,
        owner_sugar=owner_sugar,
        family="opaque-equality-unwitnessed",
        truthful=WitnessSource(
            source=_test_source(prefix, "z = 5", f"({body}) == {truthful}"),
            expected="unwitnessed",
        ),
        lying=WitnessSource(
            source=_test_source(prefix, "z = 5", f"({body}) == {lying}"),
            expected="unwitnessed",
        ),
    )


def _boolop_wrapped_pair(
    *,
    name: str,
    owner_sugar: str,
    truthful: str,
    lying: str,
    prefix: str = "",
) -> SugarWitnessPair:
    return _assertion_pair(
        name=name,
        owner_sugar=owner_sugar,
        statements="",
        truthful=truthful,
        lying=lying,
        prefix=prefix,
    )


def inert_statement_witness(
    *,
    name: str,
    owner_sugar: str,
    statement: str,
    prefix: str = "",
) -> SugarWitnessPair:
    """``statement`` first in the test (where a helper's body held it),
    then ``z = 1``: the inert statement leaves ``z == 1`` standing."""
    return _assertion_pair(
        name=name,
        owner_sugar=owner_sugar,
        statements=statement + "\nz = 1",
        truthful="z == 1",
        lying="z == 2",
        prefix=prefix,
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


def ord_byte_witness(*, owner_sugar: str) -> SugarWitnessPair:
    return _assertion_pair(
        name="ord_byte_return",
        owner_sugar=owner_sugar,
        statements="s = 'x'",
        truthful="ord(s[0]) == 120",
        lying="ord(s[0]) == 121",
    )


def collection_len_witness(
    *,
    name: str,
    owner_sugar: str,
    expression: str,
    truthful: int,
    lying: int,
) -> SugarWitnessPair:
    return _assertion_pair(
        name=name,
        owner_sugar=owner_sugar,
        statements="",
        truthful=f"len({expression}) == {truthful}",
        lying=f"len({expression}) == {lying}",
    )
