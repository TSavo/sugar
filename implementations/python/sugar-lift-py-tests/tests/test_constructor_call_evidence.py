from __future__ import annotations

import ast
import importlib
import json

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import ImportAliasValue, ObjectValue, TermValue
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _outcome(
    source: str,
    expression: str,
    *,
    temporal: TemporalContext | None = None,
):
    module = ast.parse(source)
    resolver = {
        statement.name: statement
        for statement in module.body
        if isinstance(statement, (ast.ClassDef, ast.FunctionDef))
    }
    ctx = FactoryBuildContext(
        filename="constructor.py",
        catalog=default_catalog(),
        name_resolver=resolver,
        temporal=temporal or TemporalContext.empty(),
    )
    node = ast.parse(expression, mode="eval").body
    return ctx.build_body(node, SugarRole.TERM).reduce(ctx)


def _field_values(value: ObjectValue) -> dict[str, object]:
    return {field.name: field.value for field in value.fields}


def test_dataclass_constructor_builds_annotated_fields() -> None:
    outcome = _outcome(
        "@dataclass\n" "class Box:\n" "    left: int\n" "    right: int\n",
        "Box(1, 2)",
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    assert _field_values(outcome.value) == {
        "left": TermValue(1),
        "right": TermValue(2),
    }


def test_namedtuple_constructor_builds_annotated_fields() -> None:
    outcome = _outcome(
        "class Pair(NamedTuple):\n" "    left: int\n" "    right: int\n",
        "Pair(3, 4)",
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    assert _field_values(outcome.value) == {
        "left": TermValue(3),
        "right": TermValue(4),
    }


def test_assignment_constructor_binds_trailing_positional_default() -> None:
    outcome = _outcome(
        "class Box:\n"
        "    def __init__(self, left, right=5):\n"
        "        self.left = left\n"
        "        self.right = right\n",
        "Box(3)",
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    assert _field_values(outcome.value) == {
        "left": TermValue(3),
        "right": TermValue(5),
    }


def test_static_inherited_constructor_builds_base_fields() -> None:
    outcome = _outcome(
        "class Base:\n"
        "    def __init__(self, value):\n"
        "        self.value = value\n"
        "\n"
        "class Child(Base):\n"
        "    pass\n",
        "Child(7)",
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    assert outcome.value.class_name == "Child"
    assert _field_values(outcome.value) == {"value": TermValue(7)}


def test_source_backed_imported_inherited_constructor_builds_base_fields(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "base_mod.py").write_text(
        "class Base:\n"
        "    def __init__(self, value):\n"
        "        self.value = value\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    temporal = TemporalContext.empty().bind_value(
        "Base",
        ImportAliasValue(
            "Base",
            "Base",
            import_target="base_mod.Base",
        ),
    )

    outcome = _outcome(
        "class Child(Base):\n"
        "    pass\n",
        "Child(7)",
        temporal=temporal,
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    assert outcome.value.class_name == "Child"
    assert _field_values(outcome.value) == {"value": TermValue(7)}


def test_unresolved_inherited_constructor_panics_instead_of_faking_runtime() -> None:
    with pytest.raises(FactoryPanic) as raised:
        _outcome(
            "class Child(ImportedBase):\n" "    pass\n",
            "Child(1)",
        )

    assert raised.value.info.owner == "ConstructorCallSugar"
    assert raised.value.info.requested == "statically resolved inherited constructor"
    json.dumps(raised.value.info.to_json())


def test_runtime_selected_base_keeps_authenticated_constructor_effect() -> None:
    from sugar_lift_py_tests.effect import ConstructorRuntimeEffect

    outcome = _outcome(
        "class Child(select_base()):\n" "    pass\n",
        "Child(1)",
    )

    assert type(outcome) is Incomplete
    assert type(outcome.effect) is ConstructorRuntimeEffect
    assert outcome.effect.witness.operation.name == "py.constructor"
    assert outcome.effect.witness.site.filename == "constructor.py"
    assert "runtime-selected base" in outcome.effect.reason


def test_runtime_selected_base_wrong_twin_hits_runtime_operand_door() -> None:
    from sugar_lift_py_tests.effect import runtime_effect_evidence
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment
    from sugar_lift_py_tests.ir import num

    with pytest.raises(FactoryPanic):
        runtime_effect_evidence(
            "py.constructor",
            num(1),
            SourceFragment.from_source("Child(1)", "constructor.py"),
        )


def test_effectful_init_stays_a_named_runtime_effect() -> None:
    from sugar_lift_py_tests.effect import ConstructorRuntimeEffect

    outcome = _outcome(
        "class Box:\n" "    def __init__(self, value):\n" "        assert value\n",
        "Box(1)",
    )

    assert type(outcome) is Incomplete
    assert type(outcome.effect) is ConstructorRuntimeEffect
    assert "Assert" in outcome.effect.reason


def test_statically_impossible_constructor_arity_is_witnessed_type_error() -> None:
    from sugar_lift_py_tests.effect import TypeErrorRuntimeEffect

    outcome = _outcome(
        "class Box:\n"
        "    def __init__(self, value):\n"
        "        self.value = value\n",
        "Box()",
    )

    assert type(outcome) is Incomplete
    assert type(outcome.effect) is TypeErrorRuntimeEffect
    assert outcome.effect.witness.operation.name == "py.constructor"
    assert "requires 1..1 positional arguments" in outcome.effect.reason


@pytest.mark.parametrize(
    ("prefix", "truth", "lie"),
    (
        (
            "from dataclasses import dataclass\n"
            "@dataclass\n"
            "class Box:\n"
            "    left: int\n"
            "    right: int\n"
            "\n"
            "def A():\n"
            "    return Box(1, 2).right\n",
            2,
            3,
        ),
        (
            "from typing import NamedTuple\n"
            "class Pair(NamedTuple):\n"
            "    left: int\n"
            "    right: int\n"
            "\n"
            "def A():\n"
            "    return Pair(3, 4).right\n",
            4,
            5,
        ),
        (
            "class Box:\n"
            "    def __init__(self, left, right=5):\n"
            "        self.left = left\n"
            "        self.right = right\n"
            "\n"
            "def A():\n"
            "    return Box(3).right\n",
            5,
            6,
        ),
    ),
)
def test_constructed_constructor_fields_refute_wrong_twins(
    tmp_path, prefix: str, truth: int, lie: int
) -> None:
    truthful = run_source_through_real_solver(
        tmp_path / f"truth-{truth}",
        prefix + f"\ndef test_a():\n    assert A() == {truth}\n",
    )
    lying = run_source_through_real_solver(
        tmp_path / f"lie-{truth}",
        prefix + f"\ndef test_a():\n    assert A() == {lie}\n",
    )

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
    assert "ConstructorCallSugar" in truthful.selected_sugars
    assert "ConstructorCallSugar" in lying.selected_sugars


def test_source_backed_imported_constructor_refutes_wrong_twin(tmp_path) -> None:
    prefix = (
        "from base_mod import Base\n"
        "class Child(Base):\n"
        "    pass\n"
        "\n"
        "def A():\n"
        "    return Child(7).value\n"
    )
    truthful_dir = tmp_path / "imported-constructor-truthful"
    lying_dir = tmp_path / "imported-constructor-lying"
    for project in (truthful_dir, lying_dir):
        project.mkdir()
        (project / "base_mod.py").write_text(
            "class Base:\n"
            "    def __init__(self, value):\n"
            "        self.value = value\n",
            encoding="utf-8",
        )

    truthful = run_source_through_real_solver(
        truthful_dir,
        prefix + "\ndef test_a():\n    assert A() == 7\n",
    )
    lying = run_source_through_real_solver(
        lying_dir,
        prefix + "\ndef test_a():\n    assert A() == 8\n",
    )

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
    assert "ConstructorCallSugar" in truthful.selected_sugars
    assert "ConstructorCallSugar" in lying.selected_sugars
