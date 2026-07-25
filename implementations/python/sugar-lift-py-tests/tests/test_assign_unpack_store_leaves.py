"""Assign flat unpack with Attribute/Subscript store leaves.

Historical factory mass (shape-split ledger): dual-subscript, multi-attribute,
and Name+store mixes against a display RHS. One temporal binding model: Name
leaves thread via substitute; store leaves are typed red effects — no second door.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.assign_sugar import (
    MultiAssignSugar,
    UnpackStoreAssignSugar,
)
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _function_sugar(tmp_path: Path, source: str):
    path = tmp_path / "assign_case.py"
    path.write_text(source, encoding="utf-8")
    return next(SourceFile(path_source(str(path))).functions()).sugar()


def test_dual_attribute_display_unpack_constructs(tmp_path: Path) -> None:
    sugar = _function_sugar(
        tmp_path,
        "def f(o, p, q):\n" "    o.x, o.y = p, q\n" "    return o\n",
    )
    # FunctionUniverseSugar wraps the body; walk for UnpackStoreAssignSugar.
    assert any(isinstance(stmt, UnpackStoreAssignSugar) for stmt in sugar.statements), [
        type(s).__name__ for s in sugar.statements
    ]
    out = sugar.desugar(None)
    assert isinstance(out, Complete)


def test_dual_subscript_display_unpack_constructs(tmp_path: Path) -> None:
    sugar = _function_sugar(
        tmp_path,
        "def f(a, b, p, q):\n" "    a[0], b[1] = p, q\n" "    return a\n",
    )
    assert any(isinstance(stmt, UnpackStoreAssignSugar) for stmt in sugar.statements)
    out = sugar.desugar(None)
    assert isinstance(out, Complete)


def test_name_plus_subscript_display_unpack_constructs(tmp_path: Path) -> None:
    sugar = _function_sugar(
        tmp_path,
        "def f(a, p, q):\n" "    x, a[0] = p, q\n" "    return x\n",
    )
    unpack = next(
        stmt for stmt in sugar.statements if isinstance(stmt, UnpackStoreAssignSugar)
    )
    assert unpack.bindings and unpack.bindings[0][0] == "x"
    assert len(unpack.stores) == 1
    out = sugar.desugar(None)
    assert isinstance(out, Complete)


def test_three_attribute_display_unpack_constructs(tmp_path: Path) -> None:
    sugar = _function_sugar(
        tmp_path,
        "def f(o, p, q, r):\n" "    o.x, o.y, o.z = p, q, r\n" "    return o\n",
    )
    assert any(isinstance(stmt, UnpackStoreAssignSugar) for stmt in sugar.statements)
    assert isinstance(sugar.desugar(None), Complete)


def test_name_only_display_unpack_stays_multi_assign(tmp_path: Path) -> None:
    sugar = _function_sugar(
        tmp_path,
        "def f(p, q):\n" "    a, b = p, q\n" "    return a + b\n",
    )
    assert any(isinstance(stmt, MultiAssignSugar) for stmt in sugar.statements)
    assert not any(
        isinstance(stmt, UnpackStoreAssignSugar) for stmt in sugar.statements
    )


def test_star_against_opaque_iterable_stays_loud(tmp_path: Path) -> None:
    """Non-display starred unpack remains a construction gap (#6078 territory)."""
    path = tmp_path / "star.py"
    path.write_text(
        "def f(xs):\n" "    a, *rest = xs\n" "    return a\n",
        encoding="utf-8",
    )
    fn = next(SourceFile(path_source(str(path))).functions())
    try:
        fn.sugar()
        raise AssertionError("expected SugarNotWritten for opaque star unpack")
    except SugarNotWritten as gap:
        assert "Assign" in gap.owner or "Assign" in str(gap)
