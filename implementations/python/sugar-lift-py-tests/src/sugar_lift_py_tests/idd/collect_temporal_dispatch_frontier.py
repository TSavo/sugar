from __future__ import annotations

import ast
from pathlib import Path

from .temporal_dispatch_offender import TemporalDispatchOffender
from .temporal_dispatch_report import TemporalDispatchReport


def collect_temporal_dispatch_frontier(root: Path) -> TemporalDispatchReport:
    kit_src = _kit_src(root)
    offenders: list[TemporalDispatchOffender] = []
    for path in sorted(kit_src.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(kit_src).as_posix()
        in_temporal_package = rel.startswith("temporal/")
        for node in ast.walk(tree):
            if not in_temporal_package and _is_bind_value_call(node):
                offenders.append(
                    _offender(
                        "direct_temporal_bindings",
                        rel,
                        node.lineno,
                        ".bind_value(...)",
                        "route temporal binding through temporal dispatch floor",
                    )
                )
            if not in_temporal_package and _is_temporal_replace_call(node):
                offenders.append(
                    _offender(
                        "direct_temporal_replacements",
                        rel,
                        node.lineno,
                        "replace(..., temporal=...)",
                        "route temporal context replacement through temporal dispatch floor",
                    )
                )
            if _is_temporal_rewrite_switch(node):
                offenders.append(
                    _offender(
                        "temporal_rewrite_switches",
                        rel,
                        node.lineno,
                        "TemporalContext.apply_step",
                        "route temporal rewrite through temporal dispatch floor",
                    )
                )
    return TemporalDispatchReport(offenders=offenders)


def _kit_src(root: Path) -> Path:
    candidates = (
        root / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests",
        root / "python/sugar-lift-py-tests/src/sugar_lift_py_tests",
        root / "src/sugar_lift_py_tests",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _is_bind_value_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "bind_value"
    )


def _is_temporal_replace_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "replace"
        and any(keyword.arg == "temporal" for keyword in node.keywords)
    )


def _is_temporal_rewrite_switch(node: ast.AST) -> bool:
    return isinstance(node, ast.FunctionDef) and node.name == "apply_step"


def _offender(
    kind: str,
    path: str,
    line: int,
    observed: str,
    fix: str,
) -> TemporalDispatchOffender:
    return TemporalDispatchOffender(
        kind=kind,
        path=path,
        line=line,
        observed=observed,
        fix=fix,
    )
