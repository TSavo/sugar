"""Enumeration protocol §4 — process-resident file context under content CID.

Law: prepare once per whole-file content CID; descendants reuse; changing
bytes changes the CID and misses. The tooth that made the violation
unrepresentable: two consumers of the same module content prepare ONCE.
"""

from __future__ import annotations

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.process_resident_file import (
    clear_process_resident_files,
    prepare_count_for,
    resident_size,
)
from sugar_source_tree.tree import SourceFile


def _identity(source: str, filename: str = "mod.py") -> tuple[str, str, str]:
    return (source, filename, blake3_512_of(source.encode("utf-8")))


def setup_function() -> None:
    clear_process_resident_files()


def test_same_content_cid_prepares_once_from_two_consumer_seats() -> None:
    """§4 tooth: two different seats, same content CID → MaterializeModule once."""
    body = "def shared(value):\n    return value\n"
    cid = blake3_512_of(body.encode("utf-8"))
    a = SourceFile(_identity(body, "consumer_a/dep.py"))
    b = SourceFile(_identity(body, "consumer_b/dep.py"))
    assert a.unit.source_cid == b.unit.source_cid == cid
    assert a.unit is b.unit  # same preparation
    assert a.root is b.root
    assert prepare_count_for(cid) == 1
    assert resident_size() == 1


def test_changed_bytes_change_cid_and_miss() -> None:
    """Changing the file changes the CID and therefore misses."""
    v1 = "def f():\n    return 1\n"
    v2 = "def f():\n    return 2\n"
    c1 = blake3_512_of(v1.encode("utf-8"))
    c2 = blake3_512_of(v2.encode("utf-8"))
    assert c1 != c2
    SourceFile(_identity(v1, "m.py"))
    SourceFile(_identity(v2, "m.py"))
    assert prepare_count_for(c1) == 1
    assert prepare_count_for(c2) == 1
    assert resident_size() == 2


def test_second_pass_over_same_files_does_not_reprepare() -> None:
    """Orange experiment as regression: open the same set twice; prepare once each."""
    files = [
        _identity(f"def f{i}():\n    return {i}\n", f"pkg/m{i}.py") for i in range(8)
    ]
    for identity in files:
        SourceFile(identity)
    counts_after_p1 = {
        identity[2]: prepare_count_for(identity[2]) for identity in files
    }
    assert all(c == 1 for c in counts_after_p1.values()), counts_after_p1

    for identity in files:
        SourceFile(identity)
    counts_after_p2 = {
        identity[2]: prepare_count_for(identity[2]) for identity in files
    }
    assert counts_after_p2 == counts_after_p1
    assert all(c == 1 for c in counts_after_p2.values())


def test_prefix_and_frame_doors_share_one_prepare() -> None:
    """Dual-door collapse: two SourceFile constructions of one body → one prepare."""
    body = (
        "x = 1\n"
        "def alpha(v):\n"
        "    return v\n"
        "def beta(v):\n"
        "    return v + 1\n"
    )
    cid = blake3_512_of(body.encode("utf-8"))
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

    # Prefix-style and frame-style contexts — both walk SourceFile(identity).
    SourceFile(
        _identity(body, "pandas/_config/config.py"),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    SourceFile(
        _identity(body, "pandas/_config/config.py"),
        construction_context=TreeConstructionContextV1.for_source_call_construction(
            frame_projection=True
        ),
    )
    assert prepare_count_for(cid) == 1
