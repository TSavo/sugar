"""Pytest injection seam for shared SourceFile construction-door evidence.

Consumer tests import ``sourcefile_construction_door_evidence`` from this
module and name the typed parameter in their signature. No request/name
lookup. Domain is construction-door / privacy / zero-work projection only —
not Law-of-One sugar-meaning sins.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sourcefile_construction_door_auditor import audit_sourcefile_construction_door
from sourcefile_construction_door_evidence import SourceFileConstructionDoorEvidence, assert_test_owned_evidence


# Static3's test helper imports this historical seam.  It is deliberately a
# binding to the canonical classmethod, not a wrapper or second work entry.
from sugar_source_tree.tree import SourceFile as _CanonicalSourceFile

_direct_source_file_entry = _CanonicalSourceFile.from_path


@pytest.fixture
def sourcefile_construction_door_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SourceFileConstructionDoorEvidence:
    from sugar_source_tree.backend import Backend
    from sugar_source_tree.tree import SourceFile

    if "materialize_module" not in Backend.__dict__:
        pytest.skip(
            "dormant SOURCEFILE_CONSTRUCTION_DOOR axes: R_missing_backend_materialize_module=1"
        )

    repository_root = Path(__file__).resolve().parent
    while repository_root != repository_root.parent and not (
        repository_root / "implementations"
    ).is_dir():
        repository_root = repository_root.parent
    assert (repository_root / "implementations").is_dir()
    evidence = audit_sourcefile_construction_door(
        repository_root=repository_root,
        temporary_root=tmp_path,
        monkeypatch=monkeypatch,
        source_file_entry=SourceFile.from_path,
    )
    return assert_test_owned_evidence(evidence)
