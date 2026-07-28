"""Generator CM post-yield exceptional exit face publication.

Producer: yield resource; raise RuntimeError (or finally raise) publishes
GeneratorExitHaltFaceV1 with temporal_phase=post-yield — distinct from enter
halt and not a suppression result. Temporal generator state (frame + yield
faces) preserved. Tampering refuses.
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
from sugar_lift_python_source.canonical import blake3_512_of, cid_of_json
from sugar_lift_python_source.manager_summary_derivation import (
    GeneratorBackedLifecycleProtocolV1,
    GeneratorEnterHaltFaceV1,
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
        "from unprivileged import cm\nwith cm():\n    pass\n", encoding="utf-8"
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
    return next(
        v.protocol
        for v in context.source_derived_contract_refs.values()
        if isinstance(v, SourceDerivedGeneratorResourceRefV1)
    )


_POST_YIELD_RAISE = (
    "from contextlib import contextmanager\n"
    "\n"
    "@contextmanager\n"
    "def cm():\n"
    "    yield 'resource'\n"
    "    raise RuntimeError('after')\n"
)

_FINALLY_RAISE = (
    "from contextlib import contextmanager\n"
    "\n"
    "@contextmanager\n"
    "def cm():\n"
    "    try:\n"
    "        yield 'resource'\n"
    "    finally:\n"
    "        raise RuntimeError('cleanup')\n"
)

_PRE_AND_POST = (
    "from contextlib import contextmanager\n"
    "\n"
    "@contextmanager\n"
    "def cm(flag):\n"
    "    if flag:\n"
    "        raise ValueError('enter')\n"
    "    yield 'resource'\n"
    "    raise RuntimeError('exit')\n"
)


def test_post_yield_raise_publishes_exit_halt_not_enter_halt(tmp_path: Path) -> None:
    protocol = _publish(tmp_path, _POST_YIELD_RAISE)
    assert isinstance(protocol, GeneratorBackedLifecycleProtocolV1)
    assert protocol.enter_halt_faces == ()
    assert len(protocol.yield_faces) == 1
    assert len(protocol.exit_halt_faces) == 1
    exit_face = protocol.exit_halt_faces[0]
    assert isinstance(exit_face, GeneratorExitHaltFaceV1)
    assert exit_face.temporal_phase == "post-yield"
    assert exit_face.cid == cid_of_json(exit_face.preimage)
    # Not an enter-halt kind.
    assert exit_face.preimage["kind"] == "generator-exit-halt-face"
    # Temporal frame + yield preserved.
    assert protocol.generator_frame.generator_steps is not None
    assert protocol.yield_faces[0].cid != exit_face.cid


def test_finally_raise_is_post_yield_exit_halt(tmp_path: Path) -> None:
    protocol = _publish(tmp_path, _FINALLY_RAISE)
    assert len(protocol.yield_faces) == 1
    assert len(protocol.exit_halt_faces) == 1
    assert protocol.exit_halt_faces[0].temporal_phase == "post-yield"
    assert protocol.enter_halt_faces == ()


def test_pre_and_post_raises_are_distinct_faces(tmp_path: Path) -> None:
    protocol = _publish(tmp_path, _PRE_AND_POST)
    assert len(protocol.enter_halt_faces) == 1
    assert len(protocol.exit_halt_faces) == 1
    enter = protocol.enter_halt_faces[0]
    exit_ = protocol.exit_halt_faces[0]
    assert isinstance(enter, GeneratorEnterHaltFaceV1)
    assert isinstance(exit_, GeneratorExitHaltFaceV1)
    assert enter.cid != exit_.cid
    assert enter.preimage["kind"] != exit_.preimage["kind"]
    assert exit_.temporal_phase == "post-yield"
    # Consumer cannot treat exit as enter: different kind + phase in preimage.
    assert "temporalPhase" not in enter.preimage
    assert exit_.preimage["temporalPhase"] == "post-yield"


def test_exit_halt_not_suppression_result(tmp_path: Path) -> None:
    protocol = _publish(tmp_path, _POST_YIELD_RAISE)
    exit_face = protocol.exit_halt_faces[0]
    # Suppression is exit-disposition semantics; exit-halt is exceptional exit
    # testimony with its own kind — never NeverSuppresses / ReturnTruthiness.
    assert "suppress" not in exit_face.preimage["kind"].lower()
    assert exit_face.preimage["kind"] == "generator-exit-halt-face"


def test_tampered_exit_halt_cid_refuses(tmp_path: Path) -> None:
    protocol = _publish(tmp_path, _POST_YIELD_RAISE)
    face = protocol.exit_halt_faces[0]
    with pytest.raises(ValueError, match="exit-halt face CID|does not match"):
        GeneratorExitHaltFaceV1(
            face.occurrence,
            face.exception_type_source,
            face.guard_source,
            "post-yield",
            "blake3-512:" + "0" * 128,
        )


def test_identical_reconstruction_yields_identical_exit_halt(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    left = _publish(a, _POST_YIELD_RAISE)
    right = _publish(b, _POST_YIELD_RAISE)
    assert left.exit_halt_faces[0].cid == right.exit_halt_faces[0].cid
    assert left.lifecycle_cid == right.lifecycle_cid
