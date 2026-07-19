"""#5907: a declared kit manifest reaches the real corpus mint child process.

Prior state: ``load_imported_callee_protocol`` / ``load_call_shape_protocol`` /
``load_fixture_protocol`` (#5618, proven per-family in #5902-#5905) only ever
loaded in-memory inside a test. Nothing wired them into
``corpus_fatal_triage.py``'s mint path, so no real corpus row ever saw a
loaded contract — every re-earned family stayed loud in the corpus even
though its recognizer was correct in principle.

This module exercises ``_child_payload`` — the exact function the real
corpus-mint subprocess runs per file (see ``_run_child`` / ``_run_parent``'s
``subprocess.run`` call) — with ``SUGAR_KIT_MANIFEST`` toggled, proving:

1. Empty-by-construction: no manifest declared ⇒ the callee-universe gap for
   ``numpy.issubdtype`` stays in the child's unclassified rows (loud).
2. Declared contract ⇒ that exact row disappears from the unclassified set
   (authenticates) and the child testimony carries kit-manifest provenance
   (path + sha256) traceable to the manifest file, not an ambient dict.
3. Lying twins (parameter shadow, late rebind, ``import math as np`` lookalike,
   bare FQN without import) still leave the row unclassified even with the
   real coordinate loaded — a loaded contract authenticates identity, not
   spelling.

Reverting the manifest wiring in ``corpus_fatal_triage.py`` (or the loader
module) makes case 2 fail: the row would stay unclassified even with a
manifest declared. That is the fails-before / passes-after proof.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from corpus_fatal_triage import _child_payload  # noqa: E402

from sugar_lift_py_tests.recognition.kit_manifest import (  # noqa: E402
    KIT_MANIFEST_ENV_VAR,
    KitManifestError,
    clear_all_kit_protocols,
    load_kit_manifest_text,
)


@pytest.fixture(autouse=True)
def _isolate_kit_protocols(monkeypatch):
    monkeypatch.delenv(KIT_MANIFEST_ENV_VAR, raising=False)
    clear_all_kit_protocols()
    yield
    clear_all_kit_protocols()


def _unclassified_issubdtype_rows(testimony: dict) -> list[dict]:
    return [
        row
        for row in testimony["unclassified_rows"]
        if row.get("ast_kind") == "call:numpy.issubdtype"
    ]




def _write_manifest(tmp_path: Path, document: dict) -> Path:
    manifest_path = tmp_path / "kit_manifest.json"
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    return manifest_path


_TRUTHFUL_SOURCE = (
    "import numpy as np\n"
    "\n"
    "def test_dtype(left, right):\n"
    "    assert np.issubdtype(left, right)\n"
)

_ISSUBDTYPE_MANIFEST = {"imported_callee": {"numpy.issubdtype": "NUMPY_ISSUBDTYPE"}}


def test_mint_with_no_manifest_leaves_row_loud(tmp_path: Path) -> None:
    """Empty-by-construction: no SUGAR_KIT_MANIFEST ⇒ row stays unclassified."""

    source = tmp_path / "no_contract.py"
    source.write_text(_TRUTHFUL_SOURCE, encoding="utf-8")

    testimony, returncode = _child_payload(source, "demo/no_contract.py")

    assert returncode == 0
    assert testimony["outcome"] == "completed"
    assert testimony["kit_manifest"] is None
    assert len(_unclassified_issubdtype_rows(testimony)) == 1


def test_mint_with_declared_manifest_authenticates_row(
    tmp_path: Path, monkeypatch
) -> None:
    """Declared contract ⇒ real mint child authenticates the coordinate."""

    manifest_path = _write_manifest(tmp_path, _ISSUBDTYPE_MANIFEST)
    monkeypatch.setenv(KIT_MANIFEST_ENV_VAR, str(manifest_path))
    source = tmp_path / "with_contract.py"
    source.write_text(_TRUTHFUL_SOURCE, encoding="utf-8")

    testimony, returncode = _child_payload(source, "demo/with_contract.py")

    assert returncode == 0
    assert testimony["outcome"] == "completed"
    assert _unclassified_issubdtype_rows(testimony) == []
    manifest_testimony = testimony["kit_manifest"]
    assert manifest_testimony is not None
    assert manifest_testimony["path"] == str(manifest_path)
    assert manifest_testimony["loaded_counts"] == {"imported_callee": 1}
    import hashlib

    expected_sha256 = hashlib.sha256(
        manifest_path.read_text(encoding="utf-8").encode("utf-8")
    ).hexdigest()
    assert manifest_testimony["sha256"] == expected_sha256


def _mint_with_manifest(tmp_path: Path, monkeypatch, source_text: str, name: str):
    manifest_path = _write_manifest(tmp_path, _ISSUBDTYPE_MANIFEST)
    monkeypatch.setenv(KIT_MANIFEST_ENV_VAR, str(manifest_path))
    source = tmp_path / name
    source.write_text(source_text, encoding="utf-8")
    return _child_payload(source, f"demo/{name}")


def test_lying_parameter_shadow_stays_loud_under_loaded_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    """Parameter shadow revokes the import warrant; row stays unclassified."""

    testimony, returncode = _mint_with_manifest(
        tmp_path,
        monkeypatch,
        "import numpy as np\n"
        "\n"
        "def test_dtype(np, left, right):\n"
        "    assert np.issubdtype(left, right)\n",
        "shadow.py",
    )
    assert returncode == 0
    assert testimony["outcome"] == "completed"
    assert len(_unclassified_issubdtype_rows(testimony)) == 1
    assert testimony["kit_manifest"] is not None


def test_lying_late_rebind_stays_loud_under_loaded_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    """A later rebind of the import name revokes the warrant retroactively."""

    testimony, returncode = _mint_with_manifest(
        tmp_path,
        monkeypatch,
        "import numpy as np\n"
        "\n"
        "def test_dtype(left, right):\n"
        "    assert np.issubdtype(left, right)\n"
        "    np = replacement\n",
        "rebind.py",
    )
    assert returncode == 0
    assert testimony["outcome"] == "completed"
    assert len(_unclassified_issubdtype_rows(testimony)) == 1
    assert testimony["kit_manifest"] is not None


def test_lying_lookalike_module_alias_stays_loud_under_loaded_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    """``import math as np`` is not numpy even though the loaded key is generic.

    The site resolves to ``math.issubdtype`` (a different, unloaded
    coordinate) — never to ``numpy.issubdtype``. No row is ever labelled
    with the authenticated coordinate; the real one (``math.issubdtype``)
    stays unclassified instead.
    """

    testimony, returncode = _mint_with_manifest(
        tmp_path,
        monkeypatch,
        "import math as np\n"
        "\n"
        "def test_dtype(left, right):\n"
        "    assert np.issubdtype(left, right)\n",
        "lookalike.py",
    )
    assert returncode == 0
    assert testimony["outcome"] == "completed"
    assert _unclassified_issubdtype_rows(testimony) == []
    assert any(
        row.get("ast_kind") == "call:math.issubdtype"
        for row in testimony["unclassified_rows"]
    )
    assert testimony["kit_manifest"] is not None


def test_lying_bare_fqn_without_import_stays_loud_under_loaded_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    """A bare ``numpy.issubdtype`` spelling with no import binds nothing.

    Provenance requires an import/source binding, never spelling alone — an
    unbound bare name is a harder loud outcome (FactoryPanic on the unbound
    name), not a quiet unclassified row, but it is still refusal, never
    success.
    """

    testimony, returncode = _mint_with_manifest(
        tmp_path,
        monkeypatch,
        "def test_dtype(left, right):\n"
        "    assert numpy.issubdtype(left, right)\n",
        "bare_fqn.py",
    )
    assert returncode == 3
    assert testimony["outcome"] == "factory-panic"
    assert testimony["kit_manifest"] is not None


def test_manifest_with_unknown_coordinate_fails_loudly(tmp_path: Path) -> None:
    """A manifest naming an unrecognized enum member errors, never drops silently."""

    with pytest.raises(KitManifestError):
        load_kit_manifest_text(
            json.dumps({"imported_callee": {"numpy.issubdtype": "NOT_A_REAL_SHAPE"}}),
            source="inline",
        )


def test_manifest_loader_installs_nothing_when_uninvoked() -> None:
    """Importing the loader module alone must not populate any protocol table.

    The loader is evidence (a file the caller names), never ambient
    configuration — merely importing ``kit_manifest`` must not be equivalent
    to loading a contract. (The docstring shows an example schema with
    vendor names for documentation purposes only; those strings never reach
    a production dict except by an explicit ``load_kit_manifest_*`` call
    with an actual file, which the tests above exercise.)
    """

    from sugar_lift_py_tests.recognition.callee_universe import (
        recognize_authenticated_callee_identity,
    )

    assert recognize_authenticated_callee_identity("numpy.issubdtype") is None
