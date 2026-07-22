#!/usr/bin/env python3
"""Re-census resource ``with`` sites before NeverSuppresses enrollment.

Walks installed numpy/pandas (or paths given on the CLI). For each ``with``
item, classifies the manager by membrane authentication vs RuntimeSelected
residual shape, and groups by structural manager identity.

Does **not** enroll anything. Does **not** special-case ``open``.

Exit disposition evidence is structural only at this stage:
- membrane Expects / Suppresses (assertion managers already wired)
- unauthenticated Call / Name / Attribute / other → resource residual candidates
- optional scan for source-visible ``__exit__`` bodies that only return
  None/False (candidate NeverSuppresses proof rule input)

Usage (from repo / worktree root)::

    PYTHONPATH=implementations/python/sugar-lift-py-tests/src:\\
               implementations/python/sugar-source-tree/src:\\
               implementations/python/sugar-lift-python-source/src \\
      python implementations/python/sugar-lift-py-tests/scripts/resource_with_recensus.py \\
        --packages numpy,pandas --json docs/resource-with-recensus.json
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator


# ---------------------------------------------------------------------------
# Structural manager identity (stdlib ast — no sugar construction required)
# ---------------------------------------------------------------------------


def _dotted(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        if base is None:
            return None
        return f"{base}.{node.attr}"
    return None


def _manager_shape(node: ast.AST) -> tuple[str, str]:
    """Return (shape_kind, identity_key).

    shape_kind:
      call_dotted | call_other | name | attribute | other
    identity_key is a stable grouping string for that shape.
    """
    if isinstance(node, ast.Call):
        dotted = _dotted(node.func)
        if dotted is not None:
            return "call_dotted", dotted
        return "call_other", type(node.func).__name__
    if isinstance(node, ast.Name):
        return "name", node.id
    if isinstance(node, ast.Attribute):
        dotted = _dotted(node)
        if dotted is not None:
            return "attribute", dotted
        return "attribute", f"*.{node.attr}"
    return "other", type(node).__name__


def _call_arg_sketch(node: ast.Call) -> str:
    """Coarse arity sketch for grouping (not a second authority)."""
    n_pos = len(node.args)
    kws = sorted(k.arg or "**" for k in node.keywords)
    return f"pos={n_pos};kw={','.join(kws) if kws else '-'}"


# ---------------------------------------------------------------------------
# Membrane classification (same door production With uses)
# ---------------------------------------------------------------------------


def _membrane_class(manager_node) -> str:
    """expects | suppresses | never_suppresses | unauthenticated."""
    from sugar_lift_py_tests.context_manager_contract import (
        Expects,
        NeverSuppresses,
        RuntimeSelected,
        Suppresses,
    )
    from sugar_lift_py_tests.manifest_membrane import (
        contract_for_manager,
        default_community_manifest,
    )

    contract = contract_for_manager(default_community_manifest(), manager_node)
    if isinstance(contract, Expects):
        return "expects"
    if isinstance(contract, Suppresses):
        return "suppresses"
    if isinstance(contract, NeverSuppresses):
        return "never_suppresses"
    if isinstance(contract, RuntimeSelected):
        return "runtime_selected"
    return "unauthenticated"


def _sugar_with_nodes(path: Path) -> list[Any]:
    """Materialize sugar tree With nodes for one file (best-effort)."""
    from sugar_source_tree.tree import SourceFile

    try:
        sf = SourceFile.from_path(str(path))
    except Exception:
        return []
    found: list[Any] = []

    def walk(node) -> None:
        kind = getattr(node, "kind", None)
        if kind == "With":
            found.append(node)
        for name in getattr(node, "_child_fields", ()) or ():
            child = getattr(node, name, None)
            if child is None:
                continue
            if isinstance(child, tuple):
                for c in child:
                    walk(c)
            else:
                walk(child)

    try:
        walk(sf.root)
    except Exception:
        return found
    return found


# ---------------------------------------------------------------------------
# Source-visible __exit__ candidates (general NeverSuppresses rule input)
# ---------------------------------------------------------------------------


def _returns_only_none_or_false(body: list[ast.stmt]) -> bool:
    """True when every return is literal None/False and no bare return of other.

    Conservative: any non-return control (raise, yield) or non-literal return
    → False. Empty body / implicit None → True (Python default).
    """
    has_explicit = False
    for stmt in body:
        if isinstance(stmt, ast.Return):
            has_explicit = True
            v = stmt.value
            if v is None:
                continue  # bare return → None
            if isinstance(v, ast.Constant) and v.value in (None, False):
                continue
            return False
        if isinstance(stmt, (ast.Raise, ast.Yield, ast.YieldFrom)):
            return False
        # Recurse into simple compound statements conservatively
        for child in ast.iter_child_nodes(stmt):
            if isinstance(child, ast.stmt):
                # Nested function/class: ignore their bodies
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
            # Don't deep-walk compounds with branches here — require linear-ish
        if isinstance(stmt, (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.Match)):
            # Branching exit bodies need deeper proof; not candidates here
            return False
    return True  # all returns None/False, or implicit None


def scan_exit_never_suppress_candidates(path: Path) -> list[dict[str, Any]]:
    """Find methods named __exit__ whose body returns only None/False."""
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(path))
    except (SyntaxError, OSError, UnicodeError):
        return []
    out: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != "__exit__":
            continue
        if not _returns_only_none_or_false(list(node.body)):
            continue
        # Qualify with enclosing class if any
        # (best-effort: walk parents not available on ast — use line only)
        out.append(
            {
                "file": str(path),
                "line": node.lineno,
                "qualname": node.name,
                "evidence": "source_visible_exit_returns_none_or_false",
            }
        )
    return out


# ---------------------------------------------------------------------------
# File walk
# ---------------------------------------------------------------------------


@dataclass
class WithHit:
    file: str
    line: int
    shape: str
    identity: str
    arity_sketch: str
    membrane: str  # expects|suppresses|never_suppresses|unauthenticated|unknown
    residual: str  # assertion_wired | resource_candidate | never_suppresses_enrolled


@dataclass
class FileReport:
    path: str
    with_items: int = 0
    parse_error: str | None = None
    hits: list[WithHit] = field(default_factory=list)


def package_root(name: str) -> Path:
    spec = importlib.util.find_spec(name)
    if spec is None or not spec.origin:
        raise SystemExit(f"package {name!r} not importable")
    return Path(spec.origin).resolve().parent


def iter_py_files(root: Path) -> Iterator[Path]:
    for p in sorted(root.rglob("*.py")):
        # skip caches / tests of sugar itself
        parts = set(p.parts)
        if "__pycache__" in parts or ".git" in parts:
            continue
        yield p


def census_file_ast(path: Path) -> FileReport:
    """Primary census: stdlib ast + membrane on sugar nodes when available."""
    rel = str(path)
    report = FileReport(path=rel)
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=rel)
    except SyntaxError as e:
        report.parse_error = f"SyntaxError: {e}"
        return report
    except OSError as e:
        report.parse_error = f"OSError: {e}"
        return report

    for node in ast.walk(tree):
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        for item in node.items:
            report.with_items += 1
            shape, identity = _manager_shape(item.context_expr)
            arity = ""
            if isinstance(item.context_expr, ast.Call):
                arity = _call_arg_sketch(item.context_expr)
            # Membrane needs sugar tree node — fill later or leave unknown
            report.hits.append(
                WithHit(
                    file=rel,
                    line=getattr(item.context_expr, "lineno", node.lineno),
                    shape=shape,
                    identity=identity,
                    arity_sketch=arity,
                    membrane="unknown",
                    residual="resource_candidate"
                    if shape != "call_dotted"
                    else "resource_candidate",
                )
            )
    return report


def attach_membrane_classifications(path: Path, report: FileReport) -> None:
    """Best-effort membrane classify by matching sugar With items to AST hits."""
    with_nodes = _sugar_with_nodes(path)
    if not with_nodes:
        return
    # Flatten sugar items with line numbers
    sugar_items: list[tuple[int, Any, str]] = []
    for w in with_nodes:
        try:
            for item in w.items:
                lc = item.line_col_span()
                membrane = _membrane_class(item.context_expr)
                sugar_items.append((lc.start_line, item, membrane))
        except Exception:
            continue
    # Match by line number
    by_line: dict[int, list[str]] = defaultdict(list)
    for line, _item, membrane in sugar_items:
        by_line[line].append(membrane)
    for hit in report.hits:
        membranes = by_line.get(hit.line)
        if not membranes:
            continue
        # take first membrane for that line
        m = membranes.pop(0)
        hit.membrane = m
        if m in ("expects", "suppresses"):
            hit.residual = "assertion_wired"
        elif m == "never_suppresses":
            hit.residual = "never_suppresses_enrolled"
        else:
            hit.residual = "resource_candidate"


def _manifest_spellings() -> dict[str, str]:
    """spelling → contract kind (expects|suppresses|never-suppresses)."""
    try:
        from sugar_lift_py_tests.manifest_membrane import default_community_manifest

        return {
            row.spelling: row.contract
            for row in default_community_manifest().rows
        }
    except Exception:
        return {}


def _classify_hit(hit: WithHit, spellings: dict[str, str]) -> None:
    """Fill membrane/residual from community spelling when sugar membrane skipped."""
    if hit.membrane != "unknown":
        return
    contract = spellings.get(hit.identity)
    if contract == "expects":
        hit.membrane = "expects"
        hit.residual = "assertion_wired"
    elif contract == "suppresses":
        hit.membrane = "suppresses"
        hit.residual = "assertion_wired"
    elif contract == "never-suppresses":
        hit.membrane = "never_suppresses"
        hit.residual = "never_suppresses_enrolled"
    else:
        hit.residual = "resource_candidate"


def summarize(reports: list[FileReport], exit_candidates: list[dict]) -> dict[str, Any]:
    spellings = _manifest_spellings()
    hits = [h for r in reports for h in r.hits]
    for h in hits:
        _classify_hit(h, spellings)

    by_identity: dict[str, dict[str, Any]] = {}
    identity_counter: Counter[str] = Counter()
    residual_counter: Counter[str] = Counter()
    shape_counter: Counter[str] = Counter()
    membrane_counter: Counter[str] = Counter()

    for h in hits:
        identity_counter[h.identity] += 1
        residual_counter[h.residual] += 1
        shape_counter[h.shape] += 1
        membrane_counter[h.membrane] += 1
        bucket = by_identity.setdefault(
            h.identity,
            {
                "identity": h.identity,
                "shape": h.shape,
                "count": 0,
                "residuals": Counter(),
                "membranes": Counter(),
                "arity_sketches": Counter(),
                "sample_loci": [],
            },
        )
        bucket["count"] += 1
        bucket["residuals"][h.residual] += 1
        bucket["membranes"][h.membrane] += 1
        if h.arity_sketch:
            bucket["arity_sketches"][h.arity_sketch] += 1
        if len(bucket["sample_loci"]) < 5:
            bucket["sample_loci"].append(f"{h.file}:{h.line}")

    groups = []
    for identity, bucket in sorted(
        by_identity.items(), key=lambda kv: (-kv[1]["count"], kv[0])
    ):
        groups.append(
            {
                "identity": identity,
                "shape": bucket["shape"],
                "count": bucket["count"],
                "residuals": dict(bucket["residuals"]),
                "membranes": dict(bucket["membranes"]),
                "arity_sketches": dict(bucket["arity_sketches"]),
                "sample_loci": bucket["sample_loci"],
                "enrollment_posture": (
                    "already_wired_assertion"
                    if bucket["residuals"].get("assertion_wired", 0)
                    == bucket["count"]
                    else (
                        "never_suppresses_enrolled"
                        if bucket["residuals"].get("never_suppresses_enrolled", 0)
                        else "resource_loud_candidate"
                    )
                ),
            }
        )

    resource_groups = [
        g for g in groups if g["enrollment_posture"] == "resource_loud_candidate"
    ]
    assertion_groups = [
        g for g in groups if g["enrollment_posture"] == "already_wired_assertion"
    ]

    return {
        "files_scanned": len(reports),
        "files_parse_error": sum(1 for r in reports if r.parse_error),
        "with_items_total": sum(r.with_items for r in reports),
        "hits": len(hits),
        "by_residual": dict(residual_counter),
        "by_shape": dict(shape_counter),
        "by_membrane": dict(membrane_counter),
        "manifest_spellings": spellings,
        "top_identities": identity_counter.most_common(40),
        "resource_loud_groups": resource_groups[:80],
        "assertion_wired_groups": assertion_groups[:40],
        "exit_never_suppress_candidates": {
            "count": len(exit_candidates),
            "sample": exit_candidates[:30],
        },
        "recommended_next_proof_rule": {
            "name": "source_visible_exit_returns_none_or_false",
            "disposition": "NeverSuppresses",
            "rule": (
                "When a manager's __exit__ is source-visible and every return "
                "is provably None or False (implicit None allowed; branches "
                "allowed only if they never return a suppressing truth value), "
                "issue NeverSuppresses. Admit via WithResourceSugar only with "
                "constructed enter/exit coords. Do not special-case open by "
                "name; built-ins need an attested semantic manifest later."
            ),
            "first_general_admits_after_rule": [
                "np.errstate / errstate (~315 sites; restore-only __exit__)",
                "option_context family (~407 sites; restore-only with branches)",
                "util.switchdir (37 sites; try/yield/finally)",
            ],
            "do_not": [
                "enroll open by spelling",
                "guess subclass exception matching",
                "admit RuntimeSelected as green",
            ],
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--packages",
        default="numpy,pandas",
        help="Comma-separated importable packages (default: numpy,pandas)",
    )
    ap.add_argument(
        "--roots",
        default="",
        help="Optional extra roots (colon-separated paths) instead of/in addition",
    )
    ap.add_argument("--json", default="", help="Write full JSON report here")
    ap.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Cap files per root (0 = no cap)",
    )
    ap.add_argument(
        "--membrane",
        action="store_true",
        help="Attach membrane classification via sugar tree (slower)",
    )
    ap.add_argument(
        "--scan-exit",
        action="store_true",
        default=True,
        help="Scan for source-visible __exit__ None/False candidates (default on)",
    )
    ap.add_argument("--no-scan-exit", action="store_false", dest="scan_exit")
    args = ap.parse_args(argv)

    roots: list[Path] = []
    for name in args.packages.split(","):
        name = name.strip()
        if not name:
            continue
        roots.append(package_root(name))
    if args.roots:
        for part in args.roots.split(":"):
            part = part.strip()
            if part:
                roots.append(Path(part).resolve())

    reports: list[FileReport] = []
    exit_candidates: list[dict[str, Any]] = []
    for root in roots:
        files = list(iter_py_files(root))
        if args.max_files:
            files = files[: args.max_files]
        print(f"# root {root} files={len(files)}", flush=True)
        for i, path in enumerate(files, 1):
            if i % 200 == 0:
                print(f"  … {i}/{len(files)}", flush=True)
            report = census_file_ast(path)
            if args.membrane and report.with_items:
                try:
                    attach_membrane_classifications(path, report)
                except Exception as e:
                    report.parse_error = (report.parse_error or "") + f" membrane:{e}"
            reports.append(report)
            if args.scan_exit:
                exit_candidates.extend(scan_exit_never_suppress_candidates(path))

    summary = summarize(reports, exit_candidates)
    # Human-readable
    print()
    print("=== resource-with re-census ===")
    print(f"files_scanned: {summary['files_scanned']}")
    print(f"with_items_total: {summary['with_items_total']}")
    print(f"by_residual: {summary['by_residual']}")
    print(f"by_shape: {summary['by_shape']}")
    print(f"by_membrane: {summary['by_membrane']}")
    print()
    print("--- top manager identities ---")
    for identity, count in summary["top_identities"][:25]:
        print(f"  {count:5d}  {identity}")
    print()
    print("--- top resource-loud groups ---")
    for g in summary["resource_loud_groups"][:25]:
        print(
            f"  {g['count']:5d}  {g['identity']!r}  shape={g['shape']}  "
            f"membranes={g['membranes']}"
        )
        for loc in g["sample_loci"][:2]:
            print(f"           e.g. {loc}")
    print()
    print(
        f"source-visible __exit__ None/False candidates: "
        f"{summary['exit_never_suppress_candidates']['count']}"
    )
    for row in summary["exit_never_suppress_candidates"]["sample"][:10]:
        print(f"  {row['file']}:{row['line']}")
    print()
    print("recommended_next_proof_rule:")
    print(f"  {summary['recommended_next_proof_rule']['name']}")
    print(f"  {summary['recommended_next_proof_rule']['rule']}")

    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Convert Counters already done; write summary
        out_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        print(f"\n# wrote {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
