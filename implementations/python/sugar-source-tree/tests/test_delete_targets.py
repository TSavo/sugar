"""Delete constructs lexical unbinding and ordered target effects."""

import tempfile

import pytest

from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def _entries(src):
    return _fn(src).sugar().desugar().value.record.statements


def test_name_delete_unbinds_the_old_tree_binding_and_builds():
    value = (
        _fn("def A():\n    x = 1\n    del x\n    return x\n").sugar().desugar().value
    )
    post = value.post()
    assert post.args[1].name == "x"


@pytest.mark.parametrize(
    ("source", "effect_name", "operand_text"),
    [
        (
            "def A(o):\n    del o.attr\n    return o\n",
            "AttributeDeleteRuntimeEffect",
            "delete_target.attr",
        ),
        (
            "def A(d, k):\n    del d[k]\n    return d\n",
            "SubscriptDeleteRuntimeEffect",
            "delete_target[k]",
        ),
    ],
)
def test_store_delete_builds_typed_continuing_effect(source, effect_name, operand_text):
    entries = _entries(source)
    red = [entry for entry in entries if isinstance(entry, Incomplete)]
    assert len(red) == 1
    assert type(red[0].effect).__name__ == effect_name
    assert operand_text in repr(red[0].effect.witness.runtime_operand.term)
    assert any(type(entry).__name__ == "ReturnValue" for entry in entries)


def test_multi_target_delete_builds_each_target_in_source_order():
    entries = _entries(
        "def A(o, d, k):\n" "    x = 1\n" "    del x, o.attr, d[k]\n" "    return x\n"
    )
    red = [entry for entry in entries if isinstance(entry, Incomplete)]
    assert [type(entry.effect).__name__ for entry in red] == [
        "AttributeDeleteRuntimeEffect",
        "SubscriptDeleteRuntimeEffect",
    ]
    returned = [entry for entry in entries if type(entry).__name__ == "ReturnValue"]
    assert returned[0].value.to_term(owner="test").name == "x"


@pytest.mark.parametrize("target", ["(a, b)", "[a, b]"])
def test_nested_delete_target_grammar_stays_loud(target):
    with pytest.raises(SugarNotWritten):
        _fn(f"def A(a, b):\n    del {target}\n    return a\n").sugar()
