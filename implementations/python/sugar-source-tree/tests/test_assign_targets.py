"""`a, b = <display>` destructures against a matching Tuple/List rhs, and
`x = y = e` chains a single rhs to several names -- both are threaded by
substitute exactly like the single-Name case, so both go inert at the
meaning layer. Starred/nested targets and arity mismatches do not thread
and stay loud gaps. Store targets (attribute/subscript) are never bound --
they lift straight to a typed red runtime effect instead (the fragment-type
seam; see test_store_target_effect.py for the full witness/continuation
discipline)."""

import tempfile

import pytest

from sugar_lift_py_tests.effect import (
    AttributeStoreRuntimeEffect,
    SubscriptStoreRuntimeEffect,
)
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def _post(src):
    return _fn(src).sugar().desugar().value.post()


def test_tuple_destructure_assign_lifts_through():
    post = _post("def A():\n    a, b = (1, 2)\n    return a + b\n")
    assert post.args[1].value == 3


def test_tuple_destructure_discriminates_on_pairing():
    # Swap the pair -- a different sum, a different fact -- proves the
    # binding actually threads a AND b, not just "some" value.
    forward = _post("def A():\n    a, b = (1, 2)\n    return a - b\n").args[1].value
    swapped = _post("def A():\n    a, b = (2, 1)\n    return a - b\n").args[1].value
    assert forward == -1
    assert swapped == 1
    assert forward != swapped


def test_list_display_destructure_also_lifts():
    post = _post("def A():\n    a, b = [10, 20]\n    return a + b\n")
    assert post.args[1].value == 30


def test_chained_assign_binds_every_target():
    post = _post("def A():\n    x = y = 5\n    return x + y\n")
    assert post.args[1].value == 10


def test_starred_target_binds_real_prefix_rest_and_suffix_values():
    post = _post(
        "def A():\n"
        "    a, *rest, z = (1, 2, 3, 4)\n"
        "    return a + rest[0] + rest[1] + z\n"
    )
    assert post.args[1].value == 10


def test_chained_assign_constructs_one_rhs_sugar_for_every_binding():
    function = _fn("def arbitrary():\n    renamed = other = 5\n")
    assignment = next(node for node in function.walk() if node.kind == "Assign")
    sugar = assignment.sugar()
    assert sugar.bindings[0][1] is sugar.bindings[1][1]


def test_chained_names_receive_distinct_runtime_binding_coordinates():
    function = _fn(
        "def arbitrary():\n    renamed = other = 5\n    return renamed + other\n"
    )
    trace = function.sugar().substitution_trace
    entries = dict(trace.records[0].post_bindings)
    assert (
        entries["renamed"].state.fragment.seal().cid
        == entries["other"].state.fragment.seal().cid
    )
    assert entries["renamed"].coordinate.cid != entries["other"].coordinate.cid


def test_mixed_chain_sequences_existing_store_obligation_and_name_binding():
    entries = (
        _fn("def arbitrary(o):\n    renamed = o.field = 5\n    return renamed\n")
        .sugar()
        .desugar()
        .value.record.statements
    )
    red = [entry for entry in entries if isinstance(entry, Incomplete)]
    assert len(red) == 1
    assert isinstance(red[0].effect, AttributeStoreRuntimeEffect)


def test_mixed_chain_preserves_each_store_face_in_source_order():
    entries = (
        _fn(
            "def arbitrary(o, xs):\n"
            "    renamed = o.field = xs[0] = 7\n"
            "    return renamed\n"
        )
        .sugar()
        .desugar()
        .value.record.statements
    )
    red = [entry for entry in entries if isinstance(entry, Incomplete)]
    assert [type(entry.effect) for entry in red] == [
        AttributeStoreRuntimeEffect,
        SubscriptStoreRuntimeEffect,
    ]


def test_nested_tuple_target_binds_each_structural_projection():
    post = _post(
        "def A():\n"
        "    (a, (b, c)), d = (1, (2, 3)), 4\n"
        "    return a + b + c + d\n"
    )
    assert post.args[1].value == 10


def test_nested_tuple_projection_pairing_discriminates():
    left = _post(
        "def A():\n    (a, (b, c)) = (1, (2, 4))\n    return b - c\n"
    ).args[1].value
    right = _post(
        "def A():\n    (a, (b, c)) = (1, (4, 2))\n    return b - c\n"
    ).args[1].value
    assert (left, right) == (-2, 2)


def test_nested_and_starred_targets_use_one_runtime_binding_entry_model():
    function = _fn(
        "def arbitrary():\n"
        "    (a, (b, *rest)), z = (1, (2, 3, 4)), 5\n"
        "    return a + b + rest[0] + rest[1] + z\n"
    )
    trace = function.sugar().substitution_trace
    first = trace.records[0]
    entries = dict(first.post_bindings)
    assert set(entries) == {"a", "b", "rest", "z"}
    assert len({entry.coordinate.cid for entry in entries.values()}) == 4
    paths = {
        name: tuple(entry.coordinate.preimage["projectionPath"])
        for name, entry in entries.items()
    }
    assert paths["a"][-4:] == ("tuple", 0, "tuple", 0)
    assert paths["b"][-4:] == ("tuple", 1, "tuple", 0)
    assert paths["rest"][-1] == "starred"
    assert paths["z"][-2:] == ("tuple", 1)


def test_arity_mismatch_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A():\n    a, b = (1, 2, 3)\n    return a\n").sugar()


def test_non_display_rhs_stays_loud():
    # The rhs is a Name, not a Tuple/List display -- no shape to destructure
    # against, so the tuple target is not threaded.
    with pytest.raises(SugarNotWritten):
        _fn("def A(p):\n    a, b = p\n    return a\n").sugar()


def test_mixed_chained_targets_stay_loud():
    # x is a plain Name but the second target is a tuple -- mixed shapes
    # never get a partial binding.
    with pytest.raises(SugarNotWritten):
        _fn("def A():\n    x = (a, b) = (1, 2)\n    return x\n").sugar()


def test_attribute_store_target_lifts_a_typed_red_effect():
    entries = (
        _fn("def A(o):\n    o.a = 1\n    return o\n")
        .sugar()
        .desugar()
        .value.record.statements
    )
    red = [e for e in entries if isinstance(e, Incomplete)]
    assert len(red) == 1
    assert isinstance(red[0].effect, AttributeStoreRuntimeEffect)


def test_subscript_store_target_lifts_a_typed_red_effect():
    entries = (
        _fn("def A(xs):\n    xs[0] = 1\n    return xs\n")
        .sugar()
        .desugar()
        .value.record.statements
    )
    red = [e for e in entries if isinstance(e, Incomplete)]
    assert len(red) == 1
    assert isinstance(red[0].effect, SubscriptStoreRuntimeEffect)


if __name__ == "__main__":
    test_tuple_destructure_assign_lifts_through()
    test_tuple_destructure_discriminates_on_pairing()
    test_list_display_destructure_also_lifts()
    test_chained_assign_binds_every_target()
    test_starred_target_stays_loud()
    test_nested_tuple_target_stays_loud()
    test_arity_mismatch_stays_loud()
    test_non_display_rhs_stays_loud()
    test_mixed_chained_targets_stay_loud()
    test_attribute_store_target_lifts_a_typed_red_effect()
    test_subscript_store_target_lifts_a_typed_red_effect()
    print(
        "ok: tuple/chained assign destructures; starred/nested stay loud; "
        "store targets lift typed red"
    )
