"""Conditional generator exit faces remain distinct producer-authenticated faces.

Two guarded post-yield exits keep distinct occurrence coordinates and stable
guards. Equivalent reconstruction → identical testimony. Guard/occurrence
tampering changes or rejects. Never recombine faces, scan syntax names, hash
repr, or ambient cache.
"""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceDerivedGeneratorResourceRefV1,
    TreeConstructionContextV1,
)
from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_python_source.manager_summary_derivation import (
    GeneratorBackedLifecycleProtocolV1,
    GeneratorExitHaltFaceV1,
    populate_source_derived_resource_refs,
)
from sugar_source_tree.tree import SourceFile


def _distribution(root: Path, implementation: str) -> importlib.metadata.Distribution:
    package = root / "unprivileged"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from unprivileged.helpers import cm\n", encoding="utf-8"
    )
    (package / "helpers.py").write_text(implementation, encoding="utf-8")
    metadata = root / "unprivileged_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: unprivileged-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    files = (
        "unprivileged/__init__.py",
        "unprivileged/helpers.py",
        "unprivileged_dist-1.0.dist-info/METADATA",
        "unprivileged_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for file in files:
            writer.writerow((file, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _publish(tmp_path: Path, implementation: str):
    distribution = _distribution(tmp_path, implementation)
    path = tmp_path / "consumer.py"
    path.write_text(
        "from unprivileged import cm\nwith cm(True):\n    pass\n", encoding="utf-8"
    )
    context = TreeConstructionContextV1.for_source_call_construction(
        workspace_root=str(tmp_path)
    )
    tree = SourceFile(
        path_source(str(path)),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
    )
    return next(
        v.protocol
        for v in context.source_derived_contract_refs.values()
        if isinstance(v, SourceDerivedGeneratorResourceRefV1)
    )


_CONDITIONAL_EXITS = (
    "from contextlib import contextmanager\n"
    "\n"
    "@contextmanager\n"
    "def cm(flag):\n"
    "    yield 'resource'\n"
    "    if flag:\n"
    "        raise RuntimeError('then')\n"
    "    else:\n"
    "        raise TypeError('else')\n"
)


def test_two_guarded_post_yield_exits_remain_distinct(tmp_path: Path) -> None:
    protocol = _publish(tmp_path, _CONDITIONAL_EXITS)
    assert isinstance(protocol, GeneratorBackedLifecycleProtocolV1)
    assert len(protocol.exit_halt_faces) == 2
    then_face, else_face = protocol.exit_halt_faces
    assert isinstance(then_face, GeneratorExitHaltFaceV1)
    assert isinstance(else_face, GeneratorExitHaltFaceV1)
    # Distinct occurrence coordinates.
    assert then_face.occurrence["cid"] != else_face.occurrence["cid"]
    # Distinct face CIDs (not recombined).
    assert then_face.cid != else_face.cid
    # Stable guards present and distinct (then vs else polarity).
    assert then_face.guard_source is not None
    assert else_face.guard_source is not None
    assert then_face.guard_source != else_face.guard_source
    assert else_face.guard_source.get("branch") == "orelse"
    # Both post-yield temporal phase.
    assert then_face.temporal_phase == else_face.temporal_phase == "post-yield"
    # Exception type sources differ (RuntimeError vs TypeError sites).
    assert (
        then_face.exception_type_source["cid"] != else_face.exception_type_source["cid"]
    )


def test_equivalent_reconstruction_identical_conditional_exit_testimony(
    tmp_path: Path,
) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    left = _publish(a, _CONDITIONAL_EXITS)
    right = _publish(b, _CONDITIONAL_EXITS)
    left_cids = tuple(face.cid for face in left.exit_halt_faces)
    right_cids = tuple(face.cid for face in right.exit_halt_faces)
    assert left_cids == right_cids
    assert left.lifecycle_cid == right.lifecycle_cid
    # No ambient cache / object identity.
    assert left is not right
    assert left.exit_halt_faces[0] is not right.exit_halt_faces[0]


def test_guard_tampering_changes_exit_face_cid(tmp_path: Path) -> None:
    protocol = _publish(tmp_path, _CONDITIONAL_EXITS)
    face = protocol.exit_halt_faces[0]
    mutated_guard = dict(face.guard_source)
    mutated_guard["cid"] = "blake3-512:" + "d" * 128
    mutated = GeneratorExitHaltFaceV1.mint(
        occurrence=face.occurrence,
        exception_type_source=face.exception_type_source,
        guard_source=mutated_guard,
    )
    assert mutated.cid != face.cid


def test_occurrence_tampering_changes_exit_face_cid(tmp_path: Path) -> None:
    protocol = _publish(tmp_path, _CONDITIONAL_EXITS)
    face = protocol.exit_halt_faces[0]
    mutated_occ = dict(face.occurrence)
    mutated_occ["cid"] = "blake3-512:" + "e" * 128
    mutated = GeneratorExitHaltFaceV1.mint(
        occurrence=mutated_occ,
        exception_type_source=face.exception_type_source,
        guard_source=face.guard_source,
    )
    assert mutated.cid != face.cid


def test_faces_never_recombined_into_one_cid(tmp_path: Path) -> None:
    protocol = _publish(tmp_path, _CONDITIONAL_EXITS)
    cids = [face.cid for face in protocol.exit_halt_faces]
    assert len(cids) == len(set(cids))
    # Lifecycle lists both; never a single merged face.
    assert len(protocol.lifecycle_preimage["exitHaltFaceCids"]) == 2
    assert set(protocol.lifecycle_preimage["exitHaltFaceCids"]) == set(cids)


def test_no_repr_or_spelling_in_face_preimage(tmp_path: Path) -> None:
    protocol = _publish(tmp_path, _CONDITIONAL_EXITS)
    for face in protocol.exit_halt_faces:
        rendered = repr(face.preimage)
        assert "RuntimeError" not in rendered or "exceptionTypeSource" in face.preimage
        # Preimage is sealed mementos / CIDs — not source text scan of names.
        assert face.preimage["kind"] == "generator-exit-halt-face"
        assert "cid" in face.occurrence
        assert str(id(face)) not in rendered
