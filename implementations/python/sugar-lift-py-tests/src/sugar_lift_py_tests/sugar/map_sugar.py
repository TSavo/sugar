from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.operations import MapOperation, perform_operation
from sugar_lift_py_tests.outcome import Outcome, complete_value

from .array_literal_sugar import ArrayLiteralSugar
from .method_sugar import MethodSugar


@dataclass(frozen=True)
class MapSugar:
    method: MethodSugar
    receiver: ArrayLiteralSugar
    operation: MapOperation
    blame: str

    @classmethod
    def from_method(cls, method: MethodSugar, *, blame: str) -> "MapSugar | None":
        if method.method_name != "map" or len(method.args) != 1:
            return None
        receiver = ArrayLiteralSugar.from_node(method.receiver)
        if receiver is None:
            return None
        operation = _map_operation(method.args[0])
        if operation is None:
            return None
        return cls(method=method, receiver=receiver, operation=operation, blame=blame)

    def desugar(self) -> Outcome:
        receiver = complete_value(self.receiver.desugar(), owner="MapSugar receiver")
        return perform_operation(
            owner="MapSugar",
            blame=self.blame,
            receiver=receiver,
            method_name="map_with",
            operation=self.operation,
            ctx=None,
        )


def _map_operation(node: ast.AST) -> MapOperation | None:
    if not isinstance(node, ast.Lambda):
        return None
    if len(node.args.args) != 1:
        return None
    parameter = node.args.args[0].arg
    body = node.body
    if not isinstance(body, ast.BinOp) or not isinstance(body.op, ast.Add):
        return None
    if not isinstance(body.left, ast.Name) or body.left.id != parameter:
        return None
    if not isinstance(body.right, ast.Constant) or not isinstance(body.right.value, int):
        return None
    return MapOperation(parameter=parameter, addend=body.right.value)
