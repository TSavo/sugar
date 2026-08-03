"""importorskip module facts require authenticated import bindings in state.

Truthful: ``import pytest`` / ``from pytest import importorskip`` mints the
module availability binding. Lying: same call spelling bound to a local def,
``pytest = object()``, or ``import not_pytest as pytest`` must not mint.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.import_binding import _ImportDef, _Pass, _NON_IMPORT
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _final_state(tmp_path: Path, text: str) -> dict[str, list]:
    path = tmp_path / "module.py"
    path.write_text(text, encoding="utf-8")
    source, _, source_cid = path_source(str(path))
    module = SourceFile((source, str(path), source_cid)).root
    runner = _Pass(
        source_cid=source_cid,
        module_name="module",
        module_is_package=False,
        module_identities={},
    )
    state = runner.statements(module.body, {}, module)
    out: dict[str, list] = {}
    for name, reaching in state.items():
        items = []
        for value in reaching:
            if isinstance(value, _ImportDef):
                items.append(("import", value.target_symbol))
            else:
                items.append(value)
        out[name] = items
    return out


def test_truthful_pytest_attribute_importorskip_mints_module(tmp_path: Path) -> None:
    state = _final_state(
        tmp_path,
        'import pytest\nnp = pytest.importorskip("numpy")\n',
    )
    assert state["pytest"] == [("import", "python:pytest")]
    assert state["np"] == [("import", "python:numpy")]


def test_truthful_from_import_importorskip_mints_module(tmp_path: Path) -> None:
    state = _final_state(
        tmp_path,
        'from pytest import importorskip\nnp = importorskip("numpy")\n',
    )
    assert state["importorskip"] == [("import", "python:pytest.importorskip")]
    assert state["np"] == [("import", "python:numpy")]


def test_lying_local_def_importorskip_does_not_mint(tmp_path: Path) -> None:
    state = _final_state(
        tmp_path,
        "def importorskip(m):\n" "    return m\n" 'np = importorskip("numpy")\n',
    )
    assert state["np"] == [_NON_IMPORT]
    assert not any(
        isinstance(item, tuple) and item[0] == "import" and item[1] == "python:numpy"
        for item in state["np"]
    )


def test_lying_pytest_object_shadow_does_not_mint(tmp_path: Path) -> None:
    state = _final_state(
        tmp_path,
        'pytest = object()\nnp = pytest.importorskip("numpy")\n',
    )
    assert state["pytest"] == [_NON_IMPORT]
    assert state["np"] == [_NON_IMPORT]


def test_lying_aliased_foreign_module_does_not_mint(tmp_path: Path) -> None:
    """Same local spelling ``pytest``, bound to ``not_pytest`` — not admitted."""
    state = _final_state(
        tmp_path,
        'import not_pytest as pytest\nnp = pytest.importorskip("numpy")\n',
    )
    assert state["pytest"] == [("import", "python:not_pytest")]
    assert state["np"] == [_NON_IMPORT]
