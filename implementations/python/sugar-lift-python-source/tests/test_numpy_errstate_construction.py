"""``with numpy.errstate()`` from a corpus that imports numpy.

numpy is installed, not one of step 2's files, so importing it does not enroll
it: ``errstate`` is an imported call, a coordinate plus an edge answered by an
imported proof, and its body is never lifted (#7796).
"""

from __future__ import annotations

import json
from pathlib import Path

from sugar_lift_py_tests.corpus_pin import pin_corpus


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


def test_imported_errstate_is_the_heads_reduced_value(tmp_path) -> None:
    """The code imports numpy; the import is an edge, not population.

    Nothing reads ``errstate``'s body and no row is looked up: the manager
    is what the head reduces to (#7757)."""
    from sugar_lift_py_tests.canonicalizer import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
        WithReducedManagerSugar,
    )
    from sugar_source_tree.nodes import With
    from sugar_source_tree.tree import SourceFile

    root = _corpus(tmp_path, **{"e.py": ERRSTATE})
    path = root / "e.py"
    source = path.read_text(encoding="utf-8")
    tree = SourceFile(
        (source, str(path), blake3_512_of(source.encode("utf-8"))),
        construction_context=TreeConstructionContextV1(),
    )
    with_node = next(n for n in tree.nodes() if isinstance(n, With))
    assert type(with_node.sugar()) is WithReducedManagerSugar
