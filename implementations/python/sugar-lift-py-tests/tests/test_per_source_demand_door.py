"""The provisional demand door resolves one source at a time.

Every reader of the provisional table asks about one source file. Deriving the
whole corpus before the first question made a one-file run cost the corpus.
The per-source door runs the same passes and the same join on the files that
share a source CID, on first demand, so one file costs one file.

Twins:
  truthful — per-source answers equal the whole-table answers entry for entry,
             and asking about one file derives only that file;
  lying    — a use site the corpus does not contain fails closed.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from sugar_lift_python_source.source_oracle import path_source

from sugar_lift_py_tests import lift_rpc as lr
from sugar_lift_py_tests.context_manager_resolution import (
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


def _whole_table(root: Path):
    return lr.provisional_contract_refs_from_demand_rows(
        lr._preconstruction_demand_rows(root)
    ).by_use_site


def test_per_source_answers_equal_the_whole_table(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    whole = dict(_whole_table(root))
    assert whole, "fixture must enroll with-demands"

    lr.clear_provisional_contract_refs_memo()
    refs = lr.provisional_contract_refs_from_demands(root)
    assert isinstance(refs.by_use_site, PerSourceResolutionsV1)
    assert dict(refs.by_use_site) == whole
    for use_site, resolution in whole.items():
        assert refs.require(use_site) == resolution


def test_one_file_derives_one_file_and_walks_nothing(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    whole = dict(_whole_table(root))
    local_cid = path_source(str(root / "local.py"))[2]
    local_sites = {site for site in whole if site.source_cid == local_cid}
    assert len(local_sites) == 2

    lr.clear_provisional_contract_refs_memo()
    lr.reset_preconstruction_walk_count()
    refs = lr.provisional_contract_refs_from_demands(root)
    assert refs.by_use_site.derived_source_cids() == ()

    for site in local_sites:
        assert refs.require(site) == whole[site]
    assert set(resolutions_for_source(refs.by_use_site, local_cid)) == local_sites

    assert refs.by_use_site.derived_source_cids() == (local_cid,)
    assert lr.preconstruction_walk_count() == 0


def test_identity_names_the_corpus_not_the_question(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    lr.clear_provisional_contract_refs_memo()
    before = lr.provisional_contract_refs_from_demands(root).table_cid
    lr.clear_provisional_contract_refs_memo()
    assert lr.provisional_contract_refs_from_demands(root).table_cid == before

    (root / "plain.py").write_text("x = 2\n", encoding="utf-8")
    lr.clear_provisional_contract_refs_memo()
    assert lr.provisional_contract_refs_from_demands(root).table_cid != before


def test_site_outside_the_corpus_fails_closed(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    whole = dict(_whole_table(root))
    real = next(iter(whole))

    lr.clear_provisional_contract_refs_memo()
    refs = lr.provisional_contract_refs_from_demands(root)

    forged_source = dataclasses.replace(real, source_cid="blake3:" + "0" * 64)
    with pytest.raises(ContractRefProtocolError):
        refs.require(forged_source)

    # Right source, a span no With item occupies.
    forged_span = dataclasses.replace(real, start_line=real.start_line + 400)
    with pytest.raises(ContractRefProtocolError):
        refs.require(forged_span)

    assert resolutions_for_source(refs.by_use_site, forged_source.source_cid) == {}
