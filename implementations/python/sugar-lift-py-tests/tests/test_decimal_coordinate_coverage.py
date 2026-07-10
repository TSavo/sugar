"""stdlib ``decimal`` vendor-op coordinate coverage (Part of #3809).

Fourth vendor after numpy/pandas/statistics. Public ``decimal`` prefers the C
accelerator ``_decimal`` when present; the construction-gap audit resolves the
pure-python body ``_pydecimal.py`` (see panic-audit resolver). Consumer
coordinate shapes still use the public ``decimal`` import names.

## Locator dual identity (same law as numpy/pandas/statistics)

| layer | form | example |
|-------|------|---------|
| FOL / OpaqueOpCallsite | ``call:decimal.<Name>(…)`` | ``call:decimal.Decimal(i:1)`` |
| Method on Decimal | ``call:<method>(receiver)`` | ``call:sqrt(call:decimal.Decimal(i:4))`` |
| Keyword args | ``kw:<name>(value)`` | ``call:quantize(…, kw:rounding(…))`` |

## Discrimination law (opaque vendor ops)

- ``computed=None`` when the body is not foldable (C Decimal has no pure-python
  class definition for dig) — never fabricate.
- Dual-assert witness EXECUTION is the discrimination gate (shared euf key →
  unsat). RHS must be a concrete literal (int/str); opaque Decimal RHS does not
  force EUF inequality and can stay sat.

## Dig residual (not a construction gap)

Body dig of ``decimal.Decimal`` refuses with "could not find class definition"
because the installed runtime is C ``_decimal``. Coordinate emission still
succeeds; construction-gap R for the pure-python ``_pydecimal.py`` file is 0.
Dig residual is recorded for visibility, not counted as a coordinate gap.
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

# (name, source, expected call: bases — match call:X or call:decimal.X)
_CTORS: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "ctor_int",
        "from decimal import Decimal\ndef t():\n    assert Decimal(1) == Decimal(1)\n",
        frozenset({"Decimal"}),
    ),
    (
        "ctor_str",
        'from decimal import Decimal\ndef t():\n    assert Decimal("1.5") == Decimal("1.5")\n',
        frozenset({"Decimal"}),
    ),
    (
        "from_float",
        "from decimal import Decimal\ndef t():\n    assert Decimal.from_float(1.0) == Decimal(1)\n",
        frozenset({"Decimal", "from_float"}),
    ),
    (
        "ctor_module_alias",
        "import decimal as d\ndef t():\n    assert d.Decimal(2) == d.Decimal(2)\n",
        frozenset({"Decimal"}),
    ),
)

_METHODS: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "quantize",
        'from decimal import Decimal\ndef t():\n    assert Decimal("1.234").quantize(Decimal("0.01")) == Decimal("1.23")\n',
        frozenset({"Decimal", "quantize"}),
    ),
    (
        "sqrt",
        "from decimal import Decimal\ndef t():\n    assert Decimal(4).sqrt() == Decimal(2)\n",
        frozenset({"Decimal", "sqrt"}),
    ),
    (
        "compare",
        "from decimal import Decimal\ndef t():\n    assert Decimal(1).compare(Decimal(2)) == Decimal(-1)\n",
        frozenset({"Decimal", "compare"}),
    ),
    (
        "compare_total",
        "from decimal import Decimal\ndef t():\n    assert Decimal(1).compare_total(Decimal(1)) == Decimal(0)\n",
        frozenset({"Decimal", "compare_total"}),
    ),
    (
        "as_tuple",
        'from decimal import Decimal\ndef t():\n    assert Decimal("1.5").as_tuple() is not None\n',
        frozenset({"Decimal", "as_tuple"}),
    ),
    (
        "normalize",
        'from decimal import Decimal\ndef t():\n    assert Decimal("1.50").normalize() == Decimal("1.5")\n',
        frozenset({"Decimal", "normalize"}),
    ),
    (
        "is_nan",
        'from decimal import Decimal\ndef t():\n    assert Decimal("NaN").is_nan()\n',
        frozenset({"Decimal", "is_nan"}),
    ),
    (
        "is_finite",
        "from decimal import Decimal\ndef t():\n    assert Decimal(1).is_finite()\n",
        frozenset({"Decimal", "is_finite"}),
    ),
    (
        "is_infinite",
        'from decimal import Decimal\ndef t():\n    assert Decimal("Infinity").is_infinite()\n',
        frozenset({"Decimal", "is_infinite"}),
    ),
    (
        "copy_abs",
        "from decimal import Decimal\ndef t():\n    assert Decimal(-3).copy_abs() == Decimal(3)\n",
        frozenset({"Decimal", "copy_abs"}),
    ),
    (
        "copy_negate",
        "from decimal import Decimal\ndef t():\n    assert Decimal(3).copy_negate() == Decimal(-3)\n",
        frozenset({"Decimal", "copy_negate"}),
    ),
    (
        "exp",
        "from decimal import Decimal\ndef t():\n    assert Decimal(0).exp() == Decimal(1)\n",
        frozenset({"Decimal", "exp"}),
    ),
    (
        "ln",
        "from decimal import Decimal\ndef t():\n    assert Decimal(1).ln() == Decimal(0)\n",
        frozenset({"Decimal", "ln"}),
    ),
    (
        "log10",
        "from decimal import Decimal\ndef t():\n    assert Decimal(100).log10() == Decimal(2)\n",
        frozenset({"Decimal", "log10"}),
    ),
    (
        "max_method",
        "from decimal import Decimal\ndef t():\n    assert Decimal(1).max(Decimal(2)) == Decimal(2)\n",
        frozenset({"Decimal", "max"}),
    ),
    (
        "min_method",
        "from decimal import Decimal\ndef t():\n    assert Decimal(1).min(Decimal(2)) == Decimal(1)\n",
        frozenset({"Decimal", "min"}),
    ),
    (
        "to_integral",
        'from decimal import Decimal\ndef t():\n    assert Decimal("1.9").to_integral() == Decimal(2)\n',
        frozenset({"Decimal", "to_integral"}),
    ),
    (
        "fma",
        "from decimal import Decimal\ndef t():\n    assert Decimal(2).fma(Decimal(3), Decimal(4)) == Decimal(10)\n",
        frozenset({"Decimal", "fma"}),
    ),
)

_ATTRS: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "real_attr",
        "from decimal import Decimal\ndef t():\n    assert Decimal(1).real == Decimal(1)\n",
        frozenset({"Decimal", "real"}),
    ),
)

_ARITH: tuple[tuple[str, str, frozenset[str]], ...] = (
    # Binary ops on C Decimal often lower without call: tokens; force coords
    # via int()/method so the shape still pins the public Decimal surface.
    (
        "add_via_int",
        "from decimal import Decimal\ndef t():\n    assert int(Decimal(1) + Decimal(2)) == 3\n",
        frozenset({"Decimal", "int"}),
    ),
    (
        "mul_via_int",
        "from decimal import Decimal\ndef t():\n    assert int(Decimal(2) * Decimal(3)) == 6\n",
        frozenset({"Decimal", "int"}),
    ),
    (
        "sub_via_int",
        "from decimal import Decimal\ndef t():\n    assert int(Decimal(5) - Decimal(2)) == 3\n",
        frozenset({"Decimal", "int"}),
    ),
    (
        "div_via_int",
        "from decimal import Decimal\ndef t():\n    assert int(Decimal(6) / Decimal(2)) == 3\n",
        frozenset({"Decimal", "int"}),
    ),
    (
        "mod_via_int",
        "from decimal import Decimal\ndef t():\n    assert int(Decimal(7) % Decimal(4)) == 3\n",
        frozenset({"Decimal", "int"}),
    ),
    (
        "abs_builtin",
        "from decimal import Decimal\ndef t():\n    assert abs(Decimal(-3)) == Decimal(3)\n",
        frozenset({"Decimal", "abs"}),
    ),
)

_MODULE: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "getcontext_prec",
        "from decimal import getcontext\ndef t():\n    assert getcontext().prec > 0\n",
        frozenset({"getcontext", "prec"}),
    ),
)

_KW_SHAPES: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "quantize_kw_rounding",
        'from decimal import Decimal, ROUND_HALF_UP\ndef t():\n    assert Decimal("1.25").quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) == Decimal("1.3")\n',
        frozenset({"kw:rounding"}),
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


def iter_decimal_shapes() -> Iterable[tuple[str, str, str, frozenset[str], bool]]:
    """Yield (name, family, src, expected, expect_kw)."""
    for name, src, exp in _CTORS:
        yield (name, "ctor", src, exp, False)
    for name, src, exp in _METHODS:
        yield (name, "method", src, exp, False)
    for name, src, exp in _ATTRS:
        yield (name, "attr", src, exp, False)
    for name, src, exp in _ARITH:
        yield (name, "arith", src, exp, False)
    for name, src, exp in _MODULE:
        yield (name, "module", src, exp, False)
    for name, src, exp in _KW_SHAPES:
        yield (name, "kwarg", src, exp, True)


def run_decimal_coverage() -> list[ShapeResult]:
    return [
        _lift_shape(name, family, src, expected, expect_kw=expect_kw)
        for name, family, src, expected, expect_kw in iter_decimal_shapes()
    ]


def _summarize(results: list[ShapeResult]) -> str:
    total = len(results)
    bad = [r for r in results if not r.ok]
    dig = [r for r in results if r.dig_residual]
    lines = [
        f"decimal-coverage total={total} ok={total - len(bad)} "
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


def test_decimal_coordinate_coverage_zero_gaps() -> None:
    """Real Decimal API shapes emit coordinates — 0 construction gaps."""
    results = run_decimal_coverage()
    summary = _summarize(results)
    bad = [r for r in results if not r.ok]
    print(summary)
    assert len(results) >= 20, f"coverage too narrow: {len(results)}\n{summary}"
    if bad:
        first = bad[0]
        pytest.fail(
            f"decimal coordinate gap ({len(bad)}/{len(results)}):\n"
            f"  first={first.name} family={first.family} issues={first.issues}\n"
            f"{summary}"
        )


def test_decimal_coverage_breadth_receipt() -> None:
    shapes = list(iter_decimal_shapes())
    families = {f for _, f, _, _, _ in shapes}
    assert len(shapes) >= 20
    assert {"ctor", "method", "attr", "arith", "module", "kwarg"} <= families
    print(f"breadth={len(shapes)} families={sorted(families)}")


# ---------------------------------------------------------------------------
# Discrimination seeds (witness EXECUTION)
# ---------------------------------------------------------------------------


def test_decimal_sqrt_dual_assert_refutes_lie(tmp_path: Path) -> None:
    """truthful sqrt + lying sqrt share euf key → unsat via witness.

    RHS is a concrete int (via int()) — opaque Decimal RHS does not force EUF
    inequality and would stay sat.
    """
    src = (
        "from decimal import Decimal\n"
        "def t_true():\n"
        "    assert int(Decimal(4).sqrt()) == 2\n"
        "def t_lie():\n"
        "    assert int(Decimal(4).sqrt()) == 0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    blob = repr(report.payload.ir)
    assert "call:sqrt" in blob
    assert "call:decimal.Decimal" in blob
    names = [r.name or "" for r in report.payload.ir if "#euf#" in (r.name or "")]
    assert len(names) == 2
    assert names[0] == names[1]

    result = run_source_through_real_solver(tmp_path / "sqrt-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses


def test_decimal_quantize_dual_assert_refutes_lie(tmp_path: Path) -> None:
    """quantize method coordinate discriminates via str() concrete RHS."""
    src = (
        "from decimal import Decimal\n"
        "def t_true():\n"
        '    assert str(Decimal("1.234").quantize(Decimal("0.01"))) == "1.23"\n'
        "def t_lie():\n"
        '    assert str(Decimal("1.234").quantize(Decimal("0.01"))) == "0"\n'
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    blob = repr(report.payload.ir)
    assert "call:quantize" in blob
    assert "call:decimal.Decimal" in blob

    result = run_source_through_real_solver(tmp_path / "quantize-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses


def test_decimal_compare_dual_assert_refutes_lie(tmp_path: Path) -> None:
    """compare method coordinate discriminates via int() concrete RHS."""
    src = (
        "from decimal import Decimal\n"
        "def t_true():\n"
        "    assert int(Decimal(1).compare(Decimal(2))) == -1\n"
        "def t_lie():\n"
        "    assert int(Decimal(1).compare(Decimal(2))) == 0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    blob = repr(report.payload.ir)
    assert "call:compare" in blob

    result = run_source_through_real_solver(tmp_path / "compare-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses


if __name__ == "__main__":
    results = run_decimal_coverage()
    print(_summarize(results))
    raise SystemExit(1 if any(not r.ok for r in results) else 0)
