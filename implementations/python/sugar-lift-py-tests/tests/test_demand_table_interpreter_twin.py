"""Measured 3.12/3.14 demand-table output twin on one small corpus."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from sugar_lift_py_tests.authenticated_pytest import (
    authenticate_environment,
    interpreter_identity,
)
from sugar_lift_py_tests.lift_rpc import _preconstruction_demand_rows
from sugar_lift_python_source.canonical import blake3_512_of, cid_of_json
from sugar_source_tree.cpython_adapter import CPythonAstBackend

_SOURCE = """\
from contextlib import nullcontext

def render(value, width):
    with nullcontext(f"value={value:{width}}") as rendered:
        return rendered
"""

# Independently produced from base 964dbf95d under authenticated CPython
# 3.12.13 on Battleaxe and CPython 3.14.4 on the workstation. The receipts pin
# the decisive law, not merely its convenient conclusion: same corpus,
# different parser output, byte-identical demand table.
MEASURED_CORPUS_MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)
MEASURED_DEMAND_TABLE_OUTPUT_CIDS = {
    "cpython-3.12.13": (
        "blake3-512:171cb05a5903a2d929596d9ea33b35432c4f5721f37c5553d2b012063495ee18"
        "3b0e0281f23f3dbf9ceeadc4d1fb107163e78bfe4d570d457b4a0ae2867fe7fb"
    ),
    "cpython-3.14.4": (
        "blake3-512:171cb05a5903a2d929596d9ea33b35432c4f5721f37c5553d2b012063495ee18"
        "3b0e0281f23f3dbf9ceeadc4d1fb107163e78bfe4d570d457b4a0ae2867fe7fb"
    ),
}
MEASURED_PARSER_AST_CIDS = {
    "cpython-ast-cpython-3.12": (
        "blake3-512:9981672e8b2c342a55f1c6f9e063bb4df7ae79b705aebf5c8c13c351d0574cf"
        "bf632e8cfab087382857bdf2582e73e92e02e2d0ba9dc4ba0fd0ab68e64f66910"
    ),
    "cpython-ast-cpython-3.14": (
        "blake3-512:3bb9334b3359eeb822259f977144f1d05bc5ed5854efa92fd2cb28372a94c3d7"
        "f1ff3b249358ac7dfd87af98c013c114ab01060515b71c110d2d34514088ff96"
    ),
}


def test_measured_runtime_receipts_earn_parser_identity_removal() -> None:
    """Runtime leaves the key only because the authenticated twin matched."""
    assert set(MEASURED_DEMAND_TABLE_OUTPUT_CIDS) == {
        "cpython-3.12.13",
        "cpython-3.14.4",
    }
    assert len(set(MEASURED_PARSER_AST_CIDS.values())) == 2
    assert len(set(MEASURED_DEMAND_TABLE_OUTPUT_CIDS.values())) == 1


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
