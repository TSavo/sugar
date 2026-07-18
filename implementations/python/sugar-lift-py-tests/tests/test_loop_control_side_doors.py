from __future__ import annotations

import ast
import inspect

import sugar_lift_py_tests.sugar.comprehension_clauses as comprehension_clauses
import sugar_lift_py_tests.sugar.for_else_sugar as for_else_sugar
import sugar_lift_py_tests.sugar.for_sugar as for_sugar
import sugar_lift_py_tests.sugar.try_sugar as try_sugar
import sugar_lift_py_tests.sugar.while_sugar as while_sugar
from sugar_lift_py_tests.factory.source_fragment import SourceFragment


def _site(source: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(source).body[0], "side_door.py")


def test_loop_control_sugars_have_no_inline_ast_classifiers() -> None:
    modules = (
        for_sugar,
        while_sugar,
        for_else_sugar,
        try_sugar,
        comprehension_clauses,
    )

    offenders = {
        module.__name__: line.strip()
        for module in modules
        for line in inspect.getsource(module).splitlines()
        if "ast." in line or "import ast" in line or "ast.walk" in line
    }

    assert offenders == {}, (
        "loop/control-flow AST side doors remain; route recognition through "
        f"SourceFragment.classify_loop_control_scope(): {offenders}"
    )


def test_factory_classification_owns_only_the_outer_loop_break() -> None:
    outer = _site(
        "for item in items:\n"
        "    while ready:\n"
        "        break\n"
        "    if item:\n"
        "        break\n"
        "else:\n"
        "    pass\n"
    )
    nested_only = _site(
        "for item in items:\n"
        "    while ready:\n"
        "        break\n"
        "else:\n"
        "    pass\n"
    )

    assert outer.classify_loop_control_scope().has_owned_break is True
    assert nested_only.classify_loop_control_scope().has_owned_break is False


def test_factory_classification_reports_finally_terminal_control() -> None:
    site = _site(
        "try:\n" "    pass\n" "finally:\n" "    if ready:\n" "        return 1\n"
    )
    finalbody = site.try_finalbody()
    assert finalbody is not None

    assert finalbody.classify_loop_control_scope().contains_terminal_control is True


def test_factory_classification_constructs_comprehension_target_bindings() -> None:
    expression = ast.parse(
        "[(left, right) for left, (right, extra) in rows]",
        mode="eval",
    ).body
    generator = SourceFragment.from_node(
        expression.generators[0],
        "side_door.py",
    )
    target = generator.comprehension_target()

    assert target.classify_loop_control_scope().target_bindings == (
        ("left", (0,)),
        ("right", (1, 0)),
        ("extra", (1, 1)),
    )
