"""stdlib ``pathlib`` vendor-op coordinate coverage (Part of #3809).

Sixth vendor after numpy/pandas/statistics/decimal/fractions. Pure-python path
surface: on 3.12 a single ``pathlib.py``; on 3.13+ a ``pathlib/`` package.
Resolve to the module file or package dir — never the parent stdlib tree
(the #4001 trap). Prefer ``PurePath`` shapes (no filesystem I/O).

## Locator dual identity (same law as prior vendors)

| layer | form | example |
|-------|------|---------|
| FOL / OpaqueOpCallsite | ``call:pathlib.<Name>(…)`` | ``call:pathlib.PurePath(…)`` |
| Method on PurePath | ``call:<method>(receiver)`` | ``call:with_suffix(…)`` |
| Attribute | ``call:<attr>(receiver)`` | ``call:suffix(…)`` / ``call:name(…)`` |
| Keyword args | ``kw:<name>(value)`` | when present on public API |

## Discrimination law (opaque vendor ops)

- ``computed=None`` when the body is not foldable — never fabricate.
- Dual-assert witness EXECUTION is the discrimination gate (shared euf key → unsat).
- Concrete str RHS for EUF inequality (``.suffix == '.txt'`` vs ``== ''``).

## Dig residual (not a construction gap)

Body dig of some ``pathlib`` call sites may refuse on imported callee source.
Coordinate emission still succeeds; construction-gap R for the module is 0.
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
# Real API matrix (consumer shapes) — PurePath preferred (no FS I/O)
# ---------------------------------------------------------------------------

_CTORS: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "PurePath_str",
        "from pathlib import PurePath\ndef t():\n    assert PurePath('a/b.txt') == PurePath('a/b.txt')\n",
        frozenset({"PurePath"}),
    ),
    (
        "PurePath_parts_ctor",
        "from pathlib import PurePath\ndef t():\n    assert PurePath('a', 'b.txt').name == 'b.txt'\n",
        frozenset({"PurePath", "name"}),
    ),
    (
        "Path_str",
        "from pathlib import Path\ndef t():\n    assert Path('a/b.txt').name == 'b.txt'\n",
        frozenset({"Path", "name"}),
    ),
    (
        "PurePosixPath",
        "from pathlib import PurePosixPath\ndef t():\n    assert PurePosixPath('a/b').as_posix() == 'a/b'\n",
        frozenset({"PurePosixPath", "as_posix"}),
    ),
    (
        "ctor_module_alias",
        "import pathlib as pl\ndef t():\n    assert pl.PurePath('x').name == 'x'\n",
        frozenset({"PurePath", "name"}),
    ),
)

_ATTRS: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "name",
        "from pathlib import PurePath\ndef t():\n    assert PurePath('a/b.txt').name == 'b.txt'\n",
        frozenset({"PurePath", "name"}),
    ),
    (
        "suffix",
        "from pathlib import PurePath\ndef t():\n    assert PurePath('a/b.txt').suffix == '.txt'\n",
        frozenset({"PurePath", "suffix"}),
    ),
    (
        "stem",
        "from pathlib import PurePath\ndef t():\n    assert PurePath('a/b.txt').stem == 'b'\n",
        frozenset({"PurePath", "stem"}),
    ),
    (
        "parent",
        "from pathlib import PurePath\ndef t():\n    assert PurePath('a/b.txt').parent.name == 'a'\n",
        frozenset({"PurePath", "parent", "name"}),
    ),
    (
        "parts",
        "from pathlib import PurePath\ndef t():\n    assert PurePath('a/b/c').parts[-1] == 'c'\n",
        frozenset({"PurePath", "parts"}),
    ),
    (
        "suffixes",
        "from pathlib import PurePath\ndef t():\n    assert PurePath('a/b.tar.gz').suffixes == ['.tar', '.gz']\n",
        frozenset({"PurePath", "suffixes"}),
    ),
)

_METHODS: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "joinpath",
        "from pathlib import PurePath\ndef t():\n    assert PurePath('a').joinpath('b.txt').name == 'b.txt'\n",
        frozenset({"PurePath", "joinpath", "name"}),
    ),
    (
        "with_suffix",
        "from pathlib import PurePath\ndef t():\n    assert PurePath('a/b.txt').with_suffix('.md').suffix == '.md'\n",
        frozenset({"PurePath", "with_suffix", "suffix"}),
    ),
    (
        "with_name",
        "from pathlib import PurePath\ndef t():\n    assert PurePath('a/b.txt').with_name('c.py').name == 'c.py'\n",
        frozenset({"PurePath", "with_name", "name"}),
    ),
    (
        "relative_to",
        "from pathlib import PurePath\ndef t():\n    assert PurePath('a/b/c').relative_to('a').as_posix() == 'b/c'\n",
        frozenset({"PurePath", "relative_to", "as_posix"}),
    ),
    (
        "as_posix",
        "from pathlib import PurePath\ndef t():\n    assert PurePath('a/b').as_posix() == 'a/b'\n",
        frozenset({"PurePath", "as_posix"}),
    ),
    (
        "is_absolute",
        "from pathlib import PurePath\ndef t():\n    assert not PurePath('a/b').is_absolute()\n",
        frozenset({"PurePath", "is_absolute"}),
    ),
    (
        "match",
        "from pathlib import PurePath\ndef t():\n    assert PurePath('a/b.txt').match('*.txt')\n",
        frozenset({"PurePath", "match"}),
    ),
    (
        "with_stem",
        "from pathlib import PurePath\ndef t():\n    assert PurePath('a/b.txt').with_stem('c').name == 'c.txt'\n",
        frozenset({"PurePath", "with_stem", "name"}),
    ),
)

_COMPARE: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "eq",
        "from pathlib import PurePath\ndef t():\n    assert PurePath('a/b') == PurePath('a/b')\n",
        frozenset({"PurePath"}),
    ),
    (
        "truediv",
        "from pathlib import PurePath\ndef t():\n    assert (PurePath('a') / 'b.txt').name == 'b.txt'\n",
        frozenset({"PurePath", "name"}),
    ),
    (
        "ne",
        "from pathlib import PurePath\ndef t():\n    assert PurePath('a') != PurePath('b')\n",
        frozenset({"PurePath"}),
    ),
)

_KW_SHAPES: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "relative_to_kw_walk_up",
        # walk_up added in 3.12; still a real kw shape when present.
        "from pathlib import PurePath\ndef t():\n    assert PurePath('a/b').relative_to(PurePath('a'), walk_up=False).as_posix() == 'b'\n",
        frozenset({"kw:walk_up"}),
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


def iter_pathlib_shapes() -> Iterable[tuple[str, str, str, frozenset[str], bool]]:
    """Yield (name, family, src, expected, expect_kw)."""
    for name, src, exp in _CTORS:
        yield (name, "ctor", src, exp, False)
    for name, src, exp in _ATTRS:
        yield (name, "attr", src, exp, False)
    for name, src, exp in _METHODS:
        yield (name, "method", src, exp, False)
    for name, src, exp in _COMPARE:
        yield (name, "compare", src, exp, False)
    for name, src, exp in _KW_SHAPES:
        yield (name, "kwarg", src, exp, True)


def run_pathlib_coverage() -> list[ShapeResult]:
    return [
        _lift_shape(name, family, src, expected, expect_kw=expect_kw)
        for name, family, src, expected, expect_kw in iter_pathlib_shapes()
    ]


def _summarize(results: list[ShapeResult]) -> str:
    total = len(results)
    bad = [r for r in results if not r.ok]
    dig = [r for r in results if r.dig_residual]
    lines = [
        f"pathlib-coverage total={total} ok={total - len(bad)} "
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


def test_pathlib_coordinate_coverage_zero_gaps() -> None:
    """Real PurePath/Path API shapes emit coordinates — 0 construction gaps."""
    results = run_pathlib_coverage()
    summary = _summarize(results)
    bad = [r for r in results if not r.ok]
    print(summary)
    assert len(results) >= 20, f"coverage too narrow: {len(results)}\n{summary}"
    if bad:
        first = bad[0]
        pytest.fail(
            f"pathlib coordinate gap ({len(bad)}/{len(results)}):\n"
            f"  first={first.name} family={first.family} issues={first.issues}\n"
            f"{summary}"
        )


def test_pathlib_coverage_breadth_receipt() -> None:
    shapes = list(iter_pathlib_shapes())
    families = {f for _, f, _, _, _ in shapes}
    assert len(shapes) >= 20
    assert {"ctor", "attr", "method", "compare", "kwarg"} <= families
    print(f"breadth={len(shapes)} families={sorted(families)}")


# ---------------------------------------------------------------------------
# Discrimination seeds (witness EXECUTION) — solo-per-test pools via tmp_path
# ---------------------------------------------------------------------------


def test_pathlib_suffix_dual_assert_refutes_lie(tmp_path: Path) -> None:
    """truthful .suffix + lying .suffix share euf key → unsat via witness."""
    src = (
        "from pathlib import PurePath\n"
        "def t_true():\n"
        "    assert PurePath('a/b.txt').suffix == '.txt'\n"
        "def t_lie():\n"
        "    assert PurePath('a/b.txt').suffix == ''\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    blob = repr(report.payload.ir)
    assert "call:suffix" in blob
    assert "PurePath" in blob
    names = [r.name or "" for r in report.payload.ir if "#euf#" in (r.name or "")]
    assert len(names) == 2
    assert names[0] == names[1]

    result = run_source_through_real_solver(tmp_path / "suffix-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses


def test_pathlib_stem_dual_assert_refutes_lie(tmp_path: Path) -> None:
    """truthful .stem + lying .stem → unsat."""
    src = (
        "from pathlib import PurePath\n"
        "def t_true():\n"
        "    assert PurePath('a/b.txt').stem == 'b'\n"
        "def t_lie():\n"
        "    assert PurePath('a/b.txt').stem == ''\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    blob = repr(report.payload.ir)
    assert "call:stem" in blob

    result = run_source_through_real_solver(tmp_path / "stem-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses


def test_pathlib_name_dual_assert_refutes_lie(tmp_path: Path) -> None:
    """truthful .name + lying .name → unsat."""
    src = (
        "from pathlib import PurePath\n"
        "def t_true():\n"
        "    assert PurePath('a/b.txt').name == 'b.txt'\n"
        "def t_lie():\n"
        "    assert PurePath('a/b.txt').name == ''\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    blob = repr(report.payload.ir)
    assert "call:name" in blob

    result = run_source_through_real_solver(tmp_path / "name-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses


if __name__ == "__main__":
    results = run_pathlib_coverage()
    print(_summarize(results))
    raise SystemExit(1 if any(not r.ok for r in results) else 0)
