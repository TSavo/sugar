"""Re-earn call:numpy.all (#5408) and call:numpy.dtype (#5407) via kit protocol.

Architecture (same class as #5617 parametrize / #5618 fixture):

1. **Import/source provenance** — ``imported_call_identity`` resolves the
   binding chain (import / assignment, shadow-aware). Spelling alone never
   expands.
2. **Empty kit protocol** — production ``_PROTOCOL_IMPORTED_SUPPORT`` is empty.
   Coordinates such as ``numpy.all`` / ``numpy.dtype`` arrive only through
   ``load_imported_callee_protocol``. No logo string Compare, no name
   whitelist, no inline isinstance/AST matcher.

Law: no logo string decides construction. MISSING/refused stays loud.

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


def _call_site(source: str, *, attr: str | None = None, name: str | None = None):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if attr is not None and isinstance(node.func, ast.Attribute):
            if node.func.attr == attr:
                return SourceFragment.from_node(node, "t.py", source=source)
        if name is not None and isinstance(node.func, ast.Name):
            if node.func.id == name:
                return SourceFragment.from_node(node, "t.py", source=source)
    raise AssertionError(f"no call site attr={attr!r} name={name!r}")


def _load_numpy_all_dtype_protocol() -> None:
    """Install only the two re-earned coordinates (kit evidence stand-in)."""
    load_imported_callee_protocol(
        {
            "numpy.all": CalleeUniverseSupport.NUMPY_ALL,
            "numpy.dtype": CalleeUniverseSupport.NUMPY_DTYPE,
        }
    )


# ---------------------------------------------------------------------------
# Empty-by-construction
# ---------------------------------------------------------------------------


def test_protocol_empty_by_construction() -> None:
    assert recognize_authenticated_callee_identity("numpy.all") is None
    assert recognize_authenticated_callee_identity("numpy.dtype") is None
    source = (
        "import numpy as np\n"
        "\n"
        "def test_all(value):\n"
        "    return np.all(value)\n"
    )
    site = _call_site(source, attr="all")
    # Provenance still resolves the import identity…
    assert imported_call_identity(site) == "numpy.all"
    # …but without a loaded kit contract the universe stays loud.
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe(site=site) is None
    assert not BuiltinCalleeUniverseSugar.owns(site)


# ---------------------------------------------------------------------------
# Truthful twins — import-bound + protocol → green
# ---------------------------------------------------------------------------


def test_truthful_numpy_all_attr_under_protocol() -> None:
    _load_numpy_all_dtype_protocol()
    source = (
        "import numpy as np\n"
        "\n"
        "def test_all(value):\n"
        "    return np.all(value)\n"
    )
    site = _call_site(source, attr="all")
    assert imported_call_identity(site) == "numpy.all"
    assert CalleeUniverseRecognition.coordinate(site) == "numpy.all"
    assert (
        recognize_callee_universe("call:numpy.all", site=site)
        is CalleeUniverseSupport.NUMPY_ALL
    )
    assert BuiltinCalleeUniverseSugar.owns(site)
    built = build_node(
        site,
        filename="t.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(filename="t.py", catalog=default_catalog()),
    )
    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


def test_truthful_numpy_all_from_import_under_protocol() -> None:
    """from numpy import all; all(...) authenticates as numpy.all, not bare all."""
    _load_numpy_all_dtype_protocol()
    source = "from numpy import all\n\ndef test_all(value):\n    return all(value)\n"
    site = _call_site(source, name="all")
    assert imported_call_identity(site) == "numpy.all"
    assert CalleeUniverseRecognition.coordinate(site) == "numpy.all"
    assert (
        recognize_callee_universe(site=site) is CalleeUniverseSupport.NUMPY_ALL
    )


def test_truthful_numpy_dtype_attr_under_protocol() -> None:
    _load_numpy_all_dtype_protocol()
    source = (
        "import numpy as np\n"
        "\n"
        "def test_dtype(value):\n"
        "    return np.dtype(value)\n"
    )
    site = _call_site(source, attr="dtype")
    assert imported_call_identity(site) == "numpy.dtype"
    assert CalleeUniverseRecognition.coordinate(site) == "numpy.dtype"
    assert (
        recognize_callee_universe("call:numpy.dtype", site=site)
        is CalleeUniverseSupport.NUMPY_DTYPE
    )
    assert BuiltinCalleeUniverseSugar.owns(site)
    built = build_node(
        site,
        filename="t.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(filename="t.py", catalog=default_catalog()),
    )
    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


def test_truthful_numpy_dtype_from_import_under_protocol() -> None:
    _load_numpy_all_dtype_protocol()
    source = (
        "from numpy import dtype\n"
        "\n"
        "def test_dtype(value):\n"
        "    return dtype(value)\n"
    )
    site = _call_site(source, name="dtype")
    assert imported_call_identity(site) == "numpy.dtype"
    assert CalleeUniverseRecognition.coordinate(site) == "numpy.dtype"
    assert (
        recognize_callee_universe(site=site) is CalleeUniverseSupport.NUMPY_DTYPE
    )


# ---------------------------------------------------------------------------
# Lying twins — lookalike / shadow / wrong module MUST refuse even with protocol
# ---------------------------------------------------------------------------


_LYING_ALL_SOURCES = (
    # Wrong module aliased as np (logo spelling of leaf alone is not enough).
    (
        "import math as np\n"
        "\n"
        "def test_all(value):\n"
        "    return np.all(value)\n"
    ),
    # Parameter shadow of the import binding.
    (
        "import numpy as np\n"
        "\n"
        "def test_all(np, value):\n"
        "    return np.all(value)\n"
    ),
    # Later function-local rebind revokes the import warrant.
    (
        "import numpy as np\n"
        "\n"
        "def test_all(value):\n"
        "    result = np.all(value)\n"
        "    np = replacement\n"
        "    return result\n"
    ),
    # Unauthenticated FQN spelling without an import binding.
    (
        "def test_all(value):\n"
        "    return numpy.all(value)\n"
    ),
)


@pytest.mark.parametrize("source", _LYING_ALL_SOURCES)
def test_lying_numpy_all_refuses_even_with_protocol(source: str) -> None:
    _load_numpy_all_dtype_protocol()
    site = _call_site(source, attr="all")
    # Identity is None (shadow/FQN) or a non-numpy origin (math.all) — never
    # the authenticated numpy import binding.
    assert imported_call_identity(site) != "numpy.all"
    assert recognize_callee_universe("call:numpy.all", site=site) is None
    assert CalleeUniverseRecognition.coordinate(site) != "numpy.all"
    assert not BuiltinCalleeUniverseSugar.owns(site)


_LYING_DTYPE_SOURCES = (
    (
        "import struct as np\n"
        "\n"
        "def test_dtype(value):\n"
        "    return np.dtype(value)\n"
    ),
    (
        "import math as np\n"
        "\n"
        "def test_dtype(value):\n"
        "    return np.dtype(value)\n"
    ),
    (
        "import numpy as np\n"
        "\n"
        "def test_dtype(np, value):\n"
        "    return np.dtype(value)\n"
    ),
    (
        "import numpy as np\n"
        "\n"
        "def test_dtype(value):\n"
        "    result = np.dtype(value)\n"
        "    np = replacement\n"
        "    return result\n"
    ),
    (
        "def test_dtype(value):\n"
        "    return numpy.dtype(value)\n"
    ),
)


@pytest.mark.parametrize("source", _LYING_DTYPE_SOURCES)
def test_lying_numpy_dtype_refuses_even_with_protocol(source: str) -> None:
    _load_numpy_all_dtype_protocol()
    site = _call_site(source, attr="dtype")
    assert recognize_callee_universe("call:numpy.dtype", site=site) is None
    assert CalleeUniverseRecognition.coordinate(site) != "numpy.dtype"
    assert not BuiltinCalleeUniverseSugar.owns(site)


def test_logo_spelling_alone_never_authenticates() -> None:
    """Regression: Attribute leaf 'all'/'dtype' is not a logo Compare path."""
    _load_numpy_all_dtype_protocol()
    # Spelling-only Attribute chain without any import.
    for attr, target in (("all", "call:numpy.all"), ("dtype", "call:numpy.dtype")):
        source = (
            f"def test_x(value):\n"
            f"    return pretend.{attr}(value)\n"
        )
        site = _call_site(source, attr=attr)
        assert imported_call_identity(site) is None
        assert recognize_callee_universe(target, site=site) is None


def test_production_tables_carry_no_numpy_logo_keys() -> None:
    """Hard law: production recognition tables stay empty of vendor logos."""
    from sugar_lift_py_tests.recognition import callee_universe as mod

    for key in mod._IMPORTED_SUPPORT:
        assert not key.startswith("numpy."), key
        assert not key.startswith("np."), key
    # Overlay starts empty; only this process's loaders may fill it.
    clear_imported_callee_protocol()
    assert mod._PROTOCOL_IMPORTED_SUPPORT == {}
