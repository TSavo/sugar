"""Parametrize decorator authentication is import/source provenance + protocol.

The production protocol table is empty by construction (same class as fixture
#5603). Expansion of literal rows requires a kit/bridge contract to load the
resolved import identity. Logo string comparison is never used.
"""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.recognition.native_shape import (
    NativeShape,
    clear_parametrize_protocol,
    load_parametrize_protocol,
    recognize_parametrize_decorator,
)
from sugar_lift_py_tests.recognition.remaining_semantics import (
    RemainingSemanticRecognition,
)

@pytest.fixture(autouse=True)
def _isolate_parametrize_protocol():
    clear_parametrize_protocol()
    yield
    clear_parametrize_protocol()


def _function_site(source: str, filename: str = "param.py") -> SourceFragment:
    tree = ast.parse(source)
    fn = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    return SourceFragment.from_node(fn, filename, source=source)


_TRUTHFUL_SOURCE = (
    "import pytest\n"
    "\n"
    "@pytest.mark.parametrize('x', [1, 2, 3])\n"
    "def test_values(x):\n"
    "    assert x == x\n"
)

_LOOKALIKE_SOURCES = (
    # Spelling-only Attribute chain without an import binding.
    (
        "@pytest.mark.parametrize('x', [1, 2, 3])\n"
        "def test_values(x):\n"
        "    assert x == x\n"
    ),
    # Parameter shadow of the pytest binding.
    (
        "import pytest\n"
        "\n"
        "def outer(pytest):\n"
        "    @pytest.mark.parametrize('x', [1, 2, 3])\n"
        "    def test_values(x):\n"
        "        assert x == x\n"
    ),
    # Different module with the same Attribute spelling.
    (
        "import notpytest as pytest\n"
        "\n"
        "@pytest.mark.parametrize('x', [1, 2, 3])\n"
        "def test_values(x):\n"
        "    assert x == x\n"
    ),
)


def test_parametrize_protocol_is_empty_by_construction() -> None:
    assert recognize_parametrize_decorator("pytest.mark.parametrize") is None
    site = _function_site(_TRUTHFUL_SOURCE)
    assert RemainingSemanticRecognition.literal_pytest_parametrize_rows(site) == ()


def test_import_bound_parametrize_expands_only_when_protocol_loaded() -> None:
    """Truthful twin: import-resolved identity + loaded protocol → rows."""
    load_parametrize_protocol(
        {"pytest.mark.parametrize": NativeShape.PARAMETRIZE_DECORATOR}
    )
    site = _function_site(_TRUTHFUL_SOURCE)
    rows = RemainingSemanticRecognition.literal_pytest_parametrize_rows(site)
    assert rows == ((("x",), ((1,), (2,), (3,))),)


@pytest.mark.parametrize("source", _LOOKALIKE_SOURCES)
def test_lookalike_parametrize_does_not_expand_even_with_protocol(source: str) -> None:
    """Lying twin: lookalike / shadow / unimported spelling never expands."""
    load_parametrize_protocol(
        {"pytest.mark.parametrize": NativeShape.PARAMETRIZE_DECORATOR}
    )
    # Nested def: take the innermost FunctionDef named test_values
    tree = ast.parse(source)
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "test_values":
            fn = node
    assert fn is not None
    site = SourceFragment.from_node(fn, "lookalike.py", source=source)
    assert RemainingSemanticRecognition.literal_pytest_parametrize_rows(site) == ()


def test_logo_spelling_alone_never_authenticates_without_import() -> None:
    """Regression: Attribute spelling is not enough (the old logo Compare path)."""
    load_parametrize_protocol(
        {"pytest.mark.parametrize": NativeShape.PARAMETRIZE_DECORATOR}
    )
    source = (
        "@pytest.mark.parametrize('x', [0])\n"
        "def test_values(x):\n"
        "    assert x == 0\n"
    )
    site = _function_site(source)
    assert RemainingSemanticRecognition.literal_pytest_parametrize_rows(site) == ()
