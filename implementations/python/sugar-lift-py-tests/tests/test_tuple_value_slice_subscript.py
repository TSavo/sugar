"""Finite ``TupleValue`` owns exact Python slice semantics."""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import RaiseValue, TermValue, TupleValue
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.nodes import Subscript
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _subscripts(tmp_path: Path, monkeypatch, source: str):
    path = tmp_path / "tuple_slices.py"
    path.write_text(source, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    tree = SourceFile.from_path(
        path.name,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return tuple(node for node in tree.nodes() if isinstance(node, Subscript))


def _desugar(node):
    return node.sugar().desugar(ReduceContext.root(owner="tuple-value-slice"))


def _values(outcome):
    assert isinstance(outcome, Complete), outcome
    assert isinstance(outcome.value, TupleValue)
    return tuple(element.value for element in outcome.value.elements)


def test_source_tuple_pandas_stride_slices_preserve_order_and_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    even, odd = _subscripts(
        tmp_path,
        monkeypatch,
        "even = (0, 1, 2, 3)[::2]\n"
        "odd = (0, 1, 2, 3)[1::2]\n",
    )

    assert _values(_desugar(even)) == (0, 2)
    assert _values(_desugar(odd)) == (1, 3)


def test_source_tuple_negative_and_open_slice_bounds_match_python(
    tmp_path: Path,
    monkeypatch,
) -> None:
    negative, open_upper, open_both = _subscripts(
        tmp_path,
        monkeypatch,
        "negative = (0, 1, 2, 3)[-3:-1]\n"
        "open_upper = (0, 1, 2, 3)[:-1]\n"
        "open_both = (0, 1, 2, 3)[::-1]\n",
    )

    assert _values(_desugar(negative)) == (1, 2)
    assert _values(_desugar(open_upper)) == (0, 1, 2)
    assert _values(_desugar(open_both)) == (3, 2, 1, 0)


def test_source_tuple_zero_slice_step_is_exact_value_error(
    tmp_path: Path, monkeypatch
) -> None:
    (subscript,) = _subscripts(
        tmp_path, monkeypatch, "result = (0, 1, 2)[::0]\n"
    )
    sugar = subscript.sugar()
    site = sugar.site

    outcome = sugar.desugar(ReduceContext.root(owner="tuple-value-slice"))

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "ValueError"
    assert outcome.value.effect.producer_node_owner == "TupleValue.subscript"
    assert outcome.value.effect.occurrence_id == str(site)


def test_source_tuple_symbolic_slice_bound_stays_typed_loud(
    tmp_path: Path, monkeypatch
) -> None:
    (subscript,) = _subscripts(
        tmp_path, monkeypatch, "result = (0, 1, 2)[start:]\n"
    )

    with pytest.raises(SugarNotWritten) as raised:
        _desugar(subscript)

    assert raised.value.owner == "TupleValue.subscript"
    assert raised.value.observed == (
        "undecided receiver runtime type or index semantics: TupleValue[SliceValue]"
    )
    assert raised.value.requested == (
        "a source-authenticated subscript success or exceptional exit"
    )
