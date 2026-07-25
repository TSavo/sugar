"""Store-target assignments (`obj.a = e`, `xs[i] = e`) attach a typed red
runtime-effect witness at the TREE fragment site (the fragment-type seam,
#5994-adjacent).

A store has TWO outcomes, runtime-selected: it completes (Python continues to
the next statement) or it halts. So the body reduces to an `ExitSet`, not to one
linear outcome. Everything asserted below is a fact about the COMPLETED arm --
the block kept reducing, the returned value is unaffected, the witness names the
real target -- and the assertions are unchanged; only the navigation to that arm
is explicit now. The halt arm and the composition laws are asserted in
sugar-lift-py-tests/tests/test_store_outcome_composition.py."""

import tempfile
from dataclasses import replace

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.effect import (
    AttributeStoreRuntimeEffect,
    RaiseEffect,
    SubscriptStoreRuntimeEffect,
)
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing
from sugar_source_tree.fragment import SourceFragment as TreeSourceFragment
from sugar_source_tree.tree import SourceFile


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


from sugar_lift_py_tests.outcome.exit_set import (
    sole_completed_outcome as _completed,
)


def _entries(src):
    outcome = _completed(_fn(src).sugar().desugar())
    return outcome.value.record.statements


class _CountingSugar(Sugar):
    def __init__(self, delegate, calls):
        self.delegate = delegate
        self.calls = calls

    @classmethod
    def witnesses(cls):
        return NotVerdictBearing(cls.__name__, "test probe", "counts one reduction")

    def desugar(self, ctx=None):
        self.calls.append(1)
        return self.delegate.desugar(ctx)


class _OutcomeSugar(Sugar):
    def __init__(self, outcome, calls):
        self.outcome = outcome
        self.calls = calls

    @classmethod
    def witnesses(cls):
        return NotVerdictBearing(cls.__name__, "test probe", "returns pinned outcome")

    def desugar(self, ctx=None):
        del ctx
        self.calls.append(1)
        return self.outcome


def test_attribute_store_lifts_a_red_effect_and_the_block_continues():
    entries = _entries("def A(o, v):\n    o.a = v\n    return v\n")
    red = [e for e in entries if isinstance(e, Incomplete)]
    assert len(red) == 1
    assert isinstance(red[0].effect, AttributeStoreRuntimeEffect)
    # the block kept reducing: a ReturnValue entry rides beside the effect
    assert any(type(e).__name__ == "ReturnValue" for e in entries)


def test_attribute_store_post_out_equals_the_returned_value():
    v = _completed(
        _fn("def A(o, v):\n    o.a = v\n    return v\n").sugar().desugar()
    ).value
    post = v.post()
    assert post.name == "="
    assert post.args[0].name == "out"
    assert post.args[1].name == "v"


def test_subscript_store_lifts_a_red_effect_and_the_block_continues():
    entries = _entries("def A(xs, i, v):\n    xs[i] = v\n    return v\n")
    red = [e for e in entries if isinstance(e, Incomplete)]
    assert len(red) == 1
    assert isinstance(red[0].effect, SubscriptStoreRuntimeEffect)
    assert any(type(e).__name__ == "ReturnValue" for e in entries)


def test_subscript_store_post_out_equals_the_returned_value():
    v = _completed(
        _fn("def A(xs, i, v):\n    xs[i] = v\n    return v\n").sugar().desugar()
    ).value
    post = v.post()
    assert post.name == "="
    assert post.args[0].name == "out"
    assert post.args[1].name == "v"


def test_attribute_store_witness_site_is_the_tree_fragment():
    """Discrimination: the effect's evidence names the right site AND the
    right target -- the witness address is the TREE's own fragment
    currency, not a reconstructed/factory one, and the operand cites the
    attribute actually stored."""
    entries = _entries("def A(o, v):\n    o.a = v\n    return v\n")
    (red,) = [e for e in entries if isinstance(e, Incomplete)]
    witness = red.effect.witness
    assert isinstance(witness.site, TreeSourceFragment)
    assert witness.site.text == "o.a = v"
    operand = repr(witness.runtime_operand.term)
    assert "python:attribute_store" in operand
    assert "name='o'" in operand
    assert "value='a'" in operand
    assert "name='v'" in operand
    assert "store_target" not in operand


def test_subscript_store_witness_names_the_index():
    entries = _entries("def A(xs, i, v):\n    xs[i] = v\n    return v\n")
    (red,) = [e for e in entries if isinstance(e, Incomplete)]
    witness = red.effect.witness
    assert isinstance(witness.site, TreeSourceFragment)
    assert "store_target[i]" in repr(witness.runtime_operand.term)


def test_two_stores_in_one_block_both_lift_and_discriminate_by_target():
    entries = _entries("def A(o, v, w):\n    o.a = v\n    o.b = w\n    return v\n")
    red = [e for e in entries if isinstance(e, Incomplete)]
    assert len(red) == 2
    operands = {repr(e.effect.witness.runtime_operand.term) for e in red}
    assert any("value='a'" in operand and "name='v'" in operand for operand in operands)
    assert any("value='b'" in operand and "name='w'" in operand for operand in operands)
    assert all("store_target" not in operand for operand in operands)


def test_symbolic_attribute_store_owns_real_receiver_and_value_children():
    function = _fn(
        "def arbitrary(symbolic_receiver, constructed_value):\n"
        "    symbolic_receiver.payload = constructed_value\n"
    )
    assignment = next(node for node in function.walk() if node.kind == "Assign")
    sugar = assignment.sugar()

    assert sugar.receiver == assignment.targets[0].value.sugar()
    assert sugar.value == assignment.value.sugar()


def test_symbolic_attribute_store_witnesses_real_receiver_and_value_terms():
    function = _fn(
        "def arbitrary(symbolic_receiver, constructed_value):\n"
        "    symbolic_receiver.payload = constructed_value\n"
    )
    assignment = next(node for node in function.walk() if node.kind == "Assign")
    outcome = assignment.sugar().desugar()

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, AttributeStoreRuntimeEffect)
    operation = repr(outcome.effect.witness.operation)
    assert "symbolic_receiver" in operation
    assert "constructed_value" in operation
    assert "payload" in operation


def test_chained_attribute_store_reuses_one_constructed_rhs():
    function = _fn(
        "def arbitrary(symbolic_receiver, constructed_value):\n"
        "    renamed = symbolic_receiver.payload = constructed_value\n"
        "    return renamed\n"
    )
    assignment = next(node for node in function.walk() if node.kind == "Assign")
    sugar = assignment.sugar()
    calls = []
    counted = _CountingSugar(sugar.value, calls)
    rewritten = replace(
        sugar,
        value=counted,
        stores=tuple(replace(store, value=counted) for store in sugar.stores),
    )

    rewritten.desugar()
    assert calls == [1]


def test_rhs_constructs_before_halted_receiver_and_store_does_not_continue():
    function = _fn(
        "def arbitrary(symbolic_receiver, constructed_value):\n"
        "    symbolic_receiver.payload = constructed_value\n"
    )
    assignment = next(node for node in function.walk() if node.kind == "Assign")
    sugar = assignment.sugar()
    receiver_calls = []
    value_calls = []
    halt = Incomplete(RaiseEffect(exception_name="ArbitraryError"))
    rewritten = replace(
        sugar,
        receiver=_OutcomeSugar(halt, receiver_calls),
        value=_CountingSugar(sugar.value, value_calls),
    )

    assert rewritten.desugar() is halt
    assert value_calls == [1]
    assert receiver_calls == [1]


if __name__ == "__main__":
    test_attribute_store_lifts_a_red_effect_and_the_block_continues()
    test_attribute_store_post_out_equals_the_returned_value()
    test_subscript_store_lifts_a_red_effect_and_the_block_continues()
    test_subscript_store_post_out_equals_the_returned_value()
    test_attribute_store_witness_site_is_the_tree_fragment()
    test_subscript_store_witness_names_the_index()
    test_two_stores_in_one_block_both_lift_and_discriminate_by_target()
    print("ok: store-target assignments lift typed red witnessed by the tree fragment")
