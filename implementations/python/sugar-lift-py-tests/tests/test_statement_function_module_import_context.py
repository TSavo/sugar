from __future__ import annotations

from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory import default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import ClassValue, FunctionCallable, ImportAliasValue
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.statement_function_def_sugar import (
    StatementFunctionDefSugar,
)
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _statement_callable(
    source: str, qualified_name: str, *, installed: bool = True
) -> FunctionCallable:
    root = SourceFragment.from_source(source, "/installed/module.py")
    fn = next(
        fragment
        for fragment in root.walk()
        if fragment.observed == "FunctionDef"
        and fragment.function_name() == qualified_name.rsplit(".", 1)[-1]
    )
    if installed:
        fn.node._sugar_source = source  # type: ignore[attr-defined]
        fn.node._sugar_file = "/installed/module.py"  # type: ignore[attr-defined]
        fn.node._sugar_bridge_name = qualified_name  # type: ignore[attr-defined]
    ctx = FactoryBuildContext(filename="consumer.py", catalog=default_catalog())
    sugar = StatementFunctionDefSugar.new(fn, ctx)
    value = complete_value(
        sugar.desugar(ctx), owner="installed statement function callable"
    )
    assert isinstance(value, FunctionCallable)
    return value


def test_installed_statement_callable_captures_only_needed_module_import_alias() -> (
    None
):
    callable_value = _statement_callable(
        "import provider_alpha as com\n"
        "import unrelated_provider as unused\n"
        "def select(value):\n"
        "    if com.any_none(value):\n"
        "        return 1\n"
        "    return 0\n",
        "installed.module.select",
    )

    body = callable_value.body
    assert body is not None
    contextualized = body.sugar
    com = contextualized.base_context.temporal.value_if_bound("com")
    assert isinstance(com, ImportAliasValue)
    assert com.import_target == "provider_alpha"
    assert contextualized.base_context.temporal.value_if_bound("unused") is None


def test_untagged_statement_callable_does_not_borrow_module_imports() -> None:
    callable_value = _statement_callable(
        "import provider_alpha as com\n"
        "def select(value):\n"
        "    return com.any_none(value)\n",
        "installed.module.select",
        installed=False,
    )

    body = callable_value.body
    assert body is not None
    assert body.sugar.base_context.temporal.value_if_bound("com") is None


def test_installed_statement_callable_captures_needed_forward_module_class() -> None:
    callable_value = _statement_callable(
        "def select(value):\n"
        "    return isinstance(value, Later)\n"
        "\n"
        "class Unused:\n"
        "    pass\n"
        "\n"
        "class Later(Base):\n"
        "    pass\n",
        "installed.module.select",
    )

    body = callable_value.body
    assert body is not None
    contextualized = body.sugar
    later = contextualized.base_context.temporal.value_if_bound("Later")
    assert isinstance(later, ClassValue)
    assert later.name == "Later"
    assert contextualized.base_context.temporal.value_if_bound("Unused") is None


def test_installed_statement_callable_leaves_decorated_forward_class_loud() -> None:
    callable_value = _statement_callable(
        "def select(value):\n"
        "    return isinstance(value, Later)\n"
        "\n"
        "@runtime_decorator\n"
        "class Later:\n"
        "    pass\n",
        "installed.module.select",
    )

    body = callable_value.body
    assert body is not None
    contextualized = body.sugar
    assert contextualized.base_context.temporal.value_if_bound("Later") is None


def test_module_import_context_truthful_and_lying_twins_refute(tmp_path) -> None:
    prefix = (
        "import operator as com\n" "def A():\n" "    marker = com\n" "    return 1\n"
    )
    truthful = run_source_through_real_solver(
        tmp_path / "module-import-context-truthful",
        prefix + "def test_a():\n    assert A() == 1\n",
    )
    lying = run_source_through_real_solver(
        tmp_path / "module-import-context-lying",
        prefix + "def test_a():\n    assert A() == 0\n",
    )

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
    assert "FunctionDefSugar" in truthful.selected_sugars
    assert "FunctionDefSugar" in lying.selected_sugars
