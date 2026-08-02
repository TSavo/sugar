#!/usr/bin/env python3
"""C5 residual-family twin census — pure code inventory (no corpus measure).

Enumerates residual product families from production closed vocabularies and
reports whether test tree evidence exists for a truthful twin and a lying twin.

Exit 0 always (measurement/orientation artifact). Writes markdown under
docs/audits/c5-residual-family-twin-census.md when --write is set.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYR = ROOT / "implementations" / "python"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _enum_string_members(path: Path, class_name: str) -> list[tuple[str, str]]:
    text = _read(path)
    match = re.search(rf"class {class_name}\b.*?(?=\nclass |\Z)", text, re.S)
    if not match:
        return []
    return re.findall(
        r"^\s{4}([A-Z][A-Z0-9_]*)\s*=\s*\"([^\"]+)\"", match.group(0), re.M
    )


def enumerate_families() -> list[tuple[str, str, str]]:
    families: list[tuple[str, str, str]] = []
    panic_path = PYR / "sugar-source-tree/src/sugar_source_tree/panic.py"
    for name, wire in _enum_string_members(panic_path, "WithConstructionGapKind"):
        families.append((f"WithConstructionGapKind.{name}", wire, "WithConstructionGapKind"))

    panic = _read(panic_path)
    for match in re.finditer(r"^class (\w+)\(([^)]+)\):", panic, re.M):
        cls, bases = match.group(1), match.group(2)
        if cls == "SourceTreePanic":
            continue
        residual = (
            "SugarNotWritten",
            "WithConstructionGap",
            "SourceTreePanic",
            "VocabularyMissing",
            "BackendDefect",
            "SubstituteNotWritten",
        )
        if cls in residual or any(b in bases for b in residual):
            families.append((f"panic.{cls}", cls, "panic_class"))

    gap_path = PYR / "sugar-lift-py-tests/src/sugar_lift_py_tests/gap/info.py"
    for name, wire in _enum_string_members(gap_path, "GapKind"):
        families.append((f"GapKind.{name}", wire, "GapKind"))

    families.append(("ConstructionPanic", "ConstructionPanic", "construction_panic"))
    for cat in (
        "completed",
        "construction-panic",
        "backend-defect",
        "instrument-defect-unresolvable-dispatch",
    ):
        families.append((f"recensus.category.{cat}", cat, "recensus_category"))

    seen: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for row in families:
        if row[0] in seen:
            continue
        seen.add(row[0])
        out.append(row)
    return out


def load_test_corpus() -> list[tuple[Path, str]]:
    """Load a bounded set of twin/residual-related tests (no deep full-tree walk)."""
    paths: list[Path] = []
    # Prefer glob on known test roots only — full rglob of implementations/python
    # is huge and can starve interactive inventory runs.
    for base in (
        PYR / "sugar-lift-py-tests/tests",
        PYR / "sugar-lift-python-source/tests",
        PYR / "sugar-source-tree/tests",
    ):
        if not base.is_dir():
            continue
        paths.extend(sorted(base.glob("test_*.py")))
        paths.extend(sorted(base.glob("*/*twin*.py")))
    scripts = PYR / "sugar-lift-py-tests/scripts"
    if scripts.is_dir():
        paths.extend(sorted(scripts.glob("*twin*.py")))
        paths.extend(sorted(scripts.glob("*family*.py")))

    loaded: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        text = _read(path)
        if not text:
            continue
        if not re.search(
            r"truthful|lying|twin|WithConstructionGap|SugarNotWritten|"
            r"ConstructionPanic|GapKind|instrument-defect|backend-defect|"
            r"runtime-selected|call-graph-cycle|dynamic-export",
            text,
            re.I,
        ):
            continue
        loaded.append((path, text))
    return loaded


_TR = re.compile(r"truthful|SugarWitnessPair|good_twin", re.I)
_LY = re.compile(r"lying|bad_twin|flipping", re.I)


def evidence(
    wire: str, cls_token: str, loaded: list[tuple[Path, str]]
) -> tuple[bool, bool, str] | None:
    needles = [wire, cls_token, wire.replace("-", "_")]
    best: tuple[int, bool, bool, str] | None = None
    for path, text in loaded:
        if not any(
            n
            and len(n) >= 3
            and re.search(
                rf"(?<![A-Za-z0-9_\-]){re.escape(n)}(?![A-Za-z0-9_\-])", text
            )
            for n in needles
        ):
            continue
        has_t = bool(_TR.search(text) or re.search(r"def\s+test_\w*truthful", text, re.I))
        has_l = bool(_LY.search(text) or re.search(r"def\s+test_\w*lying", text, re.I))
        rel = str(path.relative_to(ROOT))
        score = (2 if has_t else 0) + (2 if has_l else 0) + (1 if "twin" in path.name else 0)
        if best is None or score > best[0]:
            best = (score, has_t, has_l, rel)
    if best is None:
        return None
    return best[1], best[2], best[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="write docs/audits/c5-residual-family-twin-census.md",
    )
    args = parser.parse_args(argv)

    families = enumerate_families()
    loaded = load_test_corpus()
    rows: list[tuple] = []
    for fam, wire, group in families:
        cls = fam.split(".")[-1]
        ev = evidence(wire, cls, loaded)
        if ev is None:
            rows.append((fam, wire, group, False, "—", False, "—", "neither"))
        else:
            has_t, has_l, rel = ev
            if has_t and has_l:
                status = "both"
            elif has_t:
                status = "truthful_only"
            elif has_l:
                status = "lying_only"
            else:
                status = "mentioned_no_twin_markers"
            rows.append(
                (
                    fam,
                    wire,
                    group,
                    has_t,
                    rel if has_t else "—",
                    has_l,
                    rel if has_l else "—",
                    status,
                )
            )

    both = sum(1 for r in rows if r[7] == "both")
    t_only = sum(1 for r in rows if r[7] == "truthful_only")
    l_only = sum(1 for r in rows if r[7] == "lying_only")
    neither = sum(1 for r in rows if r[7] in {"neither", "mentioned_no_twin_markers"})
    miss_l = sum(1 for r in rows if not r[5])
    miss_t = sum(1 for r in rows if not r[3])

    def short(path: str) -> str:
        if path == "—":
            return "—"
        return path if len(path) <= 72 else "…" + path[-69:]

    lines = [
        "# C5 residual-family twin census (code inventory)",
        "",
        "**Criterion 5:** every residual family must be proven by BOTH a truthful twin and a lying twin.",
        "**Method:** closed production vocabularies + panic hierarchy; twin presence via static scan of focused test trees for family wire/class tokens + truthful/lying markers.",
        "**Not a recensus measure.** No battleaxe. No corpus open.",
        "",
        "## Summary",
        "",
        "| metric | count |",
        "| --- | ---: |",
        f"| residual families inventoried | {len(rows)} |",
        f"| both twins (heuristic) | {both} |",
        f"| truthful only | {t_only} |",
        f"| lying only | {l_only} |",
        f"| neither / no twin markers | {neither} |",
        f"| **missing lying twin** | **{miss_l}** |",
        f"| missing truthful twin | {miss_t} |",
        "",
        "A family with **no lying twin** is a family we cannot prove we detect.",
        "",
        "### Related inventory (different domain)",
        "",
        "- Sugar/ProofIR **semantic family** C5: `scripts/semantic_family_twin_inventory_law.py` (factory `witnesses()` / ProofIR verdict pairs).",
        "- Static twin detection can **over-credit** a kind listed only in a multi-kind vocabulary test that also carries twin markers for another kind.",
        "- `NotVerdictBearing` opt-outs belong to the sugar-family inventory, not this residual table.",
        "",
        "## Table",
        "",
        "| family | wire / product | truthful | path | lying | path | status |",
        "| --- | --- | :---: | --- | :---: | --- | --- |",
    ]
    for fam, wire, _group, has_t, t_path, has_l, l_path, status in rows:
        lines.append(
            f"| `{fam}` | `{wire}` | {'yes' if has_t else 'no'} | `{short(t_path)}` | "
            f"{'yes' if has_l else 'no'} | `{short(l_path)}` | {status} |"
        )

    lines += ["", "## Missing lying twin", ""]
    for fam, wire, _g, _ht, _tp, has_l, _lp, _st in rows:
        if not has_l:
            lines.append(f"- `{fam}` (`{wire}`)")

    lines += ["", "## Group counts", ""]
    for key, count in sorted(Counter(r[2] for r in rows).items()):
        lines.append(f"- **{key}**: {count}")
    lines.append("")
    lines.append(
        "*Generated from code inventory only (`tools/c5_residual_family_twin_census.py`).*"
    )

    report = "\n".join(lines) + "\n"
    if args.write:
        out = ROOT / "docs/audits/c5-residual-family-twin-census.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"WROTE {out}", flush=True)

    print(
        f"n={len(rows)} both={both} t_only={t_only} l_only={l_only} "
        f"neither={neither} missing_lying={miss_l} missing_truthful={miss_t} "
        f"test_files_scanned={len(loaded)}",
        flush=True,
    )
    # Always print full table to stdout for the agent report
    print(report, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
