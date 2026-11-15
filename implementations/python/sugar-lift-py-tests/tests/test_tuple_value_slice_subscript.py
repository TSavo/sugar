"""Finite ``TupleValue`` owns exact Python slice semantics."""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import TermValue, TupleValue
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_source_tree.nodes import Subscript
from sugar_lift_py_tests.lift_rpc import _open_at_seat


def _subscripts(tmp_path: Path, monkeypatch, source: str):
    path = tmp_path / "tuple_slices.py"
    path.write_text(source, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    tree = _open_at_seat(
        path,
        root=tmp_path,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return tuple(node for node in tree.nodes() if isinstance(node, Subscript))


def _desugar(node):
    return node.sugar().desugar(ReduceContext.root(owner="tuple-value-slice"))


def _values(outcome):
    value = outcome.completed_value()
    assert isinstance(value, TupleValue), outcome
    return tuple(element.value for element in value.elements)


def test_source_tuple_pandas_stride_slices_preserve_order_and_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    even, odd = _subscripts(
        tmp_path,
        monkeypatch,
        "even = (0, 1, 2, 3)[::2]\n" "odd = (0, 1, 2, 3)[1::2]\n",
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
    (subscript,) = _subscripts(tmp_path, monkeypatch, "result = (0, 1, 2)[::0]\n")
    sugar = subscript.sugar()
    site = sugar.site

    outcome = sugar.desugar(ReduceContext.root(owner="tuple-value-slice"))

    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "ValueError"
    assert halt.effect.producer_node_owner == "TupleValue.subscript"
    assert halt.effect.occurrence_id == f"{site.filename}:{site.line}:{site.col}"


def test_source_tuple_slice_bound_by_an_unbound_name_is_the_name_error(
    tmp_path: Path, monkeypatch
) -> None:
    """``start`` is bound nowhere in the module: reading it raises
    ``NameError`` before any slice is built, so the read is that one halt and
    no arm completes. (It is not an unanswered read: nothing is undecided
    about an unbound name.)"""
    from sugar_lift_py_tests.effect import NameErrorEffect

    (subscript,) = _subscripts(tmp_path, monkeypatch, "result = (0, 1, 2)[start:]\n")

    outcome = _desugar(subscript)

    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, NameErrorEffect)
    assert halt.effect.exception_name == "NameError"
    assert halt.effect.name == "start"
