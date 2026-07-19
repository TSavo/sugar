"""Drain (part of) #5913, third increment — extends the manifest landed in
#5918/#5920 (`kit_manifests/pandas_receiver_surface_5913.json`) with two more
member tickets, using the SAME plumbing (`instance_call` kit-manifest section
wired to `native_shape.load_instance_call_protocol`, built in #5918).

Member acceptance proved THIS pass:

- ``call:to_html`` (#5645, 18 rows est.) — DataFrame receiver only. The
  ticket's family also includes ``Styler.to_html`` call sites (e.g.
  ``Styler(df).format(...).to_html()``), but those receivers are the return
  value of a chained builder call, not a directly-assigned/annotated name —
  authenticating that shape honestly needs fluent-builder-return provenance,
  not just twins. Left for a later increment; this file claims DataFrame
  rows only.
- ``call:_categories_match_up_to_permutation`` (#5646, 16 rows est.) —
  Categorical receiver.

Row counts are #5913's stated ticket-body estimates (reclassified factory-walk
counts), not a fresh corpus measurement — treated as unverified estimates per
that issue's own caveat, not claimed as proven ΔR.

Investigated and left loud, NOT claimed, this pass:

- ``call:_has_no_reference`` (#5625, 48 rows est.) and ``call:has_reference``
  (#5647, 16 rows est.) — every corpus call site is a chained attribute
  receiver (``df._mgr._has_no_reference(0)``,
  ``df._mgr.blocks[0].refs.has_reference()``), never a directly-assigned or
  annotated name of a known vendor type. Authenticating these needs a genuine
  recognizer extension (BlockManager / BlockValuesRefs property-return
  provenance), which is out of scope for a twins-only member drain.
- ``call:drepr`` (#5632, 32 rows est.) — the pinned pandas 3.0.3 test source
  (``tests/scalar/timedelta/test_formats.py``) defines ``drepr`` as a
  locally-bound test-file lambda (``drepr = lambda x: x._repr_base()``), not
  a vendor attribute call at all. This is a corpus/recensus classification
  artifact, not a `call:X` receiver-surface member.
- ``call:hash`` (#5642, 22 rows est.) — the pinned pandas 3.0.3 test source
  (``tests/arrays/interval/test_interval_pyarrow.py``) calls the builtin
  ``hash(p1)``, not ``p1.hash()``. Same artifact class as ``drepr``.

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


def test_manifest_declares_the_third_increment_members() -> None:
    document = json.loads(_MANIFEST_PATH.read_text())
    assert document["call_shape"]["pandas.Categorical"] == "PANDAS_CATEGORICAL"
    assert document["instance_call"]["PANDAS_DATAFRAME.to_html"] == "pandas.DataFrame.to_html"
    assert (
        document["instance_call"]["PANDAS_CATEGORICAL._categories_match_up_to_permutation"]
        == "pandas.Categorical._categories_match_up_to_permutation"
    )


def test_production_tables_never_embed_the_increment3_vendor_fqns() -> None:
    document = json.loads(_MANIFEST_PATH.read_text())
    for fqn in document["call_shape"]:
        assert fqn not in _CALL_SHAPES, f"{fqn} must never be a hard-coded call shape"
    for shape_member in document["instance_call"]:
        head, _, tail = shape_member.partition(".")
        assert (NativeShape[head], tail) not in _NATIVE_INSTANCE_CALLS


def test_empty_by_construction_leaves_categorical_loud() -> None:
    assert recognize_native_call("pandas.Categorical") is None
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_match():\n"
        "    c1 = pd.Categorical(list('aabca'), categories=list('abc'))\n"
        "    c2 = pd.Categorical(list('aabca'), categories=list('cab'))\n"
        "    assert c1._categories_match_up_to_permutation(c2)\n"
    )
    site = _call_site(source, attr="_categories_match_up_to_permutation")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


# ---------------------------------------------------------------------------
# Truthful twins
# ---------------------------------------------------------------------------


def test_truthful_dataframe_to_html() -> None:
    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_to_html():\n"
        "    df = pd.DataFrame({'x': [1]})\n"
        "    df.to_html()\n"
    )
    site = _call_site(source, attr="to_html")
    assert CalleeUniverseRecognition.coordinate(site) == "pandas.DataFrame.to_html"
    assert (
        recognize_callee_universe("call:to_html", site=site)
        is CalleeUniverseSupport.PANDAS_DATAFRAME_TO_HTML
    )
    payload = lift_file_payload(source, "dataframe_to_html_covered_fixture.py")
    assert _universe_gaps(payload) == []


def test_truthful_categorical_categories_match_up_to_permutation() -> None:
    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_match():\n"
        "    c1 = pd.Categorical(list('aabca'), categories=list('abc'))\n"
        "    c2 = pd.Categorical(list('aabca'), categories=list('cab'))\n"
        "    assert c1._categories_match_up_to_permutation(c2)\n"
    )
    site = _call_site(source, attr="_categories_match_up_to_permutation")
    assert (
        recognize_callee_universe(
            "call:_categories_match_up_to_permutation", site=site
        )
        is CalleeUniverseSupport.PANDAS_CATEGORICAL_MATCH_UP_TO_PERMUTATION
    )
    payload = lift_file_payload(source, "categorical_match_covered_fixture.py")
    assert _universe_gaps(payload) == []


# ---------------------------------------------------------------------------
# Lying twins — MUST refute
# ---------------------------------------------------------------------------


def test_lying_lookalike_receiver_of_a_different_vendor_type_stays_loud() -> None:
    """``pd.Series`` is a real, recognized receiver-surface type (#5918), but
    it does not expose ``to_html`` in the manifest — only ``pandas.DataFrame``
    does. Same method name, genuinely different, unauthenticated
    (shape, member) pair — must stay loud.
    """

    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_to_html():\n"
        "    s = pd.Series([1, 2])\n"
        "    assert s.to_html()\n"
    )
    site = _call_site(source, attr="to_html")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None
    payload = lift_file_payload(source, "series_to_html_lookalike_fixture.py")
    gaps = _universe_gaps(payload)
    assert len(gaps) == 1
    assert gaps[0].ast_kind.endswith("to_html")


def test_lying_shadowed_parameter_stays_loud() -> None:
    """A parameter named ``df`` shadows the DataFrame-assigned local ``df``."""

    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_to_html(df):\n"
        "    other = pd.DataFrame({'x': [1]})\n"
        "    assert df.to_html()\n"
    )
    site = _call_site(source, attr="to_html")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None
    payload = lift_file_payload(source, "dataframe_to_html_shadowed_fixture.py")
    gaps = _universe_gaps(payload)
    assert len(gaps) == 1


def test_lying_late_rebind_stays_loud() -> None:
    """``c1`` is reassigned to a non-authenticated value before the call
    site. The latest visible binding for ``c1`` wins — an earlier Categorical
    Assign does not leak through a subsequent unauthenticated rebind.
    """

    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_match():\n"
        "    c1 = pd.Categorical(list('aabca'), categories=list('abc'))\n"
        "    c1 = replacement()\n"
        "    c1._categories_match_up_to_permutation(other)\n"
    )
    site = _call_site(source, attr="_categories_match_up_to_permutation")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


def test_lying_aliased_lookalike_import_stays_loud() -> None:
    """``import json as pd`` — same alias spelling, wrong module entirely."""

    _load_manifest()
    source = (
        "import json as pd\n"
        "\n"
        "def test_to_html():\n"
        "    df = pd.DataFrame({'x': [1]})\n"
        "    df.to_html()\n"
    )
    site = _call_site(source, attr="to_html")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


def test_lying_bare_unauthenticated_receiver_stays_loud() -> None:
    """``c1`` is a bare parameter — pandas is present in the file, but the
    receiver was never authenticated by an Assign at all.
    """

    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_match(c1, c2):\n"
        "    assert c1._categories_match_up_to_permutation(c2)\n"
        "    assert pd is not None\n"
    )
    site = _call_site(source, attr="_categories_match_up_to_permutation")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None


def test_kit_manifest_unloads_cleanly_increment3() -> None:
    _load_manifest()
    assert recognize_native_call("pandas.Categorical") is NativeShape.PANDAS_CATEGORICAL
    assert (
        recognize_native_instance_call(
            NativeShape.PANDAS_CATEGORICAL, "_categories_match_up_to_permutation"
        )
        == "pandas.Categorical._categories_match_up_to_permutation"
    )
    assert (
        recognize_authenticated_callee_identity(
            "pandas.Categorical._categories_match_up_to_permutation"
        )
        is CalleeUniverseSupport.PANDAS_CATEGORICAL_MATCH_UP_TO_PERMUTATION
    )
    clear_all_kit_protocols()
    assert recognize_native_call("pandas.Categorical") is None
    assert (
        recognize_authenticated_callee_identity(
            "pandas.Categorical._categories_match_up_to_permutation"
        )
        is None
    )
