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
        return {axis: sum(row.axis == axis for row in self.offenders) for axis in axes}


def collect_builtin_closed_operation_report(
    root: Path,
) -> BuiltinClosedOperationReport:
    offenders: list[BuiltinClosedOperationOffender] = []
    for path in sorted(root.rglob("*.py")):
        relative_path = path.relative_to(root)
        parts = relative_path.parts
        if "sugar_lift_py_tests" in parts:
            package_index = parts.index("sugar_lift_py_tests")
            lane = parts[package_index + 1 : package_index + 2]
            if lane and lane[0] in {"audit_only", "idd", "kit_rpc"}:
                continue
            if relative_path.name == "lift_rpc.py":
                continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        relative = str(relative_path)
        visitor = _Visitor(relative)
        visitor.visit(tree)
        offenders.extend(visitor.offenders)
    return BuiltinClosedOperationReport(tuple(offenders))


class _Visitor(ast.NodeVisitor):
    """Structural detector for spelling-gates outside authenticated coordinates.

    Name/vendor gates are compares that decide control by display text
    (``exception_name == "..."``, ``func.id == "importorskip"``,
    ``type_name in {...}``, ``name == matcher.name``) instead of an
    authenticated type/binding coordinate from the tree. A green report
    that only looked for the substrings ``pytest.raises`` /
    ``contextlib.suppress`` could not see those sins and carried no
    information.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.offenders: list[BuiltinClosedOperationOffender] = []
        self._function_stack: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        self._side_door_functions: set[int] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Name-keyed suppress API is itself the residual shell (method body may
        # only mention self.exception_names; the method *name* is the crime).
        if node.name == "suppresses_exception":
            self._add(
                "name_or_vendor_gates",
                node,
                f"def {node.name}",
                "match exception_type_coordinate against ExitSuppressionContract "
                "coordinates minted at the suppresses() door; never suppress by name",
            )
        self._function_stack.append(node)
        self.generic_visit(node)
        self._function_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Compare(self, node: ast.Compare) -> None:
        rendered = ast.unparse(node)
        if self._is_spelling_gate_compare(node):
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
        if (
            any("builtin_result" in name or "builtin_verdict" in name for name in names)
            and bools
        ):
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

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Residual after cluster-5 Suppresses fix: ExitSuppressionContract still
        # decided suppress via suppresses_exception(str) / exception_names.
        # Those shells are deleted; any reintroduction is a name_or_vendor_gate.
        # Retirement of this detector arm: when no production Attribute load of
        # either name remains AND the type system forbids constructing a
        # name-keyed suppress contract (coordinates-only field), delete this arm.
        if node.attr in {"suppresses_exception", "exception_names"}:
            self._add(
                "name_or_vendor_gates",
                node,
                ast.unparse(node),
                "match exception_type_coordinate against ExitSuppressionContract "
                "coordinates minted at the suppresses() door; never suppress by name",
            )
        self.generic_visit(node)

    def _is_spelling_gate_compare(self, node: ast.Compare) -> bool:
        """True when this compare decides by display spelling, not a coordinate."""
        # Legacy vendor-string gates (kept: still a spelling membrane).
        string_values = {
            value.value
            for value in ast.walk(node)
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        }
        if any(
            "pytest.raises" in value or "contextlib.suppress" in value
            for value in string_values
        ):
            return True

        # type_name in {…} / type_name in SOME_FROZENSET — builtin shadowing lie.
        if any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            if isinstance(node.left, ast.Name) and node.left.id == "type_name":
                return True

        operands = (node.left, *node.comparators)
        attr_names = {
            operand.attr
            for operand in operands
            if isinstance(operand, ast.Attribute)
        }
        has_str_constant = any(
            isinstance(operand, ast.Constant) and isinstance(operand.value, str)
            for operand in operands
        )

        # effect.exception_name == "StopIteration" (and any == on that attr).
        if "exception_name" in attr_names:
            return True

        # func.id == "importorskip" / func.value.id == "pytest" — unbound lexical text.
        # Member path ``.attr == "importorskip"`` is structural once the head is
        # an authenticated import binding; it is not a spelling gate by itself.
        if "id" in attr_names and has_str_constant:
            return True

        # name == matcher.name — name-less suppress / spelling equality of names.
        name_attrs = [
            operand
            for operand in operands
            if isinstance(operand, ast.Attribute) and operand.attr == "name"
        ]
        name_names = [
            operand
            for operand in operands
            if isinstance(operand, ast.Name) and operand.id == "name"
        ]
        if name_attrs and (name_names or len(name_attrs) >= 2):
            return True

        return False

    def _add(self, axis: str, node: ast.AST, observed: str, replacement: str) -> None:
        self.offenders.append(
            BuiltinClosedOperationOffender(
                axis=axis,
                path=self.path,
                line=getattr(node, "lineno", 0),
                observed=observed,
                replacement=replacement,
            )
        )
