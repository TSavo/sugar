"""Generator CM pre-yield exceptional enter-halt face publication.

Producer (manager_summary_derivation): for

    @contextmanager
    def cm(flag):
        if flag:
            raise ValueError(...)
        yield resource

publication retains a guarded named enter halt with authenticated exception
type source + raise occurrence, and the complementary yield face for the
resource handoff. Tampered face CIDs refuse. No decorator/provider spelling
admission; no nodes.py / carrier / ExitSet edits.
"""

from __future__ import annotations

import csv
import importlib.metadata
from dataclasses import replace
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceDerivedGeneratorResourceRefV1,
    TreeConstructionContextV1,
)
from sugar_lift_python_source.canonical import blake3_512_of, cid_of_json
from sugar_lift_python_source.manager_summary_derivation import (
    GeneratorBackedLifecycleProtocolV1,
    GeneratorEnterHaltFaceV1,
    GeneratorYieldFaceV1,
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


def _publish(tmp_path: Path, implementation: str, consumer: str | None = None):
    distribution = _distribution(tmp_path, implementation)
    path = tmp_path / "consumer.py"
    path.write_text(
        consumer or ("from unprivileged import cm\n" "with cm(False):\n" "    pass\n"),
        encoding="utf-8",
    )
    context = TreeConstructionContextV1.for_source_call_construction(
        workspace_root=str(tmp_path)
    )
    tree = SourceFile(
        (path.read_text(encoding="utf-8"), str(path), blake3_512_of(path.read_bytes())),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
    )
    return context


_CM_PRE_YIELD_RAISE = (
    "from contextlib import contextmanager\n"
    "\n"
    "@contextmanager\n"
    "def cm(flag):\n"
    "    if flag:\n"
    "        raise ValueError('boom')\n"
    "    yield 'resource'\n"
)


def test_pre_yield_raise_publishes_guarded_enter_halt_and_yield_face(
    tmp_path: Path,
) -> None:
    context = _publish(tmp_path, _CM_PRE_YIELD_RAISE)
    refs = [
        value
        for value in context.source_derived_contract_refs.values()
        if isinstance(value, SourceDerivedGeneratorResourceRefV1)
    ]
    assert len(refs) == 1
    protocol = refs[0].protocol
    assert isinstance(protocol, GeneratorBackedLifecycleProtocolV1)
    # Guarded named enter halt — authenticated type source + occurrence.
    assert len(protocol.enter_halt_faces) == 1
    halt = protocol.enter_halt_faces[0]
    assert isinstance(halt, GeneratorEnterHaltFaceV1)
    assert halt.guard_source is not None
    assert halt.occurrence["cid"].startswith("blake3-512:")
    assert halt.exception_type_source["cid"].startswith("blake3-512:")
    assert halt.cid == cid_of_json(halt.preimage)
    # Complementary yield face publishes the resource handoff.
    assert len(protocol.yield_faces) == 1
    yf = protocol.yield_faces[0]
    assert isinstance(yf, GeneratorYieldFaceV1)
    assert yf.resource_source is not None
    assert yf.cid == cid_of_json(yf.preimage)
    # Enter halt is not the yield face.
    assert halt.cid != yf.cid
    # Lifecycle CID authenticates both face sets.
    assert protocol.lifecycle_cid == cid_of_json(protocol.lifecycle_preimage)


def test_identical_source_reconstruction_yields_identical_enter_halt_testimony(
    tmp_path: Path,
) -> None:
    left_root = tmp_path / "a"
    right_root = tmp_path / "b"
    left_root.mkdir()
    right_root.mkdir()
    left = _publish(left_root, _CM_PRE_YIELD_RAISE)
    right = _publish(right_root, _CM_PRE_YIELD_RAISE)
    left_proto = next(
        v.protocol
        for v in left.source_derived_contract_refs.values()
        if isinstance(v, SourceDerivedGeneratorResourceRefV1)
    )
    right_proto = next(
        v.protocol
        for v in right.source_derived_contract_refs.values()
        if isinstance(v, SourceDerivedGeneratorResourceRefV1)
    )
    assert left_proto.enter_halt_faces[0].cid == right_proto.enter_halt_faces[0].cid
    assert left_proto.yield_faces[0].cid == right_proto.yield_faces[0].cid
    assert left_proto.lifecycle_cid == right_proto.lifecycle_cid


def test_tampered_enter_halt_face_cid_refuses(tmp_path: Path) -> None:
    context = _publish(tmp_path, _CM_PRE_YIELD_RAISE)
    protocol = next(
        v.protocol
        for v in context.source_derived_contract_refs.values()
        if isinstance(v, SourceDerivedGeneratorResourceRefV1)
    )
    halt = protocol.enter_halt_faces[0]
    with pytest.raises(ValueError, match="enter-halt face CID|does not match"):
        GeneratorEnterHaltFaceV1(
            halt.occurrence,
            halt.exception_type_source,
            halt.guard_source,
            "blake3-512:" + "0" * 128,
        )


def test_tampered_exception_type_source_changes_face_cid(tmp_path: Path) -> None:
    context = _publish(tmp_path, _CM_PRE_YIELD_RAISE)
    protocol = next(
        v.protocol
        for v in context.source_derived_contract_refs.values()
        if isinstance(v, SourceDerivedGeneratorResourceRefV1)
    )
    halt = protocol.enter_halt_faces[0]
    mutated_type = dict(halt.exception_type_source)
    mutated_type["cid"] = "blake3-512:" + "a" * 128
    mutated = GeneratorEnterHaltFaceV1.mint(
        occurrence=halt.occurrence,
        exception_type_source=mutated_type,
        guard_source=halt.guard_source,
    )
    assert mutated.cid != halt.cid


def test_tampered_raise_occurrence_changes_face_cid(tmp_path: Path) -> None:
    context = _publish(tmp_path, _CM_PRE_YIELD_RAISE)
    protocol = next(
        v.protocol
        for v in context.source_derived_contract_refs.values()
        if isinstance(v, SourceDerivedGeneratorResourceRefV1)
    )
    halt = protocol.enter_halt_faces[0]
    mutated_occ = dict(halt.occurrence)
    mutated_occ["cid"] = "blake3-512:" + "b" * 128
    mutated = GeneratorEnterHaltFaceV1.mint(
        occurrence=mutated_occ,
        exception_type_source=halt.exception_type_source,
        guard_source=halt.guard_source,
    )
    assert mutated.cid != halt.cid


def test_lifecycle_protocol_refuses_stale_lifecycle_cid(tmp_path: Path) -> None:
    context = _publish(tmp_path, _CM_PRE_YIELD_RAISE)
    protocol = next(
        v.protocol
        for v in context.source_derived_contract_refs.values()
        if isinstance(v, SourceDerivedGeneratorResourceRefV1)
    )
    with pytest.raises(ValueError, match="lifecycle CID"):
        GeneratorBackedLifecycleProtocolV1(
            protocol.protocol_construction_cid,
            protocol.generator_frame_cid,
            protocol.enter_definition,
            protocol.exit_definition,
            protocol.exit_face_id,
            protocol.generator_frame,
            protocol.enter_halt_faces,
            protocol.yield_faces,
            protocol.exit_halt_faces,
            "blake3-512:" + "c" * 128,
        )


def test_plain_yield_without_pre_yield_raise_has_empty_enter_halts(
    tmp_path: Path,
) -> None:
    context = _publish(
        tmp_path,
        "from contextlib import contextmanager\n"
        "\n"
        "@contextmanager\n"
        "def cm():\n"
        "    yield 'resource'\n",
    )
    protocol = next(
        v.protocol
        for v in context.source_derived_contract_refs.values()
        if isinstance(v, SourceDerivedGeneratorResourceRefV1)
    )
    assert isinstance(protocol, GeneratorBackedLifecycleProtocolV1)
    assert protocol.enter_halt_faces == ()
    assert len(protocol.yield_faces) == 1
