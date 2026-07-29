"""Explicit pytest injection seam for shared LAW_OF_ONE evidence.

Consumer tests import ``law_of_one_evidence`` from this module and name the
typed parameter in their signature.  There is no request/name lookup.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from law_of_one_auditor import audit_law_of_one
from law_of_one_evidence import LawOfOneEvidence, assert_test_owned_evidence


# Static3's test helper imports this historical seam.  It is deliberately a
# binding to the canonical classmethod, not a wrapper or second work entry.
from sugar_source_tree.tree import SourceFile as _CanonicalSourceFile

_direct_source_file_entry = _CanonicalSourceFile.from_path


@pytest.fixture
def law_of_one_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LawOfOneEvidence:
    from sugar_source_tree.backend import Backend
    from sugar_source_tree.tree import SourceFile

    if "materialize_module" not in Backend.__dict__:
        pytest.skip(
            "dormant LAW_OF_ONE axes: R_missing_backend_materialize_module=1"
        )

    repository_root = Path(__file__).resolve().parent
    while repository_root != repository_root.parent and not (
        repository_root / "implementations"
    ).is_dir():
        repository_root = repository_root.parent
    assert (repository_root / "implementations").is_dir()
    evidence = audit_law_of_one(
        repository_root=repository_root,
        temporary_root=tmp_path,
        monkeypatch=monkeypatch,
        source_file_entry=SourceFile.from_path,
    )
    return assert_test_owned_evidence(evidence)
