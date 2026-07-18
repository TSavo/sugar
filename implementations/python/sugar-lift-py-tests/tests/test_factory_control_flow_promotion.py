from __future__ import annotations

import ast
from pathlib import Path

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.factory.sugar_constructors import _ctx_with_formal_binds
from sugar_lift_py_tests.sugar.control_flow_body_sugar import ControlFlowBodySugar
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_KIT = Path(__file__).resolve().parents[1]
_FACTORY_CONSTRUCTORS = (
    _KIT / "src" / "sugar_lift_py_tests" / "factory" / "sugar_constructors.py"
)


def _selected(source: str, role: SugarRole) -> str:
    node = (
        ast.parse(source, filename="promotion.py", mode="eval").body
        if role is SugarRole.TERM
        else ast.parse(source, filename="promotion.py").body[0]
    )
    site = SourceFragment.from_node(node, "promotion.py")
    result = build_node(
        site,
        filename="promotion.py",
        role=role,
        catalog=default_catalog(),
    )
    assert result.audit_row.selected is not None
    return result.audit_row.selected


def test_control_flow_shapes_are_owned_by_registered_sugars() -> None:
    assert _selected("name", SugarRole.TERM) == "NameSugar"
    assert _selected("7", SugarRole.TERM) == "IntLiteralSugar"
    assert _selected("'text'", SugarRole.TERM) == "StringLiteralSugar"
    assert _selected("left == 7", SugarRole.TERM) == "EqualityOpSugar"
    assert _selected("left != 7", SugarRole.TERM) == "InequalityOpSugar"
    assert _selected("left > 7", SugarRole.TERM) == "GreaterThanOpSugar"
    assert _selected("left < 7", SugarRole.TERM) == "LessThanOpSugar"
    assert _selected("return 7", SugarRole.STATEMENT) == "ReturnSugar"
    assert (
        _selected("if left == 7:\n    return 1\nreturn 0", SugarRole.STATEMENT)
        == "IfSugar"
    )


def test_control_flow_function_body_is_selected_through_its_sugar_role() -> None:
    root = SourceFragment.from_source(
        "def choose(left):\n"
        "    if left == 7:\n"
        "        return 1\n"
        "    return 0\n",
        "promotion.py",
    )
    fn = next(site for site in root.walk() if site.observed == "FunctionDef")
    ctx = FactoryBuildContext(filename="promotion.py", catalog=default_catalog())
    body_ctx = _ctx_with_formal_binds(fn, ctx)

    result = build_node(
        fn,
        filename="promotion.py",
        role=SugarRole.CONTROL_FLOW_BODY,
        catalog=body_ctx.catalog,
        ctx=body_ctx,
    )

    assert result.audit_row.selected == "ControlFlowBodySugar"
    assert isinstance(result.sugar, ControlFlowBodySugar)
    formulas = result.sugar.constraint_formulas()
    assert len(formulas) == 1
    rendered = str(formulas[0])
    assert "out" in rendered
    assert "left" in rendered


def test_factory_top_has_no_control_flow_construction_helpers() -> None:
    tree = ast.parse(_FACTORY_CONSTRUCTORS.read_text(encoding="utf-8"))
    function_names = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }

    assert "_cf_operand" not in function_names
    assert "_cf_guard" not in function_names
    assert "_lift_cf_return" not in function_names
    assert "_walk_control_flow" not in function_names
    assert "build_control_flow_body_sugar" not in function_names


def test_control_flow_body_truthful_witness_discharge_and_lie_refutes(
    tmp_path: Path,
) -> None:
    pair = ControlFlowBodySugar.witnesses()
    truthful = run_source_through_real_solver(
        tmp_path / "truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", pair.lying.source)

    assert "ControlFlowBodySugar" in truthful.selected_sugars
    assert "ControlFlowBodySugar" in lying.selected_sugars
    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
