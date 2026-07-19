"""Drain (part of) #5913, second increment — extends the manifest landed in
#5918 (`kit_manifests/pandas_receiver_surface_5913.json`) with five more
member tickets, using the SAME plumbing (`instance_call` kit-manifest
section wired to `native_shape.load_instance_call_protocol`, built there).

Member acceptance proved THIS pass:

- ``call:to_csv`` (#5644, 20 rows) — DataFrame + Series receivers.
- ``call:identical`` (#5640, 24 rows) — Index receiver.
- ``call:get_loc`` (#5639, 25 rows) — Index receiver.
- ``call:is_`` (#5636, 27 rows) — Index receiver.
- ``call:slice_locs`` (#5637, 27 rows) — Index receiver.

Row counts are #5913's stated ticket-body estimates (reclassified factory-walk
counts), not a fresh corpus measurement — treated as unverified estimates per
that issue's own caveat, not claimed as proven ΔR.

Every other #5913 member ticket remains untouched and stays loud
FactoryPanic; this file does not claim them.

Law: no logo string decides construction. A same-named method on an
unauthenticated/unrelated receiver (shadowed binding, late rebind, lookalike
import, lookalike vendor type, or a plain user-defined class) never resolves
a NativeShape/member pair and stays loud. Twins below prove that refutation,
verified to fail with production protocol tables (i.e. before this manifest
loads, or with the added JSON entries reverted).
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


def test_manifest_declares_the_second_increment_members() -> None:
    document = json.loads(_MANIFEST_PATH.read_text())
    assert document["call_shape"]["pandas.Index"] == "PANDAS_INDEX"
    assert document["instance_call"]["PANDAS_DATAFRAME.to_csv"] == "pandas.DataFrame.to_csv"
    assert document["instance_call"]["PANDAS_SERIES.to_csv"] == "pandas.Series.to_csv"
    assert document["instance_call"]["PANDAS_INDEX.identical"] == "pandas.Index.identical"
    assert document["instance_call"]["PANDAS_INDEX.get_loc"] == "pandas.Index.get_loc"
    assert document["instance_call"]["PANDAS_INDEX.is_"] == "pandas.Index.is_"
    assert document["instance_call"]["PANDAS_INDEX.slice_locs"] == "pandas.Index.slice_locs"


def test_production_tables_never_embed_the_increment2_vendor_fqns() -> None:
    document = json.loads(_MANIFEST_PATH.read_text())
    for fqn in document["call_shape"]:
        assert fqn not in _CALL_SHAPES, f"{fqn} must never be a hard-coded call shape"
    for shape_member in document["instance_call"]:
        head, _, tail = shape_member.partition(".")
        assert (NativeShape[head], tail) not in _NATIVE_INSTANCE_CALLS


def test_empty_by_construction_leaves_index_identical_loud() -> None:
    assert recognize_native_call("pandas.Index") is None
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_identical():\n"
        "    a = pd.Index([1, 2])\n"
        "    b = pd.Index([1, 2])\n"
        "    assert a.identical(b)\n"
    )
    site = _call_site(source, attr="identical")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


# ---------------------------------------------------------------------------
# Truthful twins
# ---------------------------------------------------------------------------


def test_truthful_dataframe_to_csv() -> None:
    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_to_csv():\n"
        "    df = pd.DataFrame({'x': [1]})\n"
        "    df.to_csv('out.csv')\n"
    )
    site = _call_site(source, attr="to_csv")
    assert CalleeUniverseRecognition.coordinate(site) == "pandas.DataFrame.to_csv"
    assert (
        recognize_callee_universe("call:to_csv", site=site)
        is CalleeUniverseSupport.PANDAS_DATAFRAME_TO_CSV
    )
    payload = lift_file_payload(source, "dataframe_to_csv_covered_fixture.py")
    assert _universe_gaps(payload) == []


def test_truthful_series_to_csv() -> None:
    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_to_csv():\n"
        "    s = pd.Series([1, 2])\n"
        "    s.to_csv('out.csv')\n"
    )
    site = _call_site(source, attr="to_csv")
    assert (
        recognize_callee_universe("call:to_csv", site=site)
        is CalleeUniverseSupport.PANDAS_SERIES_TO_CSV
    )


def test_truthful_index_identical() -> None:
    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_identical():\n"
        "    a = pd.Index([1, 2])\n"
        "    b = pd.Index([1, 2])\n"
        "    assert a.identical(b)\n"
    )
    site = _call_site(source, attr="identical")
    assert (
        recognize_callee_universe("call:identical", site=site)
        is CalleeUniverseSupport.PANDAS_INDEX_IDENTICAL
    )
    payload = lift_file_payload(source, "index_identical_covered_fixture.py")
    assert _universe_gaps(payload) == []


def test_truthful_index_get_loc() -> None:
    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_get_loc():\n"
        "    idx = pd.Index([1, 2, 3])\n"
        "    assert idx.get_loc(2) == 1\n"
    )
    site = _call_site(source, attr="get_loc")
    assert (
        recognize_callee_universe("call:get_loc", site=site)
        is CalleeUniverseSupport.PANDAS_INDEX_GET_LOC
    )


def test_truthful_index_is_() -> None:
    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_is_():\n"
        "    idx = pd.Index([1, 2, 3])\n"
        "    other = idx.view()\n"
        "    assert idx.is_(other)\n"
    )
    site = _call_site(source, attr="is_")
    assert (
        recognize_callee_universe("call:is_", site=site)
        is CalleeUniverseSupport.PANDAS_INDEX_IS_
    )


def test_truthful_index_slice_locs() -> None:
    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_slice_locs():\n"
        "    idx = pd.Index([1, 2, 3, 4])\n"
        "    assert idx.slice_locs(2, 3) == (1, 3)\n"
    )
    site = _call_site(source, attr="slice_locs")
    assert (
        recognize_callee_universe("call:slice_locs", site=site)
        is CalleeUniverseSupport.PANDAS_INDEX_SLICE_LOCS
    )


# ---------------------------------------------------------------------------
# Lying twins — MUST refute
# ---------------------------------------------------------------------------


def test_lying_lookalike_receiver_of_a_different_vendor_type_stays_loud() -> None:
    """``pd.Series`` also exposes ``.identical``, but only ``pandas.Index``
    is declared in the ``instance_call`` section for this member. Same
    method name, same vendor module, genuinely different, unauthenticated
    receiver-member pair — must stay loud.
    """

    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_identical():\n"
        "    a = pd.Series([1, 2])\n"
        "    b = pd.Series([1, 2])\n"
        "    assert a.identical(b)\n"
    )
    site = _call_site(source, attr="identical")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None
    payload = lift_file_payload(source, "series_identical_lookalike_fixture.py")
    gaps = _universe_gaps(payload)
    assert len(gaps) == 1
    assert gaps[0].ast_kind.endswith("identical")


def test_lying_shadowed_parameter_stays_loud() -> None:
    """A parameter named ``idx`` shadows the Index-assigned local ``idx``."""

    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_get_loc(idx):\n"
        "    other = pd.Index([1, 2, 3])\n"
        "    assert idx.get_loc(2)\n"
    )
    site = _call_site(source, attr="get_loc")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None
    payload = lift_file_payload(source, "index_get_loc_shadowed_fixture.py")
    gaps = _universe_gaps(payload)
    assert len(gaps) == 1


def test_lying_late_rebind_stays_loud() -> None:
    """``idx`` is reassigned to a non-authenticated value before the call
    site. The latest visible binding for ``idx`` wins — an Index Assign
    earlier in the function does not leak through a subsequent
    unauthenticated rebind.
    """

    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_get_loc():\n"
        "    idx = pd.Index([1, 2, 3])\n"
        "    idx = replacement()\n"
        "    assert idx.get_loc(2)\n"
    )
    site = _call_site(source, attr="get_loc")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


def test_lying_aliased_lookalike_import_stays_loud() -> None:
    """``import json as pd`` — same alias spelling, wrong module entirely."""

    _load_manifest()
    source = (
        "import json as pd\n"
        "\n"
        "def test_to_csv():\n"
        "    df = pd.DataFrame({'x': [1]})\n"
        "    df.to_csv('out.csv')\n"
    )
    site = _call_site(source, attr="to_csv")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


def test_lying_same_named_attribute_on_unauthenticated_receiver_stays_loud() -> None:
    """``idx`` is a bare parameter — pandas is present in the file, but the
    receiver of ``.slice_locs`` was never authenticated by an Assign at all.
    """

    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_slice_locs(idx):\n"
        "    assert idx.slice_locs(1, 2)\n"
        "    assert pd is not None\n"
    )
    site = _call_site(source, attr="slice_locs")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


def test_kit_manifest_unloads_cleanly_increment2() -> None:
    _load_manifest()
    assert recognize_native_call("pandas.Index") is NativeShape.PANDAS_INDEX
    assert (
        recognize_native_instance_call(NativeShape.PANDAS_INDEX, "identical")
        == "pandas.Index.identical"
    )
    assert (
        recognize_authenticated_callee_identity("pandas.Index.identical")
        is CalleeUniverseSupport.PANDAS_INDEX_IDENTICAL
    )
    clear_all_kit_protocols()
    assert recognize_native_call("pandas.Index") is None
    assert recognize_authenticated_callee_identity("pandas.Index.identical") is None
