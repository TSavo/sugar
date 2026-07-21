"""Tests for the hashed kit-manifest enrollment membrane (#5994, items 1/6).

No vendor spelling appears anywhere in this file's assertions about the
membrane's mechanics; the enrolled spellings are exercised only as literal
source text fed through the oracle, exactly as any other lift test does.
"""

import json
import tempfile

import pytest

from sugar_lift_py_tests.context_manager_contract import Expects, Suppresses
from sugar_lift_py_tests.manifest_membrane import (
    ManifestIntegrityError,
    contract_for_manager,
    default_community_manifest,
    load_manifest,
)


def _oracle_source_file(source: str):
    """Test door that honors the law: text enters only through the oracle
    (mirrors `sugar_source_tree`'s own `tests/conftest.py::oracle_source_file`
    — that fixture lives in a sibling package's test tree and is not
    importable here, so this is a narrow local mirror, not a new door)."""
    from sugar_source_tree.tree import SourceFile

    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".py", delete=False
    ) as handle:
        handle.write(source)
        path = handle.name
    return SourceFile.from_path(path)


def _with_manager_node(source: str):
    """Lift `source` (one function containing a single `with` statement) and
    return the with-item's manager (context_expr) node."""
    sf = _oracle_source_file(source)
    fn = next(sf.functions())
    with_stmt = fn.body[0]
    return with_stmt.items[0].context_expr


def test_committed_manifest_loads_and_hash_verifies():
    manifest = default_community_manifest()
    assert manifest.cid.startswith("blake3-512:")
    spellings = {row.spelling for row in manifest.rows}
    assert spellings == {
        "pytest.raises",
        "contextlib.suppress",
        "tm.assert_produces_warning",
    }


def test_tampered_manifest_refuses_loudly(tmp_path):
    committed = default_community_manifest()
    data = json.loads(committed.path.read_text(encoding="utf-8"))
    # Tamper with a row without recomputing the cid.
    data["rows"][0]["spelling"] = "not.the.real.spelling"
    tampered_path = tmp_path / "tampered.json"
    tampered_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ManifestIntegrityError):
        load_manifest(tampered_path)


def test_missing_fields_refuse_loudly(tmp_path):
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps({"rows": []}), encoding="utf-8")
    with pytest.raises(ManifestIntegrityError):
        load_manifest(bad_path)


def test_membrane_issues_expects_for_enrolled_raises():
    manifest = default_community_manifest()
    source = (
        "def f():\n"
        "    with pytest.raises(ValueError):\n"
        "        pass\n"
    )
    node = _with_manager_node(source)
    contract = contract_for_manager(manifest, node)
    assert isinstance(contract, Expects)
    assert contract.matcher.kind == "raise"
    assert contract.matcher.name == "ValueError"


def test_membrane_issues_suppresses_for_enrolled_suppress():
    manifest = default_community_manifest()
    source = (
        "def f():\n"
        "    with contextlib.suppress(KeyError):\n"
        "        pass\n"
    )
    node = _with_manager_node(source)
    contract = contract_for_manager(manifest, node)
    assert isinstance(contract, Suppresses)
    assert contract.matcher.kind == "raise"
    assert contract.matcher.name == "KeyError"


def test_unenrolled_manager_returns_none():
    manifest = default_community_manifest()
    source = (
        "def f():\n"
        "    with some_unenrolled_manager(ValueError):\n"
        "        pass\n"
    )
    node = _with_manager_node(source)
    assert contract_for_manager(manifest, node) is None


def test_bare_name_spelling_not_enrolled_returns_none():
    """A bare-Name callee spelling (`raises(...)`, not `pytest.raises(...)`)
    is a different dotted-path string and must not tail-match the enrolled
    `pytest.raises` row."""
    manifest = default_community_manifest()
    source = "def f():\n    with raises(ValueError):\n        pass\n"
    node = _with_manager_node(source)
    assert contract_for_manager(manifest, node) is None


def test_keyword_argument_manager_returns_none():
    manifest = default_community_manifest()
    source = (
        "def f():\n"
        "    with pytest.raises(ValueError, match='x'):\n"
        "        pass\n"
    )
    node = _with_manager_node(source)
    assert contract_for_manager(manifest, node) is None
