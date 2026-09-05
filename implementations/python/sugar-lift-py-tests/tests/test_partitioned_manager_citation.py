"""``with m(...)`` where ``m`` is assigned an import value per selection arm.

Reproducer: ``pandas/_testing/_io.py`` binds ``compress_method`` to
``gzip.GzipFile`` / ``bz2.BZ2File`` / ... in an if/elif chain and uses it once
as the manager callee. The call has no import receipt (its callee is a local
Name), so the demand table left it ``runtime-selected`` and ``With`` panicked.

Law under test: when nothing but the assignment arms binds the callee name in
the function, the reaching value IS the arms; each arm derives through the
ordinary import door, and a partition whose members are all cited by the
population membrane is one cited partition. Any other shape stays a loud typed
gap that names the arm -- never ``runtime-selected``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerResolutionGapV1,
    ContractRefProtocolError,
    OpaqueCitedContextManagerRefV1,
    PartitionedOpaqueCitedContextManagerRefV1,
    mint_partitioned_opaque_cited_context_manager_ref,
)
from sugar_lift_py_tests.corpus_pin import pin_corpus
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.sugar.with_opaque_cited_manager_sugar import (
    WithOpaqueCitedManagerSugar,
)
from sugar_source_tree.binding_state import constructed_value_cid_v2
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
        distribution="tiny-corpus",
        source_workspace_root=root,
    )


def _with_resolution(source_file):
    with_node = next(n for n in source_file.nodes() if isinstance(n, With))
    context = source_file.root.unit.construction_context
    refs = context.source_derived_contract_refs
    (site,) = [k for k in refs if k.start_line == with_node.line_col_span().start_line]
    return with_node, refs[site]


def test_partition_of_cited_members_constructs(tmp_path: Path) -> None:
    """Truthful twin: both arms cited off-population → one cited partition."""
    root = _corpus(tmp_path, **{"part.py": PARTITION})
    source_file = _open(root, "part.py")
    with_node, ref = _with_resolution(source_file)

    assert isinstance(ref, PartitionedOpaqueCitedContextManagerRefV1)
    assert [m.target_name for m in ref.members] == ["python:gzip.GzipFile", "python:bz2.BZ2File"]
    assert [m.use_site.start_line for m in ref.members] == [6, 8]
    for member in ref.members:
        assert isinstance(member, OpaqueCitedContextManagerRefV1)
        assert member.roster.resolution_kind == "call-target-off-population"
    with pytest.raises(ContractRefProtocolError, match="no enter/exit semantics"):
        _ = ref.semantics

    sugar = with_node.sugar()
    assert isinstance(sugar, WithOpaqueCitedManagerSugar)
    assert sugar.contract_ref is ref
    # The constructed value must canonicalize: the ref is frozen data plus the
    # producer authority category (#7422), never a bare object.
    assert constructed_value_cid_v2(sugar).startswith("blake3-512:")


def test_arm_that_is_not_an_import_value_stays_loud(tmp_path: Path) -> None:
    """Lying twin: one arm bound to a local helper is not a cited member."""
    source = PARTITION.replace(
        "        compress_method = bz2.BZ2File\n",
        "        compress_method = helper\n",
    ).replace("def f(p, kind):", "def helper(p, mode):\n    return p\n\ndef f(p, kind):")
    root = _corpus(tmp_path, **{"lying.py": source})
    source_file = _open(root, "lying.py")
    with_node, ref = _with_resolution(source_file)

    assert isinstance(ref, ContextManagerResolutionGapV1)
    assert ref.kind == "partition-member-unauthenticated"
    assert "not authenticated import values" in (ref.detail or "")
    with pytest.raises(Exception, match="partition-member-unauthenticated"):
        with_node.sugar()


def test_name_rebound_elsewhere_is_not_a_partition(tmp_path: Path) -> None:
    """A loop target rebinding the callee means the arms are not its whole value."""
    source = PARTITION.replace(
        "    with compress_method(p, mode='wb') as fh:\n",
        "    for compress_method in (gzip.GzipFile,):\n        pass\n"
        "    with compress_method(p, mode='wb') as fh:\n",
    )
    root = _corpus(tmp_path, **{"rebound.py": source})
    source_file = _open(root, "rebound.py")
    _with_node, ref = _with_resolution(source_file)

    assert isinstance(ref, ContextManagerResolutionGapV1)
    assert ref.kind == "partition-member-unauthenticated"
    assert "also bound by For@" in (ref.detail or "")


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
