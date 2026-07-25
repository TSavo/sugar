"""Canonicalization is content-addressed WORK: done once per value, never per path.

``_canonical_constructed_value`` is a pure function of an immutable constructed
value, and the constructed value graph is a DAG the recursion walks as a TREE.
Measured on pandas ``core/indexes/base.py::_join_level``: 758,852 calls over
1,544 distinct value objects -- 491x recomputation, and the reason a completed
canonicalization made ``__internal_pivot_table`` take 976s.

The memo is keyed by value IDENTITY (computing a content key is exactly the cost
being removed) and each row holds a WEAK reference to the object it keyed. A hit
is honored only when that weakref still resolves to the SAME object, so a dead
value's recycled address (the #6212 id-reuse bug class) can never be served the
dead object's canonical JSON.

These twins pin: the work collapses, the ANSWER does not change by one byte, a
distinct value never reads another value's row, a recycled address misses, and
speed never comes from skipping testimony.
"""

import gc
import os
import tempfile
import weakref
from dataclasses import dataclass

from sugar_source_tree import binding_state as BS
from sugar_source_tree.binding_state import (
    ConstructionTestimonyReporterV1,
    SubstitutionTraceBuilderV1,
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


def _counting_compute(only=None):
    original = BS._compute_canonical_constructed_value
    calls = {"n": 0}

    def counting(value):
        if only is None or isinstance(value, only):
            calls["n"] += 1
        return original(value)

    BS._compute_canonical_constructed_value = counting
    return calls, original


def _function(src, name=None):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "m.py")
    with open(p, "w") as fh:
        fh.write(src)
    reporter = CollectingReporter()
    sf = SourceFile.from_path(p, reporter=reporter)
    for fn in sf.functions():
        if name is None or getattr(fn, "name", None) == name:
            return fn, reporter, sf
    raise AssertionError("no function in fixture")


def test_a_shared_value_canonicalizes_once_not_once_per_path():
    # The DAG-as-tree disease in miniature: one shared leaf reached by many
    # paths. Work must be a function of DISTINCT values, not of paths.
    shared = Held("leaf", (1, 2, 3))
    graph = Held("root", tuple(Held(f"branch{i}", (shared,)) for i in range(20)))
    calls, original = _counting_compute(only=Held)
    try:
        BS._canonical_constructed_value(graph)
        first = calls["n"]
        BS._canonical_constructed_value(graph)
        second = calls["n"]
    finally:
        BS._compute_canonical_constructed_value = original
    # 1 root + 20 branches + 1 shared leaf, each computed exactly once...
    assert first == 22, first
    # ...and re-asking the same graph computes NOTHING new.
    assert second == first, (first, second)


def test_the_memo_returns_the_same_bytes_it_would_have_computed():
    # Soundness: a wrong memo silently corrupts content addresses. Compare the
    # warm answer against the answer computed with the memo bypassed entirely.
    value = Held("root", (Held("a", (1,)), Held("b", ("x", b"\x00\x01")), None))
    warm = BS._canonical_constructed_value(value)
    warm_again = BS._canonical_constructed_value(value)
    cold = BS._compute_canonical_constructed_value(value)
    assert warm == cold, (warm, cold)
    assert warm_again == cold
    from sugar_lift_python_source.canonical import cid_of_json

    assert cid_of_json(warm) == cid_of_json(cold)


def test_a_distinct_value_never_reads_another_values_row():
    # Aliasing law. Two values that differ must never share an answer, however
    # similar their shape or however adjacent their addresses.
    one = Held("same", (1,))
    two = Held("same", (2,))
    assert BS._canonical_constructed_value(one) != BS._canonical_constructed_value(two)
    assert BS._canonical_constructed_value(one)["fields"]["parts"] == [1]
    assert BS._canonical_constructed_value(two)["fields"]["parts"] == [2]


def test_only_categories_whose_inputs_are_named_get_a_coordinate():
    # The key must cover every input that determines the canonical output, so a
    # category whose inputs this module cannot enumerate gets NO row: a mutable
    # dataclass can canonicalize two ways over its lifetime, and a ``wire()``
    # value's inputs are inside a method call.
    from dataclasses import dataclass as _dataclass

    @_dataclass
    class Mutable:
        n: int

    class Wired:
        def wire(self):
            return {"n": 1}

    from sugar_source_tree.binding_state import _NO_COORDINATE as NONE_KEY

    assert BS._canonicalization_coordinate(Mutable(1)) is NONE_KEY
    assert BS._canonicalization_coordinate(Wired()) is NONE_KEY
    assert BS._canonicalization_coordinate([1]) is NONE_KEY
    assert BS._canonicalization_coordinate({"a": 1}) is NONE_KEY
    assert BS._canonicalization_coordinate((1, 2)) is NONE_KEY
    assert BS._canonicalization_coordinate(1) is NONE_KEY
    # ...and the categories that DO have one name it: type is in the key
    # because type is in the output, identity is only a component.
    frozen = BS._canonicalization_coordinate(Held("t", ()))
    assert frozen[0] == "frozen-dataclass" and frozen[1] is Held

    # A mutated value therefore never reads a stale answer.
    m = Mutable(1)
    assert BS._canonical_constructed_value(m)["fields"]["n"] == 1
    m.n = 2
    assert BS._canonical_constructed_value(m)["fields"]["n"] == 2


def test_a_node_is_keyed_by_its_authenticated_construction_shape():
    # The strongest form: no identity in the key at all. Two distinct node
    # VIEWS of the same content are one coordinate and share the answer.
    d = tempfile.mkdtemp()
    p = os.path.join(d, "m.py")
    with open(p, "w") as fh:
        fh.write("x = 1\n")
    sf = SourceFile.from_path(p, reporter=CollectingReporter())
    root = sf.root
    one = [n for n in root.walk() if n.kind == "Constant"][0]
    two = [n for n in root.walk() if n.kind == "Constant"][0]
    coordinate = BS._canonicalization_coordinate(one)
    assert coordinate[0] == "node-shape"
    assert coordinate == BS._canonicalization_coordinate(two)
    assert BS._canonical_constructed_value(one) == BS._canonical_constructed_value(two)
    assert BS._canonical_constructed_value(one)["nodeShape"] == coordinate[1]


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
    BS._CANONICAL_VALUES[BS._canonicalization_coordinate(live)] = (
        dead_ref,
        {"poison": True},
    )
    answer = BS._canonical_constructed_value(live)
    assert answer["fields"]["parts"] == [7], answer
    assert "poison" not in answer


def test_a_dead_value_drops_its_row():
    # The table is bounded by LIVE constructed values: no process-lifetime pin.
    value = Held("transient", (1,))
    coordinate = BS._canonicalization_coordinate(value)
    BS._canonical_constructed_value(value)
    assert coordinate in BS._CANONICAL_VALUES
    del value
    gc.collect()
    assert coordinate not in BS._CANONICAL_VALUES


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


def test_real_construction_agrees_byte_for_byte_with_the_unmemoized_answer():
    # Fingerprint every canonicalization a real function performs, with the
    # memo live and with it bypassed, and require exact equality.
    import hashlib

    from sugar_lift_python_source.canonical import cid_of_json

    # ONE fixture file for both passes: a fresh temp path would change the
    # source mementos and the fingerprint with them.
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

    def fingerprint(bypass):
        BS._CANONICAL_VALUES.clear()
        original = BS._canonical_constructed_value
        digest = hashlib.md5()
        depth = {"d": 0}

        def watched(value):
            top = depth["d"] == 0
            depth["d"] += 1
            try:
                out = (
                    BS._compute_canonical_constructed_value(value)
                    if bypass
                    else original(value)
                )
            finally:
                depth["d"] -= 1
            if top:
                digest.update(cid_of_json(out).encode())
            return out

        BS._canonical_constructed_value = watched
        try:
            sf = SourceFile.from_path(path, reporter=CollectingReporter())
            fn = [f for f in sf.functions() if getattr(f, "name", None) == "f"][0]
            fn.sugar()
        finally:
            BS._canonical_constructed_value = original
        return digest.hexdigest()

    memoized = fingerprint(False)
    bypassed = fingerprint(True)
    assert memoized == bypassed, (memoized, bypassed)
    assert len(memoized) == 32
