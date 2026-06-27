from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.floor import LambdaCallable
from sugar_lift_py_tests.operations import MapOperation, perform_operation
from sugar_lift_py_tests.outcome import Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody

from .array_literal_sugar import ArrayLiteralSugar
from .method_sugar import MethodSugar


@dataclass(frozen=True)
class MapSugar:
    blame: str
    receiver: ArrayLiteralSugar | SugarBody
    operation: MapOperation | None = None
    method: MethodSugar | None = None
    mapper: SugarBody | None = None

    @classmethod
    def from_site(cls, site, ctx) -> "MapSugar | None":
        method = MethodSugar.from_call(site.node)
        if method is None or method.method_name != "map" or len(method.args) != 1:
            return None
        return cls(
            blame=site.blame,
            receiver=ctx.build_body(method.receiver, SugarRole.TERM),
            mapper=ctx.build_body(method.args[0], SugarRole.TERM),
        )

    @classmethod
    def from_method(cls, method: MethodSugar, *, blame: str, ctx) -> "MapSugar | None":
        if method.method_name != "map" or len(method.args) != 1:
            return None
        receiver = ctx.build_child(method.receiver, SugarRole.TERM).sugar
        if not isinstance(receiver, ArrayLiteralSugar):
            return None
        operation = _map_operation(method.args[0])
        if operation is None:
            return None
        return cls(method=method, receiver=receiver, operation=operation, blame=blame)

    def desugar(self, ctx=None) -> Outcome:
        if isinstance(self.receiver, SugarBody):
            receiver = complete_value(
                self.receiver.reduce(ctx), owner="MapSugar receiver"
            )
            if self.mapper is None:
                raise TypeError("MapSugar body mode requires mapper")
            mapper = complete_value(self.mapper.reduce(ctx), owner="MapSugar mapper")
            if not isinstance(mapper, LambdaCallable):
                raise TypeError("MapSugar mapper must reduce to LambdaCallable")
            operation = MapOperation(mapper=mapper, owner="MapSugar", blame=self.blame)
        else:
            receiver = complete_value(self.receiver.desugar(), owner="MapSugar receiver")
            operation = self.operation
            if operation is None:
                raise TypeError("MapSugar method mode requires operation")
        return perform_operation(
            owner="MapSugar",
            blame=self.blame,
            receiver=receiver,
            method_name="map_with",
            operation=operation,
            ctx=ctx,
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


def _owns(site) -> bool:
    method = MethodSugar.from_call(site.node)
    return method is not None and method.method_name == "map" and len(method.args) == 1


def _build(site, ctx) -> MapSugar:
    sugar = MapSugar.from_site(site, ctx)
    if sugar is None:
        raise TypeError("MapSugar claim built a non-map call")
    return sugar


MAP_CLAIM = SugarClaim(
    name="MapSugar",
    role=SugarRole.TERM,
    owns=_owns,
    build=_build,
)
