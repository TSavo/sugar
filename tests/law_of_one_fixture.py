"""Explicit pytest injection seam for shared LAW_OF_ONE evidence.

Consumer tests import ``law_of_one_evidence`` from this module and name the
typed parameter in their signature.  There is no request/name lookup.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from law_of_one_auditor import audit_law_of_one
from law_of_one_evidence import LawOfOneEvidence, assert_test_owned_evidence


def _direct_source_file_entry(path: Path, backend: object, reporter: object):
    """The single replaceable construction seat under the pending ruling."""
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.tree import SourceFile

    return SourceFile(path_source(str(path)), backend=backend, reporter=reporter)


@pytest.fixture
def law_of_one_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LawOfOneEvidence:
    repository_root = Path(__file__).resolve().parents[1]
    evidence = audit_law_of_one(
        repository_root=repository_root,
        temporary_root=tmp_path,
        monkeypatch=monkeypatch,
        source_file_entry=_direct_source_file_entry,
    )
    return assert_test_owned_evidence(evidence)
