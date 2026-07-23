"""Measured structural law for the guarded symbolic-loop recurrence lane."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from pathlib import Path
import re


_REPLACEMENT = "LoopConstructionV1 plus LoopProjectedBinding"


@dataclass(frozen=True, order=True)
class GuardedLoopRecurrenceFinding:
    path: str
    line: int
    code: str
    replacement: str


def _finding(path: Path, root: Path, line: int, code: str, replacement: str):
    try:
        rendered = str(path.relative_to(root))
    except ValueError:
        rendered = str(path)
    return GuardedLoopRecurrenceFinding(rendered, line, code, replacement)


def scan_guarded_loop_recurrence(
    root: Path,
) -> tuple[GuardedLoopRecurrenceFinding, ...]:
    findings: list[GuardedLoopRecurrenceFinding] = []
    python_files = sorted(root.rglob("*.py"))
    for path in python_files:
        text = path.read_text()
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else None
                rendered = ast.unparse(node)
                if (
                    "py.fold." in rendered
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "_make_call"
                ):
                    findings.append(
                        _finding(
                            path,
                            root,
                            node.lineno,
                            "symbolic-loop-fold-substitution",
                            _REPLACEMENT,
                        )
                    )
                if name == "ForUniversalSugar":
                    findings.append(
                        _finding(
                            path,
                            root,
                            node.lineno,
                            "symbolic-loop-universal",
                            "LoopConstructionV1 guarded recurrence",
                        )
                    )
                if name in {"node_from_cid", "value_from_cid", "term_from_cid"}:
                    findings.append(
                        _finding(
                            path,
                            root,
                            node.lineno,
                            "cid-decoded-into-value",
                            "authenticated completed-face runtime state",
                        )
                    )
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id in {"loop_values", "loop_bindings"}
            ):
                findings.append(
                    _finding(
                        path,
                        root,
                        node.lineno,
                        "ambient-loop-value-map",
                        "BindingEntryV1 carrying LoopProjectedBinding",
                    )
                )

    binding_state = next(
        (path for path in python_files if path.name == "binding_state.py"), None
    )
    if binding_state is not None:
        text = binding_state.read_text()
        if "class LoopProjectedBinding" not in text:
            findings.append(
                _finding(
                    binding_state,
                    root,
                    1,
                    "missing-loop-projected-binding",
                    _REPLACEMENT,
                )
            )
        elif not re.search(
            r"BindingState(?:\s*:[^=]*)?\s*=.*?LoopProjectedBinding",
            text,
            re.DOTALL,
        ):
            findings.append(
                _finding(
                    binding_state,
                    root,
                    1,
                    "loop-projection-outside-binding-entry-model",
                    "LoopProjectedBinding inside BindingEntryV1.state",
                )
            )
    return tuple(sorted(findings))


def summarize_guarded_loop_recurrence(
    findings: tuple[GuardedLoopRecurrenceFinding, ...],
) -> dict[str, object]:
    return {
        "instrument": "R_guarded_loop_recurrence",
        "R_guarded_loop_recurrence": len(findings),
        "offenders": [asdict(finding) for finding in findings],
        "replacement": _REPLACEMENT,
    }


__all__ = [
    "GuardedLoopRecurrenceFinding",
    "scan_guarded_loop_recurrence",
    "summarize_guarded_loop_recurrence",
]
