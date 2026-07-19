"""Re-earn call:numpy.issubdtype (#5400) via kit protocol.

Architecture (same class as #5902 numpy.all / numpy.dtype):

1. **Import/source provenance** — ``imported_call_identity`` resolves the
   binding chain (import / assignment, shadow-aware). Spelling alone never
   expands.
2. **Empty kit protocol** — production ``_PROTOCOL_IMPORTED_SUPPORT`` is empty.
   ``numpy.issubdtype`` arrives only through ``load_imported_callee_protocol``.
   No logo string Compare, no name whitelist, no inline isinstance/AST matcher.

Law: no logo string decides construction. MISSING/refused stays loud.

Honest residual: mint is a separate process; in-memory protocol load does not
reach full-corpus mint. Rows without a process-level kit loader stay
FactoryPanic — correct, not silent success.

#5409 call:conv is re-earned separately via structural class-body BOUND_SOURCE
(no kit, no logo) — see ``test_all_nine_authenticated_conv_rows_*``.
"""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.kit_rpc.factory_walk_row_dto import FactoryWalkRedRowDto
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.recognition.callee_universe import (
    CalleeUniverseRecognition,
    CalleeUniverseSupport,
    clear_imported_callee_protocol,
    imported_call_identity,
    load_imported_callee_protocol,
    recognize_authenticated_callee_identity,
    recognize_callee_universe,
)
from sugar_lift_py_tests.sugar.builtin_callee_universe_sugar import (
    BuiltinCalleeUniverseSugar,
)


@pytest.fixture(autouse=True)
def _isolate_imported_callee_protocol():
    clear_imported_callee_protocol()
    yield
    clear_imported_callee_protocol()


def _call_site(source: str, *, attr: str = "issubdtype"):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == attr
        ):
            return SourceFragment.from_node(node, "t.py", source=source)
    raise AssertionError(f"no call site attr={attr!r}")


def _load_issubdtype_protocol() -> None:
    load_imported_callee_protocol(
        {"numpy.issubdtype": CalleeUniverseSupport.NUMPY_ISSUBDTYPE}
    )


def _universe_gaps(payload) -> list[FactoryWalkRedRowDto]:
    return [
        row
        for row in payload.factory_walk
        if isinstance(row, FactoryWalkRedRowDto)
        and "callee universe coverage" in row.reason
    ]


# ---------------------------------------------------------------------------
# Empty-by-construction
# ---------------------------------------------------------------------------


def test_protocol_empty_by_construction_leaves_issubdtype_loud() -> None:
    assert recognize_authenticated_callee_identity("numpy.issubdtype") is None
    source = (
        "import numpy as np\n"
        "\n"
        "def test_dtype(left, right):\n"
        "    assert np.issubdtype(left, right)\n"
    )
    site = _call_site(source)
    assert imported_call_identity(site) == "numpy.issubdtype"
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None
    assert not BuiltinCalleeUniverseSugar.owns(site)


# ---------------------------------------------------------------------------
# Truthful twin — import-bound + protocol → green
# ---------------------------------------------------------------------------


def test_truthful_numpy_issubdtype_attr_under_protocol() -> None:
    _load_issubdtype_protocol()
    source = (
        "import numpy as np\n"
        "\n"
        "def test_dtype(left, right):\n"
        "    assert np.issubdtype(left, right)\n"
    )
    site = _call_site(source)
    assert imported_call_identity(site) == "numpy.issubdtype"
    assert CalleeUniverseRecognition.coordinate(site) == "numpy.issubdtype"
    assert (
        recognize_callee_universe("call:numpy.issubdtype", site=site)
        is CalleeUniverseSupport.NUMPY_ISSUBDTYPE
    )
    assert BuiltinCalleeUniverseSugar.owns(site)
    built = build_node(
        site,
        filename="t.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(filename="t.py", catalog=default_catalog()),
    )
    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"
    payload = lift_file_payload(source, "issubdtype_covered_fixture.py")
    assert any(
        edge.get("targetSymbol") == "call:numpy.issubdtype"
        for edge in payload.call_edges
    )
    assert _universe_gaps(payload) == []


def test_truthful_from_import_issubdtype_under_protocol() -> None:
    _load_issubdtype_protocol()
    source = (
        "from numpy import issubdtype\n"
        "\n"
        "def test_dtype(left, right):\n"
        "    assert issubdtype(left, right)\n"
    )
    tree = ast.parse(source)
    call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "issubdtype"
    )
    site = SourceFragment.from_node(call, "t.py", source=source)
    assert imported_call_identity(site) == "numpy.issubdtype"
    assert (
        recognize_callee_universe("call:numpy.issubdtype", site=site)
        is CalleeUniverseSupport.NUMPY_ISSUBDTYPE
    )


# ---------------------------------------------------------------------------
# Lying twins — refuse even with real coordinates loaded
# ---------------------------------------------------------------------------


def test_lying_parameter_shadow_stays_loud_under_protocol() -> None:
    _load_issubdtype_protocol()
    source = (
        "import numpy as np\n"
        "\n"
        "def test_dtype(np, left, right):\n"
        "    assert np.issubdtype(left, right)\n"
    )
    site = _call_site(source)
    assert imported_call_identity(site) is None
    assert recognize_callee_universe(site=site) is None
    assert not BuiltinCalleeUniverseSugar.owns(site)
    payload = lift_file_payload(source, "issubdtype_shadowed_fixture.py")
    assert [g.ast_kind for g in _universe_gaps(payload)] == [
        "call:numpy.issubdtype"
    ]


def test_lying_late_rebind_stays_loud_under_protocol() -> None:
    _load_issubdtype_protocol()
    source = (
        "import numpy as np\n"
        "\n"
        "def test_dtype(left, right):\n"
        "    assert np.issubdtype(left, right)\n"
        "    np = replacement\n"
    )
    site = _call_site(source)
    assert imported_call_identity(site) is None
    assert recognize_callee_universe(site=site) is None
    assert not BuiltinCalleeUniverseSugar.owns(site)


def test_lying_math_as_np_stays_loud_under_protocol() -> None:
    """Lookalike module alias is not numpy even when protocol is loaded."""

    _load_issubdtype_protocol()
    source = (
        "import math as np\n"
        "\n"
        "def test_dtype(left, right):\n"
        "    assert np.issubdtype(left, right)\n"
    )
    site = _call_site(source)
    # math has no issubdtype import identity matching the protocol key.
    identity = imported_call_identity(site)
    assert identity != "numpy.issubdtype"
    assert recognize_callee_universe(site=site) is None
    assert not BuiltinCalleeUniverseSugar.owns(site)


def test_lying_fqn_without_import_stays_loud_under_protocol() -> None:
    _load_issubdtype_protocol()
    source = (
        "def test_dtype(left, right):\n"
        "    assert numpy.issubdtype(left, right)\n"
    )
    site = _call_site(source)
    assert imported_call_identity(site) is None
    assert recognize_callee_universe(site=site) is None
    assert not BuiltinCalleeUniverseSugar.owns(site)


def test_production_tables_never_embed_issubdtype_logo() -> None:
    from sugar_lift_py_tests.recognition.callee_universe import _IMPORTED_SUPPORT

    assert "numpy.issubdtype" not in _IMPORTED_SUPPORT
    assert not any(
        c == "numpy.issubdtype" or c.startswith("numpy.issubdtype")
        for c in BuiltinCalleeUniverseSugar.universe_coordinates
    )
