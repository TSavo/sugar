"""General source-defined CM law for generator-face publication.

Steering (T): the generator-face producer serves the general
source-defined-context-manager law — contextlib managers, config/warning/
temp-state managers, nested generators, cleanup over Completed/Returned/
Halted. Completion bar:

- renamed import aliases publish through the identical pipeline (same body
  face CIDs as the direct binding of the same definition);
- unrelated source managers publish through that same pipeline (zero name
  arms — no option_context / provider spelling tables);
- face projection is structural over FunctionDef body, never manager names.

Does not touch nodes.py, carrier/ExitSet, or lifecycle consumers.
"""

from __future__ import annotations

import csv
import importlib.metadata
import inspect
from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import (
    SourceDerivedGeneratorResourceRefV1,
    TreeConstructionContextV1,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.manager_summary_derivation import (
    GeneratorBackedLifecycleProtocolV1,
    _project_generator_lifecycle_faces,
    populate_source_derived_resource_refs,
)
from sugar_source_tree.tree import SourceFile

_HELPERS = """\
from contextlib import contextmanager

@contextmanager
def alpha(flag):
    if flag:
        raise ValueError("enter-a")
    yield "resource-a"
    raise RuntimeError("exit-a")

@contextmanager
def beta():
    yield "resource-b"
    if True:
        raise TypeError("then-b")
    else:
        raise KeyError("else-b")
"""


def _distribution(root: Path) -> importlib.metadata.Distribution:
    package = root / "unprivileged"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from unprivileged.helpers import alpha, beta\n", encoding="utf-8"
    )
    (package / "helpers.py").write_text(_HELPERS, encoding="utf-8")
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


def _publish(tmp_path: Path, consumer: str) -> list:
    distribution = _distribution(tmp_path)
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
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
    return [
        value.protocol
        for value in context.source_derived_contract_refs.values()
        if isinstance(value, SourceDerivedGeneratorResourceRefV1)
    ]


def test_renamed_manager_publishes_identical_body_face_cids(tmp_path: Path) -> None:
    """Renamed import alias is the same definition — face CIDs must match."""
    direct_root = tmp_path / "direct"
    renamed_root = tmp_path / "renamed"
    direct_root.mkdir()
    renamed_root.mkdir()
    direct = _publish(
        direct_root,
        "from unprivileged import alpha\nwith alpha(False):\n    pass\n",
    )
    renamed = _publish(
        renamed_root,
        "from unprivileged import alpha as renamed_mgr\n"
        "with renamed_mgr(False):\n"
        "    pass\n",
    )
    assert len(direct) == len(renamed) == 1
    d, r = direct[0], renamed[0]
    assert isinstance(d, GeneratorBackedLifecycleProtocolV1)
    assert isinstance(r, GeneratorBackedLifecycleProtocolV1)
    # Body-authenticated faces are identical (definition identity, not call spelling).
    assert [f.cid for f in d.enter_halt_faces] == [f.cid for f in r.enter_halt_faces]
    assert [f.cid for f in d.exit_halt_faces] == [f.cid for f in r.exit_halt_faces]
    assert [f.cid for f in d.yield_faces] == [f.cid for f in r.yield_faces]
    assert len(d.enter_halt_faces) == 1
    assert len(d.exit_halt_faces) == 1
    assert len(d.yield_faces) == 1


def test_unrelated_source_managers_publish_through_identical_pipeline(
    tmp_path: Path,
) -> None:
    """Two unrelated managers both receive lifecycle faces — zero name arms."""
    root = tmp_path / "both"
    root.mkdir()
    protocols = _publish(
        root,
        "from unprivileged import alpha, beta\n"
        "with alpha(False):\n"
        "    pass\n"
        "with beta():\n"
        "    pass\n",
    )
    assert len(protocols) == 2
    assert all(isinstance(p, GeneratorBackedLifecycleProtocolV1) for p in protocols)
    by_shape = {
        (
            len(p.enter_halt_faces),
            len(p.exit_halt_faces),
            len(p.yield_faces),
        ): p
        for p in protocols
    }
    # alpha: pre-yield if-raise + post-yield raise + one yield
    assert (1, 1, 1) in by_shape
    # beta: no pre-yield raise; two guarded post-yield exits + one yield
    assert (0, 2, 1) in by_shape
    alpha = by_shape[(1, 1, 1)]
    beta = by_shape[(0, 2, 1)]
    # Unrelated bodies → distinct face / lifecycle identity
    assert alpha.lifecycle_cid != beta.lifecycle_cid
    assert alpha.yield_faces[0].cid != beta.yield_faces[0].cid
    assert alpha.exit_halt_faces[0].cid != beta.exit_halt_faces[0].cid
    # Conditional beta faces remain distinct
    assert beta.exit_halt_faces[0].cid != beta.exit_halt_faces[1].cid
    assert beta.exit_halt_faces[0].guard_source != beta.exit_halt_faces[1].guard_source


def test_lifecycle_projection_has_zero_manager_name_arms() -> None:
    """Projection is structural over FunctionDef — no manager name table."""
    source = inspect.getsource(_project_generator_lifecycle_faces)
    banned = (
        "option_context",
        "contextmanager",  # decorator spelling admission
        "pytest.raises",
        "warning",
        "tempfile",
        "TemporaryDirectory",
        "alpha",
        "beta",
        "renamed",
    )
    for name in banned:
        assert (
            name not in source
        ), f"name arm residual: {name!r} in lifecycle projection"
    # Must walk typed body structure, not scan source text.
    assert "FunctionDef" in source or "generator_target.body" in inspect.getsource(
        inspect.getmodule(_project_generator_lifecycle_faces)
    )


def test_face_kinds_are_phase_separated_not_name_separated(tmp_path: Path) -> None:
    """Enter vs exit is temporal phase / kind, never manager spelling."""
    root = tmp_path / "phase"
    root.mkdir()
    protocols = _publish(
        root,
        "from unprivileged import alpha\nwith alpha(False):\n    pass\n",
    )
    protocol = protocols[0]
    enter = protocol.enter_halt_faces[0]
    exit_ = protocol.exit_halt_faces[0]
    assert enter.preimage["kind"] == "generator-enter-halt-face"
    assert exit_.preimage["kind"] == "generator-exit-halt-face"
    assert exit_.temporal_phase == "post-yield"
    assert "temporalPhase" not in enter.preimage
    # No manager name in face preimages.
    for face in (enter, exit_, *protocol.yield_faces):
        blob = repr(face.preimage)
        assert "alpha" not in blob
        assert "option_context" not in blob
