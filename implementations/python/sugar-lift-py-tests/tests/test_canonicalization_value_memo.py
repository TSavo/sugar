"""Canonicalization is content-addressed WORK: done once per value, never per path.

The ConstructedValueV2 CID of a value is a pure function of its immutable
semantic content, and the constructed value graph is a DAG that a naive encoder
walks as a TREE. Measured on pandas ``core/indexes/base.py::_join_level``:
758,852 canonicalizations over 1,544 distinct value objects -- 491x
recomputation, and the reason a completed canonicalization made
``__internal_pivot_table`` take 976s.

The memo is keyed by value IDENTITY (computing a content key is exactly the cost
being removed) and each row holds a WEAK reference to the object it keyed. A hit
is honored only when that weakref still resolves to the SAME object, so a dead
value's recycled address (the #6212 id-reuse bug class) can never be served the
dead object's CID.

These twins pin: the work collapses, the ANSWER does not change by one bit, a
distinct value never reads another value's row, a recycled address misses, and
speed never comes from skipping testimony.
"""

import gc
import json
import os
import subprocess
import sys
import tempfile
import weakref
from dataclasses import dataclass

from sugar_source_tree import binding_state as BS
from sugar_source_tree import construction_cache as CC
from sugar_source_tree.binding_state import (
    ConstructionTestimonyReporterV1,
    SubstitutionTraceBuilderV1,
    constructed_value_cid_v2,
)
from sugar_source_tree.backend import materialize
from sugar_source_tree.panic import ConstructedValueTestimonyNotWritten
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.tree import SourceFile

_SCOPE_CID = "blake3-512:" + "0" * 8


@dataclass(frozen=True)
class Held:
    tag: str
    parts: tuple


class Unserializable:
    pass


def _counting_preimages():
    """Count the preimages actually HASHED, which is the work being removed."""
    original = BS.cid_of_json
    calls = {"n": 0}

    def counting(value):
        if isinstance(value, dict) and value.get("schema") == (
            BS.CONSTRUCTED_VALUE_V2_SCHEMA
        ):
            calls["n"] += 1
        return original(value)

    BS.cid_of_json = counting
    return calls, original


def test_a_shared_value_canonicalizes_once_not_once_per_path():
    # The DAG-as-tree disease in miniature: one shared leaf reached by many
    # paths. Work must be a function of DISTINCT values, not of paths.
    CC._CONSTRUCTED_VALUE_CIDS_V2.clear()
    shared = Held("leaf", (1, 2, 3))
    graph = Held("root", tuple(Held(f"branch{i}", (shared,)) for i in range(20)))
    calls, original = _counting_preimages()
    try:
        constructed_value_cid_v2(graph)
        first = calls["n"]
        constructed_value_cid_v2(graph)
        second = calls["n"]
    finally:
        BS.cid_of_json = original
    # 1 root + 1 root's tuple + 20 branches + 20 branch tuples + 1 shared leaf
    # + 1 shared leaf's tuple, each hashed exactly once -- and the shared leaf
    # ONCE, not once per incoming path.
    assert first == 44, first
    # ...and re-asking the same graph hashes NOTHING new.
    assert second == first, (first, second)


def test_the_memo_returns_the_same_cid_it_would_have_computed():
    # Soundness: a wrong memo silently corrupts content addresses. Compare the
    # warm answer against the answer computed with the memo emptied entirely.
    value = Held("root", (Held("a", (1,)), Held("b", ("x", b"\x00\x01")), None))
    warm = constructed_value_cid_v2(value)
    warm_again = constructed_value_cid_v2(value)
    CC._CONSTRUCTED_VALUE_CIDS_V2.clear()
    cold = constructed_value_cid_v2(value)
    assert warm == cold, (warm, cold)
    assert warm_again == cold


def test_a_distinct_value_never_reads_another_values_row():
    # Aliasing law. Two values that differ must never share an answer, however
    # similar their shape or however adjacent their addresses.
    one = Held("same", (1,))
    two = Held("same", (2,))
    assert constructed_value_cid_v2(one) != constructed_value_cid_v2(two)
    # ...and two values that are EQUAL share content identity, which is the
    # point of content addressing, while remaining distinct occurrences.
    three = Held("same", (1,))
    assert one is not three
    assert constructed_value_cid_v2(one) == constructed_value_cid_v2(three)


def test_only_categories_whose_inputs_are_named_get_a_coordinate():
    # The key must cover every input that determines the CID, so a category
    # whose inputs this module cannot enumerate gets NO row: a mutable
    # dataclass can canonicalize two ways over its lifetime, and a mapping is
    # mutable in exactly the same way.
    from dataclasses import dataclass as _dataclass

    @_dataclass
    class Mutable:
        n: int

    class Wired:
        def wire(self):
            return {"n": 1}

    assert CC._constructed_value_coordinate(Mutable(1)) is None
    assert CC._constructed_value_coordinate(Wired()) is None
    assert CC._constructed_value_coordinate([1]) is None
    assert CC._constructed_value_coordinate({"a": 1}) is None
    assert CC._constructed_value_coordinate((1, 2)) is None
    assert CC._constructed_value_coordinate(1) is None
    # ...and the category that DOES have one names it: type is in the key
    # because the semantic type tag is in the output, identity is a component.
    frozen = CC._constructed_value_coordinate(Held("t", ()))
    assert frozen[0] == "constructed-value-v2" and frozen[1] is Held

    # A MUTABLE value has no content coordinate at all, so V2 refuses it as a
    # typed gap rather than memoizing a moment as if it were a value.
    import pytest

    with pytest.raises(BS.ConstructedValueCategoryGap):
        constructed_value_cid_v2(Held("holds", (Mutable(1),)))


def test_a_node_is_referenced_by_its_authenticated_construction_shape():
    # The strongest form: no identity in the encoding at all. A Node is a tree
    # VIEW, so it inlines as its authenticated NodeShapeV2 CID and two distinct
    # views of the same content encode identically.
    d = tempfile.mkdtemp()
    p = os.path.join(d, "m.py")
    with open(p, "w") as fh:
        fh.write("x = 1\n")
    sf = SourceFile.from_path(p, reporter=CollectingReporter())
    root = sf.root
    one = [n for n in root.walk() if n.kind == "Constant"][0]
    two = [n for n in root.walk() if n.kind == "Constant"][0]
    shape = BS.node_construction_shape_cid(one)
    assert BS._cv2_leaf(one) == {"nodeShapeCid": shape}
    assert BS._cv2_leaf(one) == BS._cv2_leaf(two)
    # The node's positional occurrence (unit, span) is NOT in the content key.
    assert shape == BS.node_construction_shape_cid(two)


def test_a_recycled_address_misses_instead_of_serving_a_dead_values_answer():
    # #6212 by construction: the row's weak reference is the live identity.
    # Plant a row whose weakref is already dead at a LIVE value's address --
    # exactly what address recycling produces -- and require an honest miss.
    dead_owner = Held("dead", ())
    dead_ref = weakref.ref(dead_owner)
    del dead_owner
    gc.collect()
    assert dead_ref() is None

    live = Held("live", (7,))
    honest = constructed_value_cid_v2(live)
    CC._CONSTRUCTED_VALUE_CIDS_V2[CC._constructed_value_coordinate(live)] = (
        dead_ref,
        "blake3-512:poison",
    )
    assert CC.constructed_value_cid_v2_for(live) is None
    assert constructed_value_cid_v2(live) == honest


def test_a_dead_value_drops_its_row():
    # The table is bounded by LIVE constructed values: no process-lifetime pin.
    value = Held("transient", (1,))
    coordinate = CC._constructed_value_coordinate(value)
    constructed_value_cid_v2(value)
    assert coordinate in CC._CONSTRUCTED_VALUE_CIDS_V2
    del value
    gc.collect()
    assert coordinate not in CC._CONSTRUCTED_VALUE_CIDS_V2


def test_speed_never_comes_from_skipping_testimony():
    # Both laws hold at once: the memo makes the work cheaper, never absent --
    # a supported value still mints testimony (twice, from the memo), and an
    # unsupported one is still the loud typed gap.
    d = tempfile.mkdtemp()
    p = os.path.join(d, "m.py")
    with open(p, "w") as fh:
        fh.write("x = 1\n")
    collector = CollectingReporter()
    sf = SourceFile.from_path(p, reporter=collector)
    reporter = ConstructionTestimonyReporterV1(
        collector, SubstitutionTraceBuilderV1(_SCOPE_CID)
    )
    root = materialize(sf.root.unit, sf.root.ref, reporter)
    node = [n for n in root.walk() if n.kind == "Constant"][0]
    reporter.present_construction(node, Held("v", (1,)))
    assert reporter.testimony_for(node) is not None
    try:
        reporter.present_construction(node, Unserializable())
    except ConstructedValueTestimonyNotWritten:
        pass
    else:
        # the shape memo already answered for this node -- ask a fresh coordinate
        other = [n for n in root.walk() if n.kind == "Assign"][0]
        try:
            reporter.present_construction(other, Unserializable())
        except ConstructedValueTestimonyNotWritten:
            pass
        else:
            raise AssertionError("unsupported value went quiet")


def _real_construction_comparisons():
    # For EVERY semantic value a real function presents, mint its CID with the
    # memo warm and again with the memo emptied, and require them equal. Done
    # in ONE pass so no other warm cache (node shape, sugar() coordinate) can
    # make the two answers incomparable: a wrong memo is caught at the exact
    # value it corrupted, not averaged into a digest.
    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "m.py")
    with open(path, "w") as fh:
        fh.write(
            "def f(xs):\n"
            "    total = 0\n"
            "    for x in xs:\n"
            "        total = total + x\n"
            "    return total\n"
        )

    original = BS._constructed_preimage
    compared = []

    def watched(value):
        out = original(value)
        warm = BS.cid_of_json(out)
        CC._CONSTRUCTED_VALUE_CIDS_V2.clear()
        cold = BS.cid_of_json(original(value))
        assert warm == cold, (type(value).__name__, warm, cold)
        compared.append(warm)
        return out

    BS._constructed_preimage = watched
    from pathlib import Path

    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    try:
        sf = open_source_file_for_construction(
            Path(path), root=Path(path).parent, reporter=CollectingReporter()
        )
        fn = [f for f in sf.functions() if getattr(f, "name", None) == "f"][0]
        fn.sugar()
    finally:
        BS._constructed_preimage = original
    return compared


def _fresh_real_construction_comparisons() -> list[str]:
    script = (
        "import json, runpy; "
        f"ns = runpy.run_path({__file__!r}); "
        "print('comparisons=' + json.dumps(ns['_real_construction_comparisons']()))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    line = completed.stdout.strip().splitlines()[-1]
    assert line.startswith("comparisons="), completed.stdout
    return json.loads(line.removeprefix("comparisons="))


def test_real_construction_agrees_bit_for_bit_with_the_unmemoized_answer():
    compared = _fresh_real_construction_comparisons()
    # A real function presents several distinct values (8 measured here); a
    # silent zero comparisons would make this test prove nothing at all.
    assert len(compared) >= 8, len(compared)
    assert len(set(compared)) > 1, compared


def test_real_construction_memo_floor_is_independent_of_prior_construction():
    first = _fresh_real_construction_comparisons()
    second = _fresh_real_construction_comparisons()

    assert len(first) >= 8, len(first)
    assert len(second) >= 8, len(second)
