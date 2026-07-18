from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    DictValue,
    ExceptionalExitValue,
    GuardedValue,
    ImportAliasValue,
    ObjectValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_lift_py_tests.sugar.constructor_call_sugar import ConstructorCallSugar
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def test_constructor_call_sugar_has_no_inline_ast_shape_classifiers() -> None:
    source_path = (
        Path(__file__).parents[1]
        / "src"
        / "sugar_lift_py_tests"
        / "sugar"
        / "constructor_call_sugar.py"
    )
    source = source_path.read_text(encoding="utf-8")
    forbidden = (
        "ast.",
        "_is_exact_super_init_node",
        "_is_exact_super_init_fragment",
        "_explicit_imported_base_initializer",
        "_ast_dotted_name",
        "_source_initializer_needs_statement_door",
        "needs_statement_door",
    )
    offenders = tuple(token for token in forbidden if token in source)

    assert not offenders, (
        "constructor call AST side doors remain: "
        f"{offenders}; replacement=SourceFragment.initializer_call_site"
    )


def _outcome(
    source: str,
    expression: str,
    *,
    filename: str = "constructor.py",
    temporal: TemporalContext | None = None,
):
    module = ast.parse(source)
    resolver = {
        statement.name: statement
        for statement in module.body
        if isinstance(statement, (ast.ClassDef, ast.FunctionDef))
    }
    ctx = FactoryBuildContext(
        filename=filename,
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


def test_source_initializer_threads_local_assignment_into_self_fields() -> None:
    outcome = _outcome(
        "class IndexType:\n"
        "    def __init__(self, dtype, layout, pyclass):\n"
        "        self.pyclass = pyclass\n"
        "        name = f'index({dtype}, {layout})'\n"
        "        self.name = name\n"
        "        self.dtype = dtype\n"
        "        self.layout = layout\n",
        "IndexType('int64', 'C', 'Index')",
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    assert _field_values(outcome.value) == {
        "pyclass": StringValue("Index"),
        "name": StringValue("index(int64, C)"),
        "dtype": StringValue("int64"),
        "layout": StringValue("C"),
    }


def test_source_initializer_super_init_recovers_base_self_state() -> None:
    """IndexType-shaped: local name + super().__init__(name) recovers self.name."""
    outcome = _outcome(
        "class Type:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n"
        "\n"
        "class IndexType(Type):\n"
        "    def __init__(self, dtype, layout, pyclass):\n"
        "        self.pyclass = pyclass\n"
        "        name = f'index({dtype}, {layout})'\n"
        "        self.dtype = dtype\n"
        "        self.layout = layout\n"
        "        super().__init__(name)\n",
        "IndexType('int64', 'C', 'Index')",
        filename="constructor_super_index.py",
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    assert outcome.value.class_name == "IndexType"
    assert _field_values(outcome.value) == {
        "pyclass": StringValue("Index"),
        "dtype": StringValue("int64"),
        "layout": StringValue("C"),
        "name": StringValue("index(int64, C)"),
    }


def test_source_initializer_unresolved_super_stays_loud() -> None:
    """super() without a diggable static base must not empty-succeed."""
    with pytest.raises(FactoryPanic) as raised:
        _outcome(
            "class IndexType(MissingBase):\n"
            "    def __init__(self, dtype):\n"
            "        name = f'index({dtype})'\n"
            "        super().__init__(name)\n",
            "IndexType('int64')",
            filename="constructor_unresolved_super.py",
        )

    assert raised.value.info.owner == "ConstructorCallSugar"
    assert raised.value.info.requested == "constructed source initializer"


def test_source_initializer_super_setattr_constructs_ground_field() -> None:
    outcome = _outcome(
        "class CheckedCall:\n"
        "    def __init__(self, f):\n"
        '        super().__setattr__("f", f)\n',
        "CheckedCall('callable')",
        filename="constructor_super_setattr.py",
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    assert _field_values(outcome.value) == {"f": StringValue("callable")}


def test_source_initializer_super_setattr_non_ground_name_stays_loud() -> None:
    with pytest.raises(FactoryPanic) as raised:
        _outcome(
            "class CheckedCall:\n"
            "    def __init__(self, name, value):\n"
            "        super().__setattr__(name, value)\n",
            "CheckedCall('f', 'callable')",
            filename="constructor_super_setattr_non_ground.py",
        )

    assert raised.value.info.owner == "ConstructorCallSugar"
    assert raised.value.info.requested == "constructed source initializer"


def test_source_initializer_assert_constructs_exceptional_exit_face() -> None:
    outcome = _outcome(
        "class MockRequest:\n"
        "    def __init__(self, request):\n"
        "        assert request == 1\n"
        "        self.request = request\n"
        "        self.headers: dict[str, str] = {}\n",
        "MockRequest(request)",
        filename="constructor_assert_symbolic.py",
        temporal=TemporalContext.empty().bind_value(
            "request", SymbolicValue(make_var("request"))
        ),
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is GuardedValue
    assert type(outcome.value.when_true) is ObjectValue
    assert _field_values(outcome.value.when_true) == {
        "request": SymbolicValue(make_var("request")),
        "headers": DictValue(()),
    }
    assert type(outcome.value.when_false) is ExceptionalExitValue
    assert outcome.value.when_false.effect.exception_name == "AssertionError"
    assert outcome.value.when_false.effect.blame == "constructor_assert_symbolic.py:3:8"


def test_source_initializer_with_arbitrary_expression_stays_loud() -> None:
    with pytest.raises(FactoryPanic) as raised:
        _outcome(
            "class IndexType:\n"
            "    def __init__(self, dtype):\n"
            "        name = f'index({dtype})'\n"
            "        self.name = name\n"
            "        unknown(self)\n",
            "IndexType('int64')",
        )

    assert raised.value.info.owner == "ConstructorCallSugar"
    assert raised.value.info.requested == "constructed source initializer"


def test_zero_arg_self_method_constructor_recovers_method_self_state() -> None:
    """Exact zero-arg self.method() digs local body and recovers self.* rebinds."""
    outcome = _outcome(
        "class Ready:\n"
        "    def __init__(self, x):\n"
        "        self.x = x\n"
        "        self._ready()\n"
        "\n"
        "    def _ready(self):\n"
        "        self.flag = 1\n",
        "Ready(7)",
        filename="constructor_zero_arg_self_method.py",
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    assert _field_values(outcome.value) == {
        "x": TermValue(7),
        "flag": TermValue(1),
    }


def test_zero_arg_self_method_pass_only_keeps_prior_self_state() -> None:
    outcome = _outcome(
        "class Ready:\n"
        "    def __init__(self, x):\n"
        "        self.x = x\n"
        "        self._noop()\n"
        "\n"
        "    def _noop(self):\n"
        "        pass\n",
        "Ready(3)",
        filename="constructor_zero_arg_self_pass.py",
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    assert _field_values(outcome.value) == {"x": TermValue(3)}


def test_zero_arg_self_method_raise_constructs_exceptional_exit() -> None:
    bad = _outcome(
        "class Checked:\n"
        "    def __init__(self, ok):\n"
        "        self.ok = ok\n"
        "        self._validate()\n"
        "\n"
        "    def _validate(self):\n"
        "        if not self.ok:\n"
        "            raise ValueError('bad')\n",
        "Checked(False)",
        filename="constructor_zero_arg_self_raise.py",
    )
    ok = _outcome(
        "class Checked:\n"
        "    def __init__(self, ok):\n"
        "        self.ok = ok\n"
        "        self._validate()\n"
        "\n"
        "    def _validate(self):\n"
        "        if not self.ok:\n"
        "            raise ValueError('bad')\n",
        "Checked(True)",
        filename="constructor_zero_arg_self_raise_ok.py",
    )

    assert type(bad) is Complete
    assert type(bad.value) is ExceptionalExitValue
    assert bad.value.effect.exception_name == "ValueError"
    assert type(ok) is Complete
    assert type(ok.value) is ObjectValue
    ok_fields = _field_values(ok.value)
    assert set(ok_fields) == {"ok"}
    assert type(ok_fields["ok"]).__name__ == "TrueBoolLiteralSugar"


def test_zero_arg_self_method_with_return_stays_loud() -> None:
    """Return-bearing helpers are not expression-statement constructible yet."""
    with pytest.raises(FactoryPanic) as raised:
        _outcome(
            "class Ready:\n"
            "    def __init__(self, x):\n"
            "        self.x = x\n"
            "        self._ready()\n"
            "\n"
            "    def _ready(self):\n"
            "        self.flag = 1\n"
            "        return self.flag\n",
            "Ready(7)",
            filename="constructor_zero_arg_self_return.py",
        )

    assert raised.value.info.owner == "ConstructorCallSugar"
    assert raised.value.info.requested == "constructed source initializer"


def test_zero_arg_self_method_missing_stays_loud() -> None:
    with pytest.raises(FactoryPanic) as raised:
        _outcome(
            "class Ready:\n"
            "    def __init__(self, x):\n"
            "        self.x = x\n"
            "        self._missing()\n",
            "Ready(7)",
            filename="constructor_zero_arg_self_missing.py",
        )

    assert raised.value.info.owner == "ConstructorCallSugar"
    assert raised.value.info.requested == "constructed source initializer"


def test_self_method_with_args_stays_loud() -> None:
    with pytest.raises(FactoryPanic) as raised:
        _outcome(
            "class Ready:\n"
            "    def __init__(self, x):\n"
            "        self.x = x\n"
            "        self._set(1)\n"
            "\n"
            "    def _set(self, flag):\n"
            "        self.flag = flag\n",
            "Ready(7)",
            filename="constructor_self_method_args.py",
        )

    assert raised.value.info.owner == "ConstructorCallSugar"
    assert raised.value.info.requested == "constructed source initializer"


def test_pass_only_constructor_builds_empty_object() -> None:
    """MyTz-shaped: ``pass`` is exact no-op construction, not RuntimeEffect."""
    outcome = _outcome(
        "class MyTz:\n" "    def __init__(self) -> None:\n" "        pass\n",
        "MyTz()",
        filename="constructor_pass_only.py",
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    assert outcome.value.class_name == "MyTz"
    assert _field_values(outcome.value) == {}


def test_pass_before_field_constructor_keeps_self_state() -> None:
    outcome = _outcome(
        "class Box:\n"
        "    def __init__(self, x):\n"
        "        pass\n"
        "        self.x = x\n",
        "Box(3)",
        filename="constructor_pass_field.py",
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    assert _field_values(outcome.value) == {"x": TermValue(3)}


def test_if_else_self_assign_constructor_selects_branch() -> None:
    """CSS-shaped: decidable if/else self binds through the statement door."""
    true_outcome = _outcome(
        "class Gate:\n"
        "    def __init__(self, flag, value):\n"
        "        if flag:\n"
        "            self.value = value\n"
        "        else:\n"
        "            self.value = 0\n",
        "Gate(True, 7)",
        filename="constructor_if_true.py",
    )
    false_outcome = _outcome(
        "class Gate:\n"
        "    def __init__(self, flag, value):\n"
        "        if flag:\n"
        "            self.value = value\n"
        "        else:\n"
        "            self.value = 0\n",
        "Gate(False, 7)",
        filename="constructor_if_false.py",
    )

    assert type(true_outcome) is Complete
    assert type(true_outcome.value) is ObjectValue
    assert _field_values(true_outcome.value) == {"value": TermValue(7)}
    assert type(false_outcome) is Complete
    assert type(false_outcome.value) is ObjectValue
    assert _field_values(false_outcome.value) == {"value": TermValue(0)}


def test_if_raise_guard_constructor_builds_or_exits() -> None:
    ok = _outcome(
        "class Periodish:\n"
        "    def __init__(self, values, dtype=None):\n"
        "        if dtype is None:\n"
        "            raise ValueError('dtype is not specified')\n"
        "        self.values = values\n"
        "        self.dtype = dtype\n",
        "Periodish([1], 'D')",
        filename="constructor_if_raise_ok.py",
    )
    bad = _outcome(
        "class Periodish:\n"
        "    def __init__(self, values, dtype=None):\n"
        "        if dtype is None:\n"
        "            raise ValueError('dtype is not specified')\n"
        "        self.values = values\n"
        "        self.dtype = dtype\n",
        "Periodish([1])",
        filename="constructor_if_raise_bad.py",
    )

    assert type(ok) is Complete
    assert type(ok.value) is ObjectValue
    assert "values" in _field_values(ok.value)
    assert _field_values(ok.value)["dtype"] == StringValue("D")
    assert type(bad) is Complete
    assert type(bad.value) is ExceptionalExitValue
    assert bad.value.effect.exception_name == "ValueError"


def test_import_then_field_constructor_binds_module() -> None:
    """PyArrowImpl-shaped import then self field through the statement door."""
    outcome = _outcome(
        "class Bound:\n"
        "    def __init__(self):\n"
        "        import math\n"
        "        self.api = math\n"
        "        self.tag = 7\n",
        "Bound()",
        filename="constructor_import_field.py",
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    fields = _field_values(outcome.value)
    assert fields["tag"] == TermValue(7)
    assert type(fields["api"]) is ImportAliasValue


def test_importfrom_then_field_constructor_binds_name() -> None:
    outcome = _outcome(
        "class Bound:\n"
        "    def __init__(self, con):\n"
        "        from collections import Counter\n"
        "        self.con = con\n"
        "        self.meta = Counter\n",
        "Bound(1)",
        filename="constructor_importfrom_field.py",
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    fields = _field_values(outcome.value)
    assert fields["con"] == TermValue(1)
    assert type(fields["meta"]) is ImportAliasValue


def test_source_initializer_constructs_authenticated_explicit_base_call() -> None:
    temporal = TemporalContext.empty().bind_value(
        "ExternalBase",
        ImportAliasValue(
            "ExternalBase",
            "ExternalBase",
            import_target="vendor.ExternalBase",
        ),
    )

    outcome = _outcome(
        "\n\n\n\n\nclass Box(ExternalBase):\n"
        "    def __init__(self, value):\n"
        "        self.value = value\n"
        "        ExternalBase.__init__(self, value)\n",
        "Box('evidence')",
        temporal=temporal,
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    assert _field_values(outcome.value) == {"value": StringValue("evidence")}


def test_source_initializer_non_base_explicit_init_call_stays_loud() -> None:
    temporal = TemporalContext.empty().bind_value(
        "Other",
        ImportAliasValue("Other", "Other", import_target="vendor.Other"),
    )

    with pytest.raises(FactoryPanic) as raised:
        _outcome(
            "\n\n\n\n\n\nclass Box(ExternalBase):\n"
            "    def __init__(self, value):\n"
            "        self.value = value\n"
            "        Other.__init__(self, value)\n",
            "Box('evidence')",
            temporal=temporal,
        )

    assert raised.value.info.owner == "ConstructorCallSugar"
    assert raised.value.info.requested == "constructed source initializer"


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


def test_requests_cookiejar_source_bases_have_exact_c3_linearization() -> None:
    from sugar_lift_py_tests.sugar.constructor_call_sugar import (
        _static_constructor_mro,
    )
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment
    from sugar_lift_py_tests.sugar.install_source_dig import (
        resolve_install_source_class_bases,
    )

    source = (
        "class RequestsCookieJar(CookieJar, MutableMapping[str, str]):\n" "    pass\n"
    )
    class_site = SourceFragment.from_node(ast.parse(source).body[0], "cookies.py")
    temporal = (
        TemporalContext.empty()
        .bind_value(
            "CookieJar",
            ImportAliasValue(
                "CookieJar",
                "CookieJar",
                import_target="http.cookiejar.CookieJar",
            ),
        )
        .bind_value(
            "MutableMapping",
            ImportAliasValue(
                "MutableMapping",
                "MutableMapping",
                import_target="collections.abc.MutableMapping",
            ),
        )
    )
    ctx = FactoryBuildContext(
        filename="cookies.py",
        catalog=default_catalog(),
        name_resolver={"RequestsCookieJar": class_site.node},
        temporal=temporal,
    )

    mro = _static_constructor_mro("RequestsCookieJar", class_site, ctx)

    assert mro is not None, {
        "CookieJar": resolve_install_source_class_bases("http.cookiejar.CookieJar"),
        "MutableMapping": resolve_install_source_class_bases(
            "collections.abc.MutableMapping"
        ),
    }
    assert tuple(entry[1] for entry in mro) == (
        "RequestsCookieJar",
        "http.cookiejar.CookieJar",
        "collections.abc.MutableMapping",
        "collections.abc.Mapping",
        "collections.abc.Collection",
        "collections.abc.Sized",
        "collections.abc.Iterable",
        "collections.abc.Container",
        "builtins.object",
    )


def test_requests_cookiejar_enters_selected_source_init_before_next_loud_front() -> (
    None
):
    temporal = (
        TemporalContext.empty()
        .bind_value(
            "CookieJar",
            ImportAliasValue(
                "CookieJar",
                "CookieJar",
                import_target="http.cookiejar.CookieJar",
            ),
        )
        .bind_value(
            "MutableMapping",
            ImportAliasValue(
                "MutableMapping",
                "MutableMapping",
                import_target="collections.abc.MutableMapping",
            ),
        )
    )

    outcome = _outcome(
        "class RequestsCookieJar("
        "CookieJar, MutableMapping[str, str]"
        "):\n"
        "    pass\n",
        "RequestsCookieJar()",
        temporal=temporal,
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    assert outcome.value.class_name == "RequestsCookieJar"
    assert tuple(_field_values(outcome.value)) == (
        "_policy",
        "_cookies_lock",
        "_cookies",
    )


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
        "class Child(Base):\n" "    pass\n",
        "Child(7)",
        temporal=temporal,
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    assert outcome.value.class_name == "Child"
    assert _field_values(outcome.value) == {"value": TermValue(7)}


def test_dotted_imported_reexport_base_constructs_exact_inherited_object(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "base_impl.py").write_text(
        "class Root:\n" "    pass\n" "\n" "class Base(Root):\n" "    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "base_facade.py").write_text(
        "from base_impl import Base\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    temporal = TemporalContext.empty().bind_value(
        "facade",
        ImportAliasValue(
            "base_facade",
            "facade",
            import_target="base_facade",
        ),
    )

    outcome = _outcome(
        "class Child(facade.Base):\n" "    pass\n",
        "Child()",
        temporal=temporal,
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    assert outcome.value.class_name == "Child"
    assert _field_values(outcome.value) == {}


def test_unresolved_dotted_imported_base_stays_loud() -> None:
    temporal = TemporalContext.empty().bind_value(
        "facade",
        ImportAliasValue(
            "missing_facade",
            "facade",
            import_target="missing_facade",
        ),
    )

    with pytest.raises(FactoryPanic) as raised:
        _outcome(
            "class Child(facade.Base):\n" "    pass\n",
            "Child()",
            temporal=temporal,
        )

    assert raised.value.info.owner == "ConstructorCallSugar"
    assert raised.value.info.requested == "statically resolved inherited constructor"


def test_unresolved_inherited_constructor_panics_instead_of_faking_runtime() -> None:
    with pytest.raises(FactoryPanic) as raised:
        _outcome(
            "class Child(ImportedBase):\n" "    pass\n",
            "Child(1)",
        )

    assert raised.value.info.owner == "ConstructorCallSugar"
    assert raised.value.info.requested == "statically resolved inherited constructor"
    json.dumps(raised.value.info.to_json())


def test_static_multiple_inheritance_mro_uses_left_base_init() -> None:
    """RequestsCookieJar shape: class C(A, B) with A defining __init__."""
    outcome = _outcome(
        "class CookieJar:\n"
        "    def __init__(self, value):\n"
        "        self.value = value\n"
        "\n"
        "class MutableMapping:\n"
        "    pass\n"
        "\n"
        "class RequestsCookieJar(CookieJar, MutableMapping):\n"
        "    pass\n",
        "RequestsCookieJar(7)",
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    assert outcome.value.class_name == "RequestsCookieJar"
    assert _field_values(outcome.value) == {"value": TermValue(7)}


def test_static_multiple_inheritance_mro_peels_generic_alias_bases() -> None:
    """Exact requests spelling: MutableMapping[str, str | None] still MRO-heads."""
    outcome = _outcome(
        "class CookieJar:\n"
        "    def __init__(self, value):\n"
        "        self.value = value\n"
        "\n"
        "class MutableMapping:\n"
        "    pass\n"
        "\n"
        "class RequestsCookieJar(CookieJar, MutableMapping[str, str | None]):\n"
        "    pass\n",
        "RequestsCookieJar(9)",
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    assert outcome.value.class_name == "RequestsCookieJar"
    assert _field_values(outcome.value) == {"value": TermValue(9)}


def test_static_diamond_mro_finds_shared_base_init() -> None:
    outcome = _outcome(
        "class A:\n"
        "    def __init__(self, value):\n"
        "        self.value = value\n"
        "\n"
        "class B(A):\n"
        "    pass\n"
        "\n"
        "class C(A):\n"
        "    pass\n"
        "\n"
        "class D(B, C):\n"
        "    pass\n",
        "D(11)",
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    assert outcome.value.class_name == "D"
    assert _field_values(outcome.value) == {"value": TermValue(11)}


def test_source_backed_multiple_inheritance_mro_uses_imported_left_init(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "cookiejar_mod.py").write_text(
        "class CookieJar:\n"
        "    def __init__(self, value):\n"
        "        self.value = value\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    temporal = TemporalContext.empty().bind_value(
        "CookieJar",
        ImportAliasValue(
            "CookieJar",
            "CookieJar",
            import_target="cookiejar_mod.CookieJar",
        ),
    )

    outcome = _outcome(
        "class MutableMapping:\n"
        "    pass\n"
        "\n"
        "class RequestsCookieJar(CookieJar, MutableMapping):\n"
        "    pass\n",
        "RequestsCookieJar(13)",
        temporal=temporal,
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    assert outcome.value.class_name == "RequestsCookieJar"
    assert _field_values(outcome.value) == {"value": TermValue(13)}


def test_unresolved_multiple_inheritance_mro_stays_loud_construction_panic() -> None:
    with pytest.raises(FactoryPanic) as raised:
        _outcome(
            "class Child(Left, Right):\n" "    pass\n",
            "Child(1)",
        )

    assert raised.value.info.owner == "ConstructorCallSugar"
    assert raised.value.info.requested == "statically resolved inherited constructor"
    assert "multiple-inheritance MRO" in raised.value.info.fix
    json.dumps(raised.value.info.to_json())


def test_native_imported_multiple_inheritance_uses_runtime_call_operand() -> None:
    from sugar_lift_py_tests.effect import ConstructorRuntimeEffect
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import make_var

    temporal = (
        TemporalContext.empty()
        .bind_value(
            "native",
            ImportAliasValue(
                "pandas._libs.index",
                "native",
                import_target="pandas._libs.index",
            ),
        )
        .bind_value("value", SymbolicValue(make_var("value")))
    )

    outcome = _outcome(
        "class Child(native.BaseMultiIndexCodesEngine, native.ObjectEngine):\n"
        "    pass\n",
        "Child(value)",
        temporal=temporal,
    )

    assert type(outcome) is Incomplete
    assert type(outcome.effect) is ConstructorRuntimeEffect
    assert outcome.effect.runtime_operand.term.args[1] == make_var("value")


def test_native_imported_multiple_inheritance_ground_wrong_twin_stays_loud() -> None:
    temporal = TemporalContext.empty().bind_value(
        "native",
        ImportAliasValue(
            "pandas._libs.index",
            "native",
            import_target="pandas._libs.index",
        ),
    )

    with pytest.raises(FactoryPanic, match="owner=RuntimeEffect"):
        _outcome(
            "class Child(native.BaseMultiIndexCodesEngine, native.ObjectEngine):\n"
            "    pass\n",
            "Child(1)",
            temporal=temporal,
        )


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


def test_ground_true_initializer_assert_constructs_empty_object() -> None:
    outcome = _outcome(
        "class Box:\n" "    def __init__(self, value):\n" "        assert value\n",
        "Box(1)",
        filename="constructor_assert_true.py",
    )

    assert type(outcome) is Complete
    assert outcome.value == ObjectValue(
        class_name="Box",
        fields=(),
        identity="constructor_assert_true.py:1:0",
    )


def test_ground_false_initializer_assert_constructs_exceptional_exit() -> None:
    outcome = _outcome(
        "class Box:\n" "    def __init__(self, value):\n" "        assert value\n",
        "Box(0)",
        filename="constructor_assert_false.py",
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ExceptionalExitValue
    assert outcome.value.effect.exception_name == "AssertionError"


def test_source_bytesio_constructor_truthful_sat_wrong_twin_unsat(tmp_path) -> None:
    pair = next(
        witness
        for witness in ConstructorCallSugar.witnesses()
        if isinstance(witness, SugarWitnessPair)
        and witness.name == "source_bytesio_constructor"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", pair.lying.source)

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_asserted_source_constructor_truthful_sat_wrong_twin_unsat(tmp_path) -> None:
    pair = next(
        witness
        for witness in ConstructorCallSugar.witnesses()
        if isinstance(witness, SugarWitnessPair)
        and witness.name == "source_body_constructor_asserted"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", pair.lying.source)

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_super_source_constructor_truthful_sat_wrong_twin_unsat(tmp_path) -> None:
    pair = next(
        witness
        for witness in ConstructorCallSugar.witnesses()
        if isinstance(witness, SugarWitnessPair)
        and witness.name == "source_body_constructor_super_init"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", pair.lying.source)

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_explicit_base_initializer_truthful_sat_wrong_twin_unsat(tmp_path) -> None:
    pair = next(
        witness
        for witness in ConstructorCallSugar.witnesses()
        if isinstance(witness, SugarWitnessPair)
        and witness.name == "source_body_constructor_explicit_base_initializer"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", pair.lying.source)

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_zero_arg_self_method_constructor_truthful_sat_wrong_twin_unsat(
    tmp_path,
) -> None:
    pair = next(
        witness
        for witness in ConstructorCallSugar.witnesses()
        if isinstance(witness, SugarWitnessPair)
        and witness.name == "source_body_constructor_zero_arg_self_method"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", pair.lying.source)

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_super_setattr_constructor_truthful_sat_wrong_twin_unsat(tmp_path) -> None:
    pair = next(
        witness
        for witness in ConstructorCallSugar.witnesses()
        if isinstance(witness, SugarWitnessPair)
        and witness.name == "source_body_constructor_super_setattr"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", pair.lying.source)

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_inherited_bytesio_constructor_carries_seed_and_methods() -> None:
    temporal = TemporalContext.empty().bind_value(
        "BytesIO",
        ImportAliasValue(
            "BytesIO",
            "BytesIO",
            import_target="io.BytesIO",
        ),
    )
    outcome = _outcome(
        "class RandomReader(BytesIO):\n"
        "    kind = 'random-reader'\n"
        "    def marker(self):\n"
        "        return 7\n",
        "RandomReader('seeded')",
        temporal=temporal,
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    assert _field_values(outcome.value) == {
        "__bytesio_buffer__": StringValue("seeded"),
    }
    assert outcome.value.has_method("marker")
    assert {field.name: field.value for field in outcome.value.class_fields} == {
        "kind": StringValue("random-reader"),
    }


@pytest.mark.parametrize("expression", ("RandomReader()", "RandomReader(1, 2)"))
def test_inherited_bytesio_constructor_wrong_arity_stays_loud(
    expression: str,
) -> None:
    temporal = TemporalContext.empty().bind_value(
        "BytesIO",
        ImportAliasValue(
            "BytesIO",
            "BytesIO",
            import_target="io.BytesIO",
        ),
    )
    with pytest.raises(FactoryPanic) as raised:
        _outcome(
            "class RandomReader(BytesIO):\n" "    pass\n",
            expression,
            temporal=temporal,
        )

    assert raised.value.info.owner == "ConstructorCallSugar"


def test_inherited_bytesio_constructor_shadowed_base_stays_loud() -> None:
    with pytest.raises(FactoryPanic) as raised:
        _outcome(
            "class BytesIO:\n"
            "    pass\n"
            "class RandomReader(BytesIO):\n"
            "    pass\n",
            "RandomReader('seeded')",
        )

    assert raised.value.info.owner == "RuntimeEffect"
    assert raised.value.info.requested == "genuine runtime-dependent operand"


@pytest.mark.parametrize(
    "class_source",
    (
        "class RandomReader(BytesIO):\n"
        "    def __new__(cls, seed):\n"
        "        return object()\n",
        "class RandomReader(BytesIO):\n" "    __new__ = replacement\n",
        "class RandomReader(BytesIO):\n"
        "    async def __new__(cls, seed):\n"
        "        return object()\n",
        "@decorate\n" "class RandomReader(BytesIO):\n" "    pass\n",
        "class RandomReader(BytesIO, metaclass=Meta):\n" "    pass\n",
    ),
)
def test_inherited_bytesio_constructor_overrides_stay_loud(
    class_source: str,
) -> None:
    temporal = TemporalContext.empty().bind_value(
        "BytesIO",
        ImportAliasValue(
            "BytesIO",
            "BytesIO",
            import_target="io.BytesIO",
        ),
    )
    with pytest.raises(FactoryPanic):
        _outcome(
            class_source,
            "RandomReader('seeded')",
            temporal=temporal,
        )


def test_inherited_bytesio_constructor_witness_refutes_wrong_twin(tmp_path) -> None:
    pair = next(
        witness
        for witness in ConstructorCallSugar.witnesses()
        if isinstance(witness, SugarWitnessPair)
        and witness.name == "inherited_bytesio_constructor"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", pair.lying.source)

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_source_bytesio_constructor_carries_seeded_buffer() -> None:
    temporal = (
        TemporalContext.empty()
        .bind_value(
            "BytesIO",
            ImportAliasValue(
                "BytesIO",
                "BytesIO",
                import_target="io.BytesIO",
            ),
        )
        .bind_value(
            "asbytes",
            ImportAliasValue(
                "asbytes",
                "asbytes",
                import_target="numpy._utils.asbytes",
            ),
        )
    )
    outcome = _outcome(
        "class TextIO(BytesIO):\n"
        "    def __init__(self, value=''):\n"
        "        BytesIO.__init__(self, asbytes(value))\n",
        "TextIO('seeded')",
        temporal=temporal,
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ObjectValue
    fields = _field_values(outcome.value)
    assert tuple(fields) == ("__bytesio_buffer__",)
    buffer = fields["__bytesio_buffer__"]
    assert type(buffer) is CallSiteValue
    assert buffer.target_name == "numpy._utils.asbytes"
    assert buffer.arg_values == (StringValue("seeded"),)


def test_unrecognized_ground_initializer_stays_loud_constructor_gap() -> None:
    with pytest.raises(FactoryPanic) as raised:
        _outcome(
            "class Box:\n" "    def __init__(self):\n" "        unknown(self)\n",
            "Box()",
        )

    assert raised.value.info.owner == "ConstructorCallSugar"
    assert raised.value.info.requested == "constructed source initializer"


def test_source_bytesio_initializer_requires_bytesio_ancestry() -> None:
    with pytest.raises(FactoryPanic) as raised:
        _outcome(
            "from io import BytesIO\n"
            "from numpy._utils import asbytes\n"
            "class TextIO:\n"
            "    def __init__(self, value=''):\n"
            "        BytesIO.__init__(self, asbytes(value))\n",
            "TextIO()",
        )

    assert raised.value.info.owner == "ConstructorCallSugar"
    assert raised.value.info.requested == "constructed source initializer"


@pytest.mark.parametrize(
    "shadow",
    (
        "BytesIO = object\n",
        "asbytes = lambda value: value\n",
    ),
)
def test_source_bytesio_initializer_rejects_shadowed_imports(shadow: str) -> None:
    with pytest.raises(FactoryPanic) as raised:
        _outcome(
            "from io import BytesIO\n"
            "from numpy._utils import asbytes\n"
            f"{shadow}"
            "class TextIO(BytesIO):\n"
            "    def __init__(self, value=''):\n"
            "        BytesIO.__init__(self, asbytes(value))\n",
            "TextIO()",
        )

    assert raised.value.info.owner == "ConstructorCallSugar"


@pytest.mark.parametrize(
    "asbytes_call",
    (
        "asbytes()",
        "asbytes(value, value)",
        "asbytes(value=value)",
    ),
)
def test_source_bytesio_initializer_rejects_invalid_asbytes_calls(
    asbytes_call: str,
) -> None:
    temporal = (
        TemporalContext.empty()
        .bind_value(
            "BytesIO",
            ImportAliasValue(
                "BytesIO",
                "BytesIO",
                import_target="io.BytesIO",
            ),
        )
        .bind_value(
            "asbytes",
            ImportAliasValue(
                "asbytes",
                "asbytes",
                import_target="numpy._utils.asbytes",
            ),
        )
    )
    with pytest.raises(FactoryPanic) as raised:
        _outcome(
            "class TextIO(BytesIO):\n"
            "    def __init__(self, value=''):\n"
            f"        BytesIO.__init__(self, {asbytes_call})\n",
            "TextIO()",
            temporal=temporal,
        )

    assert raised.value.info.owner == "ConstructorCallSugar"


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


def test_source_backed_imported_init_body_refutes_wrong_twin(tmp_path) -> None:
    prefix = (
        "from base_mod import Base\n"
        "from marker_mod import Marker\n"
        "class Child(Base, Marker):\n"
        "    pass\n"
        "\n"
        "def A():\n"
        "    return Child().value\n"
    )
    truthful_dir = tmp_path / "source-init-truthful"
    lying_dir = tmp_path / "source-init-lying"
    for project in (truthful_dir, lying_dir):
        project.mkdir()
        (project / "base_mod.py").write_text(
            "class Base:\n"
            "    def __init__(self, value=None):\n"
            "        if value is None:\n"
            "            value = 7\n"
            "        self.value = value\n",
            encoding="utf-8",
        )
        (project / "marker_mod.py").write_text(
            "class Marker:\n" "    pass\n",
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


def test_multiple_inheritance_constructor_refutes_wrong_linearization_twin(
    tmp_path,
) -> None:
    prefix = (
        "class Left:\n"
        "    def __init__(self):\n"
        "        self.selected = 1\n"
        "\n"
        "class Right:\n"
        "    def __init__(self):\n"
        "        self.selected = 2\n"
        "\n"
        "class Child(Left, Right):\n"
        "    pass\n"
        "\n"
        "def A():\n"
        "    return Child().selected\n"
    )
    truthful = run_source_through_real_solver(
        tmp_path / "multiple-inheritance-truthful",
        prefix + "\ndef test_a():\n    assert A() == 1\n",
    )
    wrong_linearization = run_source_through_real_solver(
        tmp_path / "multiple-inheritance-wrong-order",
        prefix + "\ndef test_a():\n    assert A() == 2\n",
    )

    assert truthful.verdict == "sat"
    assert wrong_linearization.verdict == "unsat"
    assert "ConstructorCallSugar" in truthful.selected_sugars
    assert "ConstructorCallSugar" in wrong_linearization.selected_sugars


def test_recursive_constructor_method_is_a_named_factory_panic() -> None:
    source = (
        "class Recursive:\n"
        "    def again(self):\n"
        "        return Recursive()\n\n"
        "def test_recursive():\n"
        "    assert Recursive() == Recursive()\n"
    )

    with pytest.raises(FactoryPanic) as raised:
        lift_file_payload(source, "recursive_constructor.py")

    assert raised.value.info.owner == "ConstructorCallSugar"
    assert raised.value.info.observed == "recursive-constructor-method"
