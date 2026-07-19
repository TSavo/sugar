"""Re-earn call:numpy.isnan (#5404) via kit protocol.

Architecture (same class as #5902 numpy.all/numpy.dtype, #5903 issubdtype):

1. **Import/source provenance** — ``imported_call_identity`` resolves the
   binding chain (import / assignment, shadow-aware). Spelling alone never
   expands.
2. **Empty kit protocol** — production ``_PROTOCOL_IMPORTED_SUPPORT`` is empty.
   ``numpy.isnan`` arrives only through ``load_imported_callee_protocol``. No
   logo string compare, no name whitelist, no inline isinstance/AST matcher.

Law: no logo string decides construction. MISSING/refused stays loud.

Measurement (current main, post-#5612/#5614 logo-table deletion): direct
single-file lift of a minimal reproduction of the corpus shape
(``div = np.floor_divide(...); assert np.isnan(div)``, matching
``numpy/_core/tests/test_umath.py``) shows ``call:numpy.isnan`` genuinely
unclassified before this change. The full representative file
(``test_umath.py``) cannot be lifted whole today: it panics on an unrelated
pre-existing Sugar-ordering ambiguity around line 213
(``Call candidates=[CallSugar, BuiltinCalleeUniverseSugar,
BuiltinTypeCallSugar]``) that blocks completion independent of this family and
is out of scope here.

Honest residual: mint is a separate process; in-memory protocol load does not
reach full-corpus mint. Rows without a process-level kit loader stay
FactoryPanic — correct, not silent success.
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


def _call_site(source: str, *, attr: str = "isnan"):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == attr
        ):
            return SourceFragment.from_node(node, "t.py", source=source)
    raise AssertionError(f"no call site attr={attr!r}")


def _load_isnan_protocol() -> None:
    load_imported_callee_protocol(
        {"numpy.isnan": CalleeUniverseSupport.NUMPY_ISNAN}
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


def test_protocol_empty_by_construction_leaves_isnan_loud() -> None:
    assert recognize_authenticated_callee_identity("numpy.isnan") is None
    source = (
        "import numpy as np\n"
        "\n"
        "def test_isnan(div):\n"
        "    assert np.isnan(div), f'div: {div}'\n"
    )
    site = _call_site(source)
    assert imported_call_identity(site) == "numpy.isnan"
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None
    assert not BuiltinCalleeUniverseSugar.owns(site)
    payload = lift_file_payload(source, "isnan_uncovered_fixture.py")
    assert [g.ast_kind for g in _universe_gaps(payload)] == ["call:numpy.isnan"]


# ---------------------------------------------------------------------------
# Truthful twin — import-bound + protocol → green
# ---------------------------------------------------------------------------


def test_truthful_numpy_isnan_attr_under_protocol() -> None:
    _load_isnan_protocol()
    source = (
        "import numpy as np\n"
        "\n"
        "def test_isnan(div):\n"
        "    assert np.isnan(div), f'div: {div}'\n"
    )
    site = _call_site(source)
    assert imported_call_identity(site) == "numpy.isnan"
    assert CalleeUniverseRecognition.coordinate(site) == "numpy.isnan"
    assert (
        recognize_callee_universe("call:numpy.isnan", site=site)
        is CalleeUniverseSupport.NUMPY_ISNAN
    )
    assert BuiltinCalleeUniverseSugar.owns(site)
    built = build_node(
        site,
        filename="t.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(filename="t.py", catalog=default_catalog()),
    )
    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"
    payload = lift_file_payload(source, "isnan_covered_fixture.py")
    assert any(
        edge.get("targetSymbol") == "call:numpy.isnan" for edge in payload.call_edges
    )
    assert _universe_gaps(payload) == []


def test_truthful_from_import_isnan_under_protocol() -> None:
    _load_isnan_protocol()
    source = (
        "from numpy import isnan\n"
        "\n"
        "def test_isnan(div):\n"
        "    assert isnan(div), f'div: {div}'\n"
    )
    tree = ast.parse(source)
    call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "isnan"
    )
    site = SourceFragment.from_node(call, "t.py", source=source)
    assert imported_call_identity(site) == "numpy.isnan"
    assert (
        recognize_callee_universe("call:numpy.isnan", site=site)
        is CalleeUniverseSupport.NUMPY_ISNAN
    )


# ---------------------------------------------------------------------------
# Lying twins — refuse even with the real coordinate loaded
# ---------------------------------------------------------------------------


def test_lying_parameter_shadow_stays_loud_under_protocol() -> None:
    _load_isnan_protocol()
    source = (
        "import numpy as np\n"
        "\n"
        "def test_isnan(np, div):\n"
        "    assert np.isnan(div), f'div: {div}'\n"
    )
    site = _call_site(source)
    assert imported_call_identity(site) is None
    assert recognize_callee_universe(site=site) is None
    assert not BuiltinCalleeUniverseSugar.owns(site)
    payload = lift_file_payload(source, "isnan_shadowed_fixture.py")
    assert [g.ast_kind for g in _universe_gaps(payload)] == ["call:numpy.isnan"]


def test_lying_late_rebind_stays_loud_under_protocol() -> None:
    _load_isnan_protocol()
    source = (
        "import numpy as np\n"
        "\n"
        "def test_isnan(div, replacement):\n"
        "    result = np.isnan(div)\n"
        "    np = replacement\n"
        "    return result\n"
    )
    site = _call_site(source)
    assert imported_call_identity(site) is None
    assert recognize_callee_universe(site=site) is None
    assert not BuiltinCalleeUniverseSugar.owns(site)


def test_lying_math_as_np_stays_loud_under_protocol() -> None:
    """Lookalike module alias is not numpy even when protocol is loaded."""

    _load_isnan_protocol()
    source = (
        "import math as np\n"
        "\n"
        "def test_isnan(div):\n"
        "    assert np.isnan(div), f'div: {div}'\n"
    )
    site = _call_site(source)
    # math.isnan does not exist as a registered coordinate under this key —
    # the import origin resolves to math, never numpy.
    identity = imported_call_identity(site)
    assert identity != "numpy.isnan"
    assert recognize_callee_universe(site=site) is None
    assert not BuiltinCalleeUniverseSugar.owns(site)


def test_lying_fqn_without_import_stays_loud_under_protocol() -> None:
    _load_isnan_protocol()
    source = (
        "def test_isnan(div):\n"
        "    assert numpy.isnan(div), f'div: {div}'\n"
    )
    site = _call_site(source)
    assert imported_call_identity(site) is None
    assert recognize_callee_universe(site=site) is None
    assert not BuiltinCalleeUniverseSugar.owns(site)


def test_production_tables_never_embed_isnan_logo() -> None:
    from sugar_lift_py_tests.recognition.callee_universe import _IMPORTED_SUPPORT

    assert "numpy.isnan" not in _IMPORTED_SUPPORT
    assert not any(
        c == "numpy.isnan" or c.startswith("numpy.isnan")
        for c in BuiltinCalleeUniverseSugar.universe_coordinates
    )
