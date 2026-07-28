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
from sugar_lift_py_tests.demand_table_identity import demand_table_identity
from sugar_source_tree.tree import SourceTree
from sugar_lift_py_tests.lift_rpc import _preconstruction_demand_rows
from sugar_lift_python_source.canonical import blake3_512_of, cid_of_json
from sugar_source_tree.cpython_adapter import CPythonAstBackend

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
MEASURED_DEMAND_TABLE_OUTPUT_CIDS = {
    "cpython-3.12.13": (
        "blake3-512:171cb05a5903a2d929596d9ea33b35432c4f5721f37c5553d2b012063495ee18"
        "3b0e0281f23f3dbf9ceeadc4d1fb107163e78bfe4d570d457b4a0ae2867fe7fb"
    ),
}
MEASURED_PARSER_AST_CIDS = {
    "cpython-ast-cpython-3.12": (
        "blake3-512:9981672e8b2c342a55f1c6f9e063bb4df7ae79b705aebf5c8c13c351d0574cf"
        "bf632e8cfab087382857bdf2582e73e92e02e2d0ba9dc4ba0fd0ab68e64f66910"
    ),
}
DECLARED_PANDAS_TABLE_CONTENT_KEY = (
    "blake3-512:0ce7c645a7525f1fe5189b808162b49d3fc3ba3d898bfb3d5086e0f295b8b8d"
    "263fe7f530a6aa34adb125615a21e69fdee249e0314bf199b8f43580375153ab0"
)


def test_runtime_derived_testimony_names_only_the_declared_authority() -> None:
    assert declared_interpreter_runtime() == "cpython-3.12.13"
    assert set(MEASURED_DEMAND_TABLE_OUTPUT_CIDS) == {"cpython-3.12.13"}
    assert set(MEASURED_PARSER_AST_CIDS) == {"cpython-ast-cpython-3.12"}


def test_pinned_corpus_table_key_is_minted_under_declared_parser() -> None:
    corpus = authenticated_pandas_corpus()
    source_root = Path(__file__).resolve().parents[1] / "src"
    identity = demand_table_identity(
        corpus.root,
        SourceTree(corpus.root).paths(),
        source_root=source_root,
    )

    assert identity.content_key == DECLARED_PANDAS_TABLE_CONTENT_KEY


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
    assert output_cid == MEASURED_DEMAND_TABLE_OUTPUT_CIDS[runtime_identity]
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
