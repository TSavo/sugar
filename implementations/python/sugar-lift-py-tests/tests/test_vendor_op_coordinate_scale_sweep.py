"""Vendor-op coordinate coverage at real numpy/pandas scale (Part of #3809).

Seed probes (#3929–#3943) covered curated shapes. This instrument lifts a
*broad* matrix of real DataFrame/Series/ndarray methods, attributes, chains,
and numpy ufuncs — the shapes that show up in real libraries, not just the
hand-picked seeds — and fails loud on:

- dig / factory refuse (``call-method:`` / ``call-builtin:`` / body walker)
- ``py.attr`` on vendor attribute surfaces that should be ``call:<attr>``
- missing expected ``call:<op>`` coordinate for the exercised head
- dropped keywords (source has ``axis=`` / ``how=`` but IR has no ``kw:``)

Run on battleaxe (real installed numpy + pandas). Aggregate local is not the
gate for soundness seeds; this is a structural coordinate census.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

import pytest

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report

# ---------------------------------------------------------------------------
# Real-API matrix (broad, not seed-only)
# ---------------------------------------------------------------------------

# Series zero-arg methods that return a scalar / small object on a 3-float series.
_SERIES_ZERO_ARG = (
    "mean",
    "sum",
    "min",
    "max",
    "count",
    "std",
    "var",
    "median",
    "prod",
    "nunique",
    "any",
    "all",
    "isna",
    "notna",
    "isnull",
    "notnull",
    "abs",
    "round",
    "cumsum",
    "cumprod",
    "cummax",
    "cummin",
    "diff",
    "pct_change",
    "rank",
    "unique",
    "dropna",
    "head",
    "tail",
    "copy",
    "tolist",
    "to_list",
    "to_numpy",
    "to_frame",
    "reset_index",
    "sort_values",
    "sort_index",
    "value_counts",
    "describe",
    "transpose",
)

# DataFrame zero-arg / simple methods on a small frame.
_DF_ZERO_ARG = (
    "mean",
    "sum",
    "min",
    "max",
    "count",
    "std",
    "var",
    "median",
    "prod",
    "nunique",
    "any",
    "all",
    "isna",
    "notna",
    "isnull",
    "notnull",
    "abs",
    "round",
    "cumsum",
    "head",
    "tail",
    "copy",
    "dropna",
    "reset_index",
    "to_numpy",
    "values",  # treated as attr path separately if non-callable
    "transpose",
    "T",  # attr
    "describe",
    "keys",
)

# Attributes that must never be py.attr.
_SERIES_ATTRS = (
    "shape",
    "dtype",
    "dtypes",
    "index",
    "name",
    "values",
    "empty",
    "size",
    "ndim",
    "T",
    "hasnans",
    "is_unique",
    "nbytes",
)
_DF_ATTRS = (
    "shape",
    "dtypes",
    "columns",
    "index",
    "values",
    "empty",
    "size",
    "ndim",
    "T",
    "axes",
    "flags",
)

# Keyword / multi-arg real shapes.
_KWARG_SHAPES: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "series_sum_axis",
        "import pandas as pd\ndef t():\n    assert pd.Series([1.0, 2.0, 3.0]).sum(axis=0) is not None\n",
        frozenset({"call:sum", "kw:axis"}),
    ),
    (
        "series_mean_axis",
        "import pandas as pd\ndef t():\n    assert pd.Series([1.0, 2.0, 3.0]).mean(axis=0) is not None\n",
        frozenset({"call:mean", "kw:axis"}),
    ),
    (
        "df_sum_axis0",
        'import pandas as pd\ndef t():\n    assert pd.DataFrame({"a": [1.0, 2.0]}).sum(axis=0) is not None\n',
        frozenset({"call:sum", "kw:axis"}),
    ),
    (
        "df_dropna_how",
        'import pandas as pd\ndef t():\n    assert pd.DataFrame({"a": [1.0, None]}).dropna(how="any").shape[0] >= 0\n',
        frozenset({"call:dropna", "kw:how"}),
    ),
    (
        "df_fillna_value",
        'import pandas as pd\ndef t():\n    assert pd.DataFrame({"a": [1.0, None]}).fillna(0.0).shape == (2, 1)\n',
        frozenset({"call:fillna"}),
    ),
    (
        "df_astype",
        'import pandas as pd\ndef t():\n    assert pd.Series([1, 2, 3]).astype("float64").sum() == 6.0\n',
        frozenset({"call:astype", "call:sum"}),
    ),
    (
        "df_groupby_sum",
        'import pandas as pd\ndef t():\n    assert pd.DataFrame({"k": [1, 1, 2], "v": [10, 20, 30]}).groupby("k").sum().shape[0] == 2\n',
        frozenset({"call:groupby", "call:sum"}),
    ),
    (
        "df_groupby_as_index",
        'import pandas as pd\ndef t():\n    assert pd.DataFrame({"k": [1, 1, 2], "v": [10, 20, 30]}).groupby("k", as_index=False).sum().shape[0] == 2\n',
        frozenset({"call:groupby", "call:sum", "kw:as_index"}),
    ),
    (
        "df_merge",
        'import pandas as pd\ndef t():\n    L=pd.DataFrame({"k":[1],"a":[1]}); R=pd.DataFrame({"k":[1],"b":[2]}); assert L.merge(R).shape == (1, 3)\n',
        frozenset({"call:merge"}),
    ),
    (
        "df_join",
        'import pandas as pd\ndef t():\n    L=pd.DataFrame({"a":[1]}, index=[0]); R=pd.DataFrame({"b":[2]}, index=[0]); assert L.join(R).shape == (1, 2)\n',
        frozenset({"call:join"}),
    ),
    (
        "df_pivot_table",
        'import pandas as pd\ndef t():\n    df=pd.DataFrame({"a":[1,1,2],"b":[10,20,30],"c":["x","y","x"]}); assert df.pivot_table(values="b", index="a", columns="c", aggfunc="sum").shape[0] == 2\n',
        frozenset({"call:pivot_table", "kw:values", "kw:index", "kw:columns", "kw:aggfunc"}),
    ),
    (
        "df_sort_values",
        'import pandas as pd\ndef t():\n    assert pd.DataFrame({"a": [3, 1, 2]}).sort_values("a").shape == (3, 1)\n',
        frozenset({"call:sort_values"}),
    ),
    (
        "series_clip",
        "import pandas as pd\ndef t():\n    assert pd.Series([1.0, 5.0, 9.0]).clip(lower=2.0, upper=8.0).sum() > 0\n",
        frozenset({"call:clip", "kw:lower", "kw:upper"}),
    ),
    (
        "series_fillna",
        "import pandas as pd\ndef t():\n    assert pd.Series([1.0, None, 3.0]).fillna(0.0).sum() == 4.0\n",
        frozenset({"call:fillna"}),
    ),
    (
        "series_replace",
        "import pandas as pd\ndef t():\n    assert pd.Series([1, 2, 2]).replace(2, 9).sum() == 19\n",
        frozenset({"call:replace"}),
    ),
    (
        "df_rename",
        'import pandas as pd\ndef t():\n    assert list(pd.DataFrame({"a": [1]}).rename(columns={"a": "b"}).columns) == ["b"]\n',
        frozenset({"call:rename", "kw:columns"}),
    ),
    (
        "df_drop",
        'import pandas as pd\ndef t():\n    assert pd.DataFrame({"a": [1], "b": [2]}).drop(columns=["b"]).shape == (1, 1)\n',
        frozenset({"call:drop", "kw:columns"}),
    ),
    (
        "df_reindex",
        'import pandas as pd\ndef t():\n    assert pd.Series([10, 20], index=[0, 1]).reindex([0, 1, 2]).shape[0] == 3\n',
        frozenset({"call:reindex"}),
    ),
    (
        "series_where",
        "import pandas as pd\ndef t():\n    s=pd.Series([1.0, 2.0, 3.0]); assert s.where(s > 1.0, 0.0).sum() == 5.0\n",
        frozenset({"call:where"}),
    ),
    (
        "series_mask",
        "import pandas as pd\ndef t():\n    s=pd.Series([1.0, 2.0, 3.0]); assert s.mask(s > 2.0, 0.0).sum() == 3.0\n",
        frozenset({"call:mask"}),
    ),
)

# Chains (nested call:).
_CHAINS: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "dropna_mean",
        "import pandas as pd\ndef t():\n    assert pd.Series([1.0, None, 3.0]).dropna().mean() == 2.0\n",
        frozenset({"call:dropna", "call:mean"}),
    ),
    (
        "astype_sum",
        'import pandas as pd\ndef t():\n    assert pd.Series([1, 2, 3]).astype("float64").sum() == 6.0\n',
        frozenset({"call:astype", "call:sum"}),
    ),
    (
        "groupby_sum_shape",
        'import pandas as pd\ndef t():\n    assert pd.DataFrame({"k": [1, 1, 2], "v": [10, 20, 30]}).groupby("k").sum().shape == (2, 1)\n',
        frozenset({"call:groupby", "call:sum", "call:shape"}),
    ),
    (
        "head_sum",
        "import pandas as pd\ndef t():\n    assert pd.Series([1.0, 2.0, 3.0, 4.0]).head(2).sum() == 3.0\n",
        frozenset({"call:head", "call:sum"}),
    ),
    (
        "T_shape",
        'import pandas as pd\ndef t():\n    assert pd.DataFrame({"a": [1, 2, 3]}).T.shape == (1, 3)\n',
        frozenset({"call:T", "call:shape"}),
    ),
    (
        "values_shape",
        'import pandas as pd\ndef t():\n    assert pd.DataFrame({"a": [1, 2]}).values.shape == (2, 1)\n',
        frozenset({"call:values", "call:shape"}),
    ),
    (
        "fillna_sum",
        "import pandas as pd\ndef t():\n    assert pd.Series([1.0, None, 3.0]).fillna(0.0).sum() == 4.0\n",
        frozenset({"call:fillna", "call:sum"}),
    ),
    (
        "sort_head",
        'import pandas as pd\ndef t():\n    assert pd.Series([3.0, 1.0, 2.0]).sort_values().head(1).sum() == 1.0\n',
        frozenset({"call:sort_values", "call:head", "call:sum"}),
    ),
    (
        "reshape_sum",
        "import numpy as np\ndef t():\n    assert np.array([1, 2, 3, 4]).reshape(2, 2).sum() == 10\n",
        frozenset({"call:reshape", "call:sum", "call:numpy.array"}),
    ),
    (
        "T_sum_numpy",
        "import numpy as np\ndef t():\n    assert np.array([[1, 2], [3, 4]]).T.sum() == 10\n",
        frozenset({"call:T", "call:sum", "call:numpy.array"}),
    ),
)

# Numpy ufuncs (unary on array / scalar).
_UFUNCS_UNARY = (
    "sqrt",
    "sin",
    "cos",
    "exp",
    "log",
    "abs",
    "absolute",
    "negative",
    "positive",
    "sign",
    "ceil",
    "floor",
    "rint",
    "trunc",
    "square",
    "cbrt",
    "reciprocal",
    "isnan",
    "isfinite",
    "isinf",
    "logical_not",
)
_UFUNCS_BINARY = (
    "add",
    "subtract",
    "multiply",
    "divide",
    "power",
    "maximum",
    "minimum",
    "mod",
    "fmod",
    "hypot",
    "arctan2",
    "logical_and",
    "logical_or",
    "equal",
    "not_equal",
    "greater",
    "less",
)

# ndarray methods.
_NDARRAY_ZERO = (
    "sum",
    "mean",
    "min",
    "max",
    "std",
    "var",
    "prod",
    "ptp",
    "cumsum",
    "cumprod",
    "argmax",
    "argmin",
    "all",
    "any",
    "round",
    "copy",
    "flatten",
    "ravel",
    "transpose",
    "T",
    "tolist",
)

# Showcase-like real snippets (from examples/, compacted for lift).
_SHOWCASE_SNIPPETS: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "showcase_series_sum",
        "import pandas as pd\ndef t():\n    assert pd.Series([1, 2, 3]).sum() == 6\n",
        frozenset({"call:sum", "call:pandas.Series"}),
    ),
    (
        "showcase_frame_eq_shape",
        'import pandas as pd\ndef t():\n    df=pd.DataFrame({"a": [1, 2, 3]}); assert df.shape == (3, 1)\n',
        frozenset({"call:shape", "call:pandas.DataFrame"}),
    ),
    (
        "showcase_rot90_shape",
        "import numpy as np\ndef t():\n    assert np.rot90([[1, 2], [3, 4]]).shape == (2, 2)\n",
        frozenset({"call:numpy.rot90", "call:shape"}),
    ),
    (
        "showcase_numpy_sum",
        "import numpy as np\ndef t():\n    assert np.array([1, 2, 3, 4]).sum() == 10\n",
        frozenset({"call:numpy.array", "call:sum"}),
    ),
)


@dataclass
class ShapeResult:
    name: str
    family: str
    ok: bool
    expected: frozenset[str] = field(default_factory=frozenset)
    found_calls: frozenset[str] = field(default_factory=frozenset)
    found_kw: frozenset[str] = field(default_factory=frozenset)
    issues: list[str] = field(default_factory=list)


def _ir_blob(report) -> str:
    return repr(report.payload.ir)


def _calls(blob: str) -> frozenset[str]:
    return frozenset(re.findall(r"call:[A-Za-z_][A-Za-z0-9_.]*", blob))


def _kws(blob: str) -> frozenset[str]:
    return frozenset(re.findall(r"kw:[A-Za-z_][A-Za-z0-9_]*", blob))


def _gap_tokens(blob: str) -> list[str]:
    return sorted(
        set(
            re.findall(
                r"call-(?:method|builtin|keyword|kw):[A-Za-z0-9_.]+",
                blob,
            )
        )
    )


def _dig_refuses(report) -> list[str]:
    out: list[str] = []
    for d in report.payload.diagnostics or []:
        if not isinstance(d, dict) or d.get("kind") != "dig-boundary":
            continue
        reason = d.get("reason") or ""
        if "function universe body walker refused" in reason:
            out.append(reason[:180])
        if "call-method:" in reason or "call-builtin:" in reason:
            out.append(reason[:180])
    return out


def _lift_shape(
    name: str,
    family: str,
    src: str,
    expected: frozenset[str],
    *,
    forbid_py_attr: bool = False,
) -> ShapeResult:
    issues: list[str] = []
    try:
        report = build_literal_call_report(
            source=src, filename=f"{name}.py", memento_file=f"{name}.py"
        )
    except Exception as exc:  # noqa: BLE001 — census must not die on one shape
        return ShapeResult(
            name=name,
            family=family,
            ok=False,
            expected=expected,
            issues=[f"lift-exception:{type(exc).__name__}:{exc}"[:200]],
        )
    if report is None:
        return ShapeResult(
            name=name, family=family, ok=False, expected=expected, issues=["report-none"]
        )
    blob = _ir_blob(report) + repr(report.payload.diagnostics)
    calls = _calls(blob)
    kws = _kws(blob)
    gaps = _gap_tokens(blob)
    digs = _dig_refuses(report)
    if gaps:
        issues.append(f"gap-tokens:{gaps}")
    if digs:
        issues.append(f"dig-refuse:{digs[0]}")
    if forbid_py_attr and "py.attr" in blob:
        issues.append("py.attr-present")
    missing = sorted(e for e in expected if e.startswith("call:") and e not in calls)
    missing_kw = sorted(e for e in expected if e.startswith("kw:") and e not in kws)
    if missing:
        issues.append(f"missing-call:{missing}")
    if missing_kw:
        issues.append(f"missing-kw:{missing_kw}")
    # Generic/collapsed: assertion with neither expected coords nor any call:
    if expected and not (expected & (calls | kws)) and not calls:
        issues.append("no-call-coords")
    return ShapeResult(
        name=name,
        family=family,
        ok=not issues,
        expected=expected,
        found_calls=calls,
        found_kw=kws,
        issues=issues,
    )


def _series_method_src(method: str) -> str:
    # Put the method on the assert expression so the coordinate must appear in IR.
    return (
        "import pandas as pd\n"
        "def t():\n"
        f"    assert pd.Series([1.0, 2.0, 3.0]).{method}() is not None\n"
    )


def _df_method_src(method: str) -> str:
    if method in {"T", "values"}:
        return (
            "import pandas as pd\n"
            "def t():\n"
            f'    assert pd.DataFrame({{"a": [1.0, 2.0, 3.0]}}).{method} is not None\n'
        )
    return (
        "import pandas as pd\n"
        "def t():\n"
        f'    assert pd.DataFrame({{"a": [1.0, 2.0, 3.0]}}).{method}() is not None\n'
    )


def _attr_src(kind: str, attr: str) -> str:
    if kind == "series":
        return (
            "import pandas as pd\n"
            "def t():\n"
            f"    assert pd.Series([1.0, 2.0, 3.0]).{attr} is not None\n"
        )
    return (
        "import pandas as pd\n"
        "def t():\n"
        f'    assert pd.DataFrame({{"a": [1.0, 2.0]}}).{attr} is not None\n'
    )


def _ufunc_unary_src(name: str) -> str:
    return (
        "import numpy as np\n"
        "def t():\n"
        f"    assert np.{name}(np.array([1.0, 4.0, 9.0])) is not None\n"
    )


def _ufunc_binary_src(name: str) -> str:
    return (
        "import numpy as np\n"
        "def t():\n"
        f"    assert np.{name}(np.array([1.0, 2.0]), np.array([3.0, 4.0])) is not None\n"
    )


def _ndarray_method_src(method: str) -> str:
    if method == "T":
        return (
            "import numpy as np\n"
            "def t():\n"
            "    assert np.array([[1.0, 2.0], [3.0, 4.0]]).T is not None\n"
        )
    return (
        "import numpy as np\n"
        "def t():\n"
        f"    assert np.array([[1.0, 2.0], [3.0, 4.0]]).{method}() is not None\n"
    )


def iter_scale_shapes() -> Iterable[tuple[str, str, str, frozenset[str], bool]]:
    """Yield (name, family, src, expected, forbid_py_attr)."""
    for m in _SERIES_ZERO_ARG:
        yield (
            f"series.{m}",
            "series_method",
            _series_method_src(m),
            frozenset({f"call:{m}", "call:pandas.Series"}),
            False,
        )
    for m in _DF_ZERO_ARG:
        if m in {"T", "values"}:
            exp = frozenset({f"call:{m}", "call:pandas.DataFrame"})
            yield (f"df.{m}", "df_attrish", _df_method_src(m), exp, True)
            continue
        yield (
            f"df.{m}",
            "df_method",
            _df_method_src(m),
            frozenset({f"call:{m}", "call:pandas.DataFrame"}),
            False,
        )
    for a in _SERIES_ATTRS:
        yield (
            f"series_attr.{a}",
            "series_attr",
            _attr_src("series", a),
            frozenset({f"call:{a}"}),
            True,
        )
    for a in _DF_ATTRS:
        yield (
            f"df_attr.{a}",
            "df_attr",
            _attr_src("df", a),
            frozenset({f"call:{a}"}),
            True,
        )
    for name, src, exp in _KWARG_SHAPES:
        yield (name, "kwarg_multi", src, exp, False)
    for name, src, exp in _CHAINS:
        yield (name, "chain", src, exp, False)
    for u in _UFUNCS_UNARY:
        yield (
            f"ufunc.{u}",
            "ufunc_unary",
            _ufunc_unary_src(u),
            frozenset({f"call:numpy.{u}", "call:numpy.array"}),
            False,
        )
    for u in _UFUNCS_BINARY:
        yield (
            f"ufunc2.{u}",
            "ufunc_binary",
            _ufunc_binary_src(u),
            frozenset({f"call:numpy.{u}", "call:numpy.array"}),
            False,
        )
    for m in _NDARRAY_ZERO:
        exp = frozenset({f"call:{m}", "call:numpy.array"})
        yield (f"ndarray.{m}", "ndarray_method", _ndarray_method_src(m), exp, False)
    for name, src, exp in _SHOWCASE_SNIPPETS:
        yield (name, "showcase", src, exp, False)


def run_scale_sweep() -> list[ShapeResult]:
    return [
        _lift_shape(name, family, src, expected, forbid_py_attr=forbid_py_attr)
        for name, family, src, expected, forbid_py_attr in iter_scale_shapes()
    ]


def _summarize(results: list[ShapeResult]) -> str:
    total = len(results)
    bad = [r for r in results if not r.ok]
    by_fam: dict[str, list[ShapeResult]] = {}
    for r in results:
        by_fam.setdefault(r.family, []).append(r)
    lines = [
        f"scale-sweep total={total} ok={total - len(bad)} gap={len(bad)}",
    ]
    for fam, rows in sorted(by_fam.items()):
        g = sum(1 for r in rows if not r.ok)
        lines.append(f"  {fam}: {len(rows)} shapes, gaps={g}")
    if bad:
        lines.append("first gaps:")
        for r in bad[:25]:
            lines.append(f"  - {r.name} [{r.family}]: {r.issues}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------


def test_vendor_op_coordinate_scale_sweep_clean_or_loud() -> None:
    """Broad real numpy/pandas coordinate census — red names every remaining gap."""
    results = run_scale_sweep()
    summary = _summarize(results)
    bad = [r for r in results if not r.ok]
    # Always print breadth so battleaxe logs carry the receipt.
    print(summary)
    assert len(results) >= 100, f"sweep too narrow: {len(results)}\n{summary}"
    if bad:
        first = bad[0]
        pytest.fail(
            f"coordinate scale gap ({len(bad)}/{len(results)}):\n"
            f"  first={first.name} family={first.family} issues={first.issues}\n"
            f"{summary}"
        )


def test_scale_sweep_breadth_receipt() -> None:
    """Pin minimum breadth so the matrix cannot silently shrink."""
    shapes = list(iter_scale_shapes())
    families = {f for _, f, _, _, _ in shapes}
    assert len(shapes) >= 100
    assert {
        "series_method",
        "df_method",
        "series_attr",
        "df_attr",
        "kwarg_multi",
        "chain",
        "ufunc_unary",
        "ufunc_binary",
        "ndarray_method",
        "showcase",
    } <= families
    print(f"breadth={len(shapes)} families={sorted(families)}")


if __name__ == "__main__":
    results = run_scale_sweep()
    print(_summarize(results))
    bad = [r for r in results if not r.ok]
    raise SystemExit(1 if bad else 0)
