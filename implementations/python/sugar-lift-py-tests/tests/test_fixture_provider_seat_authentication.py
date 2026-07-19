"""#5578: fixture providers via general pytest.fixture protocol + exact seats.

Permanent floors:
- R_vendor_special_case = 0 by construction (no vendor fixture keys in recognition)
- Provider bodies are anchored to exact source seats (module + line/col)
- Lying twins stay loud: dual class fixtures, lookalike imports, shadow, mismatch
- Protocol authenticates via pytest.fixture only — never a vendor fixture key
"""

from __future__ import annotations

import ast

from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.sugar.class_def_sugar import ClassDefSugar


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


def test_pytest_fixture_protocol_authenticates_without_sqlalchemy_name(
    monkeypatch,
) -> None:
    """Registered fixture protocol (pytest.fixture) is enough — no SA logo."""
    provider_source = (
        "import pytest\n"
        "from sqlalchemy.orm import registry\n"
        "class FixtureBase:\n"
        "    @pytest.fixture()\n"
        "    def registry(self, metadata):\n"
        "        value = registry(metadata=metadata)\n"
        "        yield value\n"
    )
    fragment = _provider_fragment(provider_source, "registry", "example.fixtures")
    monkeypatch.setattr(
        "sugar_lift_py_tests.sugar.install_source_dig."
        "resolve_install_source_class_method",
        lambda qualified, method: (
            fragment if (qualified, method) == ("example.FixtureBase", "registry") else None
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
    source = (
        "from example import FixtureBase\n"
        "class TestThing(FixtureBase):\n"
        "    def test_it(self, registry):\n"
        "        @registry.mapped\n"
        "        class User:\n"
        "            pass\n"
    )
    assert ClassDefSugar.owns(_user_class_site(source)) is True


def test_identical_fixture_names_in_two_classes_use_exact_seat(
    monkeypatch,
) -> None:
    """Name-only search would pick WrongBase.registry (first in module).

    Both methods use the general pytest.fixture protocol — no vendor fixture key.
    """
    provider_source = (
        "import pytest\n"
        "from sqlalchemy.orm import registry\n"
        "class WrongBase:\n"
        "    @pytest.fixture()\n"
        "    def registry(self, metadata):\n"
        "        yield object()  # not a native registry shape\n"
        "\n"
        "class FixtureBase:\n"
        "    @pytest.fixture()\n"
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
    # Seat must be the FixtureBase method, not the earlier WrongBase twin.
    assert correct.lineno != wrong.lineno
    monkeypatch.setattr(
        "sugar_lift_py_tests.sugar.install_source_dig."
        "resolve_install_source_class_method",
        lambda qualified, method: (
            fragment if (qualified, method) == ("example.FixtureBase", "registry") else None
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
    source = (
        "from example import FixtureBase\n"
        "class TestThing(FixtureBase):\n"
        "    def test_it(self, registry):\n"
        "        @registry.mapped\n"
        "        class User:\n"
        "            pass\n"
    )
    assert ClassDefSugar.owns(_user_class_site(source)) is True


def test_imported_lookalike_config_fixture_stays_loud(monkeypatch) -> None:
    """Lookalike `config.fixture` (including SA testing.config) is not protocol."""
    provider_source = (
        "from sqlalchemy.testing import config\n"
        "from sqlalchemy.orm import registry\n"
        "class FixtureBase:\n"
        "    @config.fixture()\n"
        "    def registry(self, metadata):\n"
        "        value = registry(metadata=metadata)\n"
        "        yield value\n"
    )
    fragment = _provider_fragment(provider_source, "registry", "example.fixtures")
    monkeypatch.setattr(
        "sugar_lift_py_tests.sugar.install_source_dig."
        "resolve_install_source_class_method",
        lambda qualified, method: (
            fragment if (qualified, method) == ("example.FixtureBase", "registry") else None
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
    source = (
        "from example import FixtureBase\n"
        "class TestThing(FixtureBase):\n"
        "    def test_it(self, registry):\n"
        "        @registry.mapped\n"
        "        class User:\n"
        "            pass\n"
    )
    assert ClassDefSugar.owns(_user_class_site(source)) is False


def test_aliased_shadowed_fixture_decorator_stays_loud(monkeypatch) -> None:
    """Decorator spelling ``fixture`` after import-as-alias is not protocol-resolved.

    The import binds ``real_fixture``; the decorator uses unbound name ``fixture``
    (local lambda). Import map has no ``fixture`` key → not authenticated.
    """
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
    fragment = _provider_fragment(provider_source, "registry", "example.fixtures")
    monkeypatch.setattr(
        "sugar_lift_py_tests.sugar.install_source_dig."
        "resolve_install_source_class_method",
        lambda qualified, method: (
            fragment if (qualified, method) == ("example.FixtureBase", "registry") else None
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
    source = (
        "from example import FixtureBase\n"
        "class TestThing(FixtureBase):\n"
        "    def test_it(self, registry):\n"
        "        @registry.mapped\n"
        "        class User:\n"
        "            pass\n"
    )
    assert ClassDefSugar.owns(_user_class_site(source)) is False


def test_mismatched_provider_class_stays_loud(monkeypatch) -> None:
    """Resolver returns None for wrong class — parameter stays unauthenticated."""
    provider_source = (
        "import pytest\n"
        "from sqlalchemy.orm import registry\n"
        "class OtherBase:\n"
        "    @pytest.fixture()\n"
        "    def registry(self, metadata):\n"
        "        value = registry(metadata=metadata)\n"
        "        yield value\n"
    )
    fragment = _provider_fragment(provider_source, "registry", "example.fixtures")
    monkeypatch.setattr(
        "sugar_lift_py_tests.sugar.install_source_dig."
        "resolve_install_source_class_method",
        lambda qualified, method: (
            fragment if (qualified, method) == ("example.OtherBase", "registry") else None
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
    source = (
        "from example import FixtureBase\n"
        "class TestThing(FixtureBase):\n"
        "    def test_it(self, registry):\n"
        "        @registry.mapped\n"
        "        class User:\n"
        "            pass\n"
    )
    assert ClassDefSugar.owns(_user_class_site(source)) is False
