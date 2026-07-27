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

# Independently produced under authenticated CPython 3.12.13 on Battleaxe and
# CPython 3.14.4 on the workstation. Both runs named the same pandas manifest
# CID and produced this exact three-row table CID.
MEASURED_312_314_OUTPUT_CID = (
    "blake3-512:171cb05a5903a2d929596d9ea33b35432c4f5721f37c5553d2b012063495ee18"
    "3b0e0281f23f3dbf9ceeadc4d1fb107163e78bfe4d570d457b4a0ae2867fe7fb"
)
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
    assert output_cid == MEASURED_312_314_OUTPUT_CID
    interpreter = interpreter_identity()
    parser_ast_cid = blake3_512_of(
        ast.dump(ast.parse(_SOURCE), include_attributes=False).encode("utf-8")
    )
    parser_identity = CPythonAstBackend().fingerprint()
    assert parser_ast_cid == MEASURED_PARSER_AST_CIDS[parser_identity]
    receipt = {
        "schema": "demand-table-interpreter-twin/v1",
        "python": f"{interpreter.implementation}-{interpreter.version}",
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
