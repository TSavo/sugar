"""Every sugar's witness pair, run through the real solver (#7757, #8680).

A sugar's ``witnesses()`` names a truthful source and a lying one: the
truthful half's claim holds in Python and must read ``sat``, the lying
half's is false and must read ``unsat``.  Until this file nothing ran them:
``factory_ownership_law`` checks only that ``witnesses()`` is present, and
several pairs were false at their own value (#8680).  A witness nothing
measures is decoration.

The pairs are found the way the ownership census finds them: every class of
the ``sugar_lift_py_tests.sugar`` package that declares ``witnesses()``.
Each ``SugarWitnessPair`` it returns is one case; an identical pair two
classes share (``FormalRefSugar`` answers ``NameSugar``'s) runs once.  The
typed-red effect pairs and the not-verdict-bearing opt-outs claim no
``sat``/``unsat`` verdict, so they are not run here.

Each half goes through ``run_source_through_real_solver`` (real ``sugar
mint`` + ``sugar prove --z3``) and is read on the claims its test function
states (``witness_harness.claim_verdict``): a pair built on a same-file
callee (``CallSiteSugar``, ``ParamSugar``...) leaves members that callee's
own proof owes above the test function, and those are set aside, as the
method-call twins read theirs.

A pair whose claim honestly cannot be decided yet is listed in
``_OPEN_TODAY`` with the reason, and marked ``xfail(strict=True)``: it is
never weakened to accept a lying ``sat``, and the day it decides, the strict
mark fails and the entry is deleted.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

import pytest

import sugar_lift_py_tests.sugar as sugar_package
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair
from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)


def _declaring_classes():
    """Every class of the sugar package that declares its own ``witnesses()``."""
    prefix = sugar_package.__name__ + "."
    for info in pkgutil.walk_packages(sugar_package.__path__, prefix):
        module = importlib.import_module(info.name)
        for _name, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ != module.__name__:
                continue
            declared = vars(cls).get("witnesses")
            if declared is None or getattr(declared, "__isabstractmethod__", False):
                continue
            yield cls


def _witness_pairs() -> tuple[SugarWitnessPair, ...]:
    pairs: dict[tuple[str, str, str, str], SugarWitnessPair] = {}
    for cls in _declaring_classes():
        declared = cls.witnesses()
        for witness in declared if isinstance(declared, tuple) else (declared,):
            if not isinstance(witness, SugarWitnessPair):
                continue
            key = (
                witness.owner_sugar,
                witness.name,
                witness.truthful.source,
                witness.lying.source,
            )
            pairs.setdefault(key, witness)
    return tuple(pairs[key] for key in sorted(pairs))


def _pair_id(pair: SugarWitnessPair) -> str:
    return f"{pair.owner_sugar}.{pair.name}"


# ``<owner_sugar>.<name>`` -> why the claim reads ``open`` today.
_OPEN_TODAY: dict[str, str] = {}

_PAIRS = _witness_pairs()


def _cases():
    for pair in _PAIRS:
        reason = _OPEN_TODAY.get(_pair_id(pair))
        marks = () if reason is None else (pytest.mark.xfail(strict=True, reason=reason),)
        yield pytest.param(pair, id=_pair_id(pair), marks=marks)


def _test_function_line(source: str) -> int:
    """The line of the source's one ``def test_``: every helper sits above it."""
    (line,) = (
        number
        for number, text in enumerate(source.splitlines(), start=1)
        if text.startswith("def test_")
    )
    return line


def test_every_open_entry_names_a_pair() -> None:
    """An ``_OPEN_TODAY`` entry for a pair that no longer exists is stale."""
    assert _PAIRS
    assert set(_OPEN_TODAY) <= {_pair_id(pair) for pair in _PAIRS}


@pytest.mark.parametrize("pair", tuple(_cases()))
def test_witness_pair_truthful_sat_lying_unsat(
    pair: SugarWitnessPair, tmp_path: Path
) -> None:
    verdicts = {}
    for role, half in (("truthful", pair.truthful), ("lying", pair.lying)):
        result = run_source_through_real_solver(tmp_path / role, half.source)
        verdicts[role] = claim_verdict(
            result.prove_doc, claims_from_line=_test_function_line(half.source)
        )
    print(_pair_id(pair), verdicts)
    assert verdicts == {"truthful": "sat", "lying": "unsat"}
