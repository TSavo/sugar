#!/usr/bin/env python3
"""R_construction_side_doors — permanent sole-path construction floor.

Construction IS correctness. The sole path is:

    SourceOracle → backend adapter → typed Node → substitute (shadow) → sugar

Prebound authenticated contract refs may enter as construction context.
**Green only when meaning is tree + prebound refs only.**

This instrument names every current construction-path side door. There is no
baseline, threshold, or allowlist. Exit 1 while R > 0. Prefer larger honest
red over hollow green.

Measure axes (combined R; every offender named by class):

1. **membrane-admission** — production construction admits With / manager
   meaning via spelling membrane, ``community_context_managers.json``,
   ``contract_for_manager`` / ``default_community_manifest`` /
   ``manifest_membrane`` / ``row_for_spelling`` (or equivalent).
2. **ast-semantic-above-adapter** — production code outside ``*_adapter.py``
   using ``import ast`` / ``ast.parse`` / ``ast.walk`` / ``ast.NodeVisitor``
   for semantic resolve/admit. Adapters may use ast. Scripts/audit/idd may
   use ast only when they never feed construction (excluded by scan root).
3. **dual-old-lifter** (optional axis) — production enumerate path still
   imports the old ``lifter`` / ``bind_lifter`` construction door.

Self-test (``--self-test``) plants both membrane and ast twins and proves
clean trees stay quiet. Live scan prints JSON with R and named offenders.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import tempfile
import traceback
from pathlib import Path
from typing import NamedTuple, Sequence


class SideDoorOffender(NamedTuple):
    path: str
    line: int
    kind: str
    axis: str
    expression: str
    note: str


_MEMBRANE_API_NAMES = frozenset(
    {
        "contract_for_manager",
        "default_community_manifest",
        "manifest_membrane",
        "row_for_spelling",
        "community_context_managers",
        "load_community_manifest",
        "community_manifest",
    }
)

_MEMBRANE_LITERAL_NEEDLES = (
    "community_context_managers.json",
    "community_context_managers",
    "manifest_membrane",
)

_OLD_LIFTER_MODULES = frozenset(
    {
        "sugar_lift_python_source.lifter",
        "sugar_lift_python_source.bind_lifter",
    }
)

_OLD_LIFTER_NAMES = frozenset({"lifter", "bind_lifter", "lift_source", "lift_paths"})

_SIDE_DOOR_KINDS = frozenset(
    {
        "membrane-admission-api",
        "membrane-spelling-manifest",
        "ast-semantic-import",
        "ast-semantic-parse",
        "ast-semantic-walk",
        "ast-semantic-visitor",
        "dual-old-lifter",
    }
)

_SKIP_DIR_NAMES = frozenset(
    {
        "__pycache__",
        "audit_only",
        "idd",
        "tests",
        "scripts",
        ".git",
    }
)

_ADAPTER_SUFFIX = "_adapter.py"


def _rel_path(root: Path, path: Path) -> str:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        rel = Path(path.name)
    return f"{root.name}/{rel.as_posix()}"


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception as exc:  # noqa: BLE001 — auditor containment
        return f"<unparse-failed:{type(exc).__name__}>"


def _qualified_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _is_adapter_path(path: Path) -> bool:
    return path.name.endswith(_ADAPTER_SUFFIX)


def _should_skip_dir(path: Path) -> bool:
    return path.name in _SKIP_DIR_NAMES


def _read_source(path: Path) -> tuple[str | None, SideDoorOffender | None]:
    try:
        return path.read_text(encoding="utf-8"), None
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8-sig"), None
        except UnicodeDecodeError:
            try:
                return path.read_text(encoding="utf-8", errors="replace"), None
            except OSError as exc:
                return None, SideDoorOffender(
                    path=path.as_posix(),
                    line=0,
                    kind="auditor-read-error",
                    axis="auditor",
                    expression=type(exc).__name__,
                    note=f"could not read source after utf-8 fallback: {exc}",
                )
    except OSError as exc:
        return None, SideDoorOffender(
            path=path.as_posix(),
            line=0,
            kind="auditor-read-error",
            axis="auditor",
            expression=type(exc).__name__,
            note=f"could not read source: {exc}",
        )


def _import_is_ast(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(alias.name == "ast" or alias.name.startswith("ast.") for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        return bool(node.module and node.module.split(".", 1)[0] == "ast")
    return False


def _import_is_old_lifter(node: ast.AST) -> tuple[bool, str]:
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name in _OLD_LIFTER_MODULES or alias.name.startswith(
                "sugar_lift_python_source.lifter"
            ) or alias.name.startswith("sugar_lift_python_source.bind_lifter"):
                return True, alias.name
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if module in _OLD_LIFTER_MODULES:
            names = ", ".join(a.name for a in node.names) or "*"
            return True, f"from {module} import {names}"
        if module == "sugar_lift_python_source":
            for alias in node.names:
                if alias.name in _OLD_LIFTER_NAMES:
                    return True, f"from sugar_lift_python_source import {alias.name}"
    return False, ""


def _membrane_name_hits(node: ast.AST) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    if isinstance(node, ast.Name) and node.id in _MEMBRANE_API_NAMES:
        hits.append((node.id, node.id))
    elif isinstance(node, ast.Attribute) and node.attr in _MEMBRANE_API_NAMES:
        hits.append((node.attr, _qualified_name(node)))
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                base = alias.name.split(".")[-1]
                if (
                    alias.name in _MEMBRANE_API_NAMES
                    or base in _MEMBRANE_API_NAMES
                    or "manifest_membrane" in alias.name
                ):
                    hits.append((base or alias.name, alias.name))
        else:
            module = node.module or ""
            if "manifest_membrane" in module or module.endswith("manifest_membrane"):
                hits.append(("manifest_membrane", f"from {module} import ..."))
            for alias in node.names:
                if alias.name in _MEMBRANE_API_NAMES:
                    hits.append((alias.name, f"from {module} import {alias.name}"))
    elif isinstance(node, ast.Constant) and isinstance(node.value, str):
        for needle in _MEMBRANE_LITERAL_NEEDLES:
            if needle in node.value:
                hits.append((needle, repr(node.value)))
                break
    return hits


def _ast_semantic_hits(node: ast.AST) -> list[tuple[str, str]]:
    """Return (kind-suffix, expression) for semantic-ast loci on this node."""
    hits: list[tuple[str, str]] = []
    if _import_is_ast(node):
        hits.append(("import", _safe_unparse(node)))
        return hits

    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id == "ast" and func.attr == "parse":
                hits.append(("parse", _safe_unparse(node)))
            elif func.value.id == "ast" and func.attr == "walk":
                hits.append(("walk", _safe_unparse(node)))
        if isinstance(func, ast.Name) and func.id == "parse":
            # only when bound from ast — cannot prove; skip bare parse
            pass

    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        if node.value.id == "ast" and node.attr == "NodeVisitor":
            hits.append(("visitor", _safe_unparse(node)))

    if isinstance(node, ast.ClassDef):
        for base in node.bases:
            qn = _qualified_name(base)
            if qn in {"ast.NodeVisitor", "NodeVisitor"} or qn.endswith(".NodeVisitor"):
                hits.append(("visitor", f"class {node.name}({qn})"))
    return hits


def scan_file(path: Path, *, rel: str) -> list[SideDoorOffender]:
    """Scan one production file. Read/parse failures become structured rows."""
    offenders: list[SideDoorOffender] = []
    source, read_error = _read_source(path)
    if read_error is not None:
        return [read_error._replace(path=rel)]
    assert source is not None
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [
            SideDoorOffender(
                path=rel,
                line=int(exc.lineno or 0),
                kind="auditor-parse-error",
                axis="auditor",
                expression=type(exc).__name__,
                note=f"ast.parse failed: {exc.msg}",
            )
        ]
    except Exception as exc:  # noqa: BLE001
        return [
            SideDoorOffender(
                path=rel,
                line=0,
                kind="auditor-parse-error",
                axis="auditor",
                expression=type(exc).__name__,
                note=f"ast.parse failed: {exc}",
            )
        ]

    is_adapter = _is_adapter_path(path)
    # Enumerate-path modules are dual-lifter candidates even when they also
    # hold other construction duties.
    basename = path.name

    try:
        for node in ast.walk(tree):
            # --- membrane admission (all production files, including adapters) ---
            for name, expression in _membrane_name_hits(node):
                if name.endswith(".json") or name in {
                    "community_context_managers.json",
                    "community_context_managers",
                } or (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and "community_context_managers" in node.value
                ):
                    kind = "membrane-spelling-manifest"
                    note = (
                        "spelling membrane / community_context_managers data "
                        "must not admit construction meaning; only tree nodes "
                        "plus prebound authenticated contract refs"
                    )
                else:
                    kind = "membrane-admission-api"
                    note = (
                        "With/manager meaning must not enter through spelling "
                        "membrane APIs; sole path is prebound contract refs on "
                        "the typed tree"
                    )
                offenders.append(
                    SideDoorOffender(
                        path=rel,
                        line=getattr(node, "lineno", 0) or 0,
                        kind=kind,
                        axis="membrane-admission",
                        expression=expression,
                        note=note,
                    )
                )

            # --- ast semantic above adapter ---
            if not is_adapter:
                for marker, expression in _ast_semantic_hits(node):
                    kind = f"ast-semantic-{marker}"
                    offenders.append(
                        SideDoorOffender(
                            path=rel,
                            line=getattr(node, "lineno", 0) or 0,
                            kind=kind,
                            axis="ast-semantic-above-adapter",
                            expression=expression,
                            note=(
                                "raw ast is not semantic authority above adapters; "
                                "adapters may parse, then typed Node + substitute + "
                                "sugar carry meaning (prebound refs only)"
                            ),
                        )
                    )

            # --- dual old-lifter on production enumerate path ---
            if basename in {
                "lift_rpc.py",
                "tree_enumerate.py",
                "bind_rpc.py",
                "rpc.py",
            } or "enumerate" in basename:
                is_old, expression = _import_is_old_lifter(node)
                if is_old:
                    offenders.append(
                        SideDoorOffender(
                            path=rel,
                            line=getattr(node, "lineno", 0) or 0,
                            kind="dual-old-lifter",
                            axis="dual-old-lifter",
                            expression=expression,
                            note=(
                                "production enumerate must not open the old "
                                "lifter/bind_lifter door; tree_enumerate over "
                                "SourceOracle-pinned SourceFile is the sole path"
                            ),
                        )
                    )
    except Exception as exc:  # noqa: BLE001 — per-file containment
        offenders.append(
            SideDoorOffender(
                path=rel,
                line=0,
                kind="auditor-scan-error",
                axis="auditor",
                expression=type(exc).__name__,
                note=f"scan aborted for file: {exc}",
            )
        )

    # De-dupe identical locus rows.
    deduped: list[SideDoorOffender] = []
    seen: set[tuple[str, int, str, str, str]] = set()
    for row in offenders:
        key = (row.path, row.line, row.kind, row.axis, row.expression)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    if root.is_file() and root.suffix == ".py":
        return [root]
    if not root.is_dir():
        return files
    for path in sorted(root.rglob("*.py")):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIR_NAMES for part in path.parts):
            continue
        files.append(path)
    return files


def scan_roots(roots: Sequence[Path]) -> list[SideDoorOffender]:
    offenders: list[SideDoorOffender] = []
    for root in roots:
        try:
            root_resolved = root.resolve()
        except OSError as exc:
            offenders.append(
                SideDoorOffender(
                    path=str(root),
                    line=0,
                    kind="auditor-root-error",
                    axis="auditor",
                    expression=type(exc).__name__,
                    note=f"could not resolve scan root: {exc}",
                )
            )
            continue
        if not root_resolved.exists():
            offenders.append(
                SideDoorOffender(
                    path=str(root),
                    line=0,
                    kind="auditor-root-error",
                    axis="auditor",
                    expression="Missing",
                    note=f"scan root does not exist: {root_resolved}",
                )
            )
            continue
        if root_resolved.is_file():
            if root_resolved.suffix != ".py":
                continue
            rel = root_resolved.name
            offenders.extend(scan_file(root_resolved, rel=rel))
            continue
        if not root_resolved.is_dir():
            offenders.append(
                SideDoorOffender(
                    path=str(root),
                    line=0,
                    kind="auditor-root-error",
                    axis="auditor",
                    expression="NotADirectory",
                    note=f"scan root is not a directory: {root_resolved}",
                )
            )
            continue
        try:
            paths = _iter_python_files(root_resolved)
        except OSError as exc:
            offenders.append(
                SideDoorOffender(
                    path=str(root),
                    line=0,
                    kind="auditor-root-error",
                    axis="auditor",
                    expression=type(exc).__name__,
                    note=f"rglob failed: {exc}",
                )
            )
            continue
        for path in paths:
            rel = _rel_path(root_resolved, path)
            offenders.extend(scan_file(path, rel=rel))
    return sorted(offenders, key=lambda r: (r.path, r.line, r.kind, r.expression))


def default_production_roots(repo: Path | None = None) -> list[Path]:
    """Production construction packages on the sole path (and its parasites)."""
    kit = Path(__file__).resolve().parents[1]
    py = kit.parent
    # kit = .../sugar-lift-py-tests; py = .../python
    if repo is not None:
        py = (repo / "implementations" / "python").resolve()
        kit = py / "sugar-lift-py-tests"
    return [
        kit / "src" / "sugar_lift_py_tests",
        py / "sugar-source-tree" / "src" / "sugar_source_tree",
    ]


def r_construction_side_doors(offenders: Sequence[SideDoorOffender]) -> int:
    return sum(1 for row in offenders if row.kind in _SIDE_DOOR_KINDS)


def r_auditor_errors(offenders: Sequence[SideDoorOffender]) -> int:
    return sum(1 for row in offenders if row.kind.startswith("auditor-"))


def r_by_axis(offenders: Sequence[SideDoorOffender]) -> dict[str, int]:
    axes = {
        "membrane-admission": 0,
        "ast-semantic-above-adapter": 0,
        "dual-old-lifter": 0,
    }
    for row in offenders:
        if row.kind in _SIDE_DOOR_KINDS and row.axis in axes:
            axes[row.axis] += 1
    return axes


def format_report(offenders: Sequence[SideDoorOffender]) -> str:
    r = r_construction_side_doors(offenders)
    axes = r_by_axis(offenders)
    lines = [
        f"R_construction_side_doors = {r}",
        f"R_membrane_admission = {axes['membrane-admission']}",
        f"R_ast_semantic_above_adapter = {axes['ast-semantic-above-adapter']}",
        f"R_dual_old_lifter = {axes['dual-old-lifter']}",
        f"auditor_errors = {r_auditor_errors(offenders)}",
        (
            "Green only when meaning is tree + prebound refs only. "
            "Replacement: SourceOracle → adapter → typed Node → substitute → sugar."
        ),
        "",
        "Offenders:",
    ]
    for row in offenders:
        lines.append(
            f"{row.path}:{row.line}:{row.kind}:axis={row.axis} — "
            f"{row.expression} — {row.note}"
        )
    return "\n".join(lines)


def offenders_to_jsonable(offenders: Sequence[SideDoorOffender]) -> list[dict[str, object]]:
    return [
        {
            "path": row.path,
            "line": row.line,
            "kind": row.kind,
            "axis": row.axis,
            "expression": row.expression,
            "note": row.note,
        }
        for row in offenders
    ]


def discrimination_self_test() -> bool:
    """Planted membrane + ast twins trip; clean trees stay quiet."""
    membrane_plant = '''
from sugar_lift_py_tests.manifest_membrane import contract_for_manager

def admit(manager_node):
    return contract_for_manager(default_community_manifest(), manager_node)

_SPELLING = "community_context_managers.json"
'''
    ast_plant = '''
import ast

def resolve_exit(source: str):
    tree = ast.parse(source)
    class V(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            self.generic_visit(node)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "__exit__":
            return node
    return None
'''
    dual_plant = '''
from sugar_lift_python_source.lifter import lift_source

def enumerate_file(source, path):
    return lift_source(source, path)
'''
    clean = '''
def sugar_from_tree(node, prebound_refs):
    # meaning is tree + prebound refs only
    return node.sugar()
'''
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw) / "pkg"
        root.mkdir()
        (root / "membrane_door.py").write_text(membrane_plant, encoding="utf-8")
        (root / "ast_door.py").write_text(ast_plant, encoding="utf-8")
        # dual-old-lifter only fires on enumerate-path basenames
        (root / "lift_rpc.py").write_text(dual_plant, encoding="utf-8")
        (root / "clean.py").write_text(clean, encoding="utf-8")
        # adapter may use ast — must not trip
        (root / "cpython_adapter.py").write_text(
            "import ast\n\ndef parse(src):\n    return ast.parse(src)\n",
            encoding="utf-8",
        )
        planted = scan_roots((root,))
        r = r_construction_side_doors(planted)
        kinds = {row.kind for row in planted}
        axes = {row.axis for row in planted if row.kind in _SIDE_DOOR_KINDS}
        clean_only = scan_file(root / "clean.py", rel="pkg/clean.py")
        adapter_only = scan_file(
            root / "cpython_adapter.py", rel="pkg/cpython_adapter.py"
        )
        adapter_ast = [
            row for row in adapter_only if row.kind.startswith("ast-semantic-")
        ]
    return (
        r >= 3
        and "membrane-admission-api" in kinds
        and "membrane-spelling-manifest" in kinds
        and "ast-semantic-import" in kinds
        and "ast-semantic-parse" in kinds
        and "ast-semantic-walk" in kinds
        and "ast-semantic-visitor" in kinds
        and "dual-old-lifter" in kinds
        and "membrane-admission" in axes
        and "ast-semantic-above-adapter" in axes
        and "dual-old-lifter" in axes
        and r_construction_side_doors(clean_only) == 0
        and adapter_ast == []
        and r_auditor_errors(planted) == 0
    )


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="*", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Repository root for default production roots (optional)",
    )
    try:
        args = parser.parse_args(argv)
        if args.self_test:
            ok = discrimination_self_test()
            print(
                "CONSTRUCTION-SIDE-DOOR SELF-TEST " + ("GREEN" if ok else "RED")
            )
            print(
                json.dumps(
                    {
                        "instrument": "R_construction_side_doors",
                        "self_test": ok,
                    }
                )
            )
            return 0 if ok else 1
        roots = list(args.roots) if args.roots else default_production_roots(args.repo)
        offenders = scan_roots(roots)
    except Exception as exc:  # noqa: BLE001 — process-level containment
        print(
            "CONSTRUCTION-SIDE-DOOR LAW ERROR: unhandled auditor failure "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print(traceback.format_exc(), file=sys.stderr)
        print(
            json.dumps(
                {
                    "instrument": "R_construction_side_doors",
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "R_construction_side_doors": None,
                    "auditor_errors": 1,
                    "offenders": [],
                }
            )
        )
        return 2

    r = r_construction_side_doors(offenders)
    err = r_auditor_errors(offenders)
    axes = r_by_axis(offenders)
    summary = {
        "instrument": "R_construction_side_doors",
        "ok": r == 0 and err == 0,
        "R_construction_side_doors": r,
        "R_membrane_admission": axes["membrane-admission"],
        "R_ast_semantic_above_adapter": axes["ast-semantic-above-adapter"],
        "R_dual_old_lifter": axes["dual-old-lifter"],
        "auditor_errors": err,
        "offenders": offenders_to_jsonable(
            [row for row in offenders if row.kind in _SIDE_DOOR_KINDS]
        ),
    }
    if r > 0 or err > 0:
        print(
            "CONSTRUCTION-SIDE-DOOR LAW RED: "
            f"R={r}"
            f" membrane={axes['membrane-admission']}"
            f" ast_above_adapter={axes['ast-semantic-above-adapter']}"
            f" dual_old_lifter={axes['dual-old-lifter']}"
            + (f"; auditor_errors={err}" if err else "")
        )
        print(format_report(offenders))
        print(json.dumps(summary))
        return 1
    print(
        "CONSTRUCTION-SIDE-DOOR LAW GREEN: R_construction_side_doors = 0 "
        "(meaning is tree + prebound refs only)"
    )
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
