"""Drain (part of) #5921 increment 2 — pydantic keyword-bearing methods and
the ``errors`` Attribute-chain receiver, via the same kit-manifest overlay
increment 1 (#5922) started.

#5922 drained the top-2 Assign-bound, positional-only pydantic method
families (``validate_python`` / ``to_python``) and explicitly left three
groups loud, each for a stated structural reason:

- ``to_json`` / ``validate_json`` — keyword-bearing call sites, "not enrolled
  by the current partition."
- ``errors`` — an Attribute-chain receiver (``exc_info.value.errors(...)``),
  "needs a new partition."
- ``model_dump`` / ``model_dump_json`` — a Call-result receiver
  (``Model(...).model_dump()``), also "needs a new partition."

This file proves the first two are now drained:

1. **Keyword-bearing sites** — no recognizer change was needed.
   ``_surface_method_coordinate`` never blanket-refused keyword-bearing
   receiver-surface calls; the keyword guard in ``CalleeUniverseRecognition
   .coordinate`` only routes keyword sites straight to that same surface
   path (skipping the *positional free-function* branch, which would
   otherwise silently authenticate open-domain methods under keyword noise).
   Increment 1 simply never enrolled ``to_json``/``validate_json`` as
   members; this increment adds them to the manifest, unchanged code.

2. **``errors`` Attribute-chain receiver** — a genuinely NEW partition:
   ``_pytest_raises_value_coordinate`` in ``callee_universe.py``.
   Authenticates ``exc_info.value.errors(...)`` only when ``exc_info`` is the
   ``as`` target of a lexically enclosing
   ``with pytest.raises(ValidationError) as exc_info:`` — both the context
   manager call identity (``pytest.raises``) and its sole positional argument
   (the raised class reference) resolve through the SAME ``call_shape`` kit
   table (no new protocol section). Shadowing and reassignment revoke this
   warrant exactly like every other receiver-surface path in this module.

``model_dump``/``model_dump_json`` (Call-result receiver) is **not**
addressed by this file and stays loud FactoryPanic — left refused; see
``kit_manifests/README.md`` for why building it soundly within this
increment was not attempted.

Row counts are #5577's own pinned-ranking estimates, not a fresh corpus
measurement (`corpus_fatal_triage.py` carries no `pydantic` PACKAGES entry) —
treated as unverified estimates, same caveat as #5920/#5922.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.kit_rpc.factory_walk_row_dto import FactoryWalkRedRowDto
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.recognition.callee_universe import (
    CalleeUniverseSupport,
    CalleeUniverseRecognition,
    recognize_authenticated_callee_identity,
    recognize_callee_universe,
)
from sugar_lift_py_tests.recognition.kit_manifest import (
    clear_all_kit_protocols,
    load_kit_manifest_file,
)
from sugar_lift_py_tests.recognition.native_shape import (
    NativeShape,
    _CALL_SHAPES,
    _NATIVE_INSTANCE_CALLS,
    recognize_native_call,
)

_MANIFEST_PATH = (
    Path(__file__).parent.parent
    / "kit_manifests"
    / "pydantic_receiver_surface_5577.json"
)


@pytest.fixture(autouse=True)
def _isolate_kit_protocols():
    clear_all_kit_protocols()
    yield
    clear_all_kit_protocols()


def _call_site(source: str, *, attr: str):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == attr
        ):
            return SourceFragment.from_node(node, "t.py", source=source)
    raise AssertionError("no matching call site")


def _universe_gaps(payload) -> list[FactoryWalkRedRowDto]:
    return [
        row
        for row in payload.factory_walk
        if isinstance(row, FactoryWalkRedRowDto) and "callee universe coverage" in row.reason
    ]


def _load_manifest():
    return load_kit_manifest_file(_MANIFEST_PATH)


# ---------------------------------------------------------------------------
# Manifest / production table sanity
# ---------------------------------------------------------------------------


def test_manifest_declares_the_inc2_members() -> None:
    document = json.loads(_MANIFEST_PATH.read_text())
    assert document["call_shape"]["pytest.raises"] == "PYTEST_RAISES_CONTEXT"
    assert document["call_shape"]["pydantic_core.ValidationError"] == "VALIDATION_ERROR"
    assert (
        document["instance_call"]["SCHEMA_VALIDATOR.validate_json"]
        == "pydantic_core.SchemaValidator.validate_json"
    )
    assert (
        document["instance_call"]["SCHEMA_SERIALIZER.to_json"]
        == "pydantic_core.SchemaSerializer.to_json"
    )
    assert (
        document["instance_call"]["VALIDATION_ERROR.errors"]
        == "pydantic_core.ValidationError.errors"
    )


def test_production_tables_never_embed_the_inc2_vendor_fqns() -> None:
    document = json.loads(_MANIFEST_PATH.read_text())
    for fqn in document["call_shape"]:
        assert fqn not in _CALL_SHAPES, f"{fqn} must never be a hard-coded call shape"
    for shape_member in document["instance_call"]:
        head, _, tail = shape_member.partition(".")
        assert (NativeShape[head], tail) not in _NATIVE_INSTANCE_CALLS


def test_empty_by_construction_leaves_validate_json_loud() -> None:
    source = (
        "from pydantic_core import SchemaValidator\n"
        "\n"
        "def test_v(schema, payload):\n"
        "    v = SchemaValidator(schema)\n"
        "    assert v.validate_json(payload, strict=True) == payload\n"
    )
    site = _call_site(source, attr="validate_json")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


def test_empty_by_construction_leaves_errors_loud() -> None:
    source = (
        "import pytest\n"
        "from pydantic_core import ValidationError\n"
        "\n"
        "def test_e(model_cls, payload):\n"
        "    with pytest.raises(ValidationError) as exc_info:\n"
        "        model_cls(**payload)\n"
        "    assert exc_info.value.errors() == []\n"
    )
    site = _call_site(source, attr="errors")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


# ---------------------------------------------------------------------------
# Truthful twins
# ---------------------------------------------------------------------------


def test_truthful_schema_serializer_to_json_keyword() -> None:
    _load_manifest()
    source = (
        "from pydantic_core import SchemaSerializer\n"
        "\n"
        "def test_s(schema, model):\n"
        "    s = SchemaSerializer(schema)\n"
        "    assert s.to_json(model, indent=2) is not None\n"
    )
    site = _call_site(source, attr="to_json")
    assert (
        CalleeUniverseRecognition.coordinate(site)
        == "pydantic_core.SchemaSerializer.to_json"
    )
    assert (
        recognize_callee_universe("call:to_json", site=site)
        is CalleeUniverseSupport.PYDANTIC_CORE_SCHEMA_SERIALIZER_TO_JSON
    )
    payload = lift_file_payload(source, "schema_serializer_to_json_fixture.py")
    assert _universe_gaps(payload) == []


def test_truthful_schema_validator_validate_json_keyword() -> None:
    _load_manifest()
    source = (
        "from pydantic_core import SchemaValidator\n"
        "\n"
        "def test_v(schema, payload):\n"
        "    v = SchemaValidator(schema)\n"
        "    assert v.validate_json(payload, strict=True) == payload\n"
    )
    site = _call_site(source, attr="validate_json")
    assert (
        CalleeUniverseRecognition.coordinate(site)
        == "pydantic_core.SchemaValidator.validate_json"
    )
    assert (
        recognize_callee_universe("call:validate_json", site=site)
        is CalleeUniverseSupport.PYDANTIC_CORE_SCHEMA_VALIDATOR_VALIDATE_JSON
    )
    payload = lift_file_payload(source, "schema_validator_validate_json_fixture.py")
    assert _universe_gaps(payload) == []


_ERRORS_TRUTHFUL_SOURCE = (
    "import pytest\n"
    "from pydantic_core import ValidationError\n"
    "\n"
    "def test_e(model_cls, payload):\n"
    "    with pytest.raises(ValidationError) as exc_info:\n"
    "        model_cls(**payload)\n"
    "    assert exc_info.value.errors() == []\n"
)


def test_truthful_validation_error_errors() -> None:
    _load_manifest()
    site = _call_site(_ERRORS_TRUTHFUL_SOURCE, attr="errors")
    assert (
        CalleeUniverseRecognition.coordinate(site)
        == "pydantic_core.ValidationError.errors"
    )
    assert (
        recognize_callee_universe("call:errors", site=site)
        is CalleeUniverseSupport.PYDANTIC_CORE_VALIDATION_ERROR_ERRORS
    )
    payload = lift_file_payload(_ERRORS_TRUTHFUL_SOURCE, "validation_error_errors_fixture.py")
    assert _universe_gaps(payload) == []


def test_recognize_native_call_resolves_pytest_raises_and_validation_error() -> None:
    _load_manifest()
    assert recognize_native_call("pytest.raises") is NativeShape.PYTEST_RAISES_CONTEXT
    assert recognize_native_call("pydantic_core.ValidationError") is NativeShape.VALIDATION_ERROR


# ---------------------------------------------------------------------------
# Lying twins — MUST refute
# ---------------------------------------------------------------------------


def test_lying_lookalike_receiver_of_a_different_exception_stays_loud() -> None:
    """``pytest.raises`` around a DIFFERENT, unauthenticated exception class.

    ``LocalError`` happens to define its own ``errors()`` method. The class
    argument to ``raises()`` never resolves to the kit-loaded VALIDATION_ERROR
    coordinate, so the receiver must stay unauthenticated.
    """

    _load_manifest()
    source = (
        "import pytest\n"
        "\n"
        "class LocalError(Exception):\n"
        "    def errors(self):\n"
        "        return []\n"
        "\n"
        "def test_e(thing):\n"
        "    with pytest.raises(LocalError) as exc_info:\n"
        "        thing()\n"
        "    assert exc_info.value.errors() == []\n"
    )
    site = _call_site(source, attr="errors")
    assert CalleeUniverseRecognition.coordinate(site) != (
        "pydantic_core.ValidationError.errors"
    )
    assert recognize_callee_universe(site=site) is not (
        CalleeUniverseSupport.PYDANTIC_CORE_VALIDATION_ERROR_ERRORS
    )
    lift_file_payload(source, "local_error_lookalike_fixture.py")


def test_lying_shadowed_parameter_stays_loud_for_errors() -> None:
    """A parameter named ``exc_info`` shadows the with-bound ``exc_info``."""

    _load_manifest()
    source = (
        "import pytest\n"
        "from pydantic_core import ValidationError\n"
        "\n"
        "def test_e(exc_info, model_cls, payload):\n"
        "    with pytest.raises(ValidationError) as real_exc_info:\n"
        "        model_cls(**payload)\n"
        "    assert exc_info.value.errors() == []\n"
        "    assert real_exc_info is not None\n"
    )
    site = _call_site(source, attr="errors")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None
    payload = lift_file_payload(source, "exc_info_shadowed_fixture.py")
    gaps = _universe_gaps(payload)
    assert len(gaps) == 1


def test_lying_late_rebind_stays_loud_for_errors() -> None:
    """``exc_info`` is reassigned after the with-block, before ``.errors()``."""

    _load_manifest()
    source = (
        "import pytest\n"
        "from pydantic_core import ValidationError\n"
        "\n"
        "def test_e(model_cls, payload, replacement):\n"
        "    with pytest.raises(ValidationError) as exc_info:\n"
        "        model_cls(**payload)\n"
        "    exc_info = replacement\n"
        "    assert exc_info.value.errors() == []\n"
    )
    site = _call_site(source, attr="errors")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


def test_lying_aliased_lookalike_import_stays_loud_for_errors() -> None:
    """``import json as pytest`` — same alias spelling, wrong module."""

    _load_manifest()
    source = (
        "import json as pytest\n"
        "from pydantic_core import ValidationError\n"
        "\n"
        "def test_e(model_cls, payload):\n"
        "    with pytest.raises(ValidationError) as exc_info:\n"
        "        model_cls(**payload)\n"
        "    assert exc_info.value.errors() == []\n"
    )
    site = _call_site(source, attr="errors")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


def test_lying_bare_unauthenticated_receiver_stays_loud_for_errors() -> None:
    """``exc_info.value.errors()`` with no enclosing ``with pytest.raises`` at all."""

    _load_manifest()
    source = (
        "def test_e(exc_info):\n"
        "    assert exc_info.value.errors() == []\n"
    )
    site = _call_site(source, attr="errors")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


def test_lying_wrong_attribute_stays_loud_for_errors() -> None:
    """``exc_info.other.errors()`` — attribute is not literally ``value``."""

    _load_manifest()
    source = (
        "import pytest\n"
        "from pydantic_core import ValidationError\n"
        "\n"
        "def test_e(model_cls, payload):\n"
        "    with pytest.raises(ValidationError) as exc_info:\n"
        "        model_cls(**payload)\n"
        "    assert exc_info.other.errors() == []\n"
    )
    site = _call_site(source, attr="errors")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


def test_lying_lookalike_receiver_of_a_different_type_stays_loud_for_to_json() -> None:
    """A local class named ``SchemaSerializer`` with a same-named method."""

    _load_manifest()
    source = (
        "class SchemaSerializer:\n"
        "    def to_json(self, model, indent=None):\n"
        "        return model\n"
        "\n"
        "def test_s(model):\n"
        "    s = SchemaSerializer()\n"
        "    assert s.to_json(model, indent=2) == model\n"
    )
    site = _call_site(source, attr="to_json")
    assert CalleeUniverseRecognition.coordinate(site) != (
        "pydantic_core.SchemaSerializer.to_json"
    )
    assert recognize_callee_universe(site=site) is not (
        CalleeUniverseSupport.PYDANTIC_CORE_SCHEMA_SERIALIZER_TO_JSON
    )
    lift_file_payload(source, "local_schema_serializer_lookalike_fixture.py")


def test_lying_shadowed_parameter_stays_loud_for_validate_json() -> None:
    _load_manifest()
    source = (
        "from pydantic_core import SchemaValidator\n"
        "\n"
        "def test_v(v, schema, payload):\n"
        "    real = SchemaValidator(schema)\n"
        "    assert v.validate_json(payload, strict=True) == payload\n"
        "    assert real is not None\n"
    )
    site = _call_site(source, attr="validate_json")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


def test_lying_late_rebind_stays_loud_for_to_json() -> None:
    _load_manifest()
    source = (
        "from pydantic_core import SchemaSerializer\n"
        "\n"
        "def test_s(schema, model, replacement):\n"
        "    s = SchemaSerializer(schema)\n"
        "    s = replacement\n"
        "    assert s.to_json(model, indent=2) is not None\n"
    )
    site = _call_site(source, attr="to_json")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


def test_lying_aliased_lookalike_import_stays_loud_for_validate_json() -> None:
    """``import json as pydantic_core`` — same alias spelling, wrong module."""

    _load_manifest()
    source = (
        "import json as pydantic_core\n"
        "\n"
        "def test_v(schema, payload):\n"
        "    v = pydantic_core.SchemaValidator(schema)\n"
        "    assert v.validate_json(payload, strict=True) == payload\n"
    )
    site = _call_site(source, attr="validate_json")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


def test_lying_bare_unauthenticated_receiver_stays_loud_for_to_json() -> None:
    _load_manifest()
    source = (
        "def test_s(s, model):\n"
        "    assert s.to_json(model, indent=2) is not None\n"
    )
    site = _call_site(source, attr="to_json")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None
