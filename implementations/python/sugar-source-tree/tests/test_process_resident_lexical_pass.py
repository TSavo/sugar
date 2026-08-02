"""§4: lexical import pass is process-resident under content CID.

Populate product (import-use rows from the lexical walk) is module temporal
preparation for that content — pure in content + package role, not who asks.
Warm SourceFile was already resident; warm populate was still redoing this walk.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
from sugar_source_tree.process_resident_file import (
    clear_process_resident_files,
    lexical_prepare_count_for,
)
from sugar_source_tree.tree import SourceFile


def setup_function() -> None:
    clear_process_resident_files()


def _consumer(tmp_path: Path, name: str, body: str) -> tuple[Path, Path, object, str]:
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    path = root / name
    path.write_text(body, encoding="utf-8")
    source = body
    cid = blake3_512_of(source.encode("utf-8"))
    sf = SourceFile((source, str(path), cid))
    return root, path, sf, cid


def test_lexical_pass_runs_once_for_two_opens_of_same_content(tmp_path: Path) -> None:
    """Open same body twice with populate-shaped receipt mint → walk once."""
    body = (
        "from contextlib import contextmanager\n"
        "@contextmanager\n"
        "def cm():\n"
        "    yield\n"
        "with cm() as x:\n"
        "    pass\n"
    )
    root1, path1, sf1, cid = _consumer(tmp_path, "a.py", body)
    authenticated_import_use_receipts(
        root1, path1, sf1.unit.source, cid, module_identities={}, module=sf1.root
    )
    assert lexical_prepare_count_for(cid) == 1

    root2, path2, sf2, cid2 = _consumer(tmp_path, "b.py", body)
    assert cid2 == cid
    authenticated_import_use_receipts(
        root2, path2, sf2.unit.source, cid, module_identities={}, module=sf2.root
    )
    assert lexical_prepare_count_for(cid) == 1


def test_changed_bytes_re_run_lexical_pass(tmp_path: Path) -> None:
    v1 = "import os\nos.getcwd()\n"
    v2 = "import os\nos.getcwd()\nos.listdir()\n"
    r1, p1, s1, c1 = _consumer(tmp_path, "v1.py", v1)
    authenticated_import_use_receipts(
        r1, p1, s1.unit.source, c1, module_identities={}, module=s1.root
    )
    r2, p2, s2, c2 = _consumer(tmp_path, "v2.py", v2)
    assert c1 != c2
    authenticated_import_use_receipts(
        r2, p2, s2.unit.source, c2, module_identities={}, module=s2.root
    )
    assert lexical_prepare_count_for(c1) == 1
    assert lexical_prepare_count_for(c2) == 1


def test_second_pass_same_file_does_not_re_walk(tmp_path: Path) -> None:
    """Orange warm-populate regression: second open of same path → lexical once."""
    body = (
        "from contextlib import nullcontext\n"
        "with nullcontext() as a:\n"
        "    pass\n"
        "with nullcontext() as b:\n"
        "    pass\n"
    )
    root, path, sf, cid = _consumer(tmp_path, "frame.py", body)
    for _ in range(2):
        authenticated_import_use_receipts(
            root, path, sf.unit.source, cid, module_identities={}, module=sf.root
        )
    assert lexical_prepare_count_for(cid) == 1
