from __future__ import annotations

import ast
from pathlib import Path


from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

FACTORY_CONSTRUCTORS = (
    sugar_lift_py_tests_package_root()
    / "src"
    / "sugar_lift_py_tests"
    / "factory"
    / "sugar_constructors.py"
)
STATEMENT_FUNCTION_DEF_SUGAR = (
    sugar_lift_py_tests_package_root()
    / "src"
    / "sugar_lift_py_tests"
    / "sugar"
    / "statement_function_def_sugar.py"
)


def test_factory_value_helpers_are_deleted_not_relocated() -> None:
    if not FACTORY_CONSTRUCTORS.exists():
        return
    tree = ast.parse(FACTORY_CONSTRUCTORS.read_text(encoding="utf-8"))
    forbidden_names = {
        "ImportAliasValue",
        "SymbolicValue",
        "bind_temporal",
        "module_class_value",
    }
    forbidden_helpers = {"_ctx_with_formal_binds", "build_bridge_body"}
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in forbidden_helpers:
                offenders.append(f"{node.lineno}:def {node.name}")
            continue
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in forbidden_names:
            offenders.append(f"{node.lineno}:{node.func.id}")
        if isinstance(node.func, ast.Attribute) and node.func.attr == "bind_value":
            offenders.append(f"{node.lineno}:.bind_value")

    assert offenders == [], (
        "factory value construction must be owned by registered Sugar recognizers; "
        f"promote and delete these side doors: {', '.join(offenders)}"
    )


def test_promoted_module_replay_never_swallows_incomplete() -> None:
    tree = ast.parse(STATEMENT_FUNCTION_DEF_SUGAR.read_text(encoding="utf-8"))
    offenders: list[int] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if not any(
            isinstance(child, ast.Name) and child.id == "Incomplete"
            for child in ast.walk(node.test)
        ):
            continue
        if any(isinstance(child, ast.Continue) for child in node.body):
            offenders.append(node.lineno)

    assert offenders == [], (
        "promoted Sugar must construct cited evidence or stay loud; "
        f"delete Incomplete-to-continue suppression at lines {offenders}"
    )
