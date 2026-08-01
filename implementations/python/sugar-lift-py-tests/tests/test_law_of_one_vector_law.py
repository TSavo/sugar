"""Lying twins for the Law-of-One parent R vector (no curated site list)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).parents[1] / "scripts" / "law_of_one_vector_law.py"
_SPEC = importlib.util.spec_from_file_location("law_of_one_vector_law", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
LAW = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = LAW
_SPEC.loader.exec_module(LAW)


def _axes(source: str, path: str = "planted/prod.py") -> set[str]:
    return {f.axis for f in LAW.scan_python_source(source, path)}


def test_each_axis_has_a_structural_planted_twin() -> None:
    assert "FABRICATED-MEANING" in _axes(
        "def decide():\n    return MatchDecided(False)\n",
        "sugar_lift_py_tests/sugar/rogue.py",
    )
    assert "SPELLING-DISPATCH" in _axes(
        "def gate(name):\n    if name == 'pytest.raises':\n        return True\n",
        "sugar_lift_py_tests/gate.py",
    )
    assert "SWALLOWED-THROW" in _axes(
        (
            "def walk(xs):\n"
            "    for x in xs:\n"
            "        try:\n"
            "            work(x)\n"
            "        except Exception:\n"
            "            continue\n"
        ),
        "sugar_lift_py_tests/src/pkg/walk.py",
    )
    assert "NAMELESS-IDENTITY" in _axes(
        "def mint():\n    return RaiseEffect()\n",
        "sugar_lift_py_tests/src/pkg/mint.py",
    )
    assert "TWO-PRODUCERS" in _axes(
        "def decide():\n    return MatchDecided(True)\n",
        "sugar_lift_py_tests/sugar/other_door.py",
    )


def test_authenticated_matcher_may_mint_match_decided_false() -> None:
    findings = LAW.scan_python_source(
        "def m():\n    return MatchDecided(False)\n",
        "authenticated_exception_matching.py",
    )
    assert not any(f.axis == "FABRICATED-MEANING" for f in findings)
    assert not any(f.axis == "TWO-PRODUCERS" for f in findings)


def test_try_sugar_may_mint_match_decided_true_not_false() -> None:
    ok = LAW.scan_python_source(
        "def bare():\n    return MatchDecided(True)\n",
        "try_sugar.py",
    )
    assert not any(f.axis == "TWO-PRODUCERS" for f in ok)
    bad = LAW.scan_python_source(
        "def bare():\n    return MatchDecided(False)\n",
        "try_sugar.py",
    )
    assert any(f.axis == "FABRICATED-MEANING" for f in bad)


def test_report_prints_per_axis_r_and_replacement_plan() -> None:
    findings = LAW.scan_python_source(
        "def m():\n    return MatchDecided(False)\n",
        "rogue.py",
    )
    rendered = LAW.format_report(findings)
    assert "LAW-OF-ONE PARENT R VECTOR" in rendered
    assert "R_fabricated_meaning" in rendered
    assert "required fix:" in rendered
    assert "retire_when=" in rendered
    assert "rung=auditor" in rendered
    assert "stable_zero_requires" in rendered


def test_honest_discrimination_is_silent() -> None:
    source = """
def m(identity, expected):
    if expected in identity.mro:
        return MatchDecided(True)
    return MatchRetained("opaque")

def pin():
    return RaiseEffect(exception_type_coordinate=type_error, occurrence=site)

def loud():
    try:
        work()
    except ConstructionPanic:
        raise
"""
    assert LAW.scan_python_source(source, "authenticated_exception_matching.py") == []
