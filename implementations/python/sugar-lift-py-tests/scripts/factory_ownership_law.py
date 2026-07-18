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

Exit 1 while R_ownership > 0. Missing roots and source read/parse failures are
reported separately as ``auditor_errors`` and also exit red.
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
        if (
            isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == name
        ):
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


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _is_typed_runtime_effect_incomplete(node: ast.Call) -> bool:
    if _call_name(node) != "Incomplete" or not node.args:
        return False
    effect = node.args[0]
    return isinstance(effect, ast.Call) and (_call_name(effect) or "").endswith(
        "RuntimeEffect"
    )


def _has_typed_red_effect_witness(witnesses: ast.FunctionDef | None) -> bool:
    if witnesses is None:
        return False
    return any(
        isinstance(node, ast.Call)
        and _call_name(node)
        in {
            "typed_red_effect_witness",
            "SugarRedEffectWitnessPair",
        }
        for node in ast.walk(witnesses)
    )


def scan_sugar_tree(sugar_root: Path) -> list[OwnershipOffender]:
    offenders: list[OwnershipOffender] = []
    try:
        resolved_root = sugar_root.resolve()
    except OSError as error:
        return [
            OwnershipOffender(
                sugar_root.as_posix(),
                0,
                "auditor-root-error",
                "-",
                f"could not resolve scan root: {error}",
            )
        ]
    if not resolved_root.is_dir():
        return [
            OwnershipOffender(
                sugar_root.as_posix(),
                0,
                "auditor-root-error",
                "-",
                "scan root is not a directory",
            )
        ]
    try:
        paths = sorted(resolved_root.rglob("*.py"))
    except OSError as error:
        return [
            OwnershipOffender(
                sugar_root.as_posix(),
                0,
                "auditor-root-error",
                "-",
                f"could not enumerate scan root: {error}",
            )
        ]
    for path in paths:
        if path.name.startswith("_") and path.name != "__init__.py":
            continue
        relative = f"sugar/{path.relative_to(resolved_root).as_posix()}"
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            offenders.append(
                OwnershipOffender(
                    relative,
                    0,
                    "auditor-read-error",
                    "-",
                    f"could not read source: {error}",
                )
            )
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as error:
            offenders.append(
                OwnershipOffender(
                    relative,
                    int(error.lineno or 0),
                    "auditor-parse-error",
                    "-",
                    f"ast.parse failed: {error.msg}",
                )
            )
            continue
        owned_sugars: list[tuple[str, ast.FunctionDef, ast.FunctionDef | None]] = []
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if not node.name.endswith("Sugar"):
                continue
            owns = _method(node, "owns")
            if owns is None:
                continue
            # Skip abstract / protocol shells without construction surface.
            if any(_terminal_name(base) in {"ABC", "Protocol"} for base in node.bases):
                continue
            witnesses = _method(node, "witnesses")
            owned_sugars.append((node.name, owns, witnesses))
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
        if owned_sugars:
            owner = ",".join(name for name, _, _ in owned_sugars)
            incomplete_calls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and _call_name(node) == "Incomplete"
            ]
            for call in incomplete_calls:
                if _is_typed_runtime_effect_incomplete(call):
                    continue
                offenders.append(
                    OwnershipOffender(
                        relative,
                        call.lineno,
                        "untyped-incomplete-after-owns",
                        owner,
                        "owns() selected this module's Sugar, but the selected "
                        "path manufactures Incomplete without a concrete "
                        "*RuntimeEffect; unsupported construction must leave no "
                        "candidate so factory None → FactoryPanic",
                    )
                )
            if any(
                _is_typed_runtime_effect_incomplete(call) for call in incomplete_calls
            ):
                for sugar_name, owns, witnesses in owned_sugars:
                    if _has_typed_red_effect_witness(witnesses):
                        continue
                    offenders.append(
                        OwnershipOffender(
                            relative,
                            owns.lineno,
                            "unwitnessed-runtime-effect-after-owns",
                            sugar_name,
                            "owns() selects a Sugar module that manufactures a "
                            "typed RuntimeEffect, but witnesses() has no "
                            "SugarRedEffectWitnessPair / typed_red_effect_witness "
                            "whose wrong twin refutes the claimed effect",
                        )
                    )
    return sorted(offenders)


def format_report(offenders: list[OwnershipOffender]) -> str:
    by_kind = Counter(row.kind for row in offenders)
    ownership_offenders = [
        row for row in offenders if not row.kind.startswith("auditor-")
    ]
    auditor_errors = [
        row for row in offenders if row.kind.startswith("auditor-")
    ]
    lines = [
        f"R_ownership = {len(ownership_offenders)}",
        f"auditor_errors = {len(auditor_errors)}",
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
        lines.append(f"{row.path}:{row.line}:{row.kind}:{row.sugar} — {row.note}")
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
            f"{sum(not row.kind.startswith('auditor-') for row in offenders)} "
            "owns/witness gaps; "
            f"auditor_errors={sum(row.kind.startswith('auditor-') for row in offenders)}"
        )
        print(format_report(offenders))
        return 1
    print("OWNERSHIP-LAW GREEN: R_ownership = 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
