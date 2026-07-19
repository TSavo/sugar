"""#5603: fixture providers stay loud without hard-coded fixture logos.

Seat anchoring remains (name + line + col). Fixture *authentication* does not
use pytest.fixture or any vendor fixture key in production recognition —
missing kit/bridge contract ⇒ loud (owns False / no identity decorator).
"""

from __future__ import annotations

import ast

from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.recognition.class_decorator import (
    _function_at_provider_seat,
)
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


def test_fixture_protocol_table_is_empty_no_logo() -> None:
    """No hard-coded fixture logo coordinates in production recognition."""
    assert recognize_native_fixture_decorator("pytest.fixture") is None
    assert recognize_native_fixture_decorator("any.vendor.fixture") is None


def test_pytest_fixture_provider_stays_loud_without_kit_contract(
    monkeypatch,
) -> None:
    """Honest loud: pytest.fixture alone does not construct (#5603)."""
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
    assert ClassDefSugar.owns(_user_class_site(source)) is False


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


def test_imported_lookalike_config_fixture_stays_loud(monkeypatch) -> None:
    provider_source = (
        "from pretend.testing import config\n"
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
