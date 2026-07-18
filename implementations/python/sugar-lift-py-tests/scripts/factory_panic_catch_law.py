#!/usr/bin/env python3
"""R_factory_panic_catches_outside_audit — permanent floor.

Only the per-file corpus / gap-enumeration audit membrane may catch
``FactoryPanic``, and it must record a loud red row (or re-raise process-terminal).

Production construction, dig, floors, and reports must never convert
FactoryPanic into Incomplete, opacity, empty collections, soft None, or a
missing row.

The single allowed membrane (relative to the package root) is
``audit_only/collect_construction_gaps.py``. It enumerates a FactoryPanic as an
``AuditOnlyGap`` loud red row.

Every other ``except FactoryPanic`` (or catch of FactoryPanic via isinstance on
Exception) under production ``src/sugar_lift_py_tests`` is debt unless the
handler body is pure re-raise on every path (no soft assignment / continue /
return None after catch).

Exit 1 while R > 0. No baseline. No allowlist of production soft continues.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import NamedTuple


class PanicCatchOffender(NamedTuple):
    path: str
    line: int
    kind: str
    note: str


_AUDIT_MEMBRANE = "audit_only/collect_construction_gaps.py"

_SOFT_AFTER_CATCH = frozenset(
    {
        "None",
        "continue",
        "pass",
        "return",
        "append",
        "Incomplete",
        "resolved_value",
        "recovered",
    }
)


def _is_audit_membrane(rel: str) -> bool:
    return rel == _AUDIT_MEMBRANE


def _handler_names(handler: ast.ExceptHandler) -> set[str]:
    """Exception type names this handler catches."""
    names: set[str] = set()
    t = handler.type
    if t is None:
        names.add("<bare>")
        return names

    def walk(node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Tuple):
            for elt in node.elts:
                walk(elt)

    walk(t)
    return names


def _catches_factory_panic(handler: ast.ExceptHandler) -> bool:
    names = _handler_names(handler)
    return bool(
        names & {"FactoryPanic", "FactoryGap", "BaseException"}
    ) or names == {"<bare>"}


def _is_terminal_raise(stmt: ast.AST) -> bool:
    if isinstance(stmt, ast.Raise):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        # raise SystemExit(...)  is Raise; bare SystemExit() is not allowed
        return False
    return False


def _ends_in_raise(stmts: list[ast.stmt]) -> bool:
    if not stmts:
        return False
    last = stmts[-1]
    if isinstance(last, ast.Raise):
        return True
    if isinstance(last, ast.If):
        return _ends_in_raise(last.body) and _ends_in_raise(
            last.orelse if last.orelse else [ast.Raise()]
        )
    return False


def _pure_reraise(handler: ast.ExceptHandler) -> bool:
    """True if handler always re-raises (process-terminal), never soft-continues.

    Logging / _send before raise SystemExit is allowed if every path ends in raise.
    Conditional soft continue (recovered_panics append + None) is not.
    """
    body = [
        n
        for n in handler.body
        if not (
            isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)
        )
    ]
    if not body:
        return False
    # Soft continue markers anywhere in the handler → debt
    text = ast.unparse(handler)
    if any(
        tok in text
        for tok in (
            " = None",
            "return None",
            "\n    continue\n",
            "\n        continue\n",
            "resolved_value = None",
            "recovered_panics.append",
            "gaps.append",
        )
    ):
        # gaps.append is audit-adjacent; still soft for production
        if "recovered_panics" in text or " = None" in text or "return None" in text:
            return False
        if "gaps.append" in text and "raise" not in text.split("gaps.append")[-1]:
            return False
    return _ends_in_raise(body)


def _soft_continue(handler: ast.ExceptHandler) -> bool:
    """Heuristic: handler assigns None / continues / returns soft after catch."""
    text = ast.unparse(handler)
    if "raise" in text and "if " not in text and "append" not in text:
        # pure re-raise path
        if _pure_reraise(handler):
            return False
    soft_tokens = (
        " = None",
        "return None",
        "\ncontinue",
        "\n        pass",
        "Incomplete",
        "append(",
        "resolved_value = None",
    )
    return any(tok in text for tok in soft_tokens) or not _pure_reraise(handler)


def scan_package(package_root: Path) -> list[PanicCatchOffender]:
    offenders: list[PanicCatchOffender] = []
    for path in sorted(package_root.rglob("*.py")):
        rel = path.relative_to(package_root).as_posix()
        if _is_audit_membrane(rel):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if not _catches_factory_panic(node):
                continue
            if _pure_reraise(node):
                # pure re-raise is process-terminal — not a soft membrane
                continue
            # Any non-pure-reraise catch outside audit membrane is debt.
            offenders.append(
                PanicCatchOffender(
                    path=rel,
                    line=node.lineno,
                    kind="factory-panic-catch-outside-audit",
                    note=(
                        "except FactoryPanic outside audit membrane must not "
                        "continue; only per-file corpus audit may hold panic to "
                        "emit a loud red row"
                    ),
                )
            )
        # isinstance(exc, FactoryPanic) soft return
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            calls = [
                child
                for child in ast.walk(node.test)
                if isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "isinstance"
                and len(child.args) >= 2
            ]
            if not any(
                (
                    call.args[1].id
                    if isinstance(call.args[1], ast.Name)
                    else (
                        call.args[1].attr
                        if isinstance(call.args[1], ast.Attribute)
                        else ""
                    )
                )
                == "FactoryPanic"
                for call in calls
            ):
                continue
            body_text = ast.unparse(node)
            if "return None" in body_text or "return" in body_text and "raise" not in body_text:
                offenders.append(
                    PanicCatchOffender(
                        path=rel,
                        line=node.lineno,
                        kind="factory-panic-isinstance-soft-return",
                        note=(
                            "isinstance(exc, FactoryPanic) then soft return/None — "
                            "dig/report must not convert panic into opacity"
                        ),
                    )
                )
    return sorted(offenders)


def scan_repository(kit_root: Path) -> list[PanicCatchOffender]:
    roots = (
        ("src/sugar_lift_py_tests", kit_root / "src" / "sugar_lift_py_tests"),
        ("scripts", kit_root / "scripts"),
    )
    offenders: list[PanicCatchOffender] = []
    for prefix, root in roots:
        if not root.is_dir():
            continue
        offenders.extend(
            offender._replace(path=f"{prefix}/{offender.path}")
            for offender in scan_package(root)
        )
    return sorted(offenders)


def format_report(offenders: list[PanicCatchOffender]) -> str:
    lines = [
        f"R_factory_panic_catches_outside_audit = {len(offenders)}",
        "Lawful: only per-file corpus / gap-enumeration audit holds FactoryPanic "
        "and emits a loud red row. Production may only pure re-raise.",
        "",
        "Loci:",
    ]
    for row in offenders:
        lines.append(f"{row.path}:{row.line}:{row.kind} — {row.note}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kit-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    offenders = scan_repository(args.kit_root)
    if offenders:
        print(
            "FACTORY-PANIC-CATCH LAW RED: "
            f"{len(offenders)} illegal FactoryPanic catches"
        )
        print(format_report(offenders))
        return 1
    print("FACTORY-PANIC-CATCH LAW GREEN: R_factory_panic_catches_outside_audit = 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
