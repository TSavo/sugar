"""stdlib ``fractions`` vendor-op coordinate coverage (Part of #3809).

Fifth vendor after numpy/pandas/statistics/decimal. ``fractions`` is pure-python,
deterministic, installed everywhere — single-module ``fractions.py`` (same resolve
shape as statistics: module *file*, never parent stdlib dir).

## Locator dual identity (same law as numpy/pandas/statistics/decimal)

| layer | form | example |
|-------|------|---------|
| FOL / OpaqueOpCallsite | ``call:fractions.<Name>(…)`` | ``call:fractions.Fraction(i:1,i:2)`` |
| Method on Fraction | ``call:<method>(receiver)`` | ``call:limit_denominator(…)`` |
| Attribute | ``call:<attr>(receiver)`` | ``call:numerator(…)`` |
| Keyword args | ``kw:<name>(value)`` | ``call:limit_denominator(…, kw:max_denominator(…))`` |

## Discrimination law (opaque vendor ops)

- ``computed=None`` when the pure-python body is not foldable — never fabricate.
- Dual-assert witness EXECUTION is the discrimination gate (shared euf key → unsat).
- Prefer concrete int/float RHS for EUF inequality; opaque Fraction RHS may stay sat.

## Dig residual (not a construction gap)

Body dig of some ``fractions`` call sites may refuse on imported callee source.
Coordinate emission still succeeds; construction-gap R for the module file is 0.
Dig residual is recorded for visibility, not counted as a coordinate coverage gap.
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

# (name, source, expected call: bases — match call:X or call:fractions.X)
_CTORS: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "ctor_pair",
        "from fractions import Fraction\ndef t():\n    assert Fraction(1, 2) == Fraction(1, 2)\n",
        frozenset({"Fraction"}),
    ),
    (
        "ctor_int",
        "from fractions import Fraction\ndef t():\n    assert Fraction(3) == Fraction(3, 1)\n",
        frozenset({"Fraction"}),
    ),
    (
        "ctor_str",
        'from fractions import Fraction\ndef t():\n    assert Fraction("1/2") == Fraction(1, 2)\n',
        frozenset({"Fraction"}),
    ),
    (
        "from_float",
        "from fractions import Fraction\ndef t():\n    assert Fraction.from_float(0.5) == Fraction(1, 2)\n",
        frozenset({"Fraction", "from_float"}),
    ),
    (
        "ctor_module_alias",
        "import fractions as fr\ndef t():\n    assert fr.Fraction(1, 2) == fr.Fraction(1, 2)\n",
        frozenset({"Fraction"}),
    ),
)

_METHODS: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "limit_denominator",
        "from fractions import Fraction\ndef t():\n    assert Fraction(3.14159).limit_denominator(10) == Fraction(22, 7)\n",
        frozenset({"Fraction", "limit_denominator"}),
    ),
    (
        "as_integer_ratio",
        "from fractions import Fraction\ndef t():\n    assert Fraction(3, 4).as_integer_ratio() == (3, 4)\n",
        frozenset({"Fraction", "as_integer_ratio"}),
    ),
    (
        "is_integer",
        "from fractions import Fraction\ndef t():\n    assert Fraction(4, 2).is_integer()\n",
        frozenset({"Fraction", "is_integer"}),
    ),
    (
        "conjugate",
        "from fractions import Fraction\ndef t():\n    assert Fraction(1, 2).conjugate() == Fraction(1, 2)\n",
        frozenset({"Fraction", "conjugate"}),
    ),
)

_ATTRS: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "numerator",
        "from fractions import Fraction\ndef t():\n    assert Fraction(3, 4).numerator == 3\n",
        frozenset({"Fraction", "numerator"}),
    ),
    (
        "denominator",
        "from fractions import Fraction\ndef t():\n    assert Fraction(3, 4).denominator == 4\n",
        frozenset({"Fraction", "denominator"}),
    ),
    (
        "real_attr",
        "from fractions import Fraction\ndef t():\n    assert Fraction(1, 2).real == Fraction(1, 2)\n",
        frozenset({"Fraction", "real"}),
    ),
)

_ARITH: tuple[tuple[str, str, frozenset[str]], ...] = (
    # Binary ops may lower without call: tokens; force coords via int() / attrs.
    (
        "add_via_int",
        "from fractions import Fraction\ndef t():\n    assert int(Fraction(1, 2) + Fraction(1, 2)) == 1\n",
        frozenset({"Fraction", "int"}),
    ),
    (
        "sub_via_int",
        "from fractions import Fraction\ndef t():\n    assert int(Fraction(3, 2) - Fraction(1, 2)) == 1\n",
        frozenset({"Fraction", "int"}),
    ),
    (
        "mul_via_int",
        "from fractions import Fraction\ndef t():\n    assert int(Fraction(2, 3) * Fraction(3, 2)) == 1\n",
        frozenset({"Fraction", "int"}),
    ),
    (
        "div_via_int",
        "from fractions import Fraction\ndef t():\n    assert int(Fraction(3, 2) / Fraction(1, 2)) == 3\n",
        frozenset({"Fraction", "int"}),
    ),
    (
        "floordiv_via_int",
        "from fractions import Fraction\ndef t():\n    assert int(Fraction(7, 2) // Fraction(1, 1)) == 3\n",
        frozenset({"Fraction", "int"}),
    ),
    (
        "mod_via_int",
        "from fractions import Fraction\ndef t():\n    assert int(Fraction(5, 2) % Fraction(1, 1)) == 0\n",
        frozenset({"Fraction", "int"}),
    ),
    (
        "abs_builtin",
        "from fractions import Fraction\ndef t():\n    assert abs(Fraction(-3, 2)) == Fraction(3, 2)\n",
        frozenset({"Fraction", "abs"}),
    ),
    (
        "neg_via_numerator",
        "from fractions import Fraction\ndef t():\n    assert (-Fraction(1, 2)).numerator == -1\n",
        frozenset({"Fraction", "numerator"}),
    ),
    (
        "pow_via_int",
        "from fractions import Fraction\ndef t():\n    assert int(Fraction(2, 1) ** 2) == 4\n",
        frozenset({"Fraction", "int"}),
    ),
)

_COMPARE: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "eq_int",
        "from fractions import Fraction\ndef t():\n    assert Fraction(2, 1) == 2\n",
        frozenset({"Fraction"}),
    ),
    (
        "lt",
        "from fractions import Fraction\ndef t():\n    assert Fraction(1, 3) < Fraction(1, 2)\n",
        frozenset({"Fraction"}),
    ),
    (
        "le",
        "from fractions import Fraction\ndef t():\n    assert Fraction(1, 2) <= Fraction(1, 2)\n",
        frozenset({"Fraction"}),
    ),
    (
        "gt",
        "from fractions import Fraction\ndef t():\n    assert Fraction(2, 3) > Fraction(1, 2)\n",
        frozenset({"Fraction"}),
    ),
    (
        "ge",
        "from fractions import Fraction\ndef t():\n    assert Fraction(1, 2) >= Fraction(1, 3)\n",
        frozenset({"Fraction"}),
    ),
)

_KW_SHAPES: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "limit_denominator_kw",
        "from fractions import Fraction\ndef t():\n    assert Fraction(3.14159).limit_denominator(max_denominator=10) == Fraction(22, 7)\n",
        frozenset({"kw:max_denominator"}),
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
        if "could not find class definition" in reason:
            out.append(reason[:160])
        if "imported callee source was not readable" in reason:
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


def iter_fractions_shapes() -> Iterable[tuple[str, str, str, frozenset[str], bool]]:
    """Yield (name, family, src, expected, expect_kw)."""
    for name, src, exp in _CTORS:
        yield (name, "ctor", src, exp, False)
    for name, src, exp in _METHODS:
        yield (name, "method", src, exp, False)
    for name, src, exp in _ATTRS:
        yield (name, "attr", src, exp, False)
    for name, src, exp in _ARITH:
        yield (name, "arith", src, exp, False)
    for name, src, exp in _COMPARE:
        yield (name, "compare", src, exp, False)
    for name, src, exp in _KW_SHAPES:
        yield (name, "kwarg", src, exp, True)


def run_fractions_coverage() -> list[ShapeResult]:
    return [
        _lift_shape(name, family, src, expected, expect_kw=expect_kw)
        for name, family, src, expected, expect_kw in iter_fractions_shapes()
    ]


def _summarize(results: list[ShapeResult]) -> str:
    total = len(results)
    bad = [r for r in results if not r.ok]
    dig = [r for r in results if r.dig_residual]
    lines = [
        f"fractions-coverage total={total} ok={total - len(bad)} "
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


def test_fractions_coordinate_coverage_zero_gaps() -> None:
    """Real Fraction API shapes emit coordinates — 0 construction gaps."""
    results = run_fractions_coverage()
    summary = _summarize(results)
    bad = [r for r in results if not r.ok]
    print(summary)
    assert len(results) >= 20, f"coverage too narrow: {len(results)}\n{summary}"
    if bad:
        first = bad[0]
        pytest.fail(
            f"fractions coordinate gap ({len(bad)}/{len(results)}):\n"
            f"  first={first.name} family={first.family} issues={first.issues}\n"
            f"{summary}"
        )


def test_fractions_coverage_breadth_receipt() -> None:
    shapes = list(iter_fractions_shapes())
    families = {f for _, f, _, _, _ in shapes}
    assert len(shapes) >= 20
    assert {"ctor", "method", "attr", "arith", "compare", "kwarg"} <= families
    print(f"breadth={len(shapes)} families={sorted(families)}")


# ---------------------------------------------------------------------------
# Discrimination seeds (witness EXECUTION) — solo-per-test pools via tmp_path
# ---------------------------------------------------------------------------


def test_fractions_numerator_dual_assert_refutes_lie(tmp_path: Path) -> None:
    """truthful numerator + lying numerator share euf key → unsat via witness."""
    src = (
        "from fractions import Fraction\n"
        "def t_true():\n"
        "    assert Fraction(3, 4).numerator == 3\n"
        "def t_lie():\n"
        "    assert Fraction(3, 4).numerator == 0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    blob = repr(report.payload.ir)
    assert "call:numerator" in blob
    assert "call:fractions.Fraction" in blob or "Fraction" in blob
    names = [r.name or "" for r in report.payload.ir if "#euf#" in (r.name or "")]
    assert len(names) == 2
    assert names[0] == names[1]

    result = run_source_through_real_solver(tmp_path / "numerator-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses


def test_fractions_add_dual_assert_refutes_lie(tmp_path: Path) -> None:
    """Fraction add via int() — truthful vs lying concrete RHS → unsat."""
    src = (
        "from fractions import Fraction\n"
        "def t_true():\n"
        "    assert int(Fraction(1, 2) + Fraction(1, 2)) == 1\n"
        "def t_lie():\n"
        "    assert int(Fraction(1, 2) + Fraction(1, 2)) == 0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    blob = repr(report.payload.ir)
    assert "call:fractions.Fraction" in blob or "Fraction" in blob

    result = run_source_through_real_solver(tmp_path / "add-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses


def test_fractions_limit_denominator_dual_assert_refutes_lie(tmp_path: Path) -> None:
    """limit_denominator method coordinate discriminates via concrete int attr."""
    src = (
        "from fractions import Fraction\n"
        "def t_true():\n"
        "    assert Fraction(3.14159).limit_denominator(10).numerator == 22\n"
        "def t_lie():\n"
        "    assert Fraction(3.14159).limit_denominator(10).numerator == 0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    blob = repr(report.payload.ir)
    assert "call:limit_denominator" in blob

    result = run_source_through_real_solver(tmp_path / "limit-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses


if __name__ == "__main__":
    results = run_fractions_coverage()
    print(_summarize(results))
    raise SystemExit(1 if any(not r.ok for r in results) else 0)
