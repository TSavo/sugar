"""NodeKind / OperatorKind -- the typed observation vocabulary.

`SourceFragment.observed` returns the structural AST class as a typed StrEnum.
Semantic distinctions inside a structural class belong to registered Sugars,
not this factory vocabulary.

The ast-derived members are generated mechanically from `ast.__dict__` so new
Python versions extend the vocabulary without edits. Two members are NOT ast
class names and are first-class citizens of the observation vocabulary:

- ``PRIMITIVE_LITERAL`` ("PrimitiveLiteral"): retained as a legacy wire member;
  new observations report structural ``CONSTANT`` and literal Sugars own the
  value classification.
- ``BLOCK`` ("Block"): the synthetic suite node (factory/block.py), previously
  an accident of `type(node).__name__`, now an explicit member.
"""

from __future__ import annotations

import ast
import re
from enum import StrEnum
from typing import Dict, Type

from .factory_gap import factory_panic
from .factory_gap_info import FactoryGapInfo, GapKind, GapLocus

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def _member_name(class_name: str) -> str:
    return _CAMEL_BOUNDARY.sub("_", class_name).upper()


def _ast_class_names() -> list[str]:
    """Concrete (leaf) ast classes -- the only names `type(node).__name__` yields.

    Abstract grouping bases (expr, stmt, mod, operator, ...) are excluded: no
    node ever observes as one, and `ast.expr`/`ast.Expr` would collide on the
    mechanical member name EXPR."""
    classes = {
        value
        for name, value in vars(ast).items()
        if not name.startswith("_")
        and isinstance(value, type)
        and issubclass(value, ast.AST)
        and value is not ast.AST
    }
    return sorted(
        cls.__name__
        for cls in classes
        if not any(other is not cls and issubclass(other, cls) for other in classes)
    )


class NodeKind(StrEnum):
    """One member per observable node kind; value is the wire string."""

    _ignore_ = ["_class_name", "_namespace"]

    _namespace = vars()
    for _class_name in _ast_class_names():
        _namespace[_member_name(_class_name)] = _class_name

    PRIMITIVE_LITERAL = "PrimitiveLiteral"
    BLOCK = "Block"

    @classmethod
    def of(cls, node: object) -> "NodeKind":
        """The one door from a node to its observed kind.

        Maps only by structural class name. An unknown class name is a
        totality-floor violation and panics naming the missing member.
        """
        node_type = type(node)
        cached = _NODE_KIND_CACHE.get(node_type)
        if cached is not None:
            return cached
        name = node_type.__name__
        try:
            kind = cls(name)
        except ValueError:
            factory_panic(
                FactoryGapInfo(
                    owner="NodeKind.of",
                    blame=f"{node_type.__module__}.{name}",
                    observed=name,
                    requested="NodeKind member",
                    fix=(
                        f'add NodeKind.{_member_name(name)} = "{name}" to '
                        "sugar_lift_py_tests.factory.node_kind"
                    ),
                    gap_kind=GapKind.FLOOR,
                    gap_locus=GapLocus.AST,
                )
            )
        _NODE_KIND_CACHE[node_type] = kind
        return kind


_NODE_KIND_CACHE: Dict[Type[object], NodeKind] = {}


class OperatorKind(StrEnum):
    """Typed vocabulary for `operator_kind()`; value is the ast op class name."""

    ADD = "Add"
    SUB = "Sub"
    MULT = "Mult"
    DIV = "Div"
    FLOOR_DIV = "FloorDiv"
    MOD = "Mod"
    POW = "Pow"
    MAT_MULT = "MatMult"
    L_SHIFT = "LShift"
    R_SHIFT = "RShift"
    BIT_OR = "BitOr"
    BIT_XOR = "BitXor"
    BIT_AND = "BitAnd"
    U_ADD = "UAdd"
    U_SUB = "USub"
    NOT = "Not"
    INVERT = "Invert"

    @classmethod
    def of(cls, op: object) -> "OperatorKind":
        name = type(op).__name__
        try:
            return cls(name)
        except ValueError:
            factory_panic(
                FactoryGapInfo(
                    owner="OperatorKind.of",
                    blame=f"{type(op).__module__}.{name}",
                    observed=name,
                    requested="OperatorKind member",
                    fix=(
                        f'add OperatorKind.{_member_name(name)} = "{name}" to '
                        "sugar_lift_py_tests.factory.node_kind"
                    ),
                    gap_kind=GapKind.FLOOR,
                    gap_locus=GapLocus.AST,
                )
            )
