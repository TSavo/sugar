"""Test-only driver for the sole preconstruction With resolution table."""

from types import MappingProxyType
from pathlib import Path
import shutil
import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerResolutionGapV1,
    ResolvedContractRefsV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
    _hash_json,
)
from sugar_lift_py_tests.lift_rpc import _preconstruction_demand_rows
from sugar_source_tree.tree import SourceFile


def _cid(fill: str) -> str:
    return "blake3-512:" + fill * 128


def source_file_with_preconstruction(path):
    isolated = Path(tempfile.mkdtemp(prefix="sugar-with-resolution-")) / path.name
    shutil.copyfile(path, isolated)
    path = isolated
    resolutions = {}
    for row in _preconstruction_demand_rows(path.parent):
        if row.get("kind") != "context-manager-demand":
            continue
        site = SourceFragmentCoordinateV1.decode(row["useSite"])
        preimage = {
            key: row[key]
            for key in ("useSite", "targetSymbol", "importSignature", "expectedKind")
        }
        resolutions[site] = ContextManagerResolutionGapV1(
            _hash_json(preimage),
            site,
            row["targetSymbol"],
            row["gapKind"] or "unresolved-symbol",
            (),
        )
    refs = ResolvedContractRefsV1(_cid("c"), _cid("t"), MappingProxyType(resolutions))
    return SourceFile(
        path_source(str(path)),
        construction_context=TreeConstructionContextV1(refs),
    )
