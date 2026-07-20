"""PROBE (#5940): both arms of node.sugar(), exercised on real parsed nodes.

Every subject case runs both sides where a discriminator exists: the
resolving side names the completion, the non-resolving side shows the
loud arm (CompletionGap), and the ambiguity arm is shown to die at
registration for sole completions and at resolve for a broken family.
"""

from __future__ import annotations

import pytest

from sugar_source_tree.completion import (
    Completion,
    CompletionAmbiguous,
    CompletionGap,
    registered,
)
from sugar_source_tree.completion_probe import (
    AddOpCompletion,
    IfCompletion,
    KeywordCallCompletion,
    LenCallCompletion,
    MethodCallCompletion,
    PlainCallCompletion,
    WhileCompletion,
    WhileElseCompletion,
)
from sugar_source_tree.nodes import BinOp, Call, If, Node, While
from sugar_source_tree.tree import SourceFile


def _nodes_of(source: str, cls: type, tmp_path) -> list:
    path = tmp_path / "probe_case.py"
    path.write_text(source, encoding="utf-8")
    file = SourceFile.from_path(path)
    return [n for n in file.nodes() if isinstance(n, cls)]


# -- If: sole; owns deleted --------------------------------------------------


def test_if_resolves_sole_completion(tmp_path):
    (node,) = _nodes_of("if x:\n    pass\n", If, tmp_path)
    assert node.sugar() is IfCompletion


def test_elif_is_a_nested_if_and_resolves(tmp_path):
    nodes = _nodes_of("if x:\n    pass\nelif y:\n    pass\n", If, tmp_path)
    assert len(nodes) == 2
    assert all(n.sugar() is IfCompletion for n in nodes)


# -- While: closed 2-family over node.orelse --------------------------------


def test_while_partition_both_cells(tmp_path):
    (plain,) = _nodes_of("while x:\n    pass\n", While, tmp_path)
    (with_else,) = _nodes_of(
        "while x:\n    pass\nelse:\n    pass\n", While, tmp_path
    )
    assert plain.sugar() is WhileCompletion
    assert with_else.sugar() is WhileElseCompletion


# -- Call: the closed family ------------------------------------------------


def test_call_family_each_cell(tmp_path):
    (kw,) = _nodes_of("f(a, k=1)\n", Call, tmp_path)
    (method,) = _nodes_of("obj.m(a)\n", Call, tmp_path)
    (length,) = _nodes_of("len(xs)\n", Call, tmp_path)
    (plain,) = _nodes_of("f(a)\n", Call, tmp_path)
    assert kw.sugar() is KeywordCallCompletion
    assert method.sugar() is MethodCallCompletion
    assert length.sugar() is LenCallCompletion
    assert plain.sugar() is PlainCallCompletion


def test_call_computed_callable_hits_gap_arm(tmp_path):
    (node,) = _nodes_of("fs[0](a)\n", Call, tmp_path)
    with pytest.raises(CompletionGap) as err:
        node.sugar()
    assert "covers no cell" in str(err.value)


# -- BinOp: operand refinement; non-Add is the gap arm ----------------------


def test_binop_add_resolves_and_sub_gaps(tmp_path):
    (add,) = _nodes_of("a + b\n", BinOp, tmp_path)
    (sub,) = _nodes_of("a - b\n", BinOp, tmp_path)
    assert add.sugar() is AddOpCompletion
    with pytest.raises(CompletionGap):
        sub.sugar()


# -- the gap arm for a class with no completion at all ----------------------


def test_unregistered_class_gaps_loudly(tmp_path):
    from sugar_source_tree.nodes import Assert

    (node,) = _nodes_of("assert x\n", Assert, tmp_path)
    with pytest.raises(CompletionGap) as err:
        node.sugar()
    assert "nothing completes me" in str(err.value)


# -- the ambiguity arm ------------------------------------------------------


def test_second_sole_completion_dies_at_registration():
    with pytest.raises(CompletionAmbiguous):

        class SecondIfCompletion(Completion):
            completes = If

    # the failed registration left no residue
    assert registered()[If] == (IfCompletion,)


def test_broken_family_panics_ambiguous_at_resolve(tmp_path):
    class _ProbeNode2(Node):
        pass

    class _Cell1(Completion):
        completes = _ProbeNode2
        sole = False

        @classmethod
        def refines(cls, node):
            return True

    class _Cell2(Completion):
        completes = _ProbeNode2
        sole = False

        @classmethod
        def refines(cls, node):
            return True

    donor = _nodes_of("pass\n", Node, tmp_path)[0]
    fake = _ProbeNode2(unit=donor.unit, ref=donor.ref)
    with pytest.raises(CompletionAmbiguous) as err:
        fake.sugar()
    assert "not disjoint" in str(err.value) or "refine within family" in str(err.value)
