#!/usr/bin/env python3
"""R_vendor_special_case — permanent shape-over-logo floor.

Sugar, factory, and recognition may dispatch on source shape and first-class
Sugar/value types. They may not decide behavior by matching a specific vendor
module/class name or by applying ``isinstance`` to a vendor class.

Scanned vendor roots: numpy, pandas, datetime, scipy, pydantic, sqlalchemy,
cryptography, requests.

Exit 1 whenever R_vendor_special_case > 0. There is no baseline, threshold, or
allowlist. Replacement: register the source shape and construct/reduce it
through the ordinary Sugar + SugarBody + floor path.
"""

from __future__ import annotations

import argparse
import ast
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


def _is_name_match(
    node: ast.Compare, symbols: dict[str, set[str]]
) -> set[str]:
    operands: tuple[ast.AST, ...] = (node.left, *node.comparators)
    if all(
        isinstance(operand, (ast.Constant, ast.Tuple, ast.List, ast.Set))
        for operand in operands
    ):
        return set()
    direct = {
        vendor
        for operand in operands
        for vendor in _vendor_strings(operand)
    }
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
    candidates = (
        type_arg.elts
        if isinstance(type_arg, ast.Tuple)
        else (type_arg,)
    )
    for candidate in candidates:
        vendor = _vendor_from_text(_qualified_name(candidate))
        if vendor is not None:
            return vendor
    return None


def scan_roots(roots: Sequence[Path]) -> list[VendorSpecialCase]:
    offenders: list[VendorSpecialCase] = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            rel = f"{root.name}/{path.relative_to(root).as_posix()}"
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            symbols = _vendor_symbols(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Compare):
                    for vendor in sorted(_is_name_match(node, symbols)):
                        offenders.append(
                            VendorSpecialCase(
                                path=rel,
                                line=node.lineno,
                                kind="vendor-name-match",
                                vendor=vendor,
                                expression=ast.unparse(node),
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
                                line=node.lineno,
                                kind="vendor-isinstance",
                                vendor=vendor,
                                expression=ast.unparse(node),
                                note=(
                                    "vendor class checks are logo dispatch; own "
                                    "the structural source shape instead"
                                ),
                            )
                        )
    return sorted(offenders)


def r_vendor_special_case(offenders: Sequence[VendorSpecialCase]) -> int:
    return len(offenders)


def format_report(offenders: Sequence[VendorSpecialCase]) -> str:
    lines = [
        f"R_vendor_special_case = {r_vendor_special_case(offenders)}",
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


def main() -> int:
    package = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "sugar_lift_py_tests"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "roots",
        nargs="*",
        type=Path,
        default=[
            package / "sugar",
            package / "factory",
            package / "recognition",
        ],
    )
    args = parser.parse_args()
    offenders = scan_roots(args.roots)
    if offenders:
        print(
            "VENDOR-SPECIAL-CASE LAW RED: "
            f"{r_vendor_special_case(offenders)} logo-dispatch loci"
        )
        print(format_report(offenders))
        return 1
    print("VENDOR-SPECIAL-CASE LAW GREEN: R_vendor_special_case = 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
