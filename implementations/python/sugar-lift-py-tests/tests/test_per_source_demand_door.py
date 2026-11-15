"""The With demand door resolves one source at a time, and is the one door.

Every reader of the With demand table asks about one source file. The
per-source door runs the With pass and the import join on the files that share
a source CID, on first demand, so one file costs one file. There is no
whole-corpus derivation beside it and no table installed in its place
(#7757 item 46).

Twins:
  truthful — every With item of a source has one undecided row, and asking
             about one file derives only that file;
  lying    — a use site the corpus does not contain fails closed.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from sugar_lift_python_source.source_oracle import path_source

from sugar_lift_py_tests import lift_rpc as lr
from sugar_lift_py_tests.context_manager_resolution import (
    UNDECIDED_GAP_KIND,
    ContractRefProtocolError,
    PerSourceResolutionsV1,
    resolutions_for_source,
)

_WITH_IMPORTED = (
    "from helpers import cm\n"
    "def f():\n"
    "    with cm():\n"
    "        pass\n"
)
_WITH_LOCAL = (
    "import threading\n"
    "lock = threading.Lock()\n"
    "def g():\n"
    "    with lock:\n"
    "        pass\n"
    "    with open('x') as handle:\n"
    "        return handle\n"
)


def _corpus(root: Path) -> Path:
    (root / "helpers.py").write_text(
        "from contextlib import contextmanager\n"
        "@contextmanager\n"
        "def cm():\n"
        "    yield\n",
        encoding="utf-8",
    )
    (root / "uses.py").write_text(_WITH_IMPORTED, encoding="utf-8")
    # Byte-identical twin of uses.py: one source CID, two paths.
    (root / "uses_again.py").write_text(_WITH_IMPORTED, encoding="utf-8")
    (root / "local.py").write_text(_WITH_LOCAL, encoding="utf-8")
    (root / "plain.py").write_text("x = 1\n", encoding="utf-8")
    return root


def _refs(root: Path):
    lr.clear_provisional_contract_refs_memo()
    return lr.provisional_contract_refs_from_demands(root)


def test_every_with_item_has_one_undecided_row(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    uses_cid = path_source(str(root / "uses.py"))[2]
    local_cid = path_source(str(root / "local.py"))[2]

    refs = _refs(root)
    assert isinstance(refs.by_use_site, PerSourceResolutionsV1)
    rows = dict(refs.by_use_site)
    # uses.py and its byte-identical twin share one source CID, so one row.
    assert sorted((site.source_cid, site.start_line) for site in rows) == sorted(
        [(uses_cid, 3), (local_cid, 4), (local_cid, 6)]
    )
    assert {resolution.kind for resolution in rows.values()} == {UNDECIDED_GAP_KIND}
    for use_site, resolution in rows.items():
        assert refs.require(use_site) == resolution


def test_one_file_derives_one_file(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    local_cid = path_source(str(root / "local.py"))[2]

    refs = _refs(root)
    assert refs.by_use_site.derived_source_cids() == ()

    local_sites = set(resolutions_for_source(refs.by_use_site, local_cid))
    assert len(local_sites) == 2
    for site in local_sites:
        assert refs.require(site).kind == UNDECIDED_GAP_KIND

    assert refs.by_use_site.derived_source_cids() == (local_cid,)


def test_no_whole_corpus_derivation_or_install_remains() -> None:
    """The per-source door is the only derivation; nothing installs over it."""
    for name in (
        "_preconstruction_demand_rows",
        "_context_manager_demand_rows",
        "_call_use_rows",
        "provisional_contract_refs_from_demand_rows",
        "install_provisional_contract_refs",
        "preconstruction_walk_count",
    ):
        assert not hasattr(lr, name), name


def test_identity_names_the_corpus_not_the_question(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    before = _refs(root).table_cid
    assert _refs(root).table_cid == before

    (root / "plain.py").write_text("x = 2\n", encoding="utf-8")
    assert _refs(root).table_cid != before


def test_site_outside_the_corpus_fails_closed(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    refs = _refs(root)
    real = next(iter(dict(refs.by_use_site)))

    forged_source = dataclasses.replace(real, source_cid="blake3:" + "0" * 64)
    with pytest.raises(ContractRefProtocolError):
        refs.require(forged_source)

    # Right source, a span no With item occupies.
    forged_span = dataclasses.replace(real, start_line=real.start_line + 400)
    with pytest.raises(ContractRefProtocolError):
        refs.require(forged_span)

    assert resolutions_for_source(refs.by_use_site, forged_source.source_cid) == {}
