#!/usr/bin/env python3
"""R_vendor_special_case — permanent shape-over-logo floor.

Sugar, factory, and recognition may dispatch on source shape and first-class
Sugar/value types. They may not decide behavior by matching a specific vendor
module/class name, by applying ``isinstance`` to a vendor class, or by
embedding vendor spellings as keys/values in dispatch dictionaries, sets,
tuples, lists, or registry initializers.

A logo string is never sufficient construction evidence — relocating a vendor
name from a comparison into a mapping literal must not green this floor.

Scanned vendor roots: numpy, pandas, datetime, scipy, pydantic, sqlalchemy,
cryptography, requests, pytest, sklearn.

Exit 1 whenever R_vendor_special_case > 0. There is no baseline, threshold, or
allowlist. Replacement: source shape → registered Sugar → SugarBody children →
floor; fixture/vendor semantics only via explicit kit/bridge/proof contract,
never production recognition coordinates.

Portability: every load/parse failure is a loud structured diagnostic row (or
process-level structured ERROR exit), never an unhandled process crash. Windows
and Linux must both emit R / structured output.
"""

from __future__ import annotations

# Not the board. This module measures its own named denominator; the sole
# authoritative Python corpus scoreboard is scripts/control_effect_recensus.py.
# See tests/test_one_authoritative_scoreboard.py.
SCOREBOARD_AUTHORITY = False

import argparse
import ast
import json
import sys
import traceback
from pathlib import Path
from typing import NamedTuple, Sequence

VENDORS = frozenset(
    {
        "numpy",
        "pandas",
        "datetime",
        "scipy",
        "pydantic",
        "sqlalchemy",
        "cryptography",
        "requests",
        "pytest",
        "sklearn",
    }
)

_LOGO_DISPATCH_KINDS = frozenset(
    {
        "vendor-name-match",
        "vendor-isinstance",
        "vendor-table-literal",
    }
)


class VendorSpecialCase(NamedTuple):
    path: str
    line: int
    kind: str
    vendor: str
    expression: str
    note: str


def _vendor_from_text(text: str) -> str | None:
    lowered = text.strip().lower()
    for vendor in sorted(VENDORS):
        if lowered == vendor or lowered.startswith(f"{vendor}."):
            return vendor
    return None


def _vendor_strings(node: ast.AST) -> set[str]:
    vendors: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Constant) or not isinstance(child.value, str):
            continue
        vendor = _vendor_from_text(child.value)
        if vendor is not None:
            vendors.add(vendor)
    return vendors


def _qualified_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _vendor_symbols(tree: ast.AST) -> dict[str, set[str]]:
    symbols: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            vendors = _vendor_strings(node.value)
            for target in node.targets:
                if isinstance(target, ast.Name) and vendors:
                    symbols.setdefault(target.id, set()).update(vendors)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            vendors = _vendor_strings(node.value)
            if vendors:
                symbols.setdefault(node.target.id, set()).update(vendors)
    return symbols


def _is_name_match(node: ast.Compare, symbols: dict[str, set[str]]) -> set[str]:
    operands: tuple[ast.AST, ...] = (node.left, *node.comparators)
    if all(
        isinstance(operand, (ast.Constant, ast.Tuple, ast.List, ast.Set))
        for operand in operands
    ):
        return set()
    direct = {vendor for operand in operands for vendor in _vendor_strings(operand)}
    indirect = {
        vendor
        for operand in operands
        for child in ast.walk(operand)
        if isinstance(child, ast.Name)
        for vendor in symbols.get(child.id, set())
    }
    return direct | indirect


def _isinstance_vendor(node: ast.Call) -> str | None:
    if not isinstance(node.func, ast.Name) or node.func.id != "isinstance":
        return None
    if len(node.args) < 2:
        return None
    type_arg = node.args[1]
    candidates = type_arg.elts if isinstance(type_arg, ast.Tuple) else (type_arg,)
    for candidate in candidates:
        vendor = _vendor_from_text(_qualified_name(candidate))
        if vendor is not None:
            return vendor
    return None


def _table_literal_vendor_hits(node: ast.AST) -> list[tuple[str, str]]:
    """Vendor logos embedded as dispatch table / registry constants.

    Hits Constant string (or nested tuple/list/set of strings) that name a
    scanned vendor root when they appear as:

    - dict keys or values
    - set / list / tuple elements
    - nested tuple keys used by registry initializers

    Returns (vendor, expression) pairs. One Constant may contribute one hit.
    """
    hits: list[tuple[str, str]] = []

    def consider_constant(constant: ast.Constant) -> None:
        if not isinstance(constant.value, str):
            return
        vendor = _vendor_from_text(constant.value)
        if vendor is None:
            return
        hits.append((vendor, repr(constant.value)))

    def walk_collection(collection: ast.AST) -> None:
        if isinstance(collection, ast.Constant):
            consider_constant(collection)
            return
        if isinstance(collection, ast.Tuple | ast.List | ast.Set):
            for elt in collection.elts:
                walk_collection(elt)
            return
        if isinstance(collection, ast.Dict):
            for key, value in zip(collection.keys, collection.values, strict=False):
                if key is not None:
                    walk_collection(key)
                if value is not None:
                    walk_collection(value)
            return
        # Comprehension forms of registry tables (e.g. {name: True for name in (...)}).
        if isinstance(collection, ast.DictComp):
            walk_collection(collection.key)
            walk_collection(collection.value)
            for gen in collection.generators:
                walk_collection(gen.iter)
            return
        if isinstance(collection, (ast.SetComp, ast.ListComp, ast.GeneratorExp)):
            walk_collection(collection.elt)
            for gen in collection.generators:
                walk_collection(gen.iter)
            return

    if isinstance(
        node,
        (
            ast.Dict,
            ast.Set,
            ast.List,
            ast.Tuple,
            ast.DictComp,
            ast.SetComp,
            ast.ListComp,
            ast.GeneratorExp,
        ),
    ):
        walk_collection(node)
    return hits


def _rel_path(root: Path, path: Path) -> str:
    """Cross-platform relative path for reports (always forward slashes)."""
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        # Not under root (symlink / mount edge); fall back to path name.
        rel = Path(path.name)
    return f"{root.name}/{rel.as_posix()}"


def _read_source(path: Path) -> tuple[str | None, VendorSpecialCase | None]:
    """Read source text. On failure return a structured diagnostic row."""
    try:
        return path.read_text(encoding="utf-8"), None
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8-sig"), None
        except UnicodeDecodeError:
            try:
                return path.read_text(encoding="utf-8", errors="replace"), None
            except OSError as exc:
                return None, VendorSpecialCase(
                    path=path.as_posix(),
                    line=0,
                    kind="auditor-read-error",
                    vendor="-",
                    expression=type(exc).__name__,
                    note=f"could not read source after utf-8 fallback: {exc}",
                )
    except OSError as exc:
        return None, VendorSpecialCase(
            path=path.as_posix(),
            line=0,
            kind="auditor-read-error",
            vendor="-",
            expression=type(exc).__name__,
            note=f"could not read source: {exc}",
        )


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception as exc:  # noqa: BLE001 — auditor must not crash
        return f"<unparse-failed:{type(exc).__name__}>"


def scan_file(path: Path, *, rel: str) -> list[VendorSpecialCase]:
    """Scan one file. Read/parse failures become structured rows, not crashes."""
    offenders: list[VendorSpecialCase] = []
    source, read_error = _read_source(path)
    if read_error is not None:
        return [
            (
                read_error._replace(path=rel)
                if read_error.path == path.as_posix()
                else VendorSpecialCase(
                    path=rel,
                    line=read_error.line,
                    kind=read_error.kind,
                    vendor=read_error.vendor,
                    expression=read_error.expression,
                    note=read_error.note,
                )
            )
        ]
    assert source is not None
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [
            VendorSpecialCase(
                path=rel,
                line=int(exc.lineno or 0),
                kind="auditor-parse-error",
                vendor="-",
                expression=type(exc).__name__,
                note=f"ast.parse failed: {exc.msg}",
            )
        ]
    except Exception as exc:  # noqa: BLE001 — loud structured, not crash
        return [
            VendorSpecialCase(
                path=rel,
                line=0,
                kind="auditor-parse-error",
                vendor="-",
                expression=type(exc).__name__,
                note=f"ast.parse failed: {exc}",
            )
        ]

    try:
        symbols = _vendor_symbols(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for vendor in sorted(_is_name_match(node, symbols)):
                    offenders.append(
                        VendorSpecialCase(
                            path=rel,
                            line=getattr(node, "lineno", 0) or 0,
                            kind="vendor-name-match",
                            vendor=vendor,
                            expression=_safe_unparse(node),
                            note=(
                                "dispatch on source shape, registered Sugar, "
                                "and floor value types; never vendor names"
                            ),
                        )
                    )
            elif isinstance(node, ast.Call):
                vendor = _isinstance_vendor(node)
                if vendor is not None:
                    offenders.append(
                        VendorSpecialCase(
                            path=rel,
                            line=getattr(node, "lineno", 0) or 0,
                            kind="vendor-isinstance",
                            vendor=vendor,
                            expression=_safe_unparse(node),
                            note=(
                                "vendor class checks are logo dispatch; own "
                                "the structural source shape instead"
                            ),
                        )
                    )
            elif isinstance(
                node,
                (
                    ast.Dict,
                    ast.Set,
                    ast.List,
                    ast.Tuple,
                    ast.DictComp,
                    ast.SetComp,
                    ast.ListComp,
                    ast.GeneratorExp,
                ),
            ):
                # Dispatch/registry initializers (including comprehension forms).
                # Nested collections are visited as their own walk nodes too;
                # de-dupe by (line, vendor, expression).
                for vendor, expression in _table_literal_vendor_hits(node):
                    offenders.append(
                        VendorSpecialCase(
                            path=rel,
                            line=getattr(node, "lineno", 0) or 0,
                            kind="vendor-table-literal",
                            vendor=vendor,
                            expression=expression,
                            note=(
                                "logo string in dispatch dict/set/tuple/list is "
                                "still vendor identity; relocate into kit/"
                                "bridge/proof contract or delete — never "
                                "construction evidence"
                            ),
                        )
                    )
    except Exception as exc:  # noqa: BLE001 — per-file containment
        offenders.append(
            VendorSpecialCase(
                path=rel,
                line=0,
                kind="auditor-scan-error",
                vendor="-",
                expression=type(exc).__name__,
                note=f"scan aborted for file: {exc}",
            )
        )
    # De-dupe nested collection double-counts: same path/line/kind/vendor/expr.
    deduped: list[VendorSpecialCase] = []
    seen: set[tuple[str, int, str, str, str]] = set()
    for row in offenders:
        key = (row.path, row.line, row.kind, row.vendor, row.expression)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def scan_roots(roots: Sequence[Path]) -> list[VendorSpecialCase]:
    offenders: list[VendorSpecialCase] = []
    for root in roots:
        try:
            root_resolved = root.resolve()
        except OSError as exc:
            offenders.append(
                VendorSpecialCase(
                    path=str(root),
                    line=0,
                    kind="auditor-root-error",
                    vendor="-",
                    expression=type(exc).__name__,
                    note=f"could not resolve scan root: {exc}",
                )
            )
            continue
        if not root_resolved.is_dir():
            offenders.append(
                VendorSpecialCase(
                    path=str(root),
                    line=0,
                    kind="auditor-root-error",
                    vendor="-",
                    expression="NotADirectory",
                    note=f"scan root is not a directory: {root_resolved}",
                )
            )
            continue
        try:
            paths = sorted(root_resolved.rglob("*.py"))
        except OSError as exc:
            offenders.append(
                VendorSpecialCase(
                    path=str(root),
                    line=0,
                    kind="auditor-root-error",
                    vendor="-",
                    expression=type(exc).__name__,
                    note=f"rglob failed: {exc}",
                )
            )
            continue
        for path in paths:
            if not path.is_file():
                continue
            rel = _rel_path(root_resolved, path)
            offenders.extend(scan_file(path, rel=rel))
    return sorted(offenders)


def r_vendor_special_case(offenders: Sequence[VendorSpecialCase]) -> int:
    # Auditor diagnostic rows are loud process health, not logo debt.
    # They still fail the run (exit 1) via main when present, but are counted
    # separately from R_vendor_special_case so a portable crash-fix does not
    # inflate the logo-dispatch floor.
    return sum(1 for row in offenders if row.kind in _LOGO_DISPATCH_KINDS)


def r_auditor_errors(offenders: Sequence[VendorSpecialCase]) -> int:
    return sum(1 for row in offenders if row.kind.startswith("auditor-"))


def format_report(offenders: Sequence[VendorSpecialCase]) -> str:
    lines = [
        f"R_vendor_special_case = {r_vendor_special_case(offenders)}",
        f"auditor_errors = {r_auditor_errors(offenders)}",
        (
            "Replacement: source shape → registered Sugar → SugarBody children "
            "→ floor dispatch; never vendor module/class identity."
        ),
        "",
        "Loci:",
    ]
    for row in offenders:
        lines.append(
            f"{row.path}:{row.line}:{row.kind}:vendor={row.vendor} — "
            f"{row.expression} — {row.note}"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    package = Path(__file__).resolve().parents[1] / "src" / "sugar_lift_py_tests"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "roots",
        nargs="*",
        type=Path,
        # Construction/recognition surface (post-factory architecture).
        # factory/ and recognition/ were folded across these dirs: construction
        # decisions now flow through floor values, effects, outcomes, claims,
        # ProofIR, temporal/context machinery, and lift/RPC orchestration.
        # Excluded on purpose: audit_only + idd (measurement/reporting),
        # manifests (declared contract data).
        default=[
            package / "claim",
            package / "context",
            package / "effect",
            package / "floor",
            package / "gap",
            package / "kit_rpc",
            package / "lift",
            package / "outcome",
            package / "proofir",
            package / "sugar",
            package / "sugar_body",
            package / "temporal",
        ],
    )
    try:
        args = parser.parse_args(argv)
        offenders = scan_roots(args.roots)
    except Exception as exc:  # noqa: BLE001 — process-level containment
        print(
            "VENDOR-SPECIAL-CASE LAW ERROR: unhandled auditor failure "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print(traceback.format_exc(), file=sys.stderr)
        print(
            json.dumps(
                {
                    "instrument": "R_vendor_special_case",
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "R_vendor_special_case": None,
                    "auditor_errors": 1,
                }
            )
        )
        return 2

    r = r_vendor_special_case(offenders)
    err = r_auditor_errors(offenders)
    summary = {
        "instrument": "R_vendor_special_case",
        "ok": r == 0 and err == 0,
        "R_vendor_special_case": r,
        "auditor_errors": err,
    }
    if r > 0 or err > 0:
        print(
            "VENDOR-SPECIAL-CASE LAW RED: "
            f"{r} logo-dispatch loci" + (f"; {err} auditor errors" if err else "")
        )
        print(format_report(offenders))
        print(json.dumps(summary))
        return 1
    print("VENDOR-SPECIAL-CASE LAW GREEN: R_vendor_special_case = 0")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
