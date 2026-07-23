"""Store-target assignments (`obj.a = e`, `xs[i] = e`) attach a typed red
runtime-effect witness at the TREE fragment site (the fragment-type seam,
#5994-adjacent). The store completed -- Python continues -- so the block
keeps reducing past it (see outcome/incomplete.py::
_effect_continues_control_flow); the returned value is unaffected."""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.effect import (
    AttributeStoreRuntimeEffect,
    SubscriptStoreRuntimeEffect,
)
from sugar_lift_py_tests.outcome import Incomplete
from sugar_source_tree.fragment import SourceFragment as TreeSourceFragment
from sugar_source_tree.tree import SourceFile


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def _entries(src):
    outcome = _fn(src).sugar().desugar()
    return outcome.value.record.statements


def test_attribute_store_lifts_a_red_effect_and_the_block_continues():
    entries = _entries("def A(o, v):\n    o.a = v\n    return v\n")
    red = [e for e in entries if isinstance(e, Incomplete)]
    assert len(red) == 1
    assert isinstance(red[0].effect, AttributeStoreRuntimeEffect)
    # the block kept reducing: a ReturnValue entry rides beside the effect
    assert any(type(e).__name__ == "ReturnValue" for e in entries)


def test_attribute_store_post_out_equals_the_returned_value():
    v = _fn("def A(o, v):\n    o.a = v\n    return v\n").sugar().desugar().value
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
    v = _fn("def A(xs, i, v):\n    xs[i] = v\n    return v\n").sugar().desugar().value
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
    assert "store_target.a" in repr(witness.runtime_operand.term)


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
    assert any("store_target.a" in o for o in operands)
    assert any("store_target.b" in o for o in operands)


if __name__ == "__main__":
    test_attribute_store_lifts_a_red_effect_and_the_block_continues()
    test_attribute_store_post_out_equals_the_returned_value()
    test_subscript_store_lifts_a_red_effect_and_the_block_continues()
    test_subscript_store_post_out_equals_the_returned_value()
    test_attribute_store_witness_site_is_the_tree_fragment()
    test_subscript_store_witness_names_the_index()
    test_two_stores_in_one_block_both_lift_and_discriminate_by_target()
    print("ok: store-target assignments lift typed red witnessed by the tree fragment")
