"""Vendor-op coordinate coverage map (pandas/numpy wall surface).

Pins what the coordinate frontier covers after the #3905–#3918 stack:

- Direct dual-assert discrimination (shared euf key → lie refutes) for
  aggregation methods and chained numpy ops.
- Body dig mints nested call: coordinates without refuse.
- Pure-opaque single-assert body dig stays sat/sat (no fabricated value);
  discrimination for opaque vendor ops is dual-assert witness execution.

Coverage snapshot (coords = call:<op> present in IR):

| surface | direct coords | body dig coords | dual-assert unsat |
|---------|---------------|-----------------|-------------------|
| Series.mean/max/min/sum/count/std | yes | yes | mean/max/min/sum/count yes |
| Series.head/tail/astype | yes | partial | — |
| DataFrame.shape/empty | yes | yes (shape) | shape dual: unsat (tuple injectivity) |
| DataFrame.dtypes/columns/index/values | yes | columns via list() | — |
| chain dropna().shape | yes | yes | shape dual unsat |
| chain reshape().sum | yes | yes | yes |
| chain groupby().sum | yes (direct) | yes formal+zero-arg (Batch A) | via len(...) dual |
| chain dropna().mean | yes | yes formal body dig | yes dual |

Body dig for groupby().sum() is the value-equality surface
(`assert A() == A()` / shape projection), not `is not None` — see
test_groupby_body_dig.py and test_vendor_chain_coordinate_batch_a.py.

Tuple RHS dual-assert is structural unsat via ground data-ctor values
(see test_tuple_dual_assert_injectivity.py / sugar-verifier consistency).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _coords(report) -> set[str]:
    import re

    return set(re.findall(r"call:[A-Za-z_][A-Za-z0-9_.]*", repr(report.payload.ir)))


def _has_callable(report) -> bool:
    return any((r.name or "").endswith("::callable") for r in report.payload.ir)


# ---------------------------------------------------------------------------
# Dual-assert discrimination (witness execution for opaque vendor coords)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "truth", "lie", "coord"),
    [
        ("mean", "2.0", "0.0", "call:mean"),
        ("max", "3.0", "0.0", "call:max"),
        ("min", "1.0", "9.0", "call:min"),
        ("sum", "6.0", "0.0", "call:sum"),
        ("count", "3", "0", "call:count"),
    ],
)
def test_series_agg_dual_assert_refutes_lie(
    tmp_path: Path, method: str, truth: str, lie: str, coord: str
) -> None:
    src = (
        "import pandas as pd\n"
        "def t_true():\n"
        f"    assert pd.Series([1.0, 2.0, 3.0]).{method}() == {truth}\n"
        "def t_lie():\n"
        f"    assert pd.Series([1.0, 2.0, 3.0]).{method}() == {lie}\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert coord in _coords(report)
    assert "call:pandas.Series" in _coords(report)

    result = run_source_through_real_solver(tmp_path / method, src)
    assert result.verdict == "unsat", (
        method,
        result.verdict,
        [row.get("status") for row in result.prove_doc.get("rows", [])],
    )


def test_numpy_reshape_sum_chain_dual_assert_refutes_lie(tmp_path: Path) -> None:
    src = (
        "import numpy as np\n"
        "def t_true():\n"
        "    assert np.array([1, 2, 3, 4]).reshape(2, 2).sum() == 10\n"
        "def t_lie():\n"
        "    assert np.array([1, 2, 3, 4]).reshape(2, 2).sum() == 0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    coords = _coords(report)
    assert "call:sum" in coords
    assert "call:reshape" in coords
    assert "call:numpy.array" in coords

    result = run_source_through_real_solver(tmp_path / "reshape-sum", src)
    assert result.verdict == "unsat"


def test_dataframe_dropna_shape_chain_lifts_nested_coordinates() -> None:
    src = (
        "import pandas as pd\n"
        "def t_true():\n"
        "    assert pd.DataFrame({\"a\": [1, None]}).dropna().shape == (1, 1)\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    coords = _coords(report)
    assert "call:shape" in coords
    assert "call:dropna" in coords
    assert "call:pandas.DataFrame" in coords


# ---------------------------------------------------------------------------
# Body dig: nested coordinates present, no refuse
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "coord"),
    [
        ("mean", "call:mean"),
        ("max", "call:max"),
        ("min", "call:min"),
        ("sum", "call:sum"),
        ("count", "call:count"),
    ],
)
def test_series_agg_body_dig_emits_nested_coordinates(method: str, coord: str) -> None:
    src = (
        "import pandas as pd\n"
        "def A():\n"
        f"    return pd.Series([1.0, 2.0, 3.0]).{method}()\n"
        "def test_a():\n"
        "    assert A() == 0.0\n"  # pure-opaque: any RHS sat; pins no-refuse
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert _has_callable(report), [r.name for r in report.payload.ir]
    coords = _coords(report)
    assert coord in coords
    assert "call:pandas.Series" in coords
    dig = [
        d
        for d in (report.payload.diagnostics or [])
        if isinstance(d, dict) and d.get("kind") == "dig-boundary"
    ]
    assert not any(
        "function universe body walker refused" in (d.get("reason") or "")
        for d in dig
    ), dig


def test_reshape_sum_body_dig_emits_chain_coordinates() -> None:
    src = (
        "import numpy as np\n"
        "def A():\n"
        "    return np.array([1, 2, 3, 4]).reshape(2, 2).sum()\n"
        "def test_a():\n"
        "    assert A() == 0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert _has_callable(report)
    coords = _coords(report)
    assert {"call:sum", "call:reshape", "call:numpy.array"} <= coords


def test_dropna_shape_body_dig_emits_chain_coordinates() -> None:
    src = (
        "import pandas as pd\n"
        "def A():\n"
        "    return pd.DataFrame({\"a\": [1, None]}).dropna().shape\n"
        "def test_a():\n"
        "    assert A() == (0, 0)\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert _has_callable(report)
    coords = _coords(report)
    assert {"call:shape", "call:dropna", "call:pandas.DataFrame"} <= coords


def test_df_head_len_body_dig_nested_coordinates() -> None:
    src = (
        "import pandas as pd\n"
        "def A():\n"
        "    return len(pd.DataFrame({\"a\": [1, 2, 3]}).head(2))\n"
        "def test_a():\n"
        "    assert A() == 0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert _has_callable(report)
    coords = _coords(report)
    assert {"call:len", "call:head", "call:pandas.DataFrame"} <= coords


# ---------------------------------------------------------------------------
# Body dig pure-opaque: no refuse (witness path)
# ---------------------------------------------------------------------------


def test_series_mean_body_dig_truthful_and_lying_no_refuse(tmp_path: Path) -> None:
    """Opaque vendor mean: any single RHS is sat; both must not refuse."""
    true_src = (
        "import pandas as pd\n"
        "def A():\n"
        "    return pd.Series([1.0, 2.0, 3.0]).mean()\n"
        "def test_a():\n"
        "    assert A() == 2.0\n"
    )
    lie_src = (
        "import pandas as pd\n"
        "def A():\n"
        "    return pd.Series([1.0, 2.0, 3.0]).mean()\n"
        "def test_a():\n"
        "    assert A() == 0.0\n"
    )
    t = run_source_through_real_solver(tmp_path / "mean-t", true_src)
    l = run_source_through_real_solver(tmp_path / "mean-l", lie_src)
    assert t.verdict == "sat"
    assert l.verdict == "sat"
    assert "refused" not in [r.get("status") for r in t.prove_doc.get("rows", [])]
    assert "refused" not in [r.get("status") for r in l.prove_doc.get("rows", [])]
    assert "call:mean" in repr(t.lift_doc.get("ir", []))


def test_list_columns_body_dig_emits_call_list() -> None:
    """list(df.columns) body dig — was call-builtin:list refuse."""
    src = (
        "import pandas as pd\n"
        "def A():\n"
        "    return list(pd.DataFrame({\"a\": [1], \"b\": [2]}).columns)\n"
        "def test_a():\n"
        "    assert A() == [\"a\", \"b\"]\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert _has_callable(report), [r.name for r in report.payload.ir]
    coords = _coords(report)
    assert "call:list" in coords, coords
    assert "call:columns" in coords or "call:pandas.DataFrame" in coords, coords
