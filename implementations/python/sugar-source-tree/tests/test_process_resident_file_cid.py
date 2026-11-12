"""Enumeration protocol §4 — process-resident file context under content CID.

Law: prepare once per whole-file content CID and source seat; descendants
reuse; changing bytes or seat changes the identity and misses.
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


def test_same_content_cid_binds_source_seat() -> None:
    """Same seat hits; alternate seat misses; repeat remains a hit."""
    body = "def shared(value):\n    return value\n"
    cid = blake3_512_of(body.encode("utf-8"))
    a = SourceFile(_identity(body, "consumer_a/dep.py"))
    b = SourceFile(_identity(body, "consumer_b/dep.py"))
    assert a.unit.source_cid == b.unit.source_cid == cid
    assert a.unit is not b.unit
    repeat = SourceFile(_identity(body, "consumer_a/dep.py"))
    assert repeat is a
    assert prepare_count_for(cid, "consumer_a/dep.py") == 1
    assert prepare_count_for(cid, "consumer_b/dep.py") == 1
    assert resident_size() == 2


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


_TWO_DOORS_BODY = (
    "x = 1\n"
    "def alpha(v):\n"
    "    return v\n"
    "def beta(v):\n"
    "    return v + 1\n"
)


def test_an_open_with_a_different_context_prepares_its_own_unit() -> None:
    """A unit keeps the construction context it was prepared under (#7772).

    Two doors open one body at one seat, each with its own context. The second
    open used to answer with the first open's unit and rebind its context, so
    whatever the first door still held read the second door's tables. Now the
    second open prepares its own unit and the first is left as it was.
    """
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

    cid = blake3_512_of(_TWO_DOORS_BODY.encode("utf-8"))
    identity = _identity(_TWO_DOORS_BODY, "pandas/_config/config.py")
    first_context = TreeConstructionContextV1.for_source_call_construction()
    second_context = TreeConstructionContextV1.for_source_call_construction()

    first = SourceFile(identity, construction_context=first_context)
    second = SourceFile(identity, construction_context=second_context)

    assert first.unit.construction_context is first_context
    assert second.unit.construction_context is second_context
    assert first.unit is not second.unit
    assert prepare_count_for(cid) == 2


def test_an_open_with_the_same_context_reuses_the_unit() -> None:
    """The same context at the same seat is the same open: one prepare."""
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

    cid = blake3_512_of(_TWO_DOORS_BODY.encode("utf-8"))
    identity = _identity(_TWO_DOORS_BODY, "pandas/_config/config.py")
    context = TreeConstructionContextV1.for_source_call_construction()

    first = SourceFile(identity, construction_context=context)
    again = SourceFile(identity, construction_context=context)

    assert again is first
    assert again.unit.construction_context is context
    assert prepare_count_for(cid) == 1
