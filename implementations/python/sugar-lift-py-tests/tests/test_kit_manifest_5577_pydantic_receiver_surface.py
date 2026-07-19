"""Drain (part of) #5577 — pydantic method-receiver universe mass, first
increment, via the kit-manifest overlay.

#5577 (architecture, merged #5619) built the receiver-surface recognizer:
Assign-bound Name receiver → import-authenticated ctor shape → enrolled
``(NativeShape, member)`` coordinate. #5619 left it wired to **empty** kit
hooks: no ΔR, correct loud residual, because no manifest declared the
pydantic-core coordinates. #5913's pandas increments (#5918/#5920) proved
the SAME plumbing drains real vendor mass once a manifest is declared — this
file is that increment for pydantic:

1. **Receiver provenance** — ``v = SchemaValidator(...)`` /
   ``s = SchemaSerializer(...)`` authenticated by
   ``_assigned_imported_call_identity`` (shadow-aware, rebind-aware,
   alias-aware) — unchanged from #5619.
2. **Shape lookup** — ``native_shape.recognize_native_call(origin)``, kit-
   loaded only via this manifest's ``call_shape`` section; production
   ``_CALL_SHAPES`` never carries a "pydantic_core.*" key.
3. **Member lookup** — ``native_shape.recognize_native_instance_call(shape,
   member)``, kit-loaded only via this manifest's ``instance_call`` section.
4. **Universe typing** — the coordinate FQN resolves to a
   ``CalleeUniverseSupport`` member through the existing ``imported_callee``
   section (same mechanism as the pandas #5913 increments).

Member acceptance proved THIS pass (2 of #5577's ranked families, kept
honest and small): ``call:validate_python`` (rank #2, 401 rows) on
``SchemaValidator``, and ``call:to_python`` (rank #1, 533 rows) on
``SchemaSerializer`` — Assign-bound Name receiver, positional call only.
Every other #5577 family (``to_json``, ``validate_json``, ``errors``,
``model_dump``, keyword-bearing call sites, fixture/annotated-param
receivers, Attribute-chain receivers such as ``exc_info.value.errors(...)``,
Call-result receivers such as ``Model(...).model_dump()``) is left untouched
by this manifest and stays loud FactoryPanic; this file does not claim them.

Row counts are #5577's own pinned-ranking estimates (pin `0f4748f7`, window
662), not a fresh corpus measurement — `corpus_fatal_triage.py` does not yet
carry a `pydantic` package entry in its `PACKAGES` tuple, so there is no
same-mechanism live remeasurement tool for this vendor today. Treated as an
unverified estimate, not a proven ΔR (same caveat #5920 stated for its own
row counts).

Law: no logo string decides construction. A same-named method on an
unauthenticated/unrelated receiver (lookalike receiver of a different type,
shadowed parameter, late rebind, aliased lookalike import, or a bare
unauthenticated receiver) never resolves a NativeShape/member pair and stays
loud. Twins below prove that refutation, verified to fail with production
protocol tables (i.e. before this manifest loads, or with kit protocols
cleared).
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
    recognize_native_instance_call,
)
from sugar_lift_py_tests.sugar.builtin_callee_universe_sugar import (
    BuiltinCalleeUniverseSugar,
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


def test_manifest_declares_the_two_claimed_members() -> None:
    # Increment 2 (#5921) additively extends this same manifest with more
    # call_shape/instance_call entries (to_json/validate_json/errors); this
    # test only asserts increment 1's two entries are still present, not that
    # the section is exactly these two (additive, not exclusive).
    document = json.loads(_MANIFEST_PATH.read_text())
    assert document["call_shape"]["pydantic_core.SchemaValidator"] == "SCHEMA_VALIDATOR"
    assert document["call_shape"]["pydantic_core.SchemaSerializer"] == "SCHEMA_SERIALIZER"
    assert (
        document["instance_call"]["SCHEMA_VALIDATOR.validate_python"]
        == "pydantic_core.SchemaValidator.validate_python"
    )
    assert (
        document["instance_call"]["SCHEMA_SERIALIZER.to_python"]
        == "pydantic_core.SchemaSerializer.to_python"
    )


def test_production_tables_never_embed_the_5577_vendor_fqns() -> None:
    document = json.loads(_MANIFEST_PATH.read_text())
    for fqn in document["call_shape"]:
        assert fqn not in _CALL_SHAPES, f"{fqn} must never be a hard-coded call shape"
    for shape_member in document["instance_call"]:
        head, _, tail = shape_member.partition(".")
        assert (NativeShape[head], tail) not in _NATIVE_INSTANCE_CALLS


def test_empty_by_construction_leaves_validate_python_loud() -> None:
    assert recognize_native_call("pydantic_core.SchemaValidator") is None
    source = (
        "from pydantic_core import SchemaValidator\n"
        "\n"
        "def test_v(schema, payload):\n"
        "    v = SchemaValidator(schema)\n"
        "    assert v.validate_python(payload) == payload\n"
    )
    site = _call_site(source, attr="validate_python")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


def test_empty_by_construction_leaves_to_python_loud() -> None:
    assert recognize_native_call("pydantic_core.SchemaSerializer") is None
    source = (
        "from pydantic_core import SchemaSerializer\n"
        "\n"
        "def test_s(schema, model):\n"
        "    s = SchemaSerializer(schema)\n"
        "    assert s.to_python(model) is not None\n"
    )
    site = _call_site(source, attr="to_python")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


# ---------------------------------------------------------------------------
# Truthful twins
# ---------------------------------------------------------------------------


def test_truthful_schema_validator_validate_python() -> None:
    _load_manifest()
    source = (
        "from pydantic_core import SchemaValidator\n"
        "\n"
        "def test_v(schema, payload):\n"
        "    v = SchemaValidator(schema)\n"
        "    assert v.validate_python(payload) == payload\n"
    )
    site = _call_site(source, attr="validate_python")
    assert (
        CalleeUniverseRecognition.coordinate(site)
        == "pydantic_core.SchemaValidator.validate_python"
    )
    assert BuiltinCalleeUniverseSugar.owns(site) is True
    assert (
        recognize_callee_universe("call:validate_python", site=site)
        is CalleeUniverseSupport.PYDANTIC_CORE_SCHEMA_VALIDATOR_VALIDATE_PYTHON
    )
    payload = lift_file_payload(source, "schema_validator_covered_fixture.py")
    assert _universe_gaps(payload) == []


def test_truthful_schema_serializer_to_python() -> None:
    _load_manifest()
    source = (
        "from pydantic_core import SchemaSerializer\n"
        "\n"
        "def test_s(schema, model):\n"
        "    s = SchemaSerializer(schema)\n"
        "    assert s.to_python(model) is not None\n"
    )
    site = _call_site(source, attr="to_python")
    assert (
        CalleeUniverseRecognition.coordinate(site)
        == "pydantic_core.SchemaSerializer.to_python"
    )
    assert BuiltinCalleeUniverseSugar.owns(site) is True
    assert (
        recognize_callee_universe("call:to_python", site=site)
        is CalleeUniverseSupport.PYDANTIC_CORE_SCHEMA_SERIALIZER_TO_PYTHON
    )
    payload = lift_file_payload(source, "schema_serializer_covered_fixture.py")
    assert _universe_gaps(payload) == []


# ---------------------------------------------------------------------------
# Lying twins — MUST refute (per member: lookalike / shadowed / rebind /
# aliased import / bare unauthenticated receiver)
# ---------------------------------------------------------------------------


def test_lying_lookalike_receiver_of_a_different_type_stays_loud() -> None:
    """``SchemaSerializer`` also spells ``to_python``... no it does not — the

    genuine lookalike is a DIFFERENT pydantic-core type that happens to share
    the ``validate_python`` leaf name with a user-defined local class. Same
    method name, genuinely different, unauthenticated receiver type. Must
    stay loud — proves the warrant keys off the exact authenticated
    constructor shape, never off the method-name spelling alone.
    """

    _load_manifest()
    source = (
        "class LocalValidator:\n"
        "    def validate_python(self, payload):\n"
        "        return payload\n"
        "\n"
        "def test_v(payload):\n"
        "    v = LocalValidator()\n"
        "    assert v.validate_python(payload) == payload\n"
    )
    site = _call_site(source, attr="validate_python")
    # Never resolves the pydantic-core coordinate: the receiver is a local
    # class, not an Assign-bound SchemaValidator constructor call.
    assert CalleeUniverseRecognition.coordinate(site) != (
        "pydantic_core.SchemaValidator.validate_python"
    )
    assert recognize_callee_universe(site=site) is not (
        CalleeUniverseSupport.PYDANTIC_CORE_SCHEMA_VALIDATOR_VALIDATE_PYTHON
    )
    # A local class with an attachable body is legitimately dug/lifted through
    # a different path (SOURCE_AUTHENTICATED_CALLABLE); either way it must
    # never silently claim the vendor coordinate.
    lift_file_payload(source, "local_validator_lookalike_fixture.py")


def test_lying_shadowed_parameter_stays_loud() -> None:
    """A parameter named ``v`` shadows the SchemaValidator-assigned local ``v``."""

    _load_manifest()
    source = (
        "from pydantic_core import SchemaValidator\n"
        "\n"
        "def test_v(v, schema, payload):\n"
        "    real = SchemaValidator(schema)\n"
        "    assert v.validate_python(payload) == payload\n"
        "    assert real is not None\n"
    )
    site = _call_site(source, attr="validate_python")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None
    payload = lift_file_payload(source, "schema_validator_shadowed_fixture.py")
    gaps = _universe_gaps(payload)
    assert len(gaps) == 1


def test_lying_late_rebind_stays_loud() -> None:
    """``s`` is reassigned to a non-authenticated value before the call site.

    The latest visible binding for ``s`` wins — a SchemaSerializer Assign
    earlier in the function does not leak through a subsequent
    unauthenticated rebind.
    """

    _load_manifest()
    source = (
        "from pydantic_core import SchemaSerializer\n"
        "\n"
        "def test_s(schema, model, replacement):\n"
        "    s = SchemaSerializer(schema)\n"
        "    s = replacement\n"
        "    assert s.to_python(model) is not None\n"
    )
    site = _call_site(source, attr="to_python")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


def test_lying_aliased_lookalike_import_stays_loud() -> None:
    """``import json as pydantic_core`` — same alias spelling, wrong module."""

    _load_manifest()
    source = (
        "import json as pydantic_core\n"
        "\n"
        "def test_v(schema, payload):\n"
        "    v = pydantic_core.SchemaValidator(schema)\n"
        "    assert v.validate_python(payload) == payload\n"
    )
    site = _call_site(source, attr="validate_python")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


def test_lying_bare_unauthenticated_receiver_stays_loud() -> None:
    """``s`` is a bare parameter — pydantic_core is present in the file, but

    the receiver of ``.to_python`` was never authenticated by an Assign at
    all.
    """

    _load_manifest()
    source = (
        "from pydantic_core import SchemaSerializer\n"
        "\n"
        "def test_s(s, model):\n"
        "    assert s.to_python(model) is not None\n"
        "    assert SchemaSerializer is not None\n"
    )
    site = _call_site(source, attr="to_python")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


def test_kit_manifest_unloads_cleanly() -> None:
    _load_manifest()
    assert recognize_native_call("pydantic_core.SchemaValidator") is NativeShape.SCHEMA_VALIDATOR
    assert (
        recognize_native_instance_call(NativeShape.SCHEMA_VALIDATOR, "validate_python")
        == "pydantic_core.SchemaValidator.validate_python"
    )
    assert (
        recognize_authenticated_callee_identity(
            "pydantic_core.SchemaValidator.validate_python"
        )
        is CalleeUniverseSupport.PYDANTIC_CORE_SCHEMA_VALIDATOR_VALIDATE_PYTHON
    )
    clear_all_kit_protocols()
    assert recognize_native_call("pydantic_core.SchemaValidator") is None
    assert (
        recognize_authenticated_callee_identity(
            "pydantic_core.SchemaValidator.validate_python"
        )
        is None
    )
