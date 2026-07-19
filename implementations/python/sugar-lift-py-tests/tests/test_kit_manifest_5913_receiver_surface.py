"""Drain (part of) #5913 — bare attribute/bound-method Call whose receiver
type is authenticated by assignment provenance, via the kit-manifest overlay.

#5913 judged the shape as shared PLUMBING + per-path ACCEPTANCE: the
recognizer — receiver-type-authenticated attribute-call resolution — already
existed (built for #5577):

1. **Receiver provenance** — ``df = pd.DataFrame(...)`` is authenticated by
   ``_assigned_imported_call_identity`` (an Assign whose value is an
   import-bound Call), which is exactly ``imported_call_identity`` applied to
   the assigned value — shadow-aware, rebind-aware, alias-aware.
2. **Shape lookup** — ``native_shape.recognize_native_call(origin)`` maps the
   authenticated constructor FQN to a ``NativeShape`` member, kit-loaded only
   (``call_shape`` manifest section); production ``_CALL_SHAPES`` never
   carries a "pandas.*" key.
3. **Member lookup** — ``native_shape.recognize_native_instance_call(shape,
   member)`` maps ``(NativeShape, method-leaf)`` to a coordinate FQN,
   kit-loaded only (a NEW ``instance_call`` manifest section this PR wires
   into ``kit_manifest.py`` — the actual missing plumbing; the recognizer
   code itself needed nothing new).
4. **Universe typing** — the coordinate FQN resolves to a
   ``CalleeUniverseSupport`` member through the existing ``imported_callee``
   section (same mechanism as #5915/#5903/#5904/#5905).

Member acceptance proved THIS pass (2 of 143 tickets, kept honest and small):
``call:equals`` (#5622, 261 rows) and ``call:items`` (#5624, 56 rows) — for
DataFrame and Series receivers only. Every other #5913 member ticket is left
untouched and stays loud FactoryPanic; this file does not claim them.

Law: no logo string decides construction. A same-named method on an
unauthenticated/unrelated receiver (shadowed binding, late rebind, lookalike
import, or a plain user-defined class) never resolves a NativeShape and stays
loud. Twins below prove that refutation, verified to fail with production
protocol tables reverted to empty (i.e. before this manifest loads).
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

_MANIFEST_PATH = (
    Path(__file__).parent.parent
    / "kit_manifests"
    / "pandas_receiver_surface_5913.json"
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
    document = json.loads(_MANIFEST_PATH.read_text())
    # Subset check, not exact-equality: this manifest is a shared file across
    # #5913 member-drain increments (see test_kit_manifest_5913_receiver_
    # surface_increment2.py), so later increments legitimately add more
    # call_shape / instance_call entries. This test only asserts THIS file's
    # original two claims are still present and correct.
    assert document["call_shape"]["pandas.DataFrame"] == "PANDAS_DATAFRAME"
    assert document["call_shape"]["pandas.Series"] == "PANDAS_SERIES"
    assert document["instance_call"]["PANDAS_DATAFRAME.equals"] == "pandas.DataFrame.equals"
    assert document["instance_call"]["PANDAS_SERIES.equals"] == "pandas.Series.equals"
    assert document["instance_call"]["PANDAS_DATAFRAME.items"] == "pandas.DataFrame.items"
    assert document["instance_call"]["PANDAS_SERIES.items"] == "pandas.Series.items"


def test_production_tables_never_embed_the_5913_vendor_fqns() -> None:
    document = json.loads(_MANIFEST_PATH.read_text())
    for fqn in document["call_shape"]:
        assert fqn not in _CALL_SHAPES, f"{fqn} must never be a hard-coded call shape"
    for shape_member in document["instance_call"]:
        head, _, tail = shape_member.partition(".")
        assert (NativeShape[head], tail) not in _NATIVE_INSTANCE_CALLS


def test_empty_by_construction_leaves_dataframe_equals_loud() -> None:
    assert recognize_native_call("pandas.DataFrame") is None
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_eq():\n"
        "    a = pd.DataFrame({'x': [1]})\n"
        "    b = pd.DataFrame({'x': [1]})\n"
        "    assert a.equals(b)\n"
    )
    site = _call_site(source, attr="equals")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


# ---------------------------------------------------------------------------
# Truthful twins
# ---------------------------------------------------------------------------


def test_truthful_dataframe_equals() -> None:
    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_eq():\n"
        "    a = pd.DataFrame({'x': [1]})\n"
        "    b = pd.DataFrame({'x': [1]})\n"
        "    assert a.equals(b)\n"
    )
    site = _call_site(source, attr="equals")
    assert CalleeUniverseRecognition.coordinate(site) == "pandas.DataFrame.equals"
    assert (
        recognize_callee_universe("call:equals", site=site)
        is CalleeUniverseSupport.PANDAS_DATAFRAME_EQUALS
    )
    payload = lift_file_payload(source, "dataframe_equals_covered_fixture.py")
    assert _universe_gaps(payload) == []


def test_truthful_series_equals() -> None:
    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_eq():\n"
        "    a = pd.Series([1, 2, 3])\n"
        "    b = pd.Series([1, 2, 3])\n"
        "    assert a.equals(b)\n"
    )
    site = _call_site(source, attr="equals")
    assert CalleeUniverseRecognition.coordinate(site) == "pandas.Series.equals"
    assert (
        recognize_callee_universe("call:equals", site=site)
        is CalleeUniverseSupport.PANDAS_SERIES_EQUALS
    )


def test_truthful_dataframe_items() -> None:
    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_items():\n"
        "    df = pd.DataFrame({'x': [1]})\n"
        "    for name, col in df.items():\n"
        "        assert name\n"
    )
    site = _call_site(source, attr="items")
    assert (
        recognize_callee_universe("call:items", site=site)
        is CalleeUniverseSupport.PANDAS_DATAFRAME_ITEMS
    )


def test_truthful_series_items() -> None:
    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_items():\n"
        "    s = pd.Series([1, 2])\n"
        "    for idx, val in s.items():\n"
        "        assert val\n"
    )
    site = _call_site(source, attr="items")
    assert (
        recognize_callee_universe("call:items", site=site)
        is CalleeUniverseSupport.PANDAS_SERIES_ITEMS
    )


# ---------------------------------------------------------------------------
# Lying twins — MUST refute
# ---------------------------------------------------------------------------


def test_lying_lookalike_receiver_of_a_different_type_stays_loud() -> None:
    """``pd.Index`` also exposes ``.equals`` but is NOT in the loaded manifest.

    Same method name, same vendor module, genuinely different, unauthenticated
    receiver type. Must stay loud — proves the warrant keys off the exact
    authenticated constructor shape, never off the method-name spelling alone.
    """

    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_eq():\n"
        "    a = pd.Index([1, 2])\n"
        "    b = pd.Index([1, 2])\n"
        "    assert a.equals(b)\n"
    )
    site = _call_site(source, attr="equals")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None
    payload = lift_file_payload(source, "index_equals_lookalike_fixture.py")
    gaps = _universe_gaps(payload)
    assert len(gaps) == 1
    assert gaps[0].ast_kind.endswith("equals")


def test_lying_shadowed_parameter_stays_loud() -> None:
    """A parameter named ``a`` shadows the DataFrame-assigned local ``a``."""

    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_eq(a):\n"
        "    b = pd.DataFrame({'x': [1]})\n"
        "    assert a.equals(b)\n"
    )
    site = _call_site(source, attr="equals")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None
    payload = lift_file_payload(source, "dataframe_equals_shadowed_fixture.py")
    gaps = _universe_gaps(payload)
    assert len(gaps) == 1


def test_lying_late_rebind_stays_loud() -> None:
    """``a`` is reassigned to a non-authenticated value before the call site.

    The latest visible binding for ``a`` wins — a DataFrame Assign earlier in
    the function does not leak through a subsequent unauthenticated rebind.
    """

    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_eq():\n"
        "    a = pd.DataFrame({'x': [1]})\n"
        "    a = replacement()\n"
        "    b = pd.DataFrame({'x': [1]})\n"
        "    assert a.equals(b)\n"
    )
    site = _call_site(source, attr="equals")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


def test_lying_aliased_lookalike_import_stays_loud() -> None:
    """``import json as pd`` — same alias spelling, wrong module entirely."""

    _load_manifest()
    source = (
        "import json as pd\n"
        "\n"
        "def test_eq():\n"
        "    a = pd.DataFrame({'x': [1]})\n"
        "    b = pd.DataFrame({'x': [1]})\n"
        "    assert a.equals(b)\n"
    )
    site = _call_site(source, attr="equals")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


def test_lying_same_named_attribute_on_unauthenticated_receiver_stays_loud() -> None:
    """``a`` is a bare parameter — pandas is present in the file, but the
    receiver of ``.equals`` was never authenticated by an Assign at all.
    """

    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_eq(a, b):\n"
        "    assert a.equals(b)\n"
        "    assert pd is not None\n"
    )
    site = _call_site(source, attr="equals")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


def test_kit_manifest_unloads_cleanly() -> None:
    _load_manifest()
    assert recognize_native_call("pandas.DataFrame") is NativeShape.PANDAS_DATAFRAME
    assert (
        recognize_native_instance_call(NativeShape.PANDAS_DATAFRAME, "equals")
        == "pandas.DataFrame.equals"
    )
    assert (
        recognize_authenticated_callee_identity("pandas.DataFrame.equals")
        is CalleeUniverseSupport.PANDAS_DATAFRAME_EQUALS
    )
    clear_all_kit_protocols()
    assert recognize_native_call("pandas.DataFrame") is None
    assert recognize_authenticated_callee_identity("pandas.DataFrame.equals") is None
