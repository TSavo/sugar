"""Explicit pytest injection seam for shared LAW_OF_ONE evidence.

Consumer tests import ``law_of_one_evidence`` from this module and name the
typed parameter in their signature.  There is no request/name lookup.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from law_of_one_auditor import audit_law_of_one
from law_of_one_evidence import LawOfOneEvidence, assert_test_owned_evidence


@pytest.fixture
def law_of_one_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LawOfOneEvidence:
    from sugar_source_tree.tree import SourceFile

    repository_root = Path(__file__).resolve().parents[1]
    evidence = audit_law_of_one(
        repository_root=repository_root,
        temporary_root=tmp_path,
        monkeypatch=monkeypatch,
        source_file_entry=SourceFile.from_path,
    )
    return assert_test_owned_evidence(evidence)
