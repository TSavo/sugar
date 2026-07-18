#!/usr/bin/env python3
"""Ownership-law census: selected Sugar arms must construct honestly.

Blind spot the side-door census does not close: a broad ``owns()`` can claim a
shape and manufacture Incomplete instead of leaving the factory with no candidate
(→ FactoryPanic).

This instrument is STEP-1 static enforcement of the ownership law:

1. Every concrete Sugar class that defines ``owns`` must also define ``witnesses``
   (or an explicit non-verdict opt-out marker in that method).
2. ``owns`` that only inspects ``site.observed`` / a single broad observed kind
   without further structural refinement is reported as broad-owns debt.

Full twin execution (truthful SAT / lying UNSAT / typed red effect) remains the
existing sugar-witness machinery; this census keeps the ownership *gap* loud and
counts it as R until enrolled.

Exit 1 while R_ownership > 0.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from pathlib import Path
from typing import NamedTuple


class OwnershipOffender(NamedTuple):
    path: str
    line: int
    kind: str
    sugar: str
    note: str


_OPT_OUT_MARKERS = frozenset(
    {
        "NotVerdictBearing",
        "not_verdict_bearing",
        "temporal_opt_out",
        "NON_FOL_OPT_OUT",
    }
)


def _terminal_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _method(class_node: ast.ClassDef, name: str) -> ast.FunctionDef | None:
    for item in class_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name:
            return item
    return None


def _owns_is_broad(owns: ast.FunctionDef) -> bool:
    """Heuristic: owns only looks at observed equality / membership, no children."""
    text = ast.unparse(owns)
    looks_at_observed = "observed" in text
    looks_at_children = any(
        token in text
        for token in (
            "function_params",
            "call_func",
            "binop_",
            "compare_",
            "if_test",
            "return_value",
            "target",
            "name_id",
            "literal_value",
            "is_statement",
            "from_node",
        )
    )
    only_observed = looks_at_observed and not looks_at_children
    # Single-kind structural owns (e.g. Break) is fine if no observed-only catch-all.
    if "return True" in text and "observed" not in text and len(text) < 120:
        return False
    return only_observed


def _has_witness_or_opt_out(witnesses: ast.FunctionDef | None) -> bool:
    if witnesses is None:
        return False
    body = ast.unparse(witnesses)
    if any(marker in body for marker in _OPT_OUT_MARKERS):
        return True
    # Non-empty witness body that yields/returns something other than pass.
    for node in witnesses.body:
        if isinstance(node, ast.Pass):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        return True
    return False


def scan_sugar_tree(sugar_root: Path) -> list[OwnershipOffender]:
    offenders: list[OwnershipOffender] = []
    for path in sorted(sugar_root.rglob("*.py")):
        if path.name.startswith("_") and path.name != "__init__.py":
            continue
        relative = f"sugar/{path.relative_to(sugar_root).as_posix()}"
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if not node.name.endswith("Sugar"):
                continue
            owns = _method(node, "owns")
            if owns is None:
                continue
            # Skip abstract / protocol shells without construction surface.
            if any(
                _terminal_name(base) in {"ABC", "Protocol"} for base in node.bases
            ):
                continue
            witnesses = _method(node, "witnesses")
            if not _has_witness_or_opt_out(witnesses):
                offenders.append(
                    OwnershipOffender(
                        relative,
                        node.lineno,
                        "unenrolled-owns",
                        node.name,
                        "owns() present without witnesses() / opt-out — "
                        "cannot prove honest construction or typed red twin; "
                        "unsupported shapes must leave factory with no candidate "
                        "→ FactoryPanic, never soft Incomplete",
                    )
                )
            # broad-owns is advisory only (observed-kind owns is lawful for many
            # sugars). The hard law is enrollment + twin execution, not "narrow owns".
            if _owns_is_broad(owns) and not _has_witness_or_opt_out(witnesses):
                offenders.append(
                    OwnershipOffender(
                        relative,
                        owns.lineno,
                        "broad-unenrolled-owns",
                        node.name,
                        "broad observed-only owns without witnesses — capture then "
                        "Incomplete risk; enroll twin or narrow + FactoryPanic",
                    )
                )
    return sorted(offenders)


def format_report(offenders: list[OwnershipOffender]) -> str:
    by_kind = Counter(row.kind for row in offenders)
    lines = [
        f"R_ownership_law = {len(offenders)}",
        "Law: every selected Sugar arm produces cited construction or genuine typed "
        "runtime effect under a bad twin; unsupported shapes leave factory with no "
        "candidate → FactoryPanic. Soft Incomplete after broad owns is illegal.",
        "",
        "By kind:",
    ]
    for kind, count in by_kind.most_common():
        lines.append(f"  {count:4d}  {kind}")
    lines.append("")
    lines.append("Loci:")
    for row in offenders:
        lines.append(
            f"{row.path}:{row.line}:{row.kind}:{row.sugar} — {row.note}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sugar-root",
        type=Path,
        default=(
            Path(__file__).resolve().parents[1]
            / "src"
            / "sugar_lift_py_tests"
            / "sugar"
        ),
    )
    args = parser.parse_args()
    offenders = scan_sugar_tree(args.sugar_root)
    if offenders:
        print(
            "OWNERSHIP-LAW RED: "
            f"{len(offenders)} owns/witness gaps"
        )
        print(format_report(offenders))
        return 1
    print("OWNERSHIP-LAW GREEN: R_ownership_law = 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
