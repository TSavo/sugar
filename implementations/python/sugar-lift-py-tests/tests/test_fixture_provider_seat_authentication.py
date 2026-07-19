"""Fixture decorator authentication: import provenance + kit protocol (#5603).

Same shape as parametrize (#5617):
- Production protocol tables empty by construction (no logo Compare).
- Coordinates arrive only via ``load_fixture_protocol`` (and companion kit
  loaders for call shapes / instance class-decorators used by the fixture
  yield chain).
- Provider bodies anchor to exact source seats (module + line + col) — #5581.
- Lying twins refuse: lookalike, shadow, mismatch, dual-class seat.

Missing kit contract ⇒ loud (owns False). That is correct.
"""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.recognition.class_decorator import (
    _function_at_provider_seat,
    _is_authenticated_fixture,
    _module_imports,
)
from sugar_lift_py_tests.recognition.native_shape import (
    NativeShape,
    clear_call_shape_protocol,
    clear_fixture_protocol,
    clear_instance_class_decorator_protocol,
    load_call_shape_protocol,
    load_fixture_protocol,
    load_instance_class_decorator_protocol,
    recognize_native_fixture_decorator,
)
from sugar_lift_py_tests.sugar.class_def_sugar import ClassDefSugar


@pytest.fixture(autouse=True)
def _isolate_fixture_protocols():
    clear_fixture_protocol()
    clear_call_shape_protocol()
    clear_instance_class_decorator_protocol()
    yield
    clear_fixture_protocol()
    clear_call_shape_protocol()
    clear_instance_class_decorator_protocol()


def _user_class_site(source: str) -> SourceFragment:
    class_node = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ClassDef) and node.name == "User"
    )
    return SourceFragment.from_node(class_node, "t.py", source=source)


def _provider_fragment(provider_source: str, method_name: str, module: str):
    tree = ast.parse(provider_source)
    provider = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )
    setattr(provider, "_sugar_defining_module", module)
    return SourceFragment.from_node(
        provider, f"{module.replace('.', '/')}.py", source=provider_source
    )


def _load_registry_fixture_kit() -> None:
    """Kit contract for the registry→mapped fixture chain (not production logos)."""
    load_fixture_protocol(
        {
            "pytest.fixture": NativeShape.FIXTURE_DECORATOR,
            "sqlalchemy.testing.config.fixture": NativeShape.FIXTURE_DECORATOR,
        }
    )
    load_call_shape_protocol(
        {"sqlalchemy.orm.registry": NativeShape.KIT_LOADED_CONSTRUCTOR}
    )
    load_instance_class_decorator_protocol(
        {
            (NativeShape.KIT_LOADED_CONSTRUCTOR, "mapped"): (
                NativeShape.CLASS_IDENTITY_DECORATOR
            ),
        }
    )


def _install_provider(
    monkeypatch,
    provider_source: str,
    *,
    module: str = "example.fixtures",
    method: str = "registry",
    qualified_base: str = "example.FixtureBase",
):
    fragment = _provider_fragment(provider_source, method, module)
    monkeypatch.setattr(
        "sugar_lift_py_tests.sugar.install_source_dig."
        "resolve_install_source_class_method",
        lambda qualified, name: (
            fragment if (qualified, name) == (qualified_base, method) else None
        ),
    )
    monkeypatch.setattr(
        "sugar_lift_python_source.source_oracle.installed_module_source",
        lambda mod: (
            (provider_source, f"{module.replace('.', '/')}.py", "cid")
            if mod == module
            else None
        ),
    )
    return fragment


_CONSUMER = (
    "from example import FixtureBase\n"
    "class TestThing(FixtureBase):\n"
    "    def test_it(self, registry):\n"
    "        @registry.mapped\n"
    "        class User:\n"
    "            pass\n"
)

_TRUTHFUL_PROVIDER = (
    "import pytest\n"
    "from sqlalchemy.orm import registry\n"
    "class FixtureBase:\n"
    "    @pytest.fixture()\n"
    "    def registry(self, metadata):\n"
    "        value = registry(metadata=metadata)\n"
    "        yield value\n"
)


def test_fixture_protocol_table_is_empty_by_construction() -> None:
    """No hard-coded fixture logo coordinates in production recognition."""
    assert recognize_native_fixture_decorator("pytest.fixture") is None
    assert recognize_native_fixture_decorator("sqlalchemy.testing.config.fixture") is None
    assert recognize_native_fixture_decorator("any.vendor.fixture") is None


def test_import_bound_fixture_authenticates_only_when_protocol_loaded() -> None:
    """Truthful twin (unit): import-resolved identity + loaded protocol."""
    provider_source = _TRUTHFUL_PROVIDER
    tree = ast.parse(provider_source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "registry"
    )
    imports = _module_imports(tree)
    assert _is_authenticated_fixture(function, imports, tree=tree) is False
    load_fixture_protocol({"pytest.fixture": NativeShape.FIXTURE_DECORATOR})
    assert _is_authenticated_fixture(function, imports, tree=tree) is True


def test_pytest_fixture_provider_stays_loud_without_kit_contract(
    monkeypatch,
) -> None:
    """Honest loud: import-bound pytest.fixture alone does not construct."""
    _install_provider(monkeypatch, _TRUTHFUL_PROVIDER)
    assert ClassDefSugar.owns(_user_class_site(_CONSUMER)) is False


def test_pytest_fixture_protocol_authenticates_with_kit_contract(
    monkeypatch,
) -> None:
    """Truthful twin (end-to-end): kit loads fixture + yield chain coordinates."""
    _load_registry_fixture_kit()
    _install_provider(monkeypatch, _TRUTHFUL_PROVIDER)
    assert ClassDefSugar.owns(_user_class_site(_CONSUMER)) is True


def test_identical_fixture_names_anchor_to_exact_seat() -> None:
    """Seat match is by name+line+col — never bare name across the module."""
    provider_source = (
        "import pytest\n"
        "class WrongBase:\n"
        "    @pytest.fixture()\n"
        "    def registry(self, metadata):\n"
        "        yield object()\n"
        "\n"
        "class FixtureBase:\n"
        "    @pytest.fixture()\n"
        "    def registry(self, metadata):\n"
        "        yield 0\n"
    )
    tree = ast.parse(provider_source)
    fixture_base = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "FixtureBase"
    )
    correct = next(
        node
        for node in fixture_base.body
        if isinstance(node, ast.FunctionDef) and node.name == "registry"
    )
    wrong = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "WrongBase"
        for child in node.body
        if isinstance(child, ast.FunctionDef) and child.name == "registry"
        for node in [child]
    )
    setattr(correct, "_sugar_defining_module", "example.fixtures")
    fragment = SourceFragment.from_node(
        correct, "example/fixtures.py", source=provider_source
    )
    assert correct.lineno != wrong.lineno
    seated = _function_at_provider_seat(tree, fragment)
    assert seated is correct
    assert seated is not wrong


def test_identical_fixture_names_in_two_classes_use_exact_seat(
    monkeypatch,
) -> None:
    """Name-only search would pick WrongBase.registry (first in module)."""
    _load_registry_fixture_kit()
    provider_source = (
        "from sqlalchemy.testing import config\n"
        "from sqlalchemy.orm import registry\n"
        "class WrongBase:\n"
        "    @config.fixture()\n"
        "    def registry(self, metadata):\n"
        "        yield object()  # not a kit-loaded registry shape\n"
        "\n"
        "class FixtureBase:\n"
        "    @config.fixture()\n"
        "    def registry(self, metadata):\n"
        "        value = registry(metadata=metadata)\n"
        "        yield value\n"
    )
    tree = ast.parse(provider_source)
    fixture_base = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "FixtureBase"
    )
    correct = next(
        node
        for node in fixture_base.body
        if isinstance(node, ast.FunctionDef) and node.name == "registry"
    )
    wrong = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "WrongBase"
        for child in node.body
        if isinstance(child, ast.FunctionDef) and child.name == "registry"
        for node in [child]
    )
    setattr(correct, "_sugar_defining_module", "example.fixtures")
    fragment = SourceFragment.from_node(
        correct, "example/fixtures.py", source=provider_source
    )
    assert correct.lineno != wrong.lineno
    monkeypatch.setattr(
        "sugar_lift_py_tests.sugar.install_source_dig."
        "resolve_install_source_class_method",
        lambda qualified, method: (
            fragment
            if (qualified, method) == ("example.FixtureBase", "registry")
            else None
        ),
    )
    monkeypatch.setattr(
        "sugar_lift_python_source.source_oracle.installed_module_source",
        lambda module: (
            (provider_source, "example/fixtures.py", "cid")
            if module == "example.fixtures"
            else None
        ),
    )
    assert ClassDefSugar.owns(_user_class_site(_CONSUMER)) is True


def test_imported_lookalike_config_fixture_stays_loud(monkeypatch) -> None:
    """Lying twin: pretend.testing.config.fixture is not a kit fixture coordinate."""
    _load_registry_fixture_kit()
    provider_source = (
        "from pretend.testing import config\n"
        "from sqlalchemy.orm import registry\n"
        "class FixtureBase:\n"
        "    @config.fixture()\n"
        "    def registry(self, metadata):\n"
        "        value = registry(metadata=metadata)\n"
        "        yield value\n"
    )
    _install_provider(monkeypatch, provider_source)
    assert ClassDefSugar.owns(_user_class_site(_CONSUMER)) is False


def test_aliased_shadowed_fixture_decorator_stays_loud(monkeypatch) -> None:
    """Lying twin: module rebind of fixture head revokes the import warrant."""
    _load_registry_fixture_kit()
    provider_source = (
        "from pytest import fixture as real_fixture\n"
        "from sqlalchemy.orm import registry\n"
        "fixture = lambda fn: fn\n"
        "class FixtureBase:\n"
        "    @fixture()\n"
        "    def registry(self, metadata):\n"
        "        value = registry(metadata=metadata)\n"
        "        yield value\n"
    )
    _install_provider(monkeypatch, provider_source)
    assert ClassDefSugar.owns(_user_class_site(_CONSUMER)) is False


def test_class_body_shadowed_fixture_decorator_stays_loud(monkeypatch) -> None:
    """Lying twin: class-body rebind of the decorator head refuses auth."""
    _load_registry_fixture_kit()
    provider_source = (
        "import pytest\n"
        "from sqlalchemy.orm import registry\n"
        "class FixtureBase:\n"
        "    pytest = type('P', (), {'fixture': staticmethod(lambda fn: fn)})()\n"
        "    @pytest.fixture()\n"
        "    def registry(self, metadata):\n"
        "        value = registry(metadata=metadata)\n"
        "        yield value\n"
    )
    _install_provider(monkeypatch, provider_source)
    assert ClassDefSugar.owns(_user_class_site(_CONSUMER)) is False


def test_mismatched_provider_class_stays_loud(monkeypatch) -> None:
    """Lying twin: dig resolves OtherBase; consumer inherits FixtureBase."""
    _load_registry_fixture_kit()
    provider_source = (
        "import pytest\n"
        "from sqlalchemy.orm import registry\n"
        "class OtherBase:\n"
        "    @pytest.fixture()\n"
        "    def registry(self, metadata):\n"
        "        value = registry(metadata=metadata)\n"
        "        yield value\n"
    )
    _install_provider(
        monkeypatch,
        provider_source,
        qualified_base="example.OtherBase",
    )
    assert ClassDefSugar.owns(_user_class_site(_CONSUMER)) is False


def test_from_pytest_import_fixture_authenticates_with_protocol() -> None:
    """Import-from binding resolves to pytest.fixture under loaded protocol."""
    load_fixture_protocol({"pytest.fixture": NativeShape.FIXTURE_DECORATOR})
    source = (
        "from pytest import fixture\n"
        "class FixtureBase:\n"
        "    @fixture()\n"
        "    def registry(self):\n"
        "        yield 0\n"
    )
    tree = ast.parse(source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "registry"
    )
    assert _is_authenticated_fixture(function, _module_imports(tree), tree=tree) is True
