"""Do the generator laws assert anything the citation route would change?

Diagnostic only. This is the GATE on ruling (A): a pre-existing tooth going
green because the claim beneath it shrank would invert its value.

What the three failing laws assert, read from the file:

  test_renamed_manager_publishes_identical_body_face_cids
      enter_halt_faces / exit_halt_faces / yield_faces  -- their .cid and count
  test_unrelated_source_managers_publish_through_identical_pipeline
      the same faces, plus lifecycle_cid and guard_source, all as RELATIVE
      comparisons (alpha != beta), never a pinned absolute CID
  test_face_kinds_are_phase_separated_not_name_separated
      face preimage["kind"], temporal_phase, and no manager name in preimages

None of them reads an enter/exit DEFINITION coordinate, the returned manager
class, or the decorator.

What (A) changes: the enter/exit definitions handed to
``construct_generator_backed_protocol`` -- hence the protocol preimage and its
content address. It does not touch the generator frame.

Those faces come from ``_project_generator_lifecycle_faces(generator_target)``,
which takes ONLY the decorated generator function -- in-population, and
reachable WITHOUT the decorator road. So the quantity the laws assert can be
computed independently, right now, before any repair. This records it. After
(A) the published faces must carry these same CIDs; if they do, the laws'
subject matter is provably untouched and their green is honest.
"""

from __future__ import annotations

import csv
import importlib.metadata
import sys
from pathlib import Path

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


def _distribution(root: Path):
    package = root / "unprivileged"
    package.mkdir(parents=True)
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


def main() -> int:
    import tempfile

    # Bootstraps the authenticated execution environment (and sys.path for the
    # sibling packages). This probe uses a synthetic corpus, but the setup is
    # still what makes sugar_source_tree importable.
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus

    handle = authenticated_pandas_corpus()
    print(f"ENV OK ({handle.distribution} {handle.version})")

    from sugar_lift_python_source.manager_summary_derivation import (
        _project_generator_lifecycle_faces,
    )
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.nodes import FunctionDef
    from sugar_source_tree.tree import SourceFile

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        _distribution(root)
        helpers = root / "unprivileged" / "helpers.py"
        # The generator target alone -- no decorator road, no contract table.
        tree = SourceFile(path_source(str(helpers)))
        targets = {
            node.name: node
            for node in tree.root.body
            if isinstance(node, FunctionDef)
        }
        print(f"GENERATOR TARGETS {sorted(targets)}")
        for name in sorted(targets):
            enter_halts, yield_faces, exit_halts = _project_generator_lifecycle_faces(
                targets[name]
            )
            print(f"\n{name}:")
            print(
                f"  counts  enter_halt={len(enter_halts)} "
                f"yield={len(yield_faces)} exit_halt={len(exit_halts)}"
            )
            for label, faces in (
                ("enter_halt", enter_halts),
                ("yield", yield_faces),
                ("exit_halt", exit_halts),
            ):
                for index, face in enumerate(faces):
                    print(f"  {label}[{index}].cid = {face.cid}")
                    print(f"    kind = {face.preimage.get('kind')!r}")
                    phase = getattr(face, "temporal_phase", None)
                    if phase is not None:
                        print(f"    temporal_phase = {phase!r}")
                    blob = repr(face.preimage)
                    print(f"    manager name in preimage: {name in blob}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
