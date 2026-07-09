"""groupby().sum() body dig — DataFrame result surface with value equality.

Closes the weak body-dig row from the vendor-op coverage map (#3920):

  chain groupby().sum | body dig was weak (is not None) | identity refused

The correct surface is opaque-body-dig grounding on a *value equality*
(`assert A() == …`), not identity (`is not None`):

  def A():
      return df.groupby("x").sum()
  def test_a():
      assert A() == A()   # or any value-equality swear about A()

Universe post must carry the nested coordinate
`call:sum(call:groupby(call:pandas.DataFrame(...), …))` with no fabricated
DataFrame companion. Solo truthful/lying single-assert stay sat (opaque);
discrimination is dual-assert witness execution, not a solver-only fold.
"""

from __future__ import annotations

import re
from pathlib import Path

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_GROUPBY_BODY_VALUE_EQ = (
    "import pandas as pd\n"
    "\n"
    "def A():\n"
    '    return pd.DataFrame({"x": [1, 1, 2], "y": [10, 20, 30]}).groupby("x").sum()\n'
    "\n"
    "def test_a():\n"
    "    assert A() == A()\n"
)

_GROUPBY_BODY_SHAPE = (
    "import pandas as pd\n"
    "\n"
    "def A():\n"
    '    return pd.DataFrame({"x": [1, 1, 2], "y": [10, 20, 30]})'
    '.groupby("x").sum().shape\n'
    "\n"
    "def test_a():\n"
    "    assert A() == (2, 1)\n"
)

_GROUPBY_BODY_SHAPE_LIE = (
    "import pandas as pd\n"
    "\n"
    "def A():\n"
    '    return pd.DataFrame({"x": [1, 1, 2], "y": [10, 20, 30]})'
    '.groupby("x").sum().shape\n'
    "\n"
    "def test_a():\n"
    "    assert A() == (9, 9)\n"
)

_GROUPBY_IDENTITY = (
    "import pandas as pd\n"
    "\n"
    "def A():\n"
    '    return pd.DataFrame({"x": [1, 1, 2], "y": [10, 20, 30]}).groupby("x").sum()\n'
    "\n"
    "def test_a():\n"
    "    assert A() is not None\n"
)

_NESTED = ("call:pandas.DataFrame", "call:groupby", "call:sum")


def _coords(report) -> set[str]:
    return set(re.findall(r"call:[A-Za-z_][A-Za-z0-9_.]*", repr(report.payload.ir)))


def _callable_post_blob(report) -> str:
    row = next(
        r for r in report.payload.ir if (r.name or "").endswith("::callable")
    )
    return repr(row.post)


def _dig_refuses(report) -> list[str]:
    return [
        d.get("reason", "")
        for d in (report.payload.diagnostics or [])
        if isinstance(d, dict)
        and d.get("kind") == "dig-boundary"
        and "function universe body walker refused" in (d.get("reason") or "")
    ]


def test_groupby_sum_body_dig_value_eq_emits_nested_coordinate() -> None:
    """Value-equality surface digs A and mints nested call:sum(call:groupby(...))."""
    report = build_literal_call_report(
        source=_GROUPBY_BODY_VALUE_EQ,
        filename="t.py",
        memento_file="t.py",
    )
    assert report is not None
    names = [r.name for r in report.payload.ir]
    assert any((n or "").endswith("::callable") for n in names), names
    coords = _coords(report)
    assert set(_NESTED) <= coords, coords
    post = _callable_post_blob(report)
    for token in _NESTED:
        assert token in post, post
    assert not _dig_refuses(report)


def test_groupby_sum_body_dig_shape_projection_nested_coordinate() -> None:
    """Chained .shape on groupby().sum() body dig keeps the full nest + call:shape."""
    report = build_literal_call_report(
        source=_GROUPBY_BODY_SHAPE,
        filename="t.py",
        memento_file="t.py",
    )
    assert report is not None
    assert any((r.name or "").endswith("::callable") for r in report.payload.ir)
    coords = _coords(report)
    assert {"call:shape", *_NESTED} <= coords, coords
    assert not _dig_refuses(report)


def test_groupby_sum_body_dig_value_eq_truthful_sat_no_refuse(
    tmp_path: Path,
) -> None:
    """Opaque DF result: value-equality swear + nested universe → sat, no refuse.

    No fabricated DataFrame companion. Solo sat is the correct opaque receipt.
    """
    result = run_source_through_real_solver(tmp_path / "true", _GROUPBY_BODY_VALUE_EQ)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "sat", (result.verdict, statuses)
    assert "refused" not in statuses
    blob = repr(result.lift_doc.get("ir", []))
    for token in _NESTED:
        assert token in blob, blob


def test_groupby_sum_body_dig_shape_truth_and_lie_both_sat(
    tmp_path: Path,
) -> None:
    """Single-assert shape about opaque groupby chain: truthful sat, lie sat.

    Opaque discrimination requires dual-assert (witness execution), not a
    fabricated shape companion on the body. Pins no-refuse for both RHS.
    """
    truth = run_source_through_real_solver(tmp_path / "shape-t", _GROUPBY_BODY_SHAPE)
    lie = run_source_through_real_solver(tmp_path / "shape-l", _GROUPBY_BODY_SHAPE_LIE)
    for label, result in (("truth", truth), ("lie", lie)):
        statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
        assert result.verdict == "sat", (label, result.verdict, statuses)
        assert "refused" not in statuses, (label, statuses)
        blob = repr(result.lift_doc.get("ir", []))
        assert "call:groupby" in blob and "call:sum" in blob, (label, blob)


def test_groupby_sum_identity_is_not_none_does_not_dig_body() -> None:
    """Contrast: identity surface does not dig A — no nested groupby coordinate.

    Documented residual: `assert A() is not None` is not the value-equality
    door. Body dig for groupby lives on `assert A() == …`.
    """
    report = build_literal_call_report(
        source=_GROUPBY_IDENTITY,
        filename="t.py",
        memento_file="t.py",
    )
    assert report is not None
    coords = _coords(report)
    assert "call:groupby" not in coords, coords
    assert not any((r.name or "").endswith("::callable") for r in report.payload.ir)
