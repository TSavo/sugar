"""The first node -> sugar seam, end to end.

A `1` in source, asked for its sugar, constructs an IntLiteralSugar and
desugars to the number as a floor term. No factory, no owns, no catalog:
the Constant node recognizes ITSELF (its value is an int) and constructs
its sugar directly. A literal kind not yet converted throws SugarNotWritten
loudly, by kind — the honest gap arm.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from sugar_source_tree.tree import SourceFile
from sugar_source_tree.panic import SugarNotWritten
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import Complete
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
    assert outcome == Complete(TermValue(42))


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


def test_a_bool_is_not_an_int_literal_it_throws_until_written():
    # bool is a subclass of int; the node must distinguish it. True is its own
    # (not-yet-written) sugar, so it throws rather than becoming IntLiteralSugar.
    (const,) = _constants("x = True\n")
    try:
        const.sugar()
        assert False, "True must not construct IntLiteralSugar"
    except SugarNotWritten:
        pass


def test_an_unconverted_literal_kind_throws_loudly_by_kind():
    (const,) = _constants("x = 3.0\n")  # float: leaf not written yet
    try:
        const.sugar()
        assert False, "an unwritten literal kind must throw"
    except SugarNotWritten as panic:
        assert "Constant" in panic.observed


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
    assert sugar.left.desugar() == Complete(TermValue(1))
    assert sugar.right.desugar() == Complete(TermValue(1))
