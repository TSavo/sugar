"""Demand-table testimony minted on the declared CPython 3.12.13 runtime."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from sugar_lift_py_tests.authenticated_pytest import (

    authenticate_environment,
    authenticated_pandas_corpus,
    declared_interpreter_runtime,
    interpreter_identity,
)
from sugar_lift_py_tests.demand_table_identity import (
    demand_table_identity_for_manifest,
    semantic_identity_for_corpus,
)
from sugar_lift_python_source.canonical import blake3_512_of, cid_of_json
from sugar_source_tree.cpython_adapter import CPythonAstBackend

from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_SOURCE = """\
from contextlib import nullcontext

def render(value, width):
    with nullcontext(f"value={value:{width}}") as rendered:
        return rendered
"""

# Produced under authenticated CPython 3.12.13 on Battleaxe. CPython 3.14.4 is
# not a declared cell, so its historical workstation receipt is deliberately
# not accepted as managed testimony.
MEASURED_CORPUS_MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)
MEASURED_PARSER_AST_CIDS = {
    "cpython-ast-cpython-3.12": (
        "blake3-512:9981672e8b2c342a55f1c6f9e063bb4df7ae79b705aebf5c8c13c351d0574cf"
        "bf632e8cfab087382857bdf2582e73e92e02e2d0ba9dc4ba0fd0ab68e64f66910"
    ),
}
_PRODUCER_MODULES = ("lift_rpc.py", "context_manager_resolution.py", "import_binding.py")


def test_runtime_derived_testimony_names_only_the_declared_authority() -> None:
    assert declared_interpreter_runtime() == "cpython-3.12.13"
    assert set(MEASURED_PARSER_AST_CIDS) == {"cpython-ast-cpython-3.12"}


def test_walked_corpus_key_is_the_authenticated_manifest_key() -> None:
    """The key a walk over the corpus states is the authenticated manifest's."""
    corpus = authenticated_pandas_corpus()
    source_root = sugar_lift_py_tests_package_root() / "src"
    walked = semantic_identity_for_corpus(corpus.root, source_root=source_root)
    stated = demand_table_identity_for_manifest(
        corpus.manifest_cid, corpus.file_count, source_root=source_root
    )

    assert walked.content_key == stated.content_key


def _producer_source(root: Path, edits: dict[str, str] | None = None) -> Path:
    package = root / "sugar_lift_py_tests"
    package.mkdir(parents=True)
    for name in _PRODUCER_MODULES:
        text = (edits or {}).get(name, f"# producer {name}\n")
        (package / name).write_text(text, encoding="utf-8")
    return root


def _key(source_root: Path) -> str:
    return demand_table_identity_for_manifest(
        MEASURED_CORPUS_MANIFEST_CID, 1421, source_root=source_root
    ).content_key


def test_key_is_equal_for_equal_producer_content(tmp_path: Path) -> None:
    assert _key(_producer_source(tmp_path / "one")) == _key(
        _producer_source(tmp_path / "two")
    )


def test_key_moves_when_any_producer_source_file_changes(tmp_path: Path) -> None:
    base = _key(_producer_source(tmp_path / "base"))
    for name in _PRODUCER_MODULES:
        edited = _producer_source(
            tmp_path / f"edited-{name}", {name: f"# producer {name}\n# edited\n"}
        )
        assert _key(edited) != base, name


def test_key_moves_when_a_producer_source_file_disappears(tmp_path: Path) -> None:
    source = _producer_source(tmp_path / "source")
    base = _key(source)
    (source / "sugar_lift_py_tests" / "import_binding.py").unlink()
    assert _key(source) != base
