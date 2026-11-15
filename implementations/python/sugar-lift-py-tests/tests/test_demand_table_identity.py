"""A shared demand table is addressed by its preimage, not by where it lives.

THE DISCRIMINATING FACE, and the reason this file exists: moving a corpus to
another directory must produce the SAME key. A fixture keyed on a path is a
per-checkout cache wearing a CID, and it would silently stop being shared the
moment two workers had different checkouts -- which is thirteen environments
on this box today.

Every other input must move it: a source byte, path membership, the schema,
the producer's own source, the resolution configuration. Each pinned
separately, because a key that changed on all-or-nothing would hide which
input actually broke.

Mirrors `bin/sugarbin`'s `build_identity()` for the Rust binary -- authenticated
source matter in the content key, situational things in the cell path, "so a
docs-only commit cannot bust the shelf".
"""

from __future__ import annotations

import pathlib
import shutil

import pytest

from sugar_lift_py_tests.demand_table_identity import (

    CorpusManifestIdentityMismatch,
    corpus_manifest_digest_aliases,
    demand_table_identity,
    require_corpus_manifest_alias,
)

from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_SOURCE_ROOT = sugar_lift_py_tests_package_root() / "src"


def _corpus(root: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


_FILES = {
    "pkg/__init__.py": "",
    "pkg/mod.py": "def f(p):\n    with open(p) as handle:\n        return handle.read()\n",
}


def _identity(
    root: pathlib.Path,
    *,
    source_root: pathlib.Path = _SOURCE_ROOT,
    **kwargs,
):
    return demand_table_identity(
        root,
        sorted(root.rglob("*.py")),
        source_root=source_root,
        **kwargs,
    )


# -- the discriminating face: location is not identity ------------------------


def test_the_same_corpus_at_another_location_has_the_same_key(tmp_path) -> None:
    """THE face that proves the key was taken over the preimage.

    If this fails, the artifact is a per-checkout cache and cannot be shared --
    which defeats the entire reason for publishing it.
    """
    here = _corpus(tmp_path / "one" / "corpus", _FILES)
    there = tmp_path / "two" / "corpus"
    there.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(here, there)

    assert _identity(here).content_key == _identity(there).content_key


def test_a_deeper_relocation_still_has_the_same_key(tmp_path) -> None:
    """Depth is not identity either -- only the relative shape is."""
    here = _corpus(tmp_path / "a" / "corpus", _FILES)
    there = tmp_path / "x" / "y" / "z" / "corpus"
    there.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(here, there)

    assert _identity(here).content_key == _identity(there).content_key


# -- everything in the preimage must move the key -----------------------------


def test_a_changed_source_byte_changes_the_key(tmp_path) -> None:
    root = _corpus(tmp_path / "corpus", _FILES)
    before = _identity(root).content_key

    (root / "pkg" / "mod.py").write_text(
        _FILES["pkg/mod.py"].replace("handle.read()", "handle.readlines()"),
        encoding="utf-8",
    )

    assert _identity(root).content_key != before


def test_adding_a_file_changes_the_key(tmp_path) -> None:
    """Path MEMBERSHIP is part of the corpus, not just the bytes present."""
    root = _corpus(tmp_path / "corpus", _FILES)
    before = _identity(root).content_key

    (root / "pkg" / "extra.py").write_text("x = 1\n", encoding="utf-8")

    assert _identity(root).content_key != before


def test_renaming_a_file_changes_the_key(tmp_path) -> None:
    """Same bytes at a different RELATIVE path is a different corpus."""
    root = _corpus(tmp_path / "corpus", _FILES)
    before = _identity(root).content_key

    (root / "pkg" / "mod.py").rename(root / "pkg" / "renamed.py")

    assert _identity(root).content_key != before


def test_a_changed_resolution_config_changes_the_key(tmp_path) -> None:
    root = _corpus(tmp_path / "corpus", _FILES)

    assert _identity(root).content_key != _identity(root, config={"k": "v"}).content_key


def test_a_changed_schema_version_changes_the_key(tmp_path, monkeypatch) -> None:
    """A consumer holding an older-schema artifact must MISS, not decode it."""
    import sugar_lift_py_tests.demand_table_identity as module

    root = _corpus(tmp_path / "corpus", _FILES)
    before = _identity(root).content_key

    monkeypatch.setattr(module, "DEMAND_TABLE_SCHEMA_VERSION", "python-demand-table/v2")

    assert _identity(root).content_key != before


def test_a_changed_producer_source_changes_the_key(tmp_path) -> None:
    """A change to the code that builds the table changes the table."""
    root = _corpus(tmp_path / "corpus", _FILES)
    producer = tmp_path / "producer"
    shutil.copytree(_SOURCE_ROOT, producer)
    before = _identity(root, source_root=producer).content_key

    lift_rpc = producer / "sugar_lift_py_tests" / "lift_rpc.py"
    lift_rpc.write_text(
        lift_rpc.read_text(encoding="utf-8") + "\n# producer source mutation\n",
        encoding="utf-8",
    )

    assert _identity(root, source_root=producer).content_key != before


# -- the key is reproducible from its preimage alone --------------------------


def test_the_key_is_recomputable_from_the_preimage(tmp_path) -> None:
    """An identity whose preimage cannot re-derive it is an assertion, not an
    address. Any machine must reach the same key without this process."""
    from sugar_lift_python_source.canonical import cid_of_json

    identity = _identity(_corpus(tmp_path / "corpus", _FILES))

    assert cid_of_json(dict(identity.preimage())) == identity.content_key


# -- the measured law the key depends on --------------------------------------


# -- parser identity is authenticated content identity -----------------------


def test_the_parser_identity_is_in_the_preimage(tmp_path) -> None:
    import sys

    identity = _identity(_corpus(tmp_path / "corpus", _FILES))

    assert identity.parser_identity == (
        f"{sys.implementation.name}-{sys.version_info.major}."
        f"{sys.version_info.minor}"
    )
    assert identity.preimage()["parserIdentity"] == identity.parser_identity


def test_a_different_parser_identity_changes_the_content_key(
    tmp_path,
) -> None:
    """An undeclared 3.14 parser cannot share the authoritative 3.12 key."""
    import sugar_lift_py_tests.demand_table_identity as module

    root = _corpus(tmp_path / "corpus", _FILES)
    here = _identity(root).content_key

    original = module.parser_identity
    module.parser_identity = lambda: "cpython-3.14"
    try:
        elsewhere = _identity(root).content_key
    finally:
        module.parser_identity = original

    assert elsewhere != here


def test_the_runtime_authority_reason_is_recorded() -> None:
    from sugar_lift_py_tests import demand_table_identity as module

    doc = " ".join((module.__doc__ or "").split())

    assert "PARSER IDENTITY IS IN THE CONTENT KEY" in doc
    assert "CPython 3.12.13" in doc and "3.14.4" in doc
    assert "undeclared runtime" in doc


def test_the_reason_the_first_answer_was_wrong_is_recorded() -> None:
    """A key that mysteriously grew a field invites its own removal. The
    evidence travels with the correction."""
    from sugar_lift_py_tests import demand_table_identity as module

    # Normalized: the docstring wraps, and a phrase split across lines is
    # still the phrase. Asserting the wrapped form would pin the formatting
    # rather than the claim.
    doc = " ".join((module.__doc__ or "").split())

    assert "version-dependent node stream" in doc
    assert "answered the wrong question" in doc


def test_pandas_303_path_shape_digest_is_not_a_content_manifest_alias() -> None:
    """Artifact consumption refuses the circulating path-only SHA-256.

    Both accepted aliases are computed over one ordered manifest of relative
    path plus content CID.  The historical ``a223...`` value covered path
    shape only, so accepting it would make changed bytes look authenticated.
    """
    import importlib.metadata

    from sugar_source_tree.tree import SourceTree

    distribution = importlib.metadata.distribution("pandas")
    root = pathlib.Path(distribution.locate_file("pandas")).resolve()
    assert distribution.version == "3.0.3"

    aliases = corpus_manifest_digest_aliases(root, SourceTree(root).paths())

    assert aliases.file_count == 1421
    assert aliases.sha256 == (
        "sha256:0ee4e945d69e60941f74ad064215a44d9f02a0b23b081e2a507d893bdd22a938"
    )
    assert aliases.blake3_512 == (
        "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604ed"
        "a1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
    )
    require_corpus_manifest_alias(aliases, aliases.sha256)
    require_corpus_manifest_alias(aliases, aliases.blake3_512)
    with pytest.raises(CorpusManifestIdentityMismatch, match="not an alias"):
        require_corpus_manifest_alias(
            aliases,
            "sha256:a223a4499d0909f22190748b4aca9144e35a58fec31e84cb924e2c25fd3c03d0",
        )
