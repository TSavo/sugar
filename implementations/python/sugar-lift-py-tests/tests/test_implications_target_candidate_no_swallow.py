"""Implications target_candidates must not manufacture absence from exceptions.

SIN CLUSTER 4 / coord 3 — ``except Exception: continue`` around
``function_contract_rows`` dropped a resolved target from target_candidates.
Catch-and-continue is a second mechanism for surviving unfinished Sugar.

DELETE the handler. Throws rise. No counter, no named skip list.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sugar_source_tree.panic import SugarNotWritten


def test_truthful_function_contract_rows_exception_propagates():
    """Truthful twin: a raise from function_contract_rows is not continue."""

    def function_contract_rows(fn, file_rel):
        del fn, file_rel
        raise SugarNotWritten(
            blame=SimpleNamespace(filename="t.py", line=1, col=0),
            owner="test.implications.target",
            observed="body sugar not written",
            requested="Complete universe with contract rows",
            fix="write body sugar; do not drop the target from candidates",
        )

    with pytest.raises(SugarNotWritten) as raised:
        for name in ["target_fn"]:
            function_contract_rows(SimpleNamespace(name=name), "t.py")
    assert raised.value.owner == "test.implications.target"


def test_lying_continue_manufactures_absence():
    """Lying twin: except Exception continue yields empty candidates silently."""

    def function_contract_rows(fn, file_rel):
        del fn, file_rel
        raise RuntimeError("body sugar refused")

    targets = ["a", "b"]
    target_candidates = []
    silent_drops = 0
    for name in targets:
        fn = SimpleNamespace(name=name)
        try:
            _def_memento, rows = function_contract_rows(fn, "t.py")
        except Exception:
            silent_drops += 1
            continue
        if rows is None:
            continue
        target_candidates.append(name)

    assert silent_drops == 2
    assert target_candidates == []
    with pytest.raises(RuntimeError):
        function_contract_rows(SimpleNamespace(name="a"), "t.py")


def test_production_implications_loop_has_no_exception_continue():
    """Static twin: lift_rpc implications arm has no try/except around the call."""
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "sugar_lift_py_tests"
        / "lift_rpc.py"
    ).read_text(encoding="utf-8")
    marker = "def_memento, rows = _tree.function_contract_rows(fn, file_rel)"
    assert marker in source
    idx = source.index(marker)
    window = source[idx - 120 : idx + 80]
    assert "try:" not in window
    assert "except Exception" not in window
