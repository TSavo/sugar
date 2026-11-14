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


# The canonical door: the one opener's first stage, which reads a file at its
# seat and constructs the SourceFile from that identity (#7757 item 5). It is
# deliberately a binding to that stage, not a wrapper or second work entry.
from sugar_lift_py_tests.lift_rpc import _open_at_seat as _canonical_open_at_seat

_direct_source_file_entry = _canonical_open_at_seat


@pytest.fixture
def sourcefile_construction_door_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SourceFileConstructionDoorEvidence:
    from sugar_source_tree.backend import Backend

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
        source_file_entry=_canonical_open_at_seat,
    )
    return assert_test_owned_evidence(evidence)
