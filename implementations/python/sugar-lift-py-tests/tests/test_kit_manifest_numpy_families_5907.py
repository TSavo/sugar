"""#5907: the real, checked-in kit manifest reaches real corpus mint children.

#5908 wired a process-level ``SUGAR_KIT_MANIFEST`` loader into
``corpus_fatal_triage._child_payload``, proven with an inline/tmp-path
manifest for one coordinate (``numpy.issubdtype``). This module is the next
increment: it points that loader at the actual repo-tracked manifest,
``kit_manifests/numpy_families_5907.json``, which declares all five
coordinates re-earned across #5902 (``numpy.all``, ``numpy.dtype``), #5903
(``numpy.issubdtype``), #5904 (``numpy.isnat``), and #5905 (``numpy.isnan``).

Each test mints the exact same minimal source through
``corpus_fatal_triage._child_payload`` twice — once with
``SUGAR_KIT_MANIFEST`` unset (the empty-by-construction default) and once
pointed at the real manifest file on disk — and asserts:

1. Without the manifest, every one of the five families stays in
   ``unclassified_rows`` (loud, FactoryWalk-unclassified).
2. With the manifest, all five authenticate (row count 0) and the child's
   testimony carries provenance (path + sha256 of the *real* file, not an
   inline stand-in).
3. A lying twin (``import math as np`` lookalike alias) for one of the
   families stays loud even with the real manifest loaded — the manifest
   authenticates identity via import provenance, not spelling.

If the checked-in manifest is ever deleted, edited to drop a coordinate, or
the loader wiring from #5908 regresses, the "with manifest" assertions here
fail loudly — this is the fails-before/passes-after receipt for the
increment, using the actual file that ships in the repo instead of a
throwaway tmp fixture.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from corpus_fatal_triage import _child_payload  # noqa: E402

from sugar_lift_py_tests.recognition.kit_manifest import (  # noqa: E402
    KIT_MANIFEST_ENV_VAR,
    clear_all_kit_protocols,
)

MANIFEST_PATH = (
    Path(__file__).resolve().parents[1]
    / "kit_manifests"
    / "numpy_families_5907.json"
)

# (family label, truthful source, ast_kind expected in unclassified_rows)
FAMILIES = [
    (
        "numpy.all",
        "import numpy as np\n\ndef test_all(value):\n    assert np.all(value)\n",
        "call:numpy.all",
    ),
    (
        "numpy.dtype",
        "import numpy as np\n\ndef test_dtype(value):\n"
        "    assert np.dtype(value) == np.dtype(value)\n",
        "call:numpy.dtype",
    ),
    (
        "numpy.issubdtype",
        "import numpy as np\n\ndef test_issubdtype(left, right):\n"
        "    assert np.issubdtype(left, right)\n",
        "call:numpy.issubdtype",
    ),
    (
        "numpy.isnat",
        "import numpy as np\n\ndef test_isnat(dtype):\n"
        "    value = np.array('NaT', dtype=dtype)\n"
        "    assert np.isnat(value)\n",
        "call:numpy.isnat",
    ),
    (
        "numpy.isnan",
        "import numpy as np\n\ndef test_isnan(value):\n"
        "    assert np.isnan(value)\n",
        "call:numpy.isnan",
    ),
]


@pytest.fixture(autouse=True)
def _isolate_kit_protocols(monkeypatch):
    monkeypatch.delenv(KIT_MANIFEST_ENV_VAR, raising=False)
    clear_all_kit_protocols()
    yield
    clear_all_kit_protocols()


def test_manifest_file_exists_and_declares_five_coordinates() -> None:
    import json

    assert MANIFEST_PATH.is_file()
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert document["imported_callee"] == {
        "numpy.all": "NUMPY_ALL",
        "numpy.dtype": "NUMPY_DTYPE",
        "numpy.issubdtype": "NUMPY_ISSUBDTYPE",
        "numpy.isnat": "NUMPY_ISNAT",
        "numpy.isnan": "NUMPY_ISNAN",
    }


@pytest.mark.parametrize("family,source,ast_kind", FAMILIES)
def test_family_stays_loud_without_manifest(
    tmp_path: Path, family: str, source: str, ast_kind: str
) -> None:
    src = tmp_path / "no_contract.py"
    src.write_text(source, encoding="utf-8")

    testimony, returncode = _child_payload(src, f"demo/{family}/no_contract.py")

    assert returncode == 0
    assert testimony["outcome"] == "completed"
    assert testimony["kit_manifest"] is None
    matching = [
        row
        for row in testimony["unclassified_rows"]
        if row.get("ast_kind") == ast_kind
    ]
    assert matching, f"{family}: expected loud {ast_kind!r} row with no manifest"


@pytest.mark.parametrize("family,source,ast_kind", FAMILIES)
def test_family_authenticates_with_real_manifest(
    tmp_path: Path, monkeypatch, family: str, source: str, ast_kind: str
) -> None:
    monkeypatch.setenv(KIT_MANIFEST_ENV_VAR, str(MANIFEST_PATH))
    src = tmp_path / "with_contract.py"
    src.write_text(source, encoding="utf-8")

    testimony, returncode = _child_payload(src, f"demo/{family}/with_contract.py")

    assert returncode == 0
    assert testimony["outcome"] == "completed"
    matching = [
        row
        for row in testimony["unclassified_rows"]
        if row.get("ast_kind") == ast_kind
    ]
    assert matching == [], f"{family}: still loud with real manifest loaded"

    provenance = testimony["kit_manifest"]
    assert provenance is not None
    assert provenance["path"] == str(MANIFEST_PATH)
    assert provenance["loaded_counts"] == {"imported_callee": 5}

    import hashlib

    expected_sha256 = hashlib.sha256(
        MANIFEST_PATH.read_text(encoding="utf-8").encode("utf-8")
    ).hexdigest()
    assert provenance["sha256"] == expected_sha256


def test_lying_lookalike_alias_stays_loud_under_real_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    """``import math as np`` must not borrow the numpy.isnan coordinate.

    Proves the real manifest authenticates identity (import provenance),
    not the bare attribute spelling ``.isnan`` — a loaded coordinate does
    not make a lookalike module authenticate.
    """

    monkeypatch.setenv(KIT_MANIFEST_ENV_VAR, str(MANIFEST_PATH))
    src = tmp_path / "lookalike.py"
    src.write_text(
        "import math as np\n\ndef test_isnan(value):\n"
        "    assert np.isnan(value)\n",
        encoding="utf-8",
    )

    testimony, returncode = _child_payload(src, "demo/lookalike.py")

    assert returncode == 0
    assert testimony["outcome"] == "completed"
    assert not [
        row
        for row in testimony["unclassified_rows"]
        if row.get("ast_kind") == "call:numpy.isnan"
    ]
    assert any(
        row.get("ast_kind") == "call:math.isnan"
        for row in testimony["unclassified_rows"]
    )
    assert testimony["kit_manifest"] is not None
