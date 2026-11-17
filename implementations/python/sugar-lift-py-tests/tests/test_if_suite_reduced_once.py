"""One run of an ``if`` reduces each suite once, whatever number of condition
faces select over it (``if_sugar._SuiteReductions``).

A condition that is not one plain completed arm -- ``a and b`` completes as
``a`` where ``a`` is falsy and as ``b`` where it is truthy -- selects the
suites once per completed face, and each face of a symbolic test splits both
suites under the same context.  Through an ``elif`` chain, each ``elif`` the
``else`` suite of the one before, the innermost suite was reduced
2 * 2 * 2 times for three ``and`` tests: exponential in the chain's depth
(pandas ``core/arrays/_utils.py`` crossed the 120 s kit deadline on one
50-line function).  Each face still joins under its own formula; the rows the
function states are byte for byte the rows the per-face reductions stated.
"""

from __future__ import annotations

import json
from collections import Counter

_CHAIN = """\
def f(a, b, c, d, e, g):
    if a and b:
        out = 1
    elif c and d:
        out = 2
    elif e and g:
        out = 3
    else:
        out = 4
    return out
"""


def _rows(root) -> str:
    """Every row ``f`` states in the universe scan, serialized as mint reads
    it: its contract rows and the calls it owes, over one term table."""
    from sugar_lift_py_tests import tree_enumerate
    from sugar_lift_py_tests.ir import TermTableBuilder
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    # A fresh reduction every time: the owner reduction is remembered.
    tree_enumerate._OWNER_REDUCTIONS.clear()
    producer = root / "producer.py"
    if not producer.exists():
        producer.write_text(_CHAIN)
    tree = open_source_file_for_construction(producer, root=root)
    (function,) = [item for item in tree.functions() if item.name == "f"]
    _memento, rows = tree_enumerate.function_contract_rows(function, "producer.py")
    calls = owed_calls(tree_enumerate.owner_reduction(function).outcome)
    term_table = TermTableBuilder()
    payload = [row.to_rpc_with_term_table(term_table) for row in rows or ()]
    payload.extend(
        row.to_rpc_with_term_table(None)
        for row in tree_enumerate.unanswered_call_rows(calls, "producer.py")
    )
    return json.dumps({"rows": payload, "terms": term_table.nodes}, sort_keys=True)


def _counting(monkeypatch, counts: Counter) -> None:
    from sugar_lift_py_tests.sugar import if_sugar

    reduce_suite = if_sugar._reduce_suite

    def counted(body, ctx):
        counts[id(body)] += 1
        return reduce_suite(body, ctx)

    monkeypatch.setattr(if_sugar, "_reduce_suite", counted)


def _per_face(monkeypatch) -> None:
    """The reduction before ``_SuiteReductions``: every face reduces both
    suites again."""
    from sugar_lift_py_tests.sugar import if_sugar

    monkeypatch.setattr(
        if_sugar._SuiteReductions,
        "reduced",
        lambda self, body, ctx: if_sugar._reduce_suite(body, ctx),
    )


def test_every_suite_of_an_and_chain_is_reduced_once(tmp_path, monkeypatch):
    counts: Counter = Counter()
    _counting(monkeypatch, counts)

    _rows(tmp_path)

    # The three ``then`` suites, the two ``else`` suites holding the next
    # ``elif`` and the last ``else``: each reduced exactly once.
    assert len(counts) == 6, sorted(counts.values())
    assert set(counts.values()) == {1}, sorted(counts.values())


def test_the_chain_was_exponential_per_face(tmp_path, monkeypatch):
    # The defect this guards: per face, the innermost suite is reduced
    # 2 * 2 * 2 times.  If ``a and b`` ever stops being two completed faces,
    # this test says so rather than the one above passing vacuously.
    counts: Counter = Counter()
    _counting(monkeypatch, counts)
    _per_face(monkeypatch)

    _rows(tmp_path)

    assert max(counts.values()) >= 8, sorted(counts.values())


def test_the_rows_are_the_rows_the_per_face_reductions_stated(
    tmp_path, monkeypatch
):
    once = _rows(tmp_path)
    with monkeypatch.context() as patched:
        _per_face(patched)
        per_face = _rows(tmp_path)

    assert once == per_face
