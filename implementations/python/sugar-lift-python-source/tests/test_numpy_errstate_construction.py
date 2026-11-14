"""``with numpy.errstate()`` from a corpus that imports numpy is cited.

numpy is installed, not one of step 2's files, so importing it does not enroll
it: ``errstate`` is an imported call, a coordinate plus an edge answered by an
imported proof, and its body is never lifted (#7796).
"""

from __future__ import annotations

import json
from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import (
    OpaqueCitedContextManagerRefV1,
)
from sugar_lift_py_tests.corpus_pin import pin_corpus
from sugar_lift_python_source.resolution_session import SourceResolutionSession


ERRSTATE = (
    "import numpy as np\n"
    "\n"
    "def f():\n"
    "    with np.errstate(divide='ignore'):\n"
    "        return 1\n"
)


def _corpus(tmp_path: Path, **files: str) -> Path:
    root = tmp_path / "c"
    root.mkdir()
    for name, source in files.items():
        (root / name).write_text(source, encoding="utf-8")
    (tmp_path / "c.identity.json").write_text(
        json.dumps({"distribution": "tiny-corpus", "version": "0.0.1"}), encoding="utf-8"
    )
    pin_corpus(root, distribution="tiny-corpus", version="0.0.1")
    return root


def test_imported_errstate_stays_call_target_off_population(tmp_path) -> None:
    """The code imports numpy; the import is an edge, not population."""
    from sugar_lift_py_tests.canonicalizer import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.manager_summary_derivation import (
        populate_source_derived_resource_refs,
    )
    from sugar_source_tree.tree import SourceFile

    root = _corpus(tmp_path, **{"e.py": ERRSTATE})
    path = root / "e.py"
    source = path.read_text(encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, str(path), blake3_512_of(source.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=root,
        path=path,
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({"tiny-corpus"})
        ),
    )
    ref = next(iter(context.source_derived_contract_refs.values()))
    assert type(ref) is OpaqueCitedContextManagerRefV1
    assert ref.roster.resolution_kind == "call-target-off-population"
    assert ref.roster.target_name == "python:numpy.errstate"
