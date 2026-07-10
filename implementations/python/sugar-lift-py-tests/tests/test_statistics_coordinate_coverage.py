"""stdlib ``statistics`` vendor-op coordinate coverage (Part of #3809 Task G).

Third-library pin after numpy/pandas (#3944 scale sweep + #3997 R==0 gate).
``statistics`` is pure-python, deterministic, installed everywhere — the safest
stdlib surface to extend the coordinate model onto.

## Locator dual identity (same law as numpy/pandas)

| layer | form | example |
|-------|------|---------|
| FOL / OpaqueOpCallsite | ``call:statistics.<fn>(…)`` | ``call:statistics.mean(c:array(…))`` |
| Method on NormalDist | ``call:<method>(receiver)`` | ``call:cdf(call:statistics.NormalDist())`` |
| Keyword args | ``kw:<name>(value)`` | ``call:statistics.quantiles(…, kw:n(2))`` |

## Discrimination law (opaque vendor ops)

- ``computed=None`` when the pure-python body is not foldable — never fabricate.
- Dual-assert witness EXECUTION is the discrimination gate (shared euf key → unsat).

## Dig residual (not a construction gap)

Body dig of some ``statistics`` functions refuses on module-level AnnAssign
(``_sqrt_bit_width: int = …``) when sibling resolution walks the installed
source. Coordinate emission still succeeds; construction-gap R for the module
file is 0. Dig residual is recorded for visibility, not counted as a
coordinate coverage gap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import pytest

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

# ---------------------------------------------------------------------------
# Real API matrix (consumer shapes)
# ---------------------------------------------------------------------------

# (name, source, expected call: bases — match call:X or call:statistics.X)
_MODULE_FUNCS: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "mean",
        "import statistics as st\ndef t():\n    assert st.mean([1.0, 2.0, 3.0]) == 2.0\n",
        frozenset({"mean"}),
    ),
    (
        "median",
        "import statistics as st\ndef t():\n    assert st.median([1.0, 2.0, 3.0]) == 2.0\n",
        frozenset({"median"}),
    ),
    (
        "mode",
        "import statistics as st\ndef t():\n    assert st.mode([1, 1, 2]) == 1\n",
        frozenset({"mode"}),
    ),
    (
        "stdev",
        "import statistics as st\ndef t():\n    assert st.stdev([1.0, 2.0, 3.0]) > 0.0\n",
        frozenset({"stdev"}),
    ),
    (
        "pstdev",
        "import statistics as st\ndef t():\n    assert st.pstdev([1.0, 2.0, 3.0]) > 0.0\n",
        frozenset({"pstdev"}),
    ),
    (
        "variance",
        "import statistics as st\ndef t():\n    assert st.variance([1.0, 2.0, 3.0]) > 0.0\n",
        frozenset({"variance"}),
    ),
    (
        "pvariance",
        "import statistics as st\ndef t():\n    assert st.pvariance([1.0, 2.0, 3.0]) > 0.0\n",
        frozenset({"pvariance"}),
    ),
    (
        "fmean",
        "import statistics as st\ndef t():\n    assert st.fmean([1.0, 2.0, 3.0]) == 2.0\n",
        frozenset({"fmean"}),
    ),
    (
        "geometric_mean",
        "import statistics as st\ndef t():\n    assert st.geometric_mean([1.0, 4.0]) == 2.0\n",
        frozenset({"geometric_mean"}),
    ),
    (
        "harmonic_mean",
        "import statistics as st\ndef t():\n    assert st.harmonic_mean([1.0, 2.0, 4.0]) > 0.0\n",
        frozenset({"harmonic_mean"}),
    ),
    (
        "multimode",
        "import statistics as st\ndef t():\n    assert st.multimode([1, 1, 2, 2]) is not None\n",
        frozenset({"multimode"}),
    ),
    (
        "median_low",
        "import statistics as st\ndef t():\n    assert st.median_low([1, 2, 3, 4]) == 2\n",
        frozenset({"median_low"}),
    ),
    (
        "median_high",
        "import statistics as st\ndef t():\n    assert st.median_high([1, 2, 3, 4]) == 3\n",
        frozenset({"median_high"}),
    ),
    (
        "quantiles_n",
        "import statistics as st\ndef t():\n    assert st.quantiles([1, 2, 3, 4], n=2) is not None\n",
        frozenset({"quantiles"}),
    ),
    (
        "correlation",
        "import statistics as st\ndef t():\n    assert st.correlation([1, 2, 3], [1, 2, 3]) == 1.0\n",
        frozenset({"correlation"}),
    ),
    (
        "covariance",
        "import statistics as st\ndef t():\n    assert st.covariance([1, 2, 3], [1, 2, 3]) > 0.0\n",
        frozenset({"covariance"}),
    ),
    (
        "linear_regression",
        "import statistics as st\ndef t():\n    assert st.linear_regression([1, 2, 3], [1, 2, 3]) is not None\n",
        frozenset({"linear_regression"}),
    ),
    (
        "mean_from_import",
        "from statistics import mean\ndef t():\n    assert mean([1.0, 2.0, 3.0]) == 2.0\n",
        frozenset({"mean"}),
    ),
    (
        "fmean_weights",
        "import statistics as st\ndef t():\n    assert st.fmean([1.0, 2.0], weights=[1.0, 1.0]) == 1.5\n",
        frozenset({"fmean"}),
    ),
)

_NORMALDIST: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "NormalDist_ctor",
        "import statistics as st\ndef t():\n    assert st.NormalDist(mu=0.0, sigma=1.0) is not None\n",
        frozenset({"NormalDist"}),
    ),
    (
        "NormalDist_mean_attr",
        "import statistics as st\ndef t():\n    assert st.NormalDist(mu=0.0, sigma=1.0).mean == 0.0\n",
        frozenset({"NormalDist", "mean"}),
    ),
    (
        "NormalDist_cdf",
        "import statistics as st\ndef t():\n    assert st.NormalDist().cdf(0.0) == 0.5\n",
        frozenset({"NormalDist", "cdf"}),
    ),
    (
        "NormalDist_pdf",
        "import statistics as st\ndef t():\n    assert st.NormalDist().pdf(0.0) > 0.0\n",
        frozenset({"NormalDist", "pdf"}),
    ),
    (
        "NormalDist_inv_cdf",
        "import statistics as st\ndef t():\n    assert st.NormalDist().inv_cdf(0.5) == 0.0\n",
        frozenset({"NormalDist", "inv_cdf"}),
    ),
    (
        "NormalDist_stdev",
        "import statistics as st\ndef t():\n    assert st.NormalDist(mu=0.0, sigma=2.0).stdev == 2.0\n",
        frozenset({"NormalDist", "stdev"}),
    ),
)

_KW_SHAPES: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "quantiles_kw_n",
        "import statistics as st\ndef t():\n    assert st.quantiles([1, 2, 3, 4], n=4) is not None\n",
        frozenset({"kw:n"}),
    ),
    (
        "fmean_kw_weights",
        "import statistics as st\ndef t():\n    assert st.fmean([1.0, 2.0], weights=[1.0, 1.0]) == 1.5\n",
        frozenset({"kw:weights"}),
    ),
    (
        "NormalDist_kw_mu_sigma",
        "import statistics as st\ndef t():\n    assert st.NormalDist(mu=0.0, sigma=1.0).mean == 0.0\n",
        frozenset({"kw:mu", "kw:sigma"}),
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
    dig_residual: list[str] = field(default_factory=list)


def _call_bases(blob: str) -> frozenset[str]:
    found = re.findall(r"call:([A-Za-z_][A-Za-z0-9_.]*)", blob)
    bases: set[str] = set()
    for c in found:
        bases.add(c)
        bases.add(c.rsplit(".", 1)[-1])
    return frozenset(bases)


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


def _dig_residuals(report) -> list[str]:
    out: list[str] = []
    for d in report.payload.diagnostics or []:
        if not isinstance(d, dict) or d.get("kind") != "dig-boundary":
            continue
        reason = d.get("reason") or ""
        if "function universe body walker refused" in reason:
            out.append(reason[:160])
        if "callsite floor projection refused" in reason:
            out.append(reason[:160])
    return out


def _lift_shape(
    name: str,
    family: str,
    src: str,
    expected: frozenset[str],
    *,
    expect_kw: bool = False,
) -> ShapeResult:
    issues: list[str] = []
    dig_residual: list[str] = []
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
    blob = repr(report.payload.ir) + repr(report.payload.diagnostics)
    calls = _call_bases(blob)
    kws = _kws(blob)
    gaps = _gap_tokens(blob)
    dig_residual = _dig_residuals(report)
    if gaps:
        issues.append(f"gap-tokens:{gaps}")
    if "write more Sugar" in blob or "write more Floor" in blob:
        issues.append("construction-gap-text")
    if "FactoryGap" in blob and "factory gap" in blob.lower():
        issues.append("factory-gap")
    if expect_kw:
        missing_kw = sorted(e for e in expected if e.startswith("kw:") and e not in kws)
        if missing_kw:
            issues.append(f"missing-kw:{missing_kw}")
    else:
        missing = sorted(e for e in expected if e not in calls)
        if missing:
            issues.append(f"missing-call:{missing}")
    if expected and not expect_kw and not (expected & calls) and not calls:
        issues.append("no-call-coords")
    return ShapeResult(
        name=name,
        family=family,
        ok=not issues,
        expected=expected,
        found_calls=calls,
        found_kw=kws,
        issues=issues,
        dig_residual=dig_residual,
    )


def iter_statistics_shapes() -> Iterable[tuple[str, str, str, frozenset[str], bool]]:
    """Yield (name, family, src, expected, expect_kw)."""
    for name, src, exp in _MODULE_FUNCS:
        yield (name, "module_func", src, exp, False)
    for name, src, exp in _NORMALDIST:
        yield (name, "NormalDist", src, exp, False)
    for name, src, exp in _KW_SHAPES:
        yield (name, "kwarg", src, exp, True)


def run_statistics_coverage() -> list[ShapeResult]:
    return [
        _lift_shape(name, family, src, expected, expect_kw=expect_kw)
        for name, family, src, expected, expect_kw in iter_statistics_shapes()
    ]


def _summarize(results: list[ShapeResult]) -> str:
    total = len(results)
    bad = [r for r in results if not r.ok]
    dig = [r for r in results if r.dig_residual]
    lines = [
        f"statistics-coverage total={total} ok={total - len(bad)} "
        f"coord_gaps={len(bad)} dig_residual={len(dig)}",
    ]
    if bad:
        lines.append("coord gaps:")
        for r in bad[:20]:
            lines.append(f"  - {r.name} [{r.family}]: {r.issues}")
    if dig:
        lines.append(f"dig residual (not construction gaps): {len(dig)} shapes")
        for r in dig[:5]:
            lines.append(f"  - {r.name}: {r.dig_residual[0][:100]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------


def test_statistics_coordinate_coverage_zero_gaps() -> None:
    """Real statistics API shapes emit coordinates — 0 construction gaps."""
    results = run_statistics_coverage()
    summary = _summarize(results)
    bad = [r for r in results if not r.ok]
    print(summary)
    assert len(results) >= 20, f"coverage too narrow: {len(results)}\n{summary}"
    if bad:
        first = bad[0]
        pytest.fail(
            f"statistics coordinate gap ({len(bad)}/{len(results)}):\n"
            f"  first={first.name} family={first.family} issues={first.issues}\n"
            f"{summary}"
        )


def test_statistics_coverage_breadth_receipt() -> None:
    shapes = list(iter_statistics_shapes())
    families = {f for _, f, _, _, _ in shapes}
    assert len(shapes) >= 20
    assert {"module_func", "NormalDist", "kwarg"} <= families
    print(f"breadth={len(shapes)} families={sorted(families)}")


# ---------------------------------------------------------------------------
# Discrimination seeds (witness EXECUTION)
# ---------------------------------------------------------------------------


def test_statistics_mean_dual_assert_refutes_lie(tmp_path: Path) -> None:
    """truthful mean + lying mean share euf key → unsat via witness."""
    src = (
        "import statistics as st\n"
        "def t_true():\n"
        "    assert st.mean([1.0, 2.0, 3.0]) == 2.0\n"
        "def t_lie():\n"
        "    assert st.mean([1.0, 2.0, 3.0]) == 0.0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    blob = repr(report.payload.ir)
    assert "call:statistics.mean" in blob
    names = [r.name or "" for r in report.payload.ir if "#euf#" in (r.name or "")]
    assert len(names) == 2
    assert names[0] == names[1]

    result = run_source_through_real_solver(tmp_path / "mean-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses


def test_statistics_normaldist_cdf_dual_assert_refutes_lie(tmp_path: Path) -> None:
    """NormalDist().cdf truth vs lie — method coordinate discriminates."""
    src = (
        "import statistics as st\n"
        "def t_true():\n"
        "    assert st.NormalDist().cdf(0.0) == 0.5\n"
        "def t_lie():\n"
        "    assert st.NormalDist().cdf(0.0) == 0.0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    blob = repr(report.payload.ir)
    assert "call:cdf" in blob
    assert "call:statistics.NormalDist" in blob or "NormalDist" in blob

    result = run_source_through_real_solver(tmp_path / "cdf-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses


if __name__ == "__main__":
    results = run_statistics_coverage()
    print(_summarize(results))
    raise SystemExit(1 if any(not r.ok for r in results) else 0)
