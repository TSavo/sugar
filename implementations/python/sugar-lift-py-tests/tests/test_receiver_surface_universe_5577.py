"""#5577 receiver-surface method universes — architecture instruments.

Recognition law (written + executable):

1. Method leaves never authenticate alone (no bare ``to_python`` / ``validate_python``).
2. Assign-bound Name receivers authenticate only through import-constructed
   native shapes (``pattern = re.compile(...)`` → REGEX_PATTERN × search).
3. Keywords are allowed only for surface-authenticated members.
4. Vendor surfaces (SchemaValidator / SchemaSerializer / …) require kit/bridge
   contract loaders — empty by construction; rows stay loud FactoryPanic.
5. No production logo strings (``pydantic``, ``pydantic_core``, …) as
   construction keys (#5603).
"""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.recognition.callee_universe import (
    CalleeUniverseRecognition,
    recognize_callee_universe,
)
from sugar_lift_py_tests.recognition.native_shape import (
    NativeShape,
    clear_call_shape_protocol,
    clear_instance_call_protocol,
    load_call_shape_protocol,
    load_instance_call_protocol,
    recognize_native_call,
    recognize_native_instance_call,
)
from sugar_lift_py_tests.sugar.builtin_callee_universe_sugar import (
    BuiltinCalleeUniverseSugar,
)


def _call_site(source: str, *, attr: str | None = None, name: str | None = None):
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if attr is not None and isinstance(node.func, ast.Attribute) and node.func.attr == attr:
            return SourceFragment.from_node(node, "surface.py", source=source)
        if name is not None and isinstance(node.func, ast.Name) and node.func.id == name:
            return SourceFragment.from_node(node, "surface.py", source=source)
    raise AssertionError(f"no call site attr={attr!r} name={name!r}")


def test_kit_surface_registries_empty_by_construction() -> None:
    """No vendor logos smuggled via kit hooks until a real contract loads.

    Same empty-by-construction pattern as #5618 load_fixture_protocol /
    load_call_shape_protocol — production tables stay empty.
    """

    clear_call_shape_protocol()
    clear_instance_call_protocol()
    # Without a loaded protocol, kit surfaces do not authenticate.
    assert recognize_native_call("some_extension.SchemaValidator") is None
    assert (
        recognize_native_instance_call(NativeShape.SCHEMA_VALIDATOR, "validate_python")
        is None
    )


def test_production_native_shapes_carry_no_pydantic_logo_keys() -> None:
    """Hard law: no pydantic / pydantic_core string keys in production tables."""

    from sugar_lift_py_tests.recognition import native_shape as ns

    for table in (
        ns._CALL_SHAPES,
        ns._NATIVE_INSTANCE_CALLS,
        ns._NATIVE_DECORATORS,
        ns._FIXTURE_DECORATORS,
        ns._PARAMETRIZE_DECORATORS,
        ns._MODULE_NAMES,
    ):
        for key in table:
            text = key if isinstance(key, str) else repr(key)
            lowered = text.lower()
            assert "pydantic" not in lowered, text


def test_assign_bound_regex_search_positional_authenticates() -> None:
    source = (
        "import re\n"
        "\n"
        "def test_a(value):\n"
        "    pattern = re.compile('x')\n"
        "    assert pattern.search(value) is not None\n"
    )
    site = _call_site(source, attr="search")
    assert CalleeUniverseRecognition.coordinate(site) == "re.Pattern.search"
    assert BuiltinCalleeUniverseSugar.owns(site) is True
    assert recognize_callee_universe("call:re.Pattern.search", site=site) is not None


def test_assign_bound_regex_search_keyword_authenticates() -> None:
    """#5577: keywords no longer blanket-refuse authenticated surfaces."""

    source = (
        "import re\n"
        "\n"
        "def test_a(value):\n"
        "    pattern = re.compile('x')\n"
        "    assert pattern.search(value, pos=0) is not None\n"
    )
    site = _call_site(source, attr="search")
    assert site.call_has_keywords() is True
    assert CalleeUniverseRecognition.coordinate(site) == "re.Pattern.search"
    assert BuiltinCalleeUniverseSugar.owns(site) is True


def test_lookalike_search_without_compile_binding_stays_loud() -> None:
    """Lying twin: parameter receiver is not Assign-bound compile provenance."""

    source = (
        "def test_a(pattern, value):\n"
        "    assert pattern.search(value) is not None\n"
    )
    site = _call_site(source, attr="search")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert BuiltinCalleeUniverseSugar.owns(site) is False
    assert recognize_callee_universe(site=site) is None


def test_bare_to_python_leaf_never_authenticates() -> None:
    """Forbidden drain: bare method leaf without receiver warrant."""

    source = (
        "def test_a(payload):\n"
        "    assert to_python(payload) is not None\n"
    )
    site = _call_site(source, name="to_python")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert BuiltinCalleeUniverseSugar.owns(site) is False


def test_schema_validator_assign_stays_loud_without_kit_contract() -> None:
    """Honest residual: no production logo enrollment for SchemaValidator.

    Required kit/bridge evidence to drain (not present today):
    - content-addressed contract → load_call_shape_protocol mapping import
      identity for SchemaValidator → SCHEMA_VALIDATOR (loaded externally,
      never hard-coded in production tables)
    - load_instance_call_protocol for (SCHEMA_VALIDATOR, validate_python)
    Until then, Assign-bound validate_python remains loud FactoryPanic / gap.
    """

    clear_call_shape_protocol()
    clear_instance_call_protocol()
    source = (
        "from some_extension import SchemaValidator\n"
        "\n"
        "def test_a(payload):\n"
        "    v = SchemaValidator()\n"
        "    assert v.validate_python(payload) == payload\n"
    )
    site = _call_site(source, attr="validate_python")
    # Import identity may resolve, but no native shape without kit table.
    assert recognize_native_call("some_extension.SchemaValidator") is None
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert BuiltinCalleeUniverseSugar.owns(site) is False
    assert recognize_native_instance_call(
        NativeShape.SCHEMA_VALIDATOR, "validate_python"
    ) is None


def test_kit_loaded_surface_authenticates_without_production_logo_table() -> None:
    """External load_call_shape_protocol + load_instance_call_protocol path.

    Demonstrates the #5618-style kit contract mechanism for #5577 surfaces:
    tests (and future kit loaders) install coordinates externally; production
    recognition modules stay free of vendor-root string tables.
    """

    clear_call_shape_protocol()
    clear_instance_call_protocol()
    try:
        load_call_shape_protocol(
            {"some_extension.SchemaValidator": NativeShape.SCHEMA_VALIDATOR}
        )
        load_instance_call_protocol(
            {
                (NativeShape.SCHEMA_VALIDATOR, "validate_python"): (
                    "surface.SchemaValidator.validate_python"
                )
            }
        )
        source = (
            "from some_extension import SchemaValidator\n"
            "\n"
            "def test_a(payload):\n"
            "    v = SchemaValidator()\n"
            "    assert v.validate_python(payload) == payload\n"
        )
        site = _call_site(source, attr="validate_python")
        assert (
            CalleeUniverseRecognition.coordinate(site)
            == "surface.SchemaValidator.validate_python"
        )
    finally:
        clear_call_shape_protocol()
        clear_instance_call_protocol()


def test_rebind_revokes_surface_search() -> None:
    """Lying twin: later rebind of the receiver name revokes the surface."""

    source = (
        "import re\n"
        "\n"
        "def test_a(value, other):\n"
        "    pattern = re.compile('x')\n"
        "    pattern = other\n"
        "    assert pattern.search(value) is not None\n"
    )
    site = _call_site(source, attr="search")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert BuiltinCalleeUniverseSugar.owns(site) is False
