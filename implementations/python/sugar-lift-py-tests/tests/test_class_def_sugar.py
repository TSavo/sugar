"""ClassDefSugar: class body threads; bases ride as coordinates.

Plain `class C:` / `class C(Base):` only. Decorators and metaclass keywords
stay loud gaps.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    BlockValue,
    ClassValue,
    SymbolicValue,
    FunctionCallable,
)
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.lift_rpc import audit_lift_file
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.class_def_sugar import ClassDefSugar
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _site(source: str):
    node = ast.parse(source).body[0]
    return SourceFragment.from_node(node, "t.py")


def _class_value(source: str, *, binds: dict | None = None) -> ClassValue:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    if binds:
        from dataclasses import replace
        from sugar_lift_py_tests.temporal import TemporalContext

        temporal = TemporalContext.empty()
        for name, value in binds.items():
            temporal = temporal.bind_value(name, value)
        ctx = replace(ctx, temporal=temporal)
    node = ast.parse(source).body[0]
    result = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    value = complete_value(result.sugar.desugar(ctx), owner="test")
    assert isinstance(value, ClassValue)
    return value


def test_class_body_method_threads_into_the_record() -> None:
    """(1) Method FunctionDef in the body becomes a deferred callable."""
    cls = _class_value("class C:\n" "    def m(self):\n" "        return 1\n")
    assert cls.name == "C"
    assert cls.bases == ()
    # Body contribution is the method callable.
    entries = cls.contribution()
    assert len(entries) == 1
    assert isinstance(entries[0], FunctionCallable)
    assert entries[0].name == "m"
    assert entries[0].parameters == ("self",)


def test_class_bases_are_carried_as_coordinates() -> None:
    """(1) Bases reduce to type coordinates (not dropped)."""
    cls = _class_value(
        "class C(Base):\n" "    pass\n",
        binds={"Base": SymbolicValue(make_var("Base"))},
    )
    assert cls.name == "C"
    assert len(cls.bases) == 1
    assert cls.bases[0] == SymbolicValue(make_var("Base"))
    assert cls.base_terms() == (make_var("Base"),)


def test_base_or_body_discriminates() -> None:
    """(2) Different base or body method produces a different contribution."""
    with_base_a = _class_value(
        "class C(A):\n" "    pass\n",
        binds={"A": SymbolicValue(make_var("A"))},
    )
    with_base_b = _class_value(
        "class C(B):\n" "    pass\n",
        binds={"B": SymbolicValue(make_var("B"))},
    )
    assert with_base_a.bases[0] != with_base_b.bases[0]
    assert with_base_a.base_terms() != with_base_b.base_terms()

    with_m = _class_value("class C:\n" "    def m(self):\n" "        return 1\n")
    with_n = _class_value("class C:\n" "    def n(self):\n" "        return 1\n")
    assert with_m.contribution()[0].name == "m"
    assert with_n.contribution()[0].name == "n"
    assert with_m.contribution()[0].name != with_n.contribution()[0].name


def test_class_binds_name_for_later_reference() -> None:
    """Class statement extends scope so a later name resolves to ClassValue."""
    block = compose_block(
        "    class C:\n" "        pass\n" "    return C\n",
    )
    assert isinstance(block, BlockValue)
    # Class body is empty (pass is support); return resolves C.
    from sugar_lift_py_tests.floor import ReturnValue

    ret = [s for s in block.statements if isinstance(s, ReturnValue)]
    assert len(ret) == 1
    assert isinstance(ret[0].value, ClassValue)
    assert ret[0].value.name == "C"


def test_definition_root_replays_prior_class_local_definitions() -> None:
    source = (
        "class C:\n"
        "    def f2(x, y):\n"
        "        return x ** y\n"
        "\n"
        "    class Helper:\n"
        "        pass\n"
        "\n"
        "    def method(self, operation=f2, helper=Helper):\n"
        "        return operation, helper\n"
    )

    recovered = audit_lift_file(source, "class_defaults.py", recover_panics=True)

    assert [
        panic.gap
        for panic in recovered.panics
        if panic.gap.get("owner") == "TemporalContext"
    ] == []


def test_definition_root_does_not_replay_later_class_local_definition() -> None:
    source = (
        "class C:\n"
        "    def method(self, operation=f2):\n"
        "        return operation\n"
        "\n"
        "    def f2(x, y):\n"
        "        return x ** y\n"
    )

    recovered = audit_lift_file(
        source, "class_defaults_wrong_order.py", recover_panics=True
    )
    temporal = [
        panic.gap
        for panic in recovered.panics
        if panic.gap.get("owner") == "TemporalContext"
    ]

    assert temporal
    assert {gap["observed"] for gap in temporal} == {"f2"}


def test_class_local_default_witness_truthful_sat_wrong_twin_unsat(
    tmp_path: Path,
) -> None:
    pair = next(
        witness
        for witness in ClassDefSugar.witnesses()
        if witness.name == "class_local_default_binding_return"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "class-local-default-truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / "class-local-default-lying", pair.lying.source
    )

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_accessor_decorated_class_witness_truthful_sat_wrong_twin_unsat(
    tmp_path: Path,
) -> None:
    pair = next(
        witness
        for witness in ClassDefSugar.witnesses()
        if witness.name == "accessor_decorated_class_return"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "accessor-decorated-truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / "accessor-decorated-lying", pair.lying.source
    )

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_dataclass_decorated_class_witness_truthful_sat_wrong_twin_unsat(
    tmp_path: Path,
) -> None:
    pair = next(
        witness
        for witness in ClassDefSugar.witnesses()
        if witness.name == "dataclass_decorated_class_return"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "dataclass-decorated-truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / "dataclass-decorated-lying", pair.lying.source
    )

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_pydantic_dataclass_class_witness_truthful_sat_wrong_twin_unsat(
    tmp_path: Path,
) -> None:
    pair = next(
        witness
        for witness in ClassDefSugar.witnesses()
        if witness.name == "pydantic_dataclass_class_return"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "pydantic-dataclass-truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / "pydantic-dataclass-lying", pair.lying.source
    )

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_deprecated_decorated_class_witness_truthful_sat_wrong_twin_unsat(
    tmp_path: Path,
) -> None:
    pair = next(
        witness
        for witness in ClassDefSugar.witnesses()
        if witness.name == "deprecated_decorated_class_return"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "deprecated-decorated-truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / "deprecated-decorated-lying", pair.lying.source
    )

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_pydantic_base_model_extra_class_witness_truthful_sat_wrong_twin_unsat(
    tmp_path: Path,
) -> None:
    pair = next(
        witness
        for witness in ClassDefSugar.witnesses()
        if witness.name == "pydantic_base_model_extra_class_return"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "pydantic-base-model-extra-truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / "pydantic-base-model-extra-lying", pair.lying.source
    )

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_sqlalchemy_orm_decorated_class_witness_truthful_sat_wrong_twin_unsat(
    tmp_path: Path,
) -> None:
    pair = next(
        witness
        for witness in ClassDefSugar.witnesses()
        if witness.name == "sqlalchemy_orm_decorated_class_return"
    )
    seeds = Path(__file__).parent / "witness_seeds"

    truthful = run_source_through_real_solver(
        tmp_path / "sqlalchemy-class-truthful",
        (seeds / "sqlalchemy_orm_class_truthful.py").read_text(),
    )
    lying = run_source_through_real_solver(
        tmp_path / "sqlalchemy-class-lying",
        (seeds / "sqlalchemy_orm_class_lying.py").read_text(),
    )

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_typed_dict_total_class_witness_truthful_sat_wrong_twin_unsat(
    tmp_path: Path,
) -> None:
    pair = next(
        witness
        for witness in ClassDefSugar.witnesses()
        if witness.name == "typed_dict_total_class_return"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "typed-dict-total-truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / "typed-dict-total-lying", pair.lying.source
    )

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_owns_plain_class_not_decorated_metaclass_or_function() -> None:
    """(3) owns plain class; not decorated, metaclass, or FunctionDef."""
    assert ClassDefSugar.owns(_site("class C:\n    pass\n")) is True
    assert ClassDefSugar.owns(_site("class C(Base):\n    pass\n")) is True
    assert ClassDefSugar.owns(_site("class C(A, B):\n    pass\n")) is True
    assert ClassDefSugar.owns(_site("@dec\nclass C:\n    pass\n")) is False
    assert ClassDefSugar.owns(_site("class C(metaclass=M):\n    pass\n")) is False
    assert ClassDefSugar.owns(_site("def f():\n    pass\n")) is False

    catalog = default_catalog()
    plain = _site("class C:\n    pass\n")
    assert any(
        c.name == "ClassDefSugar"
        for c in catalog.candidates_for(SugarRole.STATEMENT, plain)
    )


def test_owns_authenticated_pandas_accessor_decorated_class() -> None:
    source = (
        "import pandas as pd\n"
        '@pd.api.extensions.register_series_accessor("bad")\n'
        "class Bad:\n"
        "    pass\n"
    )
    site = SourceFragment.from_node(ast.parse(source).body[1], "t.py", source=source)

    assert ClassDefSugar.owns(site) is True


def test_owns_authenticated_stdlib_dataclass_decorated_class() -> None:
    source = (
        "from dataclasses import dataclass\n"
        "@dataclass\n"
        "class Dog:\n"
        "    name: str\n"
        "    age: int\n"
    )
    site = SourceFragment.from_node(ast.parse(source).body[1], "t.py", source=source)

    assert ClassDefSugar.owns(site) is True

    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    result = build_node(site, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert result.audit_row.selected == "ClassDefSugar"


def test_owns_authenticated_module_qualified_stdlib_dataclass() -> None:
    source = (
        "import dataclasses\n"
        "@dataclasses.dataclass\n"
        "class Dog:\n"
        "    name: str\n"
    )
    site = SourceFragment.from_node(ast.parse(source).body[1], "t.py", source=source)

    assert ClassDefSugar.owns(site) is True


@pytest.mark.parametrize(
    "source",
    (
        (
            "from warnings import deprecated\n"
            '@deprecated("use other")\n'
            "class Point:\n"
            "    value = 1\n"
        ),
        (
            "import warnings\n"
            '@warnings.deprecated("use other")\n'
            "class Point:\n"
            "    value = 1\n"
        ),
        (
            "from typing_extensions import deprecated\n"
            '@deprecated("use other")\n'
            "class Point:\n"
            "    value = 1\n"
        ),
        # sklearn residual spelling: empty Call form via deprecation submodule.
        (
            "from sklearn.utils.deprecation import deprecated\n"
            "@deprecated()\n"
            "class MockClass:\n"
            "    def __init__(self, a, b=1, c=2):\n"
            "        pass\n"
        ),
        # production re-export path used by sklearn.linear_model.
        (
            "from sklearn.utils import deprecated\n"
            '@deprecated("msg")\n'
            "class Passive:\n"
            "    pass\n"
        ),
    ),
)
def test_owns_authenticated_deprecated_decorated_class(source: str) -> None:
    site = SourceFragment.from_node(ast.parse(source).body[1], "t.py", source=source)

    assert ClassDefSugar.owns(site) is True

    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    result = build_node(site, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert result.audit_row.selected == "ClassDefSugar"


@pytest.mark.parametrize(
    "source",
    (
        (
            "from sqlalchemy.orm import as_declarative as declarative_base\n"
            "@declarative_base()\n"
            "class Base:\n"
            "    pass\n"
        ),
        (
            "from sqlalchemy.ext import declarative as legacy_decl\n"
            "@legacy_decl.as_declarative()\n"
            "class Base:\n"
            "    pass\n"
        ),
        (
            "from sqlalchemy.orm import registry as registry_factory\n"
            "mapper_registry = registry_factory()\n"
            "@mapper_registry.mapped\n"
            "class User:\n"
            "    pass\n"
        ),
        (
            "import sqlalchemy.orm as orm\n"
            "mapper_registry = orm.registry()\n"
            "@mapper_registry.mapped_as_dataclass()\n"
            "class User:\n"
            "    value: int\n"
        ),
    ),
)
def test_owns_source_authenticated_sqlalchemy_orm_class_decorator(
    source: str,
) -> None:
    site = SourceFragment.from_node(ast.parse(source).body[-1], "t.py", source=source)

    assert ClassDefSugar.owns(site) is True

    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    result = build_node(site, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert result.audit_row.selected == "ClassDefSugar"


def test_same_named_local_deprecated_decorator_stays_loud() -> None:
    source = (
        'def deprecated(extra=""):\n'
        "    return lambda cls: 7\n"
        "@deprecated()\n"
        "class MockClass:\n"
        "    pass\n"
    )
    site = SourceFragment.from_node(ast.parse(source).body[1], "t.py", source=source)
    assert ClassDefSugar.owns(site) is False

    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    with pytest.raises(FactoryPanic) as raised:
        build_node(site, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert raised.value.info.observed == "ClassDef"


def test_class_keywords_auto_wrap_partition_stays_loud() -> None:
    """Sibling residual: ClassDef keywords are a separate family (not this PR)."""
    source = (
        "class _SetOutputMixin:\n"
        "    pass\n"
        "class Estimator(_SetOutputMixin, auto_wrap_output_keys=None):\n"
        "    def transform(self, X, y=None):\n"
        "        return X\n"
    )
    site = SourceFragment.from_node(ast.parse(source).body[1], "t.py", source=source)

    assert ClassDefSugar.owns(site) is False

    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    with pytest.raises(FactoryPanic) as raised:
        build_node(site, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert raised.value.info.observed == "ClassDef"


@pytest.mark.parametrize(
    "source",
    (
        (
            "def as_declarative():\n"
            "    return lambda cls: 7\n"
            "@as_declarative()\n"
            "class Base:\n"
            "    pass\n"
        ),
        (
            "class Registry:\n"
            "    mapped = lambda self, cls: 7\n"
            "registry = Registry()\n"
            "@registry.mapped\n"
            "class User:\n"
            "    pass\n"
        ),
        (
            "from sqlalchemy.orm import registry\n"
            "def build(registry):\n"
            "    @registry.mapped\n"
            "    class User:\n"
            "        pass\n"
            "    return User\n"
        ),
        (
            "from sqlalchemy.orm import as_declarative\n"
            "as_declarative = lambda: (lambda cls: 7)\n"
            "@as_declarative()\n"
            "class Base:\n"
            "    pass\n"
        ),
    ),
)
def test_sqlalchemy_decorator_lookalikes_and_shadowed_imports_stay_loud(
    source: str,
) -> None:
    class_node = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ClassDef) and node.name in {"Base", "User"}
    )
    site = SourceFragment.from_node(class_node, "t.py", source=source)

    assert ClassDefSugar.owns(site) is False

    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    with pytest.raises(FactoryPanic) as raised:
        build_node(site, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert raised.value.info.observed == "ClassDef"


@pytest.mark.parametrize(
    "import_statement",
    ("import pydantic", "import pydantic.dataclasses"),
)
def test_owns_authenticated_module_qualified_pydantic_dataclass(
    import_statement: str,
) -> None:
    source = (
        f"{import_statement}\n"
        "@pydantic.dataclasses.dataclass\n"
        "class Payload:\n"
        "    value: int\n"
    )
    site = SourceFragment.from_node(ast.parse(source).body[1], "t.py", source=source)

    assert ClassDefSugar.owns(site) is True

    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    result = build_node(site, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert result.audit_row.selected == "ClassDefSugar"


def test_same_named_local_pydantic_dataclasses_namespace_stays_loud() -> None:
    source = (
        "class dataclasses:\n"
        "    dataclass = lambda cls: 7\n"
        "class pydantic:\n"
        "    dataclasses = dataclasses\n"
        "@pydantic.dataclasses.dataclass\n"
        "class Payload:\n"
        "    value: int\n"
    )
    site = SourceFragment.from_node(ast.parse(source).body[-1], "t.py", source=source)
    assert ClassDefSugar.owns(site) is False

    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    with pytest.raises(FactoryPanic) as raised:
        build_node(site, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert raised.value.info.observed == "ClassDef"


@pytest.mark.parametrize(
    ("import_statement", "base"),
    (
        ("from pydantic import BaseModel as ModelBase", "ModelBase"),
        ("import pydantic as pd", "pd.BaseModel"),
    ),
)
def test_owns_authenticated_pydantic_base_model_extra_class(
    import_statement: str,
    base: str,
) -> None:
    source = (
        f"{import_statement}\n"
        f'class Payload({base}, extra="allow"):\n'
        "    value: int\n"
    )
    site = SourceFragment.from_node(ast.parse(source).body[1], "t.py", source=source)

    assert ClassDefSugar.owns(site) is True

    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    result = build_node(site, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert result.audit_row.selected == "ClassDefSugar"
    assert len(result.sugar.class_options) == 1


@pytest.mark.parametrize(
    "source",
    (
        (
            "class BaseModel:\n"
            "    pass\n"
            'class Payload(BaseModel, extra="allow"):\n'
            "    value: int\n"
        ),
        (
            "from pydantic import BaseModel\n"
            "class Payload(BaseModel, from_attributes=True):\n"
            "    value: int\n"
        ),
        (
            "from pydantic import BaseModel\n"
            'class Payload(BaseModel, extra="forbid"):\n'
            "    value: int\n"
        ),
        (
            "from pydantic import BaseModel\n"
            'class Payload(BaseModel, extra="allow", frozen=True):\n'
            "    value: int\n"
        ),
    ),
)
def test_unsupported_pydantic_base_model_keyword_partitions_stay_loud(
    source: str,
) -> None:
    site = SourceFragment.from_node(ast.parse(source).body[-1], "t.py", source=source)
    assert ClassDefSugar.owns(site) is False

    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    with pytest.raises(FactoryPanic) as raised:
        build_node(site, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert raised.value.info.observed == "ClassDef"


@pytest.mark.parametrize(
    "source",
    (
        (
            "from pydantic import BaseModel\n"
            "class BaseModel:\n"
            "    pass\n"
            'class Payload(BaseModel, extra="allow"):\n'
            "    value: int\n"
        ),
        (
            "import pydantic as pd\n"
            "pd = object()\n"
            'class Payload(pd.BaseModel, extra="allow"):\n'
            "    value: int\n"
        ),
        (
            'class Payload(BaseModel, extra="allow"):\n'
            "    value: int\n"
            "from pydantic import BaseModel\n"
        ),
    ),
)
def test_shadowed_or_late_pydantic_base_model_import_stays_loud(
    source: str,
) -> None:
    node = next(
        statement
        for statement in ast.parse(source).body
        if isinstance(statement, ast.ClassDef) and statement.name == "Payload"
    )
    site = SourceFragment.from_node(node, "t.py", source=source)
    assert ClassDefSugar.owns(site) is False

    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    with pytest.raises(FactoryPanic) as raised:
        build_node(site, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert raised.value.info.observed == "ClassDef"


def test_same_named_local_dataclasses_namespace_stays_unowned() -> None:
    source = (
        "class dataclasses:\n"
        "    dataclass = lambda cls: 7\n"
        "@dataclasses.dataclass\n"
        "class Dog:\n"
        "    name: str\n"
    )
    site = SourceFragment.from_node(ast.parse(source).body[1], "t.py", source=source)

    assert ClassDefSugar.owns(site) is False


@pytest.mark.parametrize(
    ("module", "total"),
    (("typing", "False"), ("typing_extensions", "True")),
)
def test_owns_authenticated_typed_dict_total_class(module: str, total: str) -> None:
    source = (
        f"from {module} import TypedDict\n"
        f"class Payload(TypedDict, total={total}):\n"
        "    value: int\n"
    )
    site = SourceFragment.from_node(ast.parse(source).body[1], "t.py", source=source)

    assert ClassDefSugar.owns(site) is True

    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    result = build_node(site, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert result.audit_row.selected == "ClassDefSugar"


@pytest.mark.parametrize(
    "source",
    (
        (
            "class TypedDict:\n"
            "    pass\n"
            "class Payload(TypedDict, total=False):\n"
            "    value: int\n"
        ),
        (
            "from typing_extensions import TypedDict\n"
            "flag = False\n"
            "class Payload(TypedDict, total=flag):\n"
            "    value: int\n"
        ),
        (
            "from typing_extensions import TypedDict\n"
            'class Payload(TypedDict, extra="forbid"):\n'
            "    value: int\n"
        ),
    ),
)
def test_unsupported_typed_dict_total_partition_stays_loud(source: str) -> None:
    node = ast.parse(source).body[-1]
    site = SourceFragment.from_node(node, "t.py", source=source)
    assert ClassDefSugar.owns(site) is False

    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    with pytest.raises(FactoryPanic) as raised:
        build_node(site, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert raised.value.info.observed == "ClassDef"


def test_same_named_local_dataclass_decorator_stays_unowned() -> None:
    source = (
        "def dataclass(cls):\n"
        "    return 7\n"
        "@dataclass\n"
        "class Dog:\n"
        "    name: str\n"
    )
    site = SourceFragment.from_node(ast.parse(source).body[1], "t.py", source=source)

    assert ClassDefSugar.owns(site) is False


def test_unknown_qualified_decorated_class_stays_unowned() -> None:
    source = (
        "import provider as p\n"
        "@p.decorators.replace\n"
        "class Replaced:\n"
        "    pass\n"
    )
    site = SourceFragment.from_node(ast.parse(source).body[1], "t.py", source=source)

    assert ClassDefSugar.owns(site) is False


def test_decorated_class_is_a_loud_factory_gap() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("@dec\nclass C:\n    pass\n").body[0]
    with pytest.raises(FactoryPanic) as raised:
        build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert raised.value.info.observed == "ClassDef"


def test_metaclass_keyword_is_a_loud_factory_gap() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("class C(metaclass=M):\n    pass\n").body[0]
    with pytest.raises(FactoryPanic) as raised:
        build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert raised.value.info.observed == "ClassDef"


def test_function_def_is_not_owned_by_class_def_sugar() -> None:
    assert ClassDefSugar.owns(_site("def f():\n    return 1\n")) is False
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("def f():\n    return 1\n").body[0]
    result = build_node(node, filename="t.py", role=SugarRole.DEFINITION, ctx=ctx)
    assert result.audit_row.selected == "FunctionDefSugar"
