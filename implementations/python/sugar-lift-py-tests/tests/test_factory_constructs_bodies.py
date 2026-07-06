from __future__ import annotations

import ast
from pathlib import Path

from sugar_lift_py_tests.claim import SugarCatalog, SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.sugar.add_sugar import AddSugar
from sugar_lift_py_tests.sugar.array_literal_sugar import ArrayLiteralSugar
from sugar_lift_py_tests.sugar.bitwise_op_sugar import BitwiseOpSugar
from sugar_lift_py_tests.sugar.binop_sugar import BinOpSugar
from sugar_lift_py_tests.sugar.builder_ctor_sugar import BuilderCtorSugar
from sugar_lift_py_tests.sugar.lambda_sugar import LambdaSugar
from sugar_lift_py_tests.sugar.map_sugar import MapSugar
from sugar_lift_py_tests.sugar.to_list_sugar import ToListSugar
from sugar_lift_py_tests.sugar_body import SugarBody

SUGAR_DIR = (
    Path(__file__).resolve().parents[1] / "src" / "sugar_lift_py_tests" / "sugar"
)
FACTORY_CONSTRUCTORS = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "sugar_lift_py_tests"
    / "factory"
    / "sugar_constructors.py"
)


def _non_build_class_nodes(class_node: ast.ClassDef):
    """Yield all descendant AST nodes of `class_node`, skipping the body of any
    method named `build`. The `build` classmethod is allowed to call ctx.build_body
    (that IS the factory composing children); other methods are not."""
    for child in class_node.body:
        if isinstance(child, ast.FunctionDef) and child.name == "build":
            continue  # skip the build() classmethod -- it may call ctx.build_body
        yield from ast.walk(child)


def test_factory_backed_sugars_do_not_call_ctx_builders() -> None:
    offenders: list[str] = []
    for path in sorted(SUGAR_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for child in _non_build_class_nodes(node):
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr.startswith("build_")
                    and isinstance(child.func.value, ast.Name)
                    and child.func.value.id == "ctx"
                ):
                    offenders.append(f"{path.name}:{node.name}.{child.func.attr}")

    assert offenders == []


def test_factory_constructors_do_not_delegate_method_shape_to_sugar() -> None:
    tree = ast.parse(FACTORY_CONSTRUCTORS.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "from_call"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "MethodSugar"
        ):
            offenders.append(f"{FACTORY_CONSTRUCTORS.name}:{node.lineno}")

    assert offenders == []


def test_sugar_constructors_take_factory_built_bodies() -> None:
    body = SugarBody(sugar=object(), role=SugarRole.TERM)
    assert AddSugar(receiver=body, operand=body, blame="x.py:1:0").receiver is body
    assert ArrayLiteralSugar(elements=(body,)).elements == (body,)
    assert BitwiseOpSugar(operator="&", left=body, right=body).left is body
    assert (
        BinOpSugar(operator="+", left=body, right=body, blame="x.py:1:0").left is body
    )
    assert BuilderCtorSugar(items=body, blame="x.py:1:0").items is body
    assert LambdaSugar(parameter="x", body=body, blame="x.py:1:0").body is body
    assert MapSugar(blame="x.py:1:0", receiver=body, mapper=body).mapper is body
    assert ToListSugar(receiver=body, blame="x.py:1:0").receiver is body


def test_factory_context_is_still_the_body_builder() -> None:
    tree = ast.parse("[1]", mode="eval").body
    ctx = FactoryBuildContext(
        filename="x.py",
        catalog=SugarCatalog([]),
    )

    assert hasattr(ctx, "build_body")
    assert isinstance(tree, ast.List)
