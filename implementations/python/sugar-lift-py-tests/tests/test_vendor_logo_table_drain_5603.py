"""#5603 slice: vendor logo tables deleted; language/structural paths remain.

Hard law: no logo string is construction evidence. Deleting a hard-coded
numpy/scipy coordinate and leaving corpus rows loud is correct.
"""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.recognition.callee_universe import (
    CalleeUniverseRecognition,
    recognize_authenticated_callee_identity,
    recognize_callee_universe,
    _IMPORTED_SUPPORT,
    _DTYPE_RESULT_SUPPORT,
)
from sugar_lift_py_tests.sugar.builtin_callee_universe_sugar import (
    BuiltinCalleeUniverseSugar,
)


def test_production_tables_carry_no_vendor_root_logos() -> None:
    """Dispatch tables must not embed numpy/scipy/pandas/… logo keys."""

    forbidden_roots = (
        "numpy.",
        "scipy.",
        "pandas.",
        "pydantic.",
        "requests.",
        "sklearn.",
        "sqlalchemy.",
        "pytest.",
    )
    for coordinate in (*_IMPORTED_SUPPORT, *_DTYPE_RESULT_SUPPORT):
        assert not any(
            coordinate == root.rstrip(".") or coordinate.startswith(root)
            for root in forbidden_roots
        ), coordinate
    for coordinate in BuiltinCalleeUniverseSugar.universe_coordinates:
        assert not any(
            coordinate == root.rstrip(".") or coordinate.startswith(root)
            for root in forbidden_roots
        ), coordinate


def test_deleted_numpy_can_cast_logo_does_not_authenticate() -> None:
    """Illegal logo branch DELETED — pure np.can_cast is not table-warranted."""

    source = (
        "import numpy as np\n"
        "\n"
        "def test_a(x, y):\n"
        "    assert np.can_cast(x, y)\n"
    )
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "can_cast"
    )
    site = SourceFragment.from_node(call, "can_cast.py", source=source)
    assert recognize_authenticated_callee_identity("numpy.can_cast") is None
    # No hard-coded logo table entry; identity alone does not type the support.
    assert recognize_callee_universe("call:numpy.can_cast", site=site) is None
    assert recognize_callee_universe("call:can_cast", site=site) is None


def test_lookalike_can_cast_without_import_stays_unowned() -> None:
    """Lying twin: lookalike without import provenance must not authenticate."""

    source = (
        "def test_a(np, x, y):\n"
        "    assert np.can_cast(x, y)\n"
    )
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "can_cast"
    )
    site = SourceFragment.from_node(call, "lookalike.py", source=source)
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert BuiltinCalleeUniverseSugar.owns(site) is False
    assert recognize_callee_universe(site=site) is None


def test_language_json_loads_still_authenticates() -> None:
    """(a) language/stdlib protocol remains table-warranted."""

    source = (
        "import json\n"
        "\n"
        "def test_a(payload):\n"
        "    assert json.loads(payload) == json.loads(payload)\n"
    )
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "loads"
    )
    site = SourceFragment.from_node(call, "json_loads.py", source=source)
    assert BuiltinCalleeUniverseSugar.owns(site) is True
    assert recognize_callee_universe("call:json.loads", site=site) is not None


def test_nested_functiondef_compare_dtypes_still_authenticates() -> None:
    """Structural nested FunctionDef provenance survives logo-table deletion."""

    source = (
        "def test_drop_metadata(dt, dt_m):\n"
        "    def _compare_dtypes(dt1, dt2):\n"
        "        return dt1\n"
        "    assert _compare_dtypes(dt, dt_m) is True\n"
    )
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_compare_dtypes"
    )
    site = SourceFragment.from_node(call, "compare.py", source=source)
    assert BuiltinCalleeUniverseSugar.owns(site) is True
