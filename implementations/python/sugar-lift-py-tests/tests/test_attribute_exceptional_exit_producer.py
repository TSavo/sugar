"""Attribute lookup is an effect producer; an undecided lookup is two-faced."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import mmap
from pathlib import Path
import subprocess

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import CallSiteValue, NoneValue, SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.nodes import Attribute
from sugar_source_tree.tree import SourceFile


from sugar_lift_py_tests.repo_root import resolve_repo_root

SITE_SHA256 = "4d2599448c6b329af3822dbc2295fafe142d9ce84e49821c435d9b1c11fea793"
SOURCE_CID = (
    "blake3-512:43cdd8a4f204ef75c77996a7e7a98b84bcd174de708cfe1e9e430415bbd636e2"
    "186f44518e941e76854029b14db48605c43ff6c242c0750322c215eb7c646013"
)
MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)


def _repo_root() -> Path:
    return resolve_repo_root()


def _site_attribute(source: str, site: Path) -> Attribute:
    assert blake3_512_of(source.encode()) == SOURCE_CID
    tree = SourceFile(
        workspace_path_source(str(site), root=str(site.parents[2])),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    matches = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, Attribute)
        and node.attr == "bad"
        and node.line_col_span().start_line == 104
    )
    assert len(matches) == 1
    return matches[0]


def _call_result() -> CallSiteValue:
    return CallSiteValue(
        "source-constructor",
        (),
        (),
        ctor("call:source-constructor", []),
        None,
    )


@dataclass(frozen=True)
class _ReceiverSugar(ConstructedTermSugar):
    """A constructed receiver: ``AttributeSugar.receiver`` admits only a
    ``ConstructedTermSugar`` (``require_constructed_term_sugar``)."""

    value: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return ExitSet.completed(self.value)

    def to_term(self, *, owner):
        return self.value.to_term(owner=owner)


def _assert_two_faced_read(outcome, owner: str):
    """The one two-faced unanswered read: completes under the attribute's
    completes atom, else an undetermined raise owned by ``owner``; the read
    is owed at its site.  No AttributeError is named."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Completed, Halted
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    halts = [
        arm
        for arm in outcome.exits
        if isinstance(arm, Halted)
        and isinstance(arm.effect, UndeterminedRaiseEffect)
        and arm.effect.producer_node_owner == owner
    ]
    assert len(halts) == 1
    completed = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert completed
    # A read on a parameter is keyed per evaluation (``attribute_op``,
    # ``floor_value.undecided_attribute_result``); any other undecided read
    # keeps its ``attribute`` atom.
    assert any(
        "python:attribute.completes" in repr(arm.guard)
        or "python:attribute_op.completes" in repr(arm.guard)
        for arm in completed
    )
    assert "AttributeError" not in repr(halts[0].effect)
    assert any(item.site is not None for item in owed_calls(outcome))
    return halts[0]


def _assert_undecided(node: Attribute, receiver, *, name: str | None = None) -> None:
    operation = replace(
        node.sugar(),
        receiver=_ReceiverSugar(receiver),
        name=node.attr if name is None else name,
    )
    halt = _assert_two_faced_read(
        operation.desugar(None), f"{type(receiver).__name__}.attribute"
    )
    assert halt.effect.blame == str(node.fragment)


def test_real_pandas_constructed_receiver_attribute_is_named_undecided() -> None:
    site = _authenticated_corpus_file("tests/test_register_accessor.py")
    source = site.read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode()).hexdigest() == SITE_SHA256
    node = _site_attribute(source, site)

    _assert_undecided(node, _call_result())


def test_symbolic_receiver_attribute_is_the_same_named_third_value() -> None:
    site = _authenticated_corpus_file("tests/test_register_accessor.py")
    source = site.read_text(encoding="utf-8")
    node = _site_attribute(source, site)

    _assert_undecided(node, SymbolicValue(make_var("series")))


def test_lying_known_member_does_not_license_blanket_attribute_error() -> None:
    outcome = NoneValue().attribute("__class__", "lying-none-class", None)

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), SymbolicValue)


def test_replacing_bad_with_known_member_still_cannot_invent_an_exit() -> None:
    site = _authenticated_corpus_file("tests/test_register_accessor.py")
    source = site.read_text(encoding="utf-8")
    assert source.count("pd.Series([], dtype=object).bad") == 1
    lying = source.replace(
        "pd.Series([], dtype=object).bad",
        "pd.Series([], dtype=object).__class__",
    )
    assert "pd.Series([], dtype=object).__class__" in lying

    _assert_undecided(_site_attribute(source, site), _call_result(), name="__class__")


# --- No-call Attribute family corpus pins (denominator 41) -----------------
# Bare desugar without bindings yields SymbolicValue receivers; the producer
# answers the two-faced unanswered read (owner SymbolicValue.attribute) rather
# than invent AttributeError. These sites are enrolled Attribute bodies
# under the no-Call-descendant law.


def _authenticated_corpus_file(relative: str) -> Path:
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus

    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.manifest_cid, corpus.file_count) == (
        "3.0.3",
        MANIFEST_CID,
        1421,
    )
    return corpus.root / relative


def _line_attribute(source: str, path: Path, *, line: int, attr: str) -> Attribute:
    source_cid = blake3_512_of(source.encode("utf-8"))
    tree = SourceFile(
        (source, str(path), source_cid),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    matches = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, Attribute)
        and node.attr == attr
        and node.line_col_span().start_line == line
    )
    assert len(matches) == 1
    return matches[0]


def _assert_bare_desugar_symbolic_attribute(node: Attribute) -> None:
    """Production door: expression.sugar().desugar(None) with no bindings."""
    _assert_two_faced_read(node.sugar().desugar(None), "SymbolicValue.attribute")


@pytest.mark.parametrize(
    "relative,line,attr,snippet",
    [
        ("tests/series/test_api.py", 175, "foo", "ser.foo"),
        ("tests/series/test_api.py", 195, "weekday", "ser.weekday"),
        ("tests/strings/test_api.py", 88, "str", "mi.str"),
        ("tests/series/accessors/test_cat_accessor.py", 65, "cat", "invalid.cat"),
        ("tests/arrays/sparse/test_accessor.py", 97, "density", "ser.sparse.density"),
    ],
)
def test_no_call_attribute_corpus_sites_stay_symbolic_undecided(
    relative: str, line: int, attr: str, snippet: str
) -> None:
    path = _authenticated_corpus_file(relative)
    source = path.read_text(encoding="utf-8")
    assert snippet in source
    node = _line_attribute(source, path, line=line, attr=attr)
    _assert_bare_desugar_symbolic_attribute(node)


def test_import_member_path_read_is_the_closed_reference() -> None:
    """``pd.util.foo`` under ``import pandas as pd`` is an import member path.

    Every import-bound reference reads the one import table (#7837, #7851):
    the table authenticates the head and the attribute chain names the export
    path, so the value read is the one closed reference
    ``ref:pandas.util.foo``.  The alias is never an opaque symbolic receiver
    asked for a member (the deleted second way this row used to pin as
    ``SymbolicValue.attribute``), and no ``AttributeError`` is named here.
    The read can raise where it is read and the lifter holds no module's
    namespace, so it is the one two-faced unanswered read
    (``ImportMemberValue.read_faces``): the reference under its completes
    atom, an undetermined raise under the complement, the read owed.
    """
    from sugar_lift_py_tests.floor.import_member_value import ImportMemberValue
    from sugar_lift_py_tests.outcome import Completed

    path = _authenticated_corpus_file("tests/api/test_api.py")
    source = path.read_text(encoding="utf-8")
    assert "pd.util.foo" in source
    node = _line_attribute(source, path, line=491, attr="foo")

    outcome = node.sugar().desugar(None)

    _assert_two_faced_read(outcome, "ImportMemberValue.read")
    (member,) = [arm.value for arm in outcome.exits if isinstance(arm, Completed)]
    assert isinstance(member, ImportMemberValue)
    assert member.qualified_name == "pandas.util.foo"
    assert member.exported_member_path == ("util", "foo")
    assert member.to_term(owner="test") == ctor(
        "ref:pandas.util.foo", [], symbol_kind="coordinate"
    )


def test_binop_child_np_nan_is_the_closed_reference_under_the_binary_faces() -> None:
    """BinOp ``s_0123 & np.nan``: ``np.nan`` is an import member.

    The operand reads the one import table (#7837, #7851): it is the closed
    reference ``ref:numpy.nan``, never ``.nan`` asked of an opaque symbolic
    ``np`` (the deleted second way this test used to pin as
    ``SymbolicValue.attribute``).  The binary operation over an undecided
    left operand keeps its own two faces.
    """
    path = _authenticated_corpus_file("tests/series/test_logical_ops.py")
    source = path.read_text(encoding="utf-8")
    assert source.count("s_0123 & np.nan") == 1
    source_cid = blake3_512_of(source.encode("utf-8"))
    tree = SourceFile(
        (source, str(path), source_cid),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    from sugar_source_tree.nodes import BinOp

    matches = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, BinOp)
        and node.op.kind == "BitAnd"
        and node.line_col_span().start_line == 96
    )
    assert len(matches) == 1
    outcome = matches[0].sugar().desugar(None)
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Halted

    owners = [
        arm.effect.producer_node_owner
        for arm in outcome.exits
        if isinstance(arm, Halted) and isinstance(arm.effect, UndeterminedRaiseEffect)
    ]
    assert "UndecidedBinary:&" in owners
    assert "SymbolicValue.attribute" not in owners
    assert "numpy.nan" in repr(outcome)
