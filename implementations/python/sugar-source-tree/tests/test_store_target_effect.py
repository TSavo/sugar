"""Store-target assignments preserve their target-specific obligations.

Attribute-store coverage here reads the one undecided attribute mutation's
completes atom and halt (#7757 NEW-4). Subscript
store coverage pins the stronger rule: absent ``__setitem__`` testimony it
stays loud and cannot borrow ``__getitem__`` or a generic completed arm."""

import tempfile
from dataclasses import replace

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.effect import (
    RaiseEffect,
    UndeterminedRaiseEffect,
)
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing
from sugar_source_tree.fragment import SourceFragment as TreeSourceFragment
from sugar_source_tree.panic import SugarNotWritten
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions())


from sugar_lift_py_tests.outcome.exit_set import (
    sole_completed_value as _completed,
)


def _entries(src):
    return _completed(_fn(src).sugar().desugar()).record.statements


def _red(entries) -> list:
    """The halted arms of the recorded entries in which every arm halts."""
    return [
        halt
        for entry in entries
        if isinstance(entry, ExitSet) and entry.halts() == entry.exits
        for halt in entry.halts()
    ]


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
    # A canned statement binds nothing before its halts: the block's prefix
    # is their record.
    halts_at_statement_head = True

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


# ``o`` is free only because a star import the lifter cannot read may bind it:
# a name nothing in the module binds is a NameError halt, and no store runs.
_FREE = "from unread_module import *\n"


def _undecided_stores(outcome) -> list:
    """The halts of the one undecided attribute mutation (#7757 NEW-4)."""
    return [
        halt
        for halt in outcome.halts()
        if getattr(halt.effect, "producer_node_owner", None) == "UndecidedSetattr"
    ]


def test_attribute_store_lifts_a_red_effect_and_the_block_continues():
    # Free undecided ``o``: the one undecided attribute mutation, as a formal
    # receiver's store is (``store_effect_sugar.attribute_mutation``).
    outcome = _fn(_FREE + "def A(v):\n    o.a = v\n    return v\n").sugar().desugar()
    red = _undecided_stores(outcome)
    assert len(red) == 1
    assert isinstance(red[0].effect, UndeterminedRaiseEffect)
    # the block kept reducing on the completed arm: a ReturnValue entry
    entries = _completed(outcome).record.statements
    assert any(type(e).__name__ == "ReturnValue" for e in entries)


def test_attribute_store_post_out_equals_the_returned_value():
    v = _completed(_fn("def A(v):\n    o.a = v\n    return v\n").sugar().desugar())
    post = v.post()
    assert post.name == "="
    assert post.args[0].name == "out"
    assert post.args[1].name == "v"


def _subscript_store_outcome():
    """``xs[i] = v`` on a formal: the one item mutation
    (``store_effect_sugar.item_mutation``, #7757 step 7), never a carrier
    waiting on a caller's actuals -- the dispatched ``__setitem__`` where
    ``xs``'s class is an input, the undecided mutation where it is not."""
    outcome = _fn("def A(xs, i, v):\n    xs[i] = v\n    return v\n").sugar().desugar()
    return outcome


def test_subscript_store_on_a_formal_keeps_its_halt_and_waits_on_no_caller():
    text = repr(_subscript_store_outcome())

    # The store's own halt face is kept: the dispatched call's, or the
    # undecided mutation's.
    assert "UnknownCallee:dispatch:__setitem__" in text or "UndecidedSetitem" in text


def test_subscript_store_does_not_borrow_the_read_path():
    text = repr(_subscript_store_outcome())

    assert "__setitem__" in text
    assert "__getitem__" not in text


def test_attribute_store_witness_site_is_the_tree_fragment():
    """Discrimination: the store's halt names the right site AND its guard
    the right target -- the site is the TREE's own fragment currency, not a
    reconstructed/factory one, and the store's operation
    (``python:setattr(<receiver>, "<attr>", <key>)``) cites the attribute
    actually stored.  An undecided store states nothing about the value."""
    outcome = _fn(_FREE + "def A(v):\n    o.a = v\n    return v\n").sugar().desugar()
    (red,) = _undecided_stores(outcome)
    assert isinstance(red.effect.site, TreeSourceFragment)
    assert red.effect.site.text == "o.a = v"
    operand = repr(red.guard)
    assert "python:setattr" in operand
    assert "name='o'" in operand
    assert "value='a'" in operand
    assert "store_target" not in operand


def test_subscript_store_demand_names_all_three_formal_coordinates():
    pending = _pending_subscript_store()

    assert len(pending.demand.operand_coordinate_cids) == 3
    assert len(set(pending.demand.operand_coordinate_cids)) == 3


def test_two_stores_in_one_block_both_lift_and_discriminate_by_target():
    source = _FREE + "def A(v, w):\n    o.a = v\n    o.b = w\n    return v\n"
    outcome = _fn(source).sugar().desugar()
    red = _undecided_stores(outcome)
    assert len(red) == 2
    operands = {repr(e.guard) for e in red}
    assert any("value='a'" in operand for operand in operands)
    assert any("value='b'" in operand for operand in operands)
    assert all("store_target" not in operand for operand in operands)


def test_symbolic_attribute_store_owns_real_receiver_and_value_children():
    function = _fn(
        "def arbitrary(constructed_value):\n"
        "    symbolic_receiver.payload = constructed_value\n"
    )
    assignment = next(node for node in function.walk() if node.kind == "Assign")
    sugar = assignment.sugar()

    assert sugar.receiver == assignment.targets[0].value.sugar()
    assert sugar.value == assignment.value.sugar()


def test_symbolic_attribute_store_witnesses_real_receiver_and_value_terms():
    # Free undecided receiver: the one undecided attribute mutation (#7757
    # NEW-4), its receiver and attribute named by its completes atom.
    function = _fn(
        _FREE + "def arbitrary(constructed_value):\n"
        "    symbolic_receiver.payload = constructed_value\n"
    )
    assignment = next(node for node in function.walk() if node.kind == "Assign")
    outcome = assignment.sugar().desugar()

    (halt,) = _undecided_stores(outcome)
    # The halted face raises something undetermined; the store's operation
    # is the atom its guard cites.
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    operation = repr(halt.guard)
    assert "python:setattr" in operation
    assert "symbolic_receiver" in operation
    assert "payload" in operation


def test_chained_attribute_store_reuses_one_constructed_rhs():
    function = _fn(
        "def arbitrary(constructed_value):\n"
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
        "def arbitrary(constructed_value):\n"
        "    symbolic_receiver.payload = constructed_value\n"
    )
    assignment = next(node for node in function.walk() if node.kind == "Assign")
    sugar = assignment.sugar()
    receiver_calls = []
    value_calls = []
    halt = ExitSet.halted(
        RaiseEffect.for_builtin(
            "RuntimeError",
            occurrence="implementations/python/sugar-source-tree/tests/test_store_target_effect.py:205:0",
        )
    )
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
