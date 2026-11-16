"""Authenticated mutable-dict globals own symbolic membership coordinates."""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import MutableGlobalValue, PredicateValue, StringValue
from sugar_lift_py_tests.ir import atomic
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted, complement_guard
from sugar_source_tree.nodes import Compare, Name
from sugar_source_tree.panic import SugarNotWritten
from sugar_lift_py_tests.lift_rpc import _open_at_seat


def _source(tmp_path: Path, name: str, *, suffix: str = ""):
    path = tmp_path / name
    path.write_text(
        "OPTIONS = {}\n"
        "def has_option(key):\n"
        "    return key in OPTIONS\n" + suffix,
        encoding="utf-8",
    )
    tree = _open_at_seat(path, root=tmp_path)
    binding = next(
        node.fragment
        for node in tree.nodes()
        if isinstance(node, Name)
        and node.fragment.text == "OPTIONS"
        and node.line_col_span().start_line == 1
    )
    compare = next(node for node in tree.nodes() if isinstance(node, Compare))
    return binding, compare


def _context(binding, *, kind: str):
    value = MutableGlobalValue("OPTIONS", kind, binding.source_cid, binding.seal())
    ctx = ReduceContext.root(owner="mutable-global-membership")
    return value, ctx.with_temporal(ctx.temporal.bind_value("OPTIONS", value))


def test_same_source_mutable_dict_membership_keeps_exact_predicate(
    tmp_path: Path,
) -> None:
    binding, compare = _source(tmp_path, "truth.py")
    value, _ctx = _context(binding, kind="dict")
    item = StringValue("key")
    site = compare.fragment

    outcome = value.contains(item, site)

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), PredicateValue)
    assert outcome.completed_value().site is site
    assert outcome.completed_value().formula == atomic(
        "py.in",
        [
            item.to_term(owner="mutable global membership test"),
            value.to_term(owner="mutable global membership test"),
        ],
    )


def test_mutable_dict_membership_refuses_same_span_foreign_source(
    tmp_path: Path,
) -> None:
    binding, truthful = _source(tmp_path, "truth.py")
    _foreign_binding, foreign = _source(
        tmp_path, "foreign.py", suffix="# content-distinct foreign source\n"
    )
    value, _ctx = _context(binding, kind="dict")
    item = StringValue("key")

    assert value.contains(item, truthful.fragment).completed_value() is not None

    with pytest.raises(SugarNotWritten) as raised:
        value.contains(item, foreign.fragment)

    assert raised.value.owner == "MutableGlobalValue.contains"
    assert raised.value.observed == (
        "foreign source for mutable-global membership occurrence"
    )
    assert raised.value.requested == "authenticated same-source membership occurrence"


def test_non_dict_mutable_global_does_not_borrow_dict_membership(
    tmp_path: Path,
) -> None:
    binding, compare = _source(tmp_path, "wrong_kind.py")
    value, _ctx = _context(binding, kind="list")
    item = StringValue("key")
    site = compare.fragment

    outcome = value.contains(item, site)

    # A pin that is not a dict decides no membership structure: which
    # ``__contains__`` runs is not decided here.  That is the two-faced
    # undecided membership -- never the dict pin's sole predicate, and never
    # a lifter panic over a test Python runs.
    assert outcome.completed_value() is None
    (completed,) = [face for face in outcome.exits if isinstance(face, Completed)]
    (halted,) = [face for face in outcome.exits if isinstance(face, Halted)]
    assert completed.guard.name == "python:compare.completes"
    assert isinstance(completed.value, PredicateValue)
    # The truth of the undecided membership's value, keyed per evaluation
    # (#7757 NEW-1).
    assert completed.value.formula.name == "python:truth_result"
    assert completed.value.formula.args[0].name == "python:compare_result"
    assert completed.value.formula.args[0].args[0].value == "In"
    assert halted.guard == complement_guard(completed.guard)
    assert halted.effect.exception_name is None
    assert halted.effect.producer_node_owner == "UndecidedCompare:In"
    assert halted.owed and halted.owed == completed.owed


def test_symbolic_source_membership_keeps_complementary_dispatch_faces(
    tmp_path: Path,
) -> None:
    binding, compare = _source(tmp_path, "symbolic.py")
    _value, ctx = _context(binding, kind="dict")
    sugar = compare.sugar()
    site = sugar.site

    outcome = sugar.desugar(ctx)

    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 2
    halted = next(face for face in outcome.exits if isinstance(face, Halted))
    completed = next(face for face in outcome.exits if isinstance(face, Completed))
    assert halted.effect.exception_name is None
    # The one two-faced outcome (``ExitSet.two_faced``): the undecided
    # dispatch's own owner, complementary guards, and both arms owing the
    # one undecided member.
    assert halted.effect.producer_node_owner == "UndecidedCompare:In"
    assert halted.effect.blame == str(site)
    assert isinstance(completed.value, PredicateValue)
    assert completed.value.site is site
    assert completed.guard.name == "python:compare.completes"
    assert completed.guard == complement_guard(halted.guard)
    # The truth of the undecided membership's value, keyed per evaluation
    # (#7757 NEW-1).
    assert completed.value.formula.name == "python:truth_result"
    assert completed.value.formula.args[0].name == "python:compare_result"
    assert completed.value.formula.args[0].args[0].value == "In"
    assert halted.owed and halted.owed == completed.owed
