from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BuiltinClosedOperationOffender:
    axis: str
    path: str
    line: int
    observed: str
    replacement: str


@dataclass(frozen=True)
class BuiltinClosedOperationReport:
    offenders: tuple[BuiltinClosedOperationOffender, ...]

    @property
    def r(self) -> dict[str, int]:
        axes = (
            "construction_side_doors",
            "generic_builtin_verdicts",
            "name_or_vendor_gates",
            "panic_catches",
        )
        return {
            axis: sum(row.axis == axis for row in self.offenders) for axis in axes
        }


def collect_builtin_closed_operation_report(
    root: Path,
) -> BuiltinClosedOperationReport:
    offenders: list[BuiltinClosedOperationOffender] = []
    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        relative = str(path.relative_to(root))
        visitor = _Visitor(relative)
        visitor.visit(tree)
        offenders.extend(visitor.offenders)
    return BuiltinClosedOperationReport(tuple(offenders))


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.offenders: list[BuiltinClosedOperationOffender] = []
        self._function_stack: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        self._side_door_functions: set[int] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function_stack.append(node)
        self.generic_visit(node)
        self._function_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Compare(self, node: ast.Compare) -> None:
        rendered = ast.unparse(node)
        string_values = {
            value.value
            for value in ast.walk(node)
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        }
        if any("pytest.raises" in value or "contextlib.suppress" in value for value in string_values):
            self._add(
                "name_or_vendor_gates",
                node,
                rendered,
                "route the authenticated builtin coordinate through the Python floor",
            )
            if self._function_stack:
                function = self._function_stack[-1]
                key = id(function)
                if key not in self._side_door_functions:
                    self._side_door_functions.add(key)
                    self._add(
                        "construction_side_doors",
                        function,
                        function.name,
                        "use the sole floor callable_application_with construction path",
                    )
        names = {value.id for value in ast.walk(node) if isinstance(value, ast.Name)}
        bools = {
            value.value
            for value in ast.walk(node)
            if isinstance(value, ast.Constant) and type(value.value) is bool
        }
        if any("builtin_result" in name or "builtin_verdict" in name for name in names) and bools:
            self._add(
                "generic_builtin_verdicts",
                node,
                rendered,
                "construct the closed semantic operation and result on the Python floor",
            )
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        caught = ast.unparse(node.type) if node.type is not None else "bare"
        if "Panic" in caught:
            self._add(
                "panic_catches",
                node,
                caught,
                "leave unsupported floor construction loud; never catch its panic",
            )
        self.generic_visit(node)

    def _add(
        self, axis: str, node: ast.AST, observed: str, replacement: str
    ) -> None:
        self.offenders.append(
            BuiltinClosedOperationOffender(
                axis=axis,
                path=self.path,
                line=getattr(node, "lineno", 0),
                observed=observed,
                replacement=replacement,
            )
        )
