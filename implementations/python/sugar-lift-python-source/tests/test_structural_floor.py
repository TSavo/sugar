from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
PKG_SRC = ROOT / "implementations/python/sugar-lift-python-source/src"
if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))

from sugar_lift_python_source.value_pins import (
    VALUE_PIN_BOUNDARY_KIND,
    _unaccounted_grammar,
    scan_module_value_pins,
)


def _scan(source: str):
    return scan_module_value_pins(ast.parse(source))


def _refusals(scan):
    return [r for r in scan.boundaries if r["kind"] == VALUE_PIN_BOUNDARY_KIND]


# --- the floor holds on this interpreter, by exhaustion not by oath ---


def test_grammar_accounting_is_total():
    assert _unaccounted_grammar() == {}


def test_floor_detects_grammar_growth(monkeypatch):
    # Simulate a future Python adding a statement kind: the accounting must
    # SEE it as a hole, not generic_visit past it. (At real import time this
    # raises; here we probe the detector directly.)
    class FutureStmt(ast.stmt):
        pass

    monkeypatch.setattr(ast, "FutureStmt", FutureStmt, raising=False)
    holes = _unaccounted_grammar()
    assert holes.get("stmt") == ["FutureStmt"]


def test_floor_detects_pattern_growth(monkeypatch):
    class FuturePattern(ast.pattern):
        pass

    monkeypatch.setattr(ast, "FuturePattern", FuturePattern, raising=False)
    holes = _unaccounted_grammar()
    assert holes.get("pattern") == ["FuturePattern"]


# --- the two holes the floor caught while being built ---


@pytest.mark.skipif(not hasattr(ast, "TryStar"), reason="needs except* (3.11+)")
def test_except_star_as_rebinding_refuses_pin():
    scan = _scan(
        "X = 1\n" "try:\n" "    pass\n" "except* ValueError as X:\n" "    pass\n"
    )
    assert "X" not in scan.pins
    assert _refusals(scan) and "except-as" in _refusals(scan)[0]["reason"]


@pytest.mark.skipif(not hasattr(ast, "TypeAlias"), reason="needs type aliases (3.12+)")
def test_type_alias_shadow_refuses_pin():
    scan = _scan("X = 1\ntype X = int\n")
    assert "X" not in scan.pins
    assert _refusals(scan) and "type-alias" in _refusals(scan)[0]["reason"]


def test_totality_still_holds_with_new_kinds():
    scan = _scan("X = 1\ntype X = int\nY = 2\n")
    assert scan.totality_holds()
    assert "Y" in scan.pins
