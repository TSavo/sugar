"""The first node -> sugar seam, end to end.

A `1` in source, asked for its sugar, constructs an IntLiteralSugar and
desugars to the number as a floor term. No factory, no owns, no catalog:
the Constant node recognizes ITSELF (its value is an int) and constructs
its sugar directly. Every literal kind is converted: each is its own sugar,
picked by the value's exact type, and none is folded into the int leaf.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_python_source.source_oracle import path_source


def _constants(source: str):
    fh = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False)
    fh.write(source)
    fh.close()
    try:
        sf = SourceFile(path_source(fh.name))
        return [n for n in sf if n.kind == "Constant"]
    finally:
        Path(fh.name).unlink()


def test_an_int_literal_node_constructs_int_literal_sugar():
    (const,) = _constants("x = 1\n")
    sugar = const.sugar()
    assert isinstance(sugar, IntLiteralSugar)
    assert sugar.value == 1


def test_the_int_literal_sugar_desugars_to_the_number_as_a_term():
    (const,) = _constants("x = 42\n")
    outcome = const.sugar().desugar()
    assert outcome == ExitSet.completed(TermValue(42))


def test_the_sugar_carries_the_nodes_own_fragment_as_its_site():
    (const,) = _constants("x = 7\n")
    sugar = const.sugar()
    site, frag = sugar.site, const.fragment
    # the site IS the node's source fragment: same address (CID + span).
    # NOTE: .fragment mints a fresh equal object per call, so this is value
    # equality, not identity. Stable-identity .fragment (memoized, ask-twice-
    # same-object) is a real open item, deferred — the memento is the identity
    # that matters, and equal CID+span is the same address.
    assert site.source_cid == frag.source_cid
    assert (site.span.start, site.span.end) == (frag.span.start, frag.span.end)


def test_a_bool_is_not_an_int_literal_it_is_its_own_sugar():
    # bool is a subclass of int; the node must distinguish it. True and False
    # are their own sugars, never IntLiteralSugar(1) / IntLiteralSugar(0).
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    (true_const,) = _constants("x = True\n")
    true_sugar = true_const.sugar()
    assert isinstance(true_sugar, TrueBoolLiteralSugar)
    assert not isinstance(true_sugar, IntLiteralSugar)

    (false_const,) = _constants("x = False\n")
    false_sugar = false_const.sugar()
    assert isinstance(false_sugar, FalseBoolLiteralSugar)
    assert not isinstance(false_sugar, IntLiteralSugar)


def test_every_other_literal_kind_is_its_own_sugar_by_exact_type():
    # Every literal kind is converted: none is left to refuse, and none is
    # folded into the int leaf. The value's exact type picks the sugar.
    from sugar_lift_py_tests.sugar.bytes_literal_sugar import BytesLiteralSugar
    from sugar_lift_py_tests.sugar.complex_literal_sugar import ComplexLiteralSugar
    from sugar_lift_py_tests.sugar.ellipsis_literal_sugar import (
        EllipsisLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.none_literal_sugar import NoneLiteralSugar
    from sugar_lift_py_tests.sugar.real_literal_sugar import RealLiteralSugar
    from sugar_lift_py_tests.sugar.string_literal_sugar import StringLiteralSugar

    (real,) = _constants("x = 3.0\n")
    real_sugar = real.sugar()
    assert isinstance(real_sugar, RealLiteralSugar)
    assert not isinstance(real_sugar, IntLiteralSugar)
    assert real_sugar.value == 3.0 and type(real_sugar.value) is float

    for source, expected in (
        ("x = None\n", NoneLiteralSugar),
        ("x = 'a'\n", StringLiteralSugar),
        ("x = b'a'\n", BytesLiteralSugar),
        ("x = ...\n", EllipsisLiteralSugar),
        ("x = 2j\n", ComplexLiteralSugar),
    ):
        (const,) = _constants(source)
        sugar = const.sugar()
        assert isinstance(sugar, expected), source
        assert not isinstance(sugar, IntLiteralSugar), source


# ── the Sugar base contract: meaning-only, enforced by ABC ──────────────


def test_a_sugar_cannot_exist_without_desugar_and_witnesses():
    """The base's whole job: a sugar IS desugar + witnesses. ABC enforces it
    at construction — a half-sugar is unconstructable, no bookkeeping, no
    registry check. This replaced the factory-era __init_subclass__ gate."""
    from sugar_lift_py_tests.sugar.sugar_base import Sugar

    class HalfSugar(Sugar):  # defines neither desugar nor witnesses
        pass

    try:
        HalfSugar()
        assert False, "a sugar without desugar/witnesses must be unconstructable"
    except TypeError as exc:
        assert "abstract" in str(exc)
        assert "desugar" in str(exc) and "witnesses" in str(exc)


def test_the_base_carries_no_recognition_and_no_registry():
    """Sugar is meaning. owns/new/role/registry all moved off (owns+new to the
    node's .sugar(); role is the node's fact; the catalog is deleted)."""
    from sugar_lift_py_tests.sugar import sugar_base as base
    from sugar_lift_py_tests.sugar.sugar_base import Sugar

    assert not hasattr(Sugar, "owns")
    assert not hasattr(Sugar, "new")
    assert not hasattr(base, "_REGISTRY")
    assert not hasattr(base, "registered_claims")


def test_int_and_equality_sugars_are_meaning_only():
    """The two converted leaves declare no role and no recognition."""
    from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
    from sugar_lift_py_tests.sugar.equality_op_sugar import EqualityOpSugar

    for cls in (IntLiteralSugar, EqualityOpSugar):
        assert not hasattr(cls, "owns")
        assert not hasattr(cls, "new")
        assert hasattr(cls, "desugar") and hasattr(cls, "witnesses")


# ── the whole point, from a source string: `1 == 1` → sugar ──────────────


def test_source_string_one_equals_one_gives_back_sugar():
    """Python source as a string. Parse it. Ask the comparison node for its
    sugar. We get an EqualityOpSugar whose two sides are IntLiteralSugar(1),
    and it desugars. No factory, no owns, no catalog — the tree produced it."""
    source = "result = 1 == 1\n"

    fh = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False)
    fh.write(source)
    fh.close()
    try:
        sf = SourceFile(path_source(fh.name))
        (compare,) = [n for n in sf if n.kind == "Compare"]
    finally:
        Path(fh.name).unlink()

    from sugar_lift_py_tests.sugar.equality_op_sugar import EqualityOpSugar

    sugar = compare.sugar()

    # the comparison IS an equality sugar
    assert isinstance(sugar, EqualityOpSugar)

    # both sides are the integer literal 1, as sugar
    assert isinstance(sugar.left, IntLiteralSugar) and sugar.left.value == 1
    assert isinstance(sugar.right, IntLiteralSugar) and sugar.right.value == 1

    # and each side desugars to the number as a floor term
    assert sugar.left.desugar() == ExitSet.completed(TermValue(1))
    assert sugar.right.desugar() == ExitSet.completed(TermValue(1))
