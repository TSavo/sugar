"""``with m(...)`` where ``m`` is assigned an import value per selection arm.

Reproducer: ``pandas/_testing/_io.py`` binds ``compress_method`` to
``gzip.GzipFile`` / ``bz2.BZ2File`` / ... in an if/elif chain and uses it once
as the manager callee.  The head is reduced as any expression is: the name
reads the value its arm bound, and each arm's call is an imported call no
proof here answers, so the manager is the undecided manager (#7757).  The
partitioned citation keeps its own minting law.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    ContractRefProtocolError,
    PartitionedOpaqueCitedContextManagerRefV1,
    mint_partitioned_opaque_cited_context_manager_ref,
)
from sugar_lift_py_tests.corpus_pin import pin_corpus
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
    WithReducedManagerSugar,
)
from sugar_source_tree.nodes import With
from sugar_source_tree.reporter import CollectingReporter

PARTITION = (
    "import bz2\n"
    "import gzip\n"
    "\n"
    "def f(p, kind):\n"
    "    if kind == 'gzip':\n"
    "        compress_method = gzip.GzipFile\n"
    "    elif kind == 'bz2':\n"
    "        compress_method = bz2.BZ2File\n"
    "    else:\n"
    "        raise ValueError(kind)\n"
    "    with compress_method(p, mode='wb') as fh:\n"
    "        return fh\n"
)


def _corpus(tmp_path: Path, **files: str) -> Path:
    root = tmp_path / "c"
    root.mkdir()
    for name, source in files.items():
        (root / name).write_text(source, encoding="utf-8")
    (tmp_path / "c.identity.json").write_text(
        json.dumps({"distribution": "tiny-corpus", "version": "0.0.1"}),
        encoding="utf-8",
    )
    pin_corpus(root, distribution="tiny-corpus", version="0.0.1")
    return root


def _open(root: Path, name: str):
    return open_source_file_for_construction(
        root / name,
        root=root,
        reporter=CollectingReporter(),
        source_workspace_root=root,
    )


def test_partition_of_imported_members_is_the_heads_reduced_value(
    tmp_path: Path,
) -> None:
    root = _corpus(tmp_path, **{"part.py": PARTITION})
    source_file = _open(root, "part.py")
    with_node = next(n for n in source_file.nodes() if isinstance(n, With))
    assert isinstance(with_node.sugar(), WithReducedManagerSugar)


def test_mint_refuses_lies() -> None:
    site = _site(1)
    with pytest.raises(ContractRefProtocolError, match="names no member"):
        mint_partitioned_opaque_cited_context_manager_ref(use_site=site, members=())
    with pytest.raises(ContractRefProtocolError, match="authenticated opaque-cited"):
        mint_partitioned_opaque_cited_context_manager_ref(
            use_site=site, members=(object(),)  # type: ignore[arg-type]
        )
    # The public constructor cannot mint authority.
    with pytest.raises(ContractRefProtocolError, match="lacks producer authority"):
        PartitionedOpaqueCitedContextManagerRefV1(site, (), "blake3-512:" + "00" * 64)


def _site(line: int):
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )

    return SourceFragmentCoordinateV1("blake3-512:" + "ab" * 64, line, 0, line, 10)
