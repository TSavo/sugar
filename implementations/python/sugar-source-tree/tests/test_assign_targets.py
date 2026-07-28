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

from sugar_lift_py_tests.effect import AttributeStoreRuntimeEffect
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


def _completed_entries(src):
    """Entries recorded on the arm where every store completed.

    A store is not infallible, so a body containing one partitions into a
    completed and a halted arm and reduces to an ExitSet. What each store
    witnesses, and the source order of several stores, are facts about the
    completed arm; the halt faces and the composition laws are asserted in
    sugar-lift-py-tests/tests/test_store_outcome_composition.py.
    """
    from sugar_lift_py_tests.outcome.exit_set import sole_completed_outcome

    outcome = sole_completed_outcome(_fn(src).sugar().desugar())
    return outcome.value.record.statements


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
    entries = _completed_entries(
        "def arbitrary():\n    renamed = o.field = 5\n    return renamed\n"
    )
    red = [entry for entry in entries if isinstance(entry, Incomplete)]
    assert len(red) == 1
    assert isinstance(red[0].effect, AttributeStoreRuntimeEffect)


def test_mixed_chain_never_fabricates_a_completed_subscript_store():
    with pytest.raises(SugarNotWritten, match="undischarged subscript store"):
        _fn(
            "def arbitrary(xs):\n"
            "    renamed = o.field = xs[0] = 7\n"
            "    return renamed\n"
        ).sugar().desugar()


def test_nested_tuple_target_binds_each_structural_projection():
    post = _post(
        "def A():\n    (a, (b, c)), d = (1, (2, 3)), 4\n    return a + b + c + d\n"
    )
    assert post.args[1].value == 10


def test_nested_tuple_projection_pairing_discriminates():
    left = (
        _post("def A():\n    (a, (b, c)) = (1, (2, 4))\n    return b - c\n")
        .args[1]
        .value
    )
    right = (
        _post("def A():\n    (a, (b, c)) = (1, (4, 2))\n    return b - c\n")
        .args[1]
        .value
    )
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


def test_non_display_rhs_constructs_and_retains_its_arity_obligation():
    # Construction must be total enough for an unreachable branch to coexist
    # with a closed guard. If execution reaches the dynamic unpack, its unknown
    # iteration/cardinality semantics remain loud rather than fabricating binds.
    #
    # "Loud" used to mean SugarNotWritten -- a refusal that banked as measured
    # while saying nothing about WHAT was owed. #6316 drained it: the demand is
    # now a typed effect naming the exact obligation
    # `python:unpack.destructure(term, arity)`. Same law, one rung up, and the
    # assertion is correspondingly stronger.
    from sugar_lift_py_tests.effect import SequenceUnpackRuntimeEffect

    function = _fn("def A(p):\n    a, b = p\n    return a\n")
    sugar = function.sugar()

    out = sugar.desugar()
    assert isinstance(out, Incomplete)
    assert isinstance(out.effect, SequenceUnpackRuntimeEffect)
    assert "exactly 2 members" in out.effect.reason
    assert "(a, b)" in out.effect.reason


def test_display_rhs_arity_mismatch_is_still_a_refusal_not_an_effect():
    # DISCRIMINATING against the change above: a DISPLAY right-hand side has
    # lift-time cardinality, so `a, b = (1, 2, 3)` is decidably wrong and must
    # NOT be softened into the runtime-cardinality effect. Only the undecidable
    # count becomes an obligation.
    with pytest.raises(SugarNotWritten):
        _fn("def A():\n    a, b = (1, 2, 3)\n    return a\n").sugar()


def test_mixed_chained_targets_stay_loud():
    # x is a plain Name but the second target is a tuple -- mixed shapes
    # never get a partial binding.
    with pytest.raises(SugarNotWritten):
        _fn("def A():\n    x = (a, b) = (1, 2)\n    return x\n").sugar()


def test_attribute_store_target_lifts_a_typed_red_effect():
    entries = _completed_entries("def A():\n    o.a = 1\n    return 1\n")
    red = [e for e in entries if isinstance(e, Incomplete)]
    assert len(red) == 1
    assert isinstance(red[0].effect, AttributeStoreRuntimeEffect)


def test_subscript_store_target_retains_setitem_demand_without_caller():
    from sugar_lift_py_tests.outcome import NativeOperationExitCarrierV1

    pending = _fn("def A(xs):\n    xs[0] = 1\n    return xs\n").sugar().desugar()

    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setitem"
    assert pending.demand.operand_coordinate_cids[0] is not None
    assert pending.demand.operand_coordinate_cids[1:] == (None, None)


def test_subscript_store_producer_retains_receiver_key_and_rhs():
    function = _fn("def A(xs, key, value):\n    xs[key] = value\n")
    assignment = next(node for node in function.walk() if node.kind == "Assign")

    store = assignment.sugar()

    assert type(store).__name__ == "SubscriptStoreEffectSugar"
    assert store.receiver.site.text == "xs"
    assert store.index.site.text == "key"
    assert store.value.site.text == "value"


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
    test_subscript_store_target_retains_setitem_demand_without_caller()
    print(
        "ok: tuple/chained assign destructures; starred/nested stay loud; "
        "subscript stores require setitem testimony"
    )
