"""Authenticated mutable-dict globals own symbolic membership coordinates."""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import MutableGlobalValue, PredicateValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import atomic, make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.nodes import Compare, Name
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _source(tmp_path: Path, name: str):
    path = tmp_path / name
    path.write_text(
        "OPTIONS = {}\n"
        "def has_option(key):\n"
        "    return key in OPTIONS\n",
        encoding="utf-8",
    )
    tree = SourceFile.from_path(path)
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
    value = MutableGlobalValue(
        "OPTIONS", kind, binding.source_cid, binding.seal()
    )
    ctx = ReduceContext.root(owner="mutable-global-membership")
    return value, ctx.with_temporal(ctx.temporal.bind_value("OPTIONS", value))


def test_same_source_mutable_dict_membership_keeps_symbolic_guard(
    tmp_path: Path,
) -> None:
    binding, compare = _source(tmp_path, "truth.py")
    value, ctx = _context(binding, kind="dict")

    outcome = compare.sugar().desugar(ctx)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, PredicateValue)
    assert outcome.value.site is compare.fragment
    assert outcome.value.formula == atomic(
        "py.in",
        [
            make_var("key"),
            value.to_term(owner="mutable global membership test"),
        ],
    )


def test_mutable_dict_membership_refuses_same_span_foreign_source(
    tmp_path: Path,
) -> None:
    binding, _truthful = _source(tmp_path, "truth.py")
    _foreign_binding, foreign = _source(tmp_path, "foreign.py")
    _value, ctx = _context(binding, kind="dict")

    with pytest.raises(SugarNotWritten) as raised:
        foreign.sugar().desugar(ctx)

    assert raised.value.owner == "MutableGlobalValue.contains"
    assert raised.value.observed == (
        "foreign source for mutable-global membership occurrence"
    )
    assert raised.value.requested == "authenticated same-source membership occurrence"


def test_non_dict_mutable_global_does_not_borrow_dict_membership(
    tmp_path: Path,
) -> None:
    binding, compare = _source(tmp_path, "wrong_kind.py")
    _value, ctx = _context(binding, kind="list")

    with pytest.raises(ConstructionPanic) as raised:
        compare.sugar().desugar(ctx)

    assert raised.value.info.owner == "contains"
    assert raised.value.info.observed == "MutableGlobalValue"
    assert raised.value.info.requested == "stand on the membership floor"
