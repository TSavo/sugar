"""Fixture providers stay loud until kit/bridge/proof contract evidence.

Doctrine: no logo string (including ``pytest.fixture``) is sufficient
construction evidence. Production ``_FIXTURE_DECORATORS`` is empty.

Seat anchoring and lying-twin structure remain tested so the future contract
path cannot reintroduce name-only provider selection or logo compares.
"""

from __future__ import annotations

import ast

from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.recognition.native_shape import (
    recognize_native_fixture_decorator,
)
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


def test_no_logo_fixture_coordinate_is_registered() -> None:
    assert recognize_native_fixture_decorator("pytest.fixture") is None
    assert (
        recognize_native_fixture_decorator("sqlalchemy.testing.config.fixture")
        is None
    )


def test_pytest_fixture_provider_stays_loud_without_kit_contract(
    monkeypatch,
) -> None:
    """Even a perfect seat-anchored pytest.fixture provider stays loud."""
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
    source = (
        "from example import FixtureBase\n"
        "class TestThing(FixtureBase):\n"
        "    def test_it(self, registry):\n"
        "        @registry.mapped\n"
        "        class User:\n"
        "            pass\n"
    )
    assert ClassDefSugar.owns(_user_class_site(source)) is False


def test_sqlalchemy_config_fixture_provider_stays_loud(monkeypatch) -> None:
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
    source = (
        "from example import FixtureBase\n"
        "class TestThing(FixtureBase):\n"
        "    def test_it(self, registry):\n"
        "        @registry.mapped\n"
        "        class User:\n"
        "            pass\n"
    )
    assert ClassDefSugar.owns(_user_class_site(source)) is False


def test_identical_fixture_names_cannot_false_green_via_name_only(
    monkeypatch,
) -> None:
    """Seat machinery still resolves exact line/col; protocol remains empty → loud."""
    provider_source = (
        "import pytest\n"
        "from sqlalchemy.orm import registry\n"
        "class WrongBase:\n"
        "    @pytest.fixture()\n"
        "    def registry(self, metadata):\n"
        "        yield object()\n"
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
    setattr(correct, "_sugar_defining_module", "example.fixtures")
    fragment = SourceFragment.from_node(
        correct, "example/fixtures.py", source=provider_source
    )
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
    source = (
        "from example import FixtureBase\n"
        "class TestThing(FixtureBase):\n"
        "    def test_it(self, registry):\n"
        "        @registry.mapped\n"
        "        class User:\n"
        "            pass\n"
    )
    assert ClassDefSugar.owns(_user_class_site(source)) is False


def test_lookalike_and_shadow_fixture_decorators_stay_loud(monkeypatch) -> None:
    for provider_source in (
        (
            "from pretend.testing import config\n"
            "from sqlalchemy.orm import registry\n"
            "class FixtureBase:\n"
            "    @config.fixture()\n"
            "    def registry(self, metadata):\n"
            "        value = registry(metadata=metadata)\n"
            "        yield value\n"
        ),
        (
            "from sqlalchemy.testing import config\n"
            "from sqlalchemy.orm import registry\n"
            "config = type('C', (), {'fixture': staticmethod(lambda: (lambda f: f))})()\n"
            "class FixtureBase:\n"
            "    @config.fixture()\n"
            "    def registry(self, metadata):\n"
            "        value = registry(metadata=metadata)\n"
            "        yield value\n"
        ),
    ):
        fragment = _provider_fragment(provider_source, "registry", "example.fixtures")
        monkeypatch.setattr(
            "sugar_lift_py_tests.sugar.install_source_dig."
            "resolve_install_source_class_method",
            lambda qualified, method, frag=fragment: (
                frag
                if (qualified, method) == ("example.FixtureBase", "registry")
                else None
            ),
        )
        monkeypatch.setattr(
            "sugar_lift_python_source.source_oracle.installed_module_source",
            lambda module, src=provider_source: (
                (src, "example/fixtures.py", "cid")
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
