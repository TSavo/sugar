from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.operations import CallableMapOperation, perform_operation
from sugar_lift_py_tests.outcome import Outcome, complete_value

from .function_ref_sugar import FunctionRefSugar
from .range_sugar import RangeSugar, range_sugar


@dataclass(frozen=True)
class MapBuiltinSugar:
    callable: FunctionRefSugar
    sequence: RangeSugar
    blame: str
    source_line: int
    source_col: int

    @classmethod
    def from_site(
        cls,
        site,
        *,
        functions_by_name: dict[str, ast.FunctionDef],
        blame: str,
    ) -> "MapBuiltinSugar | None":
        return map_builtin_sugar(site.node, functions_by_name, blame=blame)

    def desugar(self) -> Outcome:
        receiver = complete_value(self.sequence.desugar(), owner="MapBuiltinSugar receiver")
        callable_value = complete_value(
            self.callable.desugar(),
            owner="MapBuiltinSugar callable",
        )
        return perform_operation(
            owner="MapBuiltinSugar",
            blame=self.blame,
            receiver=receiver,
            method_name="map_with",
            operation=CallableMapOperation(callable_value),
            ctx=None,
        )


def map_builtin_sugar(
    node: ast.AST,
    functions_by_name: dict[str, ast.FunctionDef],
    *,
    blame: str,
) -> MapBuiltinSugar | None:
    if not isinstance(node, ast.Call):
        return None
    if not isinstance(node.func, ast.Name) or node.func.id != "map":
        return None
    if node.keywords or len(node.args) != 2:
        return None
    callable_sugar = FunctionRefSugar.from_node(node.args[0], functions_by_name)
    if callable_sugar is None:
        return None
    sequence = range_sugar(node.args[1])
    if sequence is None:
        return None
    return MapBuiltinSugar(
        callable=callable_sugar,
        sequence=sequence,
        blame=blame,
        source_line=node.lineno,
        source_col=node.col_offset,
    )
