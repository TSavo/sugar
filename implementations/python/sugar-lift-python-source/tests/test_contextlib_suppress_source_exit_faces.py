"""The ``source-exit-faces`` completion, and the tiny-corpus opener.

``source-exit-faces`` admits an exit that may halt: With re-runs the exit
frame per body face, so every exit halt supersedes the body exit as its own
effect.  ``_corpus`` / ``_open`` are the one-file corpus and the one opener
other tests construct through.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    ContextManagerContractError,
    ExitContractV1,
    ProtocolResourceSemanticsV1,
    ReturnTruthinessDispositionV1,
    SourceExitFacesCompletionV1,
    _decode_protocol_resource,
    semantics_to_value,
)
from sugar_lift_py_tests.corpus_pin import pin_corpus
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_source_tree.reporter import CollectingReporter
from sugar_lift_python_source.resolution_session import (
    SourceResolutionSession,
    clear_walk_sessions,
)


def _corpus(tmp_path: Path, source: str) -> Path:
    root = tmp_path / "c"
    root.mkdir()
    (root / "e.py").write_text(source, encoding="utf-8")
    (tmp_path / "c.identity.json").write_text(
        json.dumps({"distribution": "tiny-corpus", "version": "0.0.1"}), encoding="utf-8"
    )
    pin_corpus(root, distribution="tiny-corpus", version="0.0.1")
    return root


def _open(root: Path):
    clear_walk_sessions()
    return open_source_file_for_construction(
        root / "e.py",
        root=root,
        reporter=CollectingReporter(),
        source_workspace_root=root,
        resolution_session=SourceResolutionSession(
            enrolled_distributions=frozenset({"tiny-corpus", "cpython-stdlib:contextlib"})
        ),
    )


def test_source_exit_faces_round_trips_and_stays_distinct_from_total():
    from sugar_lift_py_tests.canonicalizer import encode_jcs
    from sugar_lift_py_tests.context_manager_contract import EnterResultContractV1
    from sugar_lift_py_tests.ir import PrimitiveSort

    semantics = ProtocolResourceSemanticsV1(
        EnterResultContractV1(PrimitiveSort("Value")),
        ExitContractV1(ReturnTruthinessDispositionV1(), SourceExitFacesCompletionV1()),
    )
    raw = json.loads(encode_jcs(semantics_to_value(semantics)))
    assert raw["exit"]["completion"] == {"kind": "source-exit-faces"}
    assert _decode_protocol_resource(raw) == semantics
    raw["exit"]["completion"] = {"kind": "partial"}
    with pytest.raises(ContextManagerContractError):
        _decode_protocol_resource(raw)
