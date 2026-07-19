"""Drain #5911 (qualified/dotted import-binding-resolvable Call, 775 rows/130
tickets, filed off the shape re-audit at #5252) via the kit-manifest overlay.

Mechanism (same class as #5902/#5903/#5904/#5905 — no new recognizer code):

1. **Import/source provenance** — ``imported_call_identity`` resolves the
   binding chain (``import X`` / ``from X import Y``, alias-aware, shadow-
   aware, rebind-aware). This machinery already existed and is untouched.
2. **Empty-by-construction kit protocol** — production
   ``_PROTOCOL_IMPORTED_SUPPORT`` never carries a vendor-root key. The 130
   member tickets' FQNs (``pandas.Timedelta``,
   ``pandas._libs.tslibs.timestamps.Timestamp``, ``datetime.datetime``, ...)
   arrive only through ``load_imported_callee_protocol`` /
   ``load_kit_manifest_file`` loading
   ``kit_manifests/pandas_import_binding_5911.json`` — the manifest is the
   evidence, never an ambient dict or a name whitelist compiled into
   production recognition.
3. The 125 new ``CalleeUniverseSupport`` members added for #5911 are pure
   enum data; two distinct import paths for the identical construction
   target collapse onto one member (``PANDAS_TIMEDELTA``, ``PANDAS_TIMESTAMP``,
   ``PANDAS_PERIOD``, ``PANDAS_INTERVAL``, ``PANDAS_ISNA``).

Law: no logo string decides construction. MISSING/refused stays loud. Lying
twins (aliased import, shadowed binding, late rebind, bare FQN with no
import) all refute under the *same loaded protocol* — proving the warrant is
lexical binding provenance, never spelling.
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
    clear_imported_callee_protocol,
    imported_call_identity,
    recognize_authenticated_callee_identity,
    recognize_callee_universe,
)
from sugar_lift_py_tests.recognition.kit_manifest import (
    clear_all_kit_protocols,
    load_kit_manifest_file,
)

_MANIFEST_PATH = (
    Path(__file__).parent.parent / "kit_manifests" / "pandas_import_binding_5911.json"
)


@pytest.fixture(autouse=True)
def _isolate_kit_protocols():
    clear_all_kit_protocols()
    yield
    clear_all_kit_protocols()


def _call_site(source: str, *, attr: str | None = None, name: str | None = None):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if attr is not None and isinstance(node.func, ast.Attribute) and node.func.attr == attr:
            return SourceFragment.from_node(node, "t.py", source=source)
        if name is not None and isinstance(node.func, ast.Name) and node.func.id == name:
            return SourceFragment.from_node(node, "t.py", source=source)
    raise AssertionError("no matching call site")


def _universe_gaps(payload) -> list[FactoryWalkRedRowDto]:
    return [
        row
        for row in payload.factory_walk
        if isinstance(row, FactoryWalkRedRowDto) and "callee universe coverage" in row.reason
    ]


# ---------------------------------------------------------------------------
# Manifest content sanity
# ---------------------------------------------------------------------------


def test_manifest_declares_all_130_member_ticket_fqns() -> None:
    document = json.loads(_MANIFEST_PATH.read_text())
    coordinates = document["imported_callee"]
    assert len(coordinates) == 130
    assert coordinates["pandas.Timedelta"] == "PANDAS_TIMEDELTA"
    assert (
        coordinates["pandas._libs.tslibs.timedeltas.Timedelta"] == "PANDAS_TIMEDELTA"
    )
    assert coordinates["datetime.datetime"] == "DATETIME_DATETIME"
    assert coordinates["pandas.SparseDtype"] == "PANDAS_SPARSEDTYPE"


def test_production_tables_never_embed_the_5911_vendor_fqns() -> None:
    from sugar_lift_py_tests.recognition.callee_universe import _IMPORTED_SUPPORT

    document = json.loads(_MANIFEST_PATH.read_text())
    for fqn in document["imported_callee"]:
        assert fqn not in _IMPORTED_SUPPORT, f"{fqn} must never be a hard-coded logo"


def test_empty_by_construction_leaves_pandas_timedelta_loud() -> None:
    assert recognize_authenticated_callee_identity("pandas.Timedelta") is None
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_td():\n"
        "    assert pd.Timedelta(1, unit='D')\n"
    )
    site = _call_site(source, attr="Timedelta")
    assert imported_call_identity(site) == "pandas.Timedelta"
    assert recognize_callee_universe(site=site) is None


# ---------------------------------------------------------------------------
# Truthful twins — different lexical shapes over the SAME mechanism
# ---------------------------------------------------------------------------


def _load_manifest():
    return load_kit_manifest_file(_MANIFEST_PATH)


def test_truthful_import_dotted_attr_pandas_timedelta() -> None:
    _load_manifest()
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_td():\n"
        "    assert pd.Timedelta(1, unit='D')\n"
    )
    site = _call_site(source, attr="Timedelta")
    assert imported_call_identity(site) == "pandas.Timedelta"
    assert (
        recognize_callee_universe("call:Timedelta", site=site)
        is CalleeUniverseSupport.PANDAS_TIMEDELTA
    )
    payload = lift_file_payload(source, "timedelta_covered_fixture.py")
    assert _universe_gaps(payload) == []


def test_truthful_from_import_bare_name_pandas_timedelta_deep_path() -> None:
    """Same construction target, reached via the fully-qualified private path."""

    _load_manifest()
    source = (
        "from pandas._libs.tslibs.timedeltas import Timedelta\n"
        "\n"
        "def test_td():\n"
        "    assert Timedelta(1, unit='D')\n"
    )
    site = _call_site(source, name="Timedelta")
    assert imported_call_identity(site) == "pandas._libs.tslibs.timedeltas.Timedelta"
    assert (
        recognize_callee_universe("call:Timedelta", site=site)
        is CalleeUniverseSupport.PANDAS_TIMEDELTA
    )


def test_truthful_datetime_datetime_stdlib() -> None:
    _load_manifest()
    source = (
        "import datetime\n"
        "\n"
        "def test_dt():\n"
        "    assert datetime.datetime(2020, 1, 1)\n"
    )
    site = _call_site(source, attr="datetime")
    assert imported_call_identity(site) == "datetime.datetime"
    assert (
        recognize_callee_universe("call:datetime", site=site)
        is CalleeUniverseSupport.DATETIME_DATETIME
    )


def test_truthful_deeply_nested_dotted_ujson_loads() -> None:
    _load_manifest()
    source = (
        "import pandas._libs.json as json_lib\n"
        "\n"
        "def test_loads():\n"
        "    assert json_lib.ujson_loads('{}')\n"
    )
    site = _call_site(source, attr="ujson_loads")
    assert imported_call_identity(site) == "pandas._libs.json.ujson_loads"
    assert (
        recognize_callee_universe("call:ujson_loads", site=site)
        is CalleeUniverseSupport.LIBS_JSON_UJSON_LOADS
    )


# ---------------------------------------------------------------------------
# Lying twins — refuse even with the real coordinate loaded
# ---------------------------------------------------------------------------


def test_lying_aliased_lookalike_import_stays_loud() -> None:
    """``import json as pd`` — same alias spelling, wrong module entirely."""

    _load_manifest()
    source = (
        "import json as pd\n"
        "\n"
        "def test_td():\n"
        "    assert pd.Timedelta(1, unit='D')\n"
    )
    site = _call_site(source, attr="Timedelta")
    identity = imported_call_identity(site)
    assert identity != "pandas.Timedelta"
    assert recognize_callee_universe(site=site) is None
    payload = lift_file_payload(source, "timedelta_aliased_lookalike_fixture.py")
    gaps = _universe_gaps(payload)
    assert len(gaps) == 1
    assert gaps[0].ast_kind.endswith("Timedelta")


def test_lying_shadowed_parameter_stays_loud() -> None:
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_td(pd):\n"
        "    assert pd.Timedelta(1, unit='D')\n"
    )
    _load_manifest()
    site = _call_site(source, attr="Timedelta")
    assert imported_call_identity(site) is None
    assert recognize_callee_universe(site=site) is None
    payload = lift_file_payload(source, "timedelta_shadowed_fixture.py")
    gaps = _universe_gaps(payload)
    assert len(gaps) == 1
    assert gaps[0].ast_kind.endswith("Timedelta")


def test_lying_late_rebind_stays_loud() -> None:
    source = (
        "import pandas as pd\n"
        "\n"
        "def test_td():\n"
        "    assert pd.Timedelta(1, unit='D')\n"
        "    pd = replacement\n"
    )
    _load_manifest()
    site = _call_site(source, attr="Timedelta")
    assert imported_call_identity(site) is None
    assert recognize_callee_universe(site=site) is None


def test_lying_bare_fqn_without_import_stays_loud() -> None:
    """A bare fully-qualified spelling with no binding at all is never proof.

    ``pandas`` is not imported, so the name itself is unbound: the honest
    outcome is a hard ``FactoryPanic`` on the unbound Name, not a silent
    universe-coverage gap and never a green construction (same class as the
    numpy.issubdtype lying twin at
    ``test_lying_fqn_without_import_stays_loud_under_protocol``).
    """

    from sugar_lift_py_tests.factory.factory_gap import FactoryPanic

    source = (
        "def test_td():\n"
        "    assert pandas.Timedelta(1, unit='D')\n"
    )
    _load_manifest()
    site = _call_site(source, attr="Timedelta")
    assert imported_call_identity(site) is None
    assert recognize_callee_universe(site=site) is None
    with pytest.raises(FactoryPanic):
        lift_file_payload(source, "timedelta_no_import_fixture.py")


def test_kit_manifest_unloads_cleanly() -> None:
    _load_manifest()
    assert recognize_authenticated_callee_identity("pandas.Timedelta") is not None
    clear_imported_callee_protocol()
    assert recognize_authenticated_callee_identity("pandas.Timedelta") is None
