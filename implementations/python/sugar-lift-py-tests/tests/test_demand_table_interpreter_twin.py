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
    demand_table_identity,
    demand_table_identity_for_manifest,
)
from sugar_lift_py_tests.no_call_body_attribution import (
    shared_demand_table_content_key,
)
from sugar_source_tree.tree import SourceTree
from sugar_lift_py_tests.lift_rpc import _preconstruction_demand_rows
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


def test_shared_table_key_is_the_walked_corpus_key() -> None:
    """The key production asks for is the key a mint over the corpus states."""
    corpus = authenticated_pandas_corpus()
    source_root = sugar_lift_py_tests_package_root() / "src"
    identity = demand_table_identity(
        corpus.root,
        SourceTree(corpus.root).paths(),
        source_root=source_root,
    )

    assert identity.content_key == shared_demand_table_content_key()


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


def test_demand_table_output_interpreter_twin(tmp_path: Path) -> None:
    """Produce, content-address, and report the real table after corpus auth."""
    pandas, numpy, lift, manifest_cid = authenticate_environment()
    corpus = tmp_path / "small-demand-table-corpus"
    package = corpus / "sample"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "format_context.py").write_text(_SOURCE, encoding="utf-8")

    rows = _preconstruction_demand_rows(corpus)
    assert rows, "the acceptance corpus produced no demand-table rows"
    output_cid = cid_of_json(
        {"kind": "python-preconstruction-demand-table", "rows": rows}
    )
    interpreter = interpreter_identity()
    runtime_identity = f"{interpreter.implementation}-{interpreter.version}"
    assert manifest_cid == MEASURED_CORPUS_MANIFEST_CID
    assert output_cid == cid_of_json(
        {
            "kind": "python-preconstruction-demand-table",
            "rows": _preconstruction_demand_rows(corpus),
        }
    ), "the demand rows are not a function of the corpus"
    parser_ast_cid = blake3_512_of(
        ast.dump(ast.parse(_SOURCE), include_attributes=False).encode("utf-8")
    )
    parser_identity = CPythonAstBackend().fingerprint()
    assert parser_ast_cid == MEASURED_PARSER_AST_CIDS[parser_identity]
    receipt = {
        "schema": "demand-table-interpreter-twin/v1",
        "python": runtime_identity,
        "pythonExecutable": str(interpreter.executable),
        "parserIdentity": parser_identity,
        "parserAstCid": parser_ast_cid,
        "corpusManifestCid": manifest_cid,
        "pandas": pandas.version,
        "numpy": numpy.version,
        "liftPath": str(lift.loaded_from),
        "demandTableOutputCid": output_cid,
        "rows": len(rows),
    }
    print("DEMAND_TABLE_INTERPRETER_TWIN " + json.dumps(receipt, sort_keys=True))
