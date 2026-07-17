"""#4688 — ADJUDICATED async witness callable / termination contract.

Ruling (T, 2026-07-16), peer to equality #4371 / comparison #4568:

1. Call ≠ termination. ``async def F`` constructs a coroutine-producing
   callable. ``F(...)`` yields a coroutine value; it does not discharge the
   body result. Body result is available only after the coroutine is driven
   to termination.

2. Definition is deterministic. Minting AsyncFunctionDef as a definition
   universe is lawful construction (grammar ledger). Async-ness bites at
   the CALL / await / scheduler membrane, not at the def keyword.

3. Two awaitable regimes (mirror equality's warranted vs opaque):
   - Closed static dunder: concrete ObjectValue with ``__await__`` /
     ``__aenter__`` / ``__aexit__`` / ``__aiter__`` / ``__anext__`` may
     force_floor without claiming event-loop success.
   - Symbolic / runtime membrane: free awaitables and scheduler
     interleaving stay typed red
     (``AwaitRuntimeEffect`` / ``AsyncIterationRuntimeEffect`` /
     ``AsyncContextManagerRuntimeEffect``). MISSING never becomes success.

4. Lawful enrolled witness form NOW: typed red effect over a symbolic
   operand inside ``async def``. Truthful matches effect class+reason;
   lying mismatches. Forbidden: bare ``assert 1 == 1``, and
   ``assert F(x) == y`` treating an async call as body result.

5. Retirement path for sat/unsat proof-bearing callsites:
   - construct ``async_function_def_sugar`` (factory already names this)
   - body universe under formals is fine
   - call-site bridge must NOT auto-join body post to bare ``F(x)``
   - join only under explicit termination drive (``await F(x)`` / executor
     witness)
   - then closed-static terminated face admits truthful discharge / lying
     refute

These instruments pin the ruling. No panic is weakened.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.idd.sugar_witness_instruments import (
    evaluate_seed_witnesses,
    seeds_from_catalog_witnesses,
)
from sugar_lift_py_tests.sugar.async_for_sugar import AsyncForSugar
from sugar_lift_py_tests.sugar.async_with_sugar import AsyncWithSugar
from sugar_lift_py_tests.sugar.await_sugar import AwaitSugar
from sugar_lift_py_tests.sugar.witnesses import (
    SugarRedEffectWitnessPair,
    SugarWitnessPair,
)

_ASYNC_OWNER_TO_SEED = {
    "AwaitSugar": "await_runtime_effect",
    "AsyncForSugar": "async_for_runtime_effect",
    "AsyncWithSugar": "async_with_runtime_effect",
}

_ASYNC_OWNER_TO_EFFECT = {
    "AwaitSugar": "AwaitRuntimeEffect",
    "AsyncForSugar": "AsyncIterationRuntimeEffect",
    "AsyncWithSugar": "AsyncContextManagerRuntimeEffect",
}


def _async_catalog_seeds() -> tuple[SugarRedEffectWitnessPair, ...]:
    seeds = tuple(
        seed
        for seed in seeds_from_catalog_witnesses()
        if seed.owner_sugar in _ASYNC_OWNER_TO_SEED
    )
    return seeds  # type: ignore[return-value]


def test_async_owners_enroll_typed_red_not_forged_sat_unsat() -> None:
    """Ruling pin: enrolled form is typed red, never forged sat/unsat pairs."""
    by_owner = {
        cls.__name__: cls.witnesses()
        for cls in (AwaitSugar, AsyncForSugar, AsyncWithSugar)
    }
    for owner, witnesses in by_owner.items():
        assert isinstance(witnesses, SugarRedEffectWitnessPair), (
            f"{owner} must enroll typed-red effect witness under #4688 "
            f"(call≠termination); observed {type(witnesses).__name__}"
        )
        assert witnesses.name == _ASYNC_OWNER_TO_SEED[owner]
        assert (
            witnesses.truthful.expectation.effect_class == _ASYNC_OWNER_TO_EFFECT[owner]
        )
        assert "async def" in witnesses.truthful.source
        # Forbidden forge: bare unrelated assert as the discrimination face.
        assert "assert 1 == 1" not in witnesses.truthful.source
        assert "assert 1 == 2" not in witnesses.lying.source


def test_async_witnesses_refuse_sat_unsat_call_as_body_result() -> None:
    """Ruling pin: async call is not body-result discrimination."""
    for cls in (AwaitSugar, AsyncForSugar, AsyncWithSugar):
        witnesses = cls.witnesses()
        assert not isinstance(witnesses, SugarWitnessPair)
        # No A(literal) == face that would forge termination of an async def.
        assert "assert A(" not in witnesses.truthful.source
        assert "assert A(" not in witnesses.lying.source


def test_async_typed_red_seeds_discriminate_and_select_owner(tmp_path: Path) -> None:
    """Instrument: truthful matches effect; lying mismatches; owner fires."""
    seeds = _async_catalog_seeds()
    assert {seed.name for seed in seeds} == set(_ASYNC_OWNER_TO_SEED.values())
    assert len(seeds) == 3

    report = evaluate_seed_witnesses(seeds, tmp_path / "async-adjudication")

    assert report.is_zero
    assert report.triple_failures == ()
    assert report.non_circularity_failures == ()
    for seed in seeds:
        assert seed.owner_sugar in {
            "AwaitSugar",
            "AsyncForSugar",
            "AsyncWithSugar",
        }


def test_forged_async_sat_unsat_pair_is_not_the_catalog_form() -> None:
    """Regression: the pre-adjudication bare-assert forge must stay dead."""
    forbidden_names = {
        "async_for_dunder",
        "async_with_dunder",
        "await_dunder_return",
    }
    live_names = {seed.name for seed in seeds_from_catalog_witnesses()}
    assert forbidden_names.isdisjoint(live_names), (
        "forged async sat/unsat dunder seeds returned; #4688 requires typed "
        f"red. live offenders={sorted(forbidden_names & live_names)}"
    )


def test_async_function_def_remains_loud_named_gap_at_production_mint(
    tmp_path: Path,
) -> None:
    """Production residual: AsyncFunctionDef has no sugar yet (retirement path).

    The factory panic names the replacement architecture. This pin ensures we
    did not silence the gap with an unsound sync-shaped callable.
    """
    from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
    from sugar_lift_py_tests.factory.build import build_node
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment
    from sugar_lift_py_tests.claim import SugarRole

    module = SourceFragment.from_source(
        "async def A(z):\n    return await z\n",
        "async_def_gap.py",
    )
    async_def = next(
        fragment
        for fragment in module.walk()
        if fragment.observed == "AsyncFunctionDef"
    )
    with pytest.raises(FactoryPanic) as exc:
        build_node(async_def, filename="async_def_gap.py", role=SugarRole.STATEMENT)
    message = str(exc.value)
    assert "AsyncFunctionDef" in message
    assert "async_function_def" in message or "write more Sugar" in message
