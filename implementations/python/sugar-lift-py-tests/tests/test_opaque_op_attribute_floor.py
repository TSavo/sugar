"""OpaqueOpCallsite.attribute_with — drain construction gap #1 (Part of #3809).

Lift-probe (before fix):

    x = pd.Series([1.0, 2.0, 3.0]).cumsum()
    assert x.shape[0] == 3

Temporal bind of the method result is OpaqueOpCallsite; AttributeSugar then
dispatched attribute_with → FactoryGap (observed=OpaqueOpCallsite,
requested=attribute_with). Direct ``Series(…).cumsum().shape`` already nested
via symbolic_term; body/statement path needed the floor.

Fix: OpaqueOpCallsite.attribute_with mints ``call:<attr>(self)`` with
computed=None (never fabricate). Discrimination: dual-assert witness EXECUTION.
"""

from __future__ import annotations

import re
from pathlib import Path

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _calls(report) -> set[str]:
    return set(re.findall(r"call:[A-Za-z_][A-Za-z0-9_.]*", repr(report.payload.ir)))


def test_temporal_opaque_method_attr_shape_lifts_nested_coordinates() -> None:
    """x = Series.cumsum(); x.shape — no FactoryGap; call:shape + call:cumsum."""
    src = (
        "import pandas as pd\n"
        "def t():\n"
        "    x = pd.Series([1.0, 2.0, 3.0]).cumsum()\n"
        "    assert x.shape == (3,)\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    coords = _calls(report)
    assert "call:cumsum" in coords, coords
    assert "call:shape" in coords, coords
    assert "call:pandas.Series" in coords, coords
    blob = repr(report.payload)
    assert "requested=attribute_with" not in blob
    assert "observed=OpaqueOpCallsite" not in blob or "attribute_with" not in blob


def test_temporal_opaque_dropna_shape_no_floor_gap() -> None:
    src = (
        "import pandas as pd\n"
        "def t():\n"
        "    x = pd.Series([1.0, None, 3.0]).dropna()\n"
        "    assert x.shape == (2,)\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    coords = _calls(report)
    assert "call:dropna" in coords, coords
    assert "call:shape" in coords, coords


def test_direct_chain_shape_still_nested() -> None:
    """Regression: direct chain without temporal bind stays nested."""
    src = (
        "import pandas as pd\n"
        "def t():\n"
        "    assert pd.Series([1.0, 2.0, 3.0]).cumsum().shape == (3,)\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    name = report.payload.ir[0].name or ""
    assert "call:shape" in name and "call:cumsum" in name, name


def test_temporal_shape_dual_assert_refutes_lie_via_witness(tmp_path: Path) -> None:
    """Dual-assert discrimination: shared euf / witness EXECUTION → unsat.

    Solo opaque shape euf is vacuous-refuse without a sibling (honest); the
    dual twin is the discrimination receipt.
    """
    src = (
        "import pandas as pd\n"
        "def t_true():\n"
        "    x = pd.Series([1.0, 2.0, 3.0]).cumsum()\n"
        "    assert x.shape == (3,)\n"
        "def t_lie():\n"
        "    x = pd.Series([1.0, 2.0, 3.0]).cumsum()\n"
        "    assert x.shape == (0,)\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert "call:shape" in _calls(report)
    assert "call:cumsum" in _calls(report)

    result = run_source_through_real_solver(tmp_path / "opaque-attr-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses