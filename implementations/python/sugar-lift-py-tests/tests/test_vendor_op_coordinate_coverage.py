"""DEFINITIVE vendor-op coordinate coverage map (Part of #3809).

Reference instrument for the coordinate/vendor-op lane after #3929–#3937.
Every surface below is either green (locator + dig + discrimination pinned)
or a lift-probed residual with an explicit refuse/shape pin.

## Locator dual identity (do not collapse)

| layer | form | example |
|-------|------|---------|
| FOL / OpaqueOpCallsite / EUF name | ``call:<name>(…)`` | ``call:mean(call:pandas.Series(…))`` |
| callEdges.targetSymbol (method-locus) | ``method:<name>`` | ``method:mean`` |
| Attribute coordinate (never ``py.attr``) | ``call:<attr>(receiver)`` | ``call:shape(call:T(df))`` |
| Keyword args (when grounded) | ``kw:<name>(value)`` in call args | ``call:sum(s, kw:axis(0))`` |
| Nested chain | outer wraps inner once | ``call:sum(call:groupby(df, 'k'))`` |

FOL stays in the ``call:`` family. Re-stamping FOL as ``method:`` would break
congruence with len/str/chains. Edge ``method:`` is the method-locus only.

## Discrimination law (opaque vendor ops)

- ``computed=None`` when the vendor value is not foldable — never fabricate.
- Solo truthful / solo lying opaque asserts stay solver-**sat** (honest limit).
- Real discrimination is **dual-assert witness EXECUTION** (shared euf key →
  unsat). Aggregate-local sat is not the gate; use the real solver path.

## Surface map (post #3929–#3937)

| surface | locator emitted | direct ground | body dig | dual-assert unsat (witness) | PR |
|---------|-----------------|---------------|----------|-----------------------------|-----|
| **Builtin call** ``sum``/``len``/``list`` | FOL ``call:<builtin>``; edge ``call:`` | yes | yes | yes (fold or dual) | #3918, #3914 |
| **Series/DF method** ``.mean/.max/.min/.sum/.count`` | FOL ``call:m``; edge ``method:m`` | yes | bare formal yes (#3933); ``df[col].m`` yes | yes dual-assert | #3930, #3933 |
| **Vendor attribute** ``.shape/.dtypes/.columns/.index/.values/.T/.empty`` | FOL ``call:<attr>`` (not py.attr) | yes | formal + zero-arg yes | via ``len(attr)`` dual | #3905, #3932 |
| **Chained call** ``groupby().sum()``, ``dropna().mean()``, ``reshape().sum()`` | nested ``call:outer(call:inner(…))`` | yes | formal nest yes | via ``len(…)`` dual | #3929, #3920 |
| **Formal-receiver body dig** ``def A(s): return s.mean()`` | universe ``out == call:mean(s)`` | n/a | yes (build + bridge binds) | dual unsat | #3933 |
| **Composition chain** ``len(A())`` / ``groupby().sum`` nest in dig | outer over dug coord | yes | full nest in universe | dual unsat | #3914, #3937 |
| **Multi-arg method** ``left.merge(right)`` | ``call:merge(left, right)`` | yes | formal ``out==call:merge(l,r)`` | shape dual (tuple path) | lift-probed green |
| **Keyword method** ``s.sum(axis=0)`` | ``call:sum(…, kw:axis(0))``; edge ``method:sum`` | yes | formal + constructed dig yes | dual-assert unsat | kwarg body dig PR |
| **Nested attr chain** ``df.T.shape`` | ``call:shape(call:T(df))`` | yes | formal dig yes | via len projection | #3932 |
| **Numpy ufunc** ``np.sqrt(…)`` | ``call:numpy.sqrt(…)`` | yes | formal dig yes | via outer fold/dual | lift-probed green |

### Residual notes

| seed | status | notes |
|------|--------|-------|
| ``def A(s): return s.mean(axis=0)`` | **green** dig | ``out == call:mean(s, kw:axis(0))`` |
| ``def A(): return Series(…).sum(axis=0)`` | **green** dig | constructed + kwargs |
| ``pivot_table(…kwargs…)`` direct | green inv coords | projected-equality path; not always euf-stamped name |
| ``groupby(k, as_index=False)`` direct | green | nest + ``kw:as_index`` in inv |

Keyword body dig instruments: ``test_kwarg_method_coordinate_body_dig.py``.

Instruments in sibling modules (do not delete when editing this map):

- ``test_vendor_chain_coordinate_batch_a.py`` — chains / formal nest
- ``test_vendor_method_coordinate_batch_b.py`` — methods dual locator
- ``test_vendor_attribute_coordinate_batch_c.py`` — attributes
- ``test_formal_method_body_dig.py`` — bare formal methods
- ``test_groupby_chain_compositional_body_dig.py`` — composition nest
- ``test_composition_congruence.py`` — len(make()) composition
- ``test_groupby_body_dig.py`` / ``test_vendor_method_body_dig.py`` — earlier pins
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _coords(report) -> set[str]:
    return set(re.findall(r"call:[A-Za-z_][A-Za-z0-9_.]*", repr(report.payload.ir)))


def _kw_coords(report) -> set[str]:
    return set(re.findall(r"kw:[A-Za-z_][A-Za-z0-9_]*", repr(report.payload.ir)))


def _edge_methods(report) -> set[str]:
    out: set[str] = set()
    for edge in report.payload.call_edges or []:
        if isinstance(edge, dict):
            sym = edge.get("targetSymbol")
        else:
            sym = getattr(edge, "target_symbol", None) or getattr(
                edge, "targetSymbol", None
            )
        if isinstance(sym, str) and sym.startswith("method:"):
            out.add(sym)
    return out


def _has_callable(report) -> bool:
    return any((r.name or "").endswith("::callable") for r in report.payload.ir)


def _callable_post(report) -> str:
    row = next(r for r in report.payload.ir if (r.name or "").endswith("::callable"))
    return repr(row.post)


def _dig_body_refuses(report, callee: str = "A") -> list[str]:
    return [
        d.get("reason", "")
        for d in (report.payload.diagnostics or [])
        if isinstance(d, dict)
        and d.get("kind") == "dig-boundary"
        and d.get("callee") == callee
        and "function universe body walker refused" in (d.get("reason") or "")
    ]


def _has_py_attr(report) -> bool:
    return "py.attr" in repr(report.payload.ir)


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
        '    assert pd.DataFrame({"a": [1, None]}).dropna().shape == (1, 1)\n'
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
        '    return pd.DataFrame({"a": [1, None]}).dropna().shape\n'
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
        '    return len(pd.DataFrame({"a": [1, 2, 3]}).head(2))\n'
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
        '    return list(pd.DataFrame({"a": [1], "b": [2]}).columns)\n'
        "def test_a():\n"
        '    assert A() == ["a", "b"]\n'
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert _has_callable(report), [r.name for r in report.payload.ir]
    coords = _coords(report)
    assert "call:list" in coords, coords
    assert "call:columns" in coords or "call:pandas.DataFrame" in coords, coords


# ---------------------------------------------------------------------------
# Map matrix: one instrument per surface class (post #3929–#3937)
# ---------------------------------------------------------------------------


class TestMapBuiltinCall:
    def test_len_builtin_fol_call_locator(self) -> None:
        src = (
            "def t():\n"
            "    assert len([1, 2, 3]) == 3\n"
        )
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
        assert report is not None
        assert "call:len" in _coords(report)


class TestMapSeriesDataFrameMethod:
    def test_mean_dual_locator_fol_call_and_edge_method(self) -> None:
        src = (
            "import pandas as pd\n"
            "def t():\n"
            "    assert pd.Series([1.0, 2.0, 3.0]).mean() == 0\n"
        )
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
        assert report is not None
        assert "call:mean" in _coords(report)
        assert "method:mean" in _edge_methods(report)
        name = report.payload.ir[0].name or ""
        assert "call:mean" in name
        assert "method:mean" not in name


class TestMapVendorAttribute:
    def test_shape_is_call_shape_not_py_attr(self) -> None:
        src = (
            "import pandas as pd\n"
            "def t():\n"
            '    assert pd.DataFrame({"a": [1]}).shape == (1, 1)\n'
        )
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
        assert report is not None
        assert "call:shape" in _coords(report)
        assert not _has_py_attr(report)


class TestMapChainedCall:
    def test_groupby_sum_nested_call_coordinates(self) -> None:
        src = (
            "import pandas as pd\n"
            "def t():\n"
            '    assert pd.DataFrame({"k": [1, 1, 2], "v": [10, 20, 30]})'
            '.groupby("k").sum().shape == (2, 1)\n'
        )
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
        assert report is not None
        assert {"call:groupby", "call:sum", "call:shape"} <= _coords(report)
        name = report.payload.ir[0].name or ""
        assert "call:sum(c:call:groupby" in name, name


class TestMapFormalReceiverBodyDig:
    def test_bare_formal_mean_universe_post(self) -> None:
        src = (
            "import pandas as pd\n"
            "def A(s):\n"
            "    return s.mean()\n"
            "def test_a():\n"
            "    assert A(pd.Series([1.0, 2.0, 3.0])) == 2.0\n"
        )
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
        assert report is not None
        assert _has_callable(report)
        post = _callable_post(report)
        assert "call:mean" in post, post
        assert not _dig_body_refuses(report), _dig_body_refuses(report)
        for reason in _dig_body_refuses(report):
            assert "call-method:" not in reason


class TestMapCompositionChain:
    def test_groupby_sum_formal_nest_in_universe(self) -> None:
        src = (
            "import pandas as pd\n"
            "def A(df):\n"
            '    return df.groupby("k").sum()\n'
            "def test_a():\n"
            '    assert A(pd.DataFrame({"k": [1, 1, 2], "v": [10, 20, 30]}))'
            ' == A(pd.DataFrame({"k": [1, 1, 2], "v": [10, 20, 30]}))\n'
        )
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
        assert report is not None
        assert _has_callable(report)
        post = _callable_post(report)
        assert "call:sum" in post and "call:groupby" in post, post
        assert not _dig_body_refuses(report), _dig_body_refuses(report)


class TestMapMultiArgMethod:
    """Lift-probed green: multi-arg vendor methods emit call: with all positionals."""

    def test_direct_merge_nested_coordinates(self) -> None:
        src = (
            "import pandas as pd\n"
            "def t():\n"
            '    left = pd.DataFrame({"k": [1, 2], "a": [10, 20]})\n'
            '    right = pd.DataFrame({"k": [1, 2], "b": [100, 200]})\n'
            "    assert left.merge(right).shape == (2, 3)\n"
        )
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
        assert report is not None
        assert {"call:merge", "call:shape", "call:pandas.DataFrame"} <= _coords(report)
        name = report.payload.ir[0].name or ""
        assert "call:merge" in name, name
        # Two DataFrame args under merge
        assert name.count("call:pandas.DataFrame") >= 2 or "call:merge(c:call:pandas.DataFrame" in name

    def test_formal_merge_body_dig_emits_call_merge_both_formals(self) -> None:
        src = (
            "import pandas as pd\n"
            "def A(left, right):\n"
            "    return left.merge(right)\n"
            "def test_a():\n"
            '    L = pd.DataFrame({"k": [1], "a": [1]})\n'
            '    R = pd.DataFrame({"k": [1], "b": [2]})\n'
            "    assert A(L, R) == A(L, R)\n"
        )
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
        assert report is not None
        assert _has_callable(report)
        post = _callable_post(report)
        assert "call:merge" in post, post
        assert "left" in post and "right" in post, post
        assert not _dig_body_refuses(report), _dig_body_refuses(report)


class TestMapKeywordMethodDirect:
    """Direct kwarg methods ground via symbolic_term (kw: in call args)."""

    def test_sum_axis_emits_call_sum_with_kw_axis(self) -> None:
        src = (
            "import pandas as pd\n"
            "def t():\n"
            "    assert pd.Series([1.0, 2.0, 3.0]).sum(axis=0) == 6.0\n"
        )
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
        assert report is not None
        assert "call:sum" in _coords(report)
        assert "kw:axis" in _kw_coords(report)
        assert "method:sum" in _edge_methods(report)
        name = report.payload.ir[0].name or ""
        assert "kw:axis" in name, name

    def test_pivot_table_kwargs_in_inv_coordinates(self) -> None:
        src = (
            "import pandas as pd\n"
            "def t():\n"
            '    df = pd.DataFrame({"a": [1, 1, 2], "b": [10, 20, 30], "c": ["x", "y", "x"]})\n'
            '    assert df.pivot_table(values="b", index="a", columns="c", aggfunc="sum")'
            ".shape == (2, 2)\n"
        )
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
        assert report is not None
        assert "call:pivot_table" in _coords(report)
        assert {"kw:values", "kw:index", "kw:columns", "kw:aggfunc"} <= _kw_coords(
            report
        )


class TestMapNestedAttributeChain:
    def test_t_shape_nested_call_coordinates(self) -> None:
        src = (
            "import pandas as pd\n"
            "def t():\n"
            '    assert pd.DataFrame({"a": [1, 2, 3]}).T.shape == (1, 3)\n'
        )
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
        assert report is not None
        assert {"call:T", "call:shape"} <= _coords(report)
        assert not _has_py_attr(report)
        name = report.payload.ir[0].name or ""
        assert "call:shape(c:call:T" in name, name

    def test_formal_t_shape_body_dig(self) -> None:
        src = (
            "import pandas as pd\n"
            "def A(df):\n"
            "    return df.T.shape\n"
            "def test_a():\n"
            '    assert A(pd.DataFrame({"a": [1, 2]})) == (1, 2)\n'
        )
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
        assert report is not None
        assert _has_callable(report)
        post = _callable_post(report)
        assert "call:shape" in post and "call:T" in post, post
        assert not _dig_body_refuses(report), _dig_body_refuses(report)


class TestMapNumpyUfunc:
    def test_sqrt_direct_call_numpy_sqrt(self) -> None:
        src = (
            "import numpy as np\n"
            "def t():\n"
            "    assert np.sqrt(np.array([4.0, 9.0])).sum() == 5.0\n"
        )
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
        assert report is not None
        assert {"call:numpy.sqrt", "call:numpy.array", "call:sum"} <= _coords(report)
        name = report.payload.ir[0].name or ""
        assert "call:numpy.sqrt" in name, name

    def test_sqrt_formal_body_dig(self) -> None:
        src = (
            "import numpy as np\n"
            "def A(x):\n"
            "    return np.sqrt(x)\n"
            "def test_a():\n"
            "    assert A(4.0) == 2.0\n"
        )
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
        assert report is not None
        assert _has_callable(report)
        post = _callable_post(report)
        assert "call:numpy.sqrt" in post, post
        assert not _dig_body_refuses(report), _dig_body_refuses(report)


# ---------------------------------------------------------------------------
# Keyword method body dig (was residual refuse; now green dig + kw: carry)
# ---------------------------------------------------------------------------


class TestKeywordMethodBodyDigMap:
    """Body dig matches direct: call:<m>(receiver, …, kw:…)."""

    def test_formal_mean_axis_body_dig_emits_call_mean_kw_axis(self) -> None:
        src = (
            "import pandas as pd\n"
            "def A(s):\n"
            "    return s.mean(axis=0)\n"
            "def test_a():\n"
            "    assert A(pd.Series([1.0, 2.0, 3.0])) == 2.0\n"
        )
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
        assert report is not None
        assert _has_callable(report), [r.name for r in report.payload.ir]
        post = _callable_post(report)
        assert "call:mean" in post, post
        assert "kw:axis" in post, post
        assert not _dig_body_refuses(report), _dig_body_refuses(report)

    def test_constructed_sum_axis_body_dig_emits_call_sum_kw_axis(self) -> None:
        src = (
            "import pandas as pd\n"
            "def A():\n"
            "    return pd.Series([1.0, 2.0, 3.0]).sum(axis=0)\n"
            "def test_a():\n"
            "    assert A() == 6.0\n"
        )
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
        assert report is not None
        assert _has_callable(report), [r.name for r in report.payload.ir]
        post = _callable_post(report)
        assert "call:sum" in post, post
        assert "kw:axis" in post, post
        assert not _dig_body_refuses(report), _dig_body_refuses(report)
