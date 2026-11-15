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



from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

def test_truthful_function_contract_rows_exception_propagates():
    """Truthful twin: a raise from function_contract_rows is not continue."""

    def function_contract_rows(fn, file_rel):
        del fn, file_rel
        raise SugarNotWritten(
            blame=SimpleNamespace(filename="t.py", line=1, col=0),
            owner="test.implications.target",
            observed="body sugar not written",
            requested="a completed universe with contract rows",
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


def test_production_universe_scan_has_no_exception_continue():
    """Static twin: the one production caller of ``function_contract_rows``
    never drops a function silently.

    The ``implications`` level this twin first read is deleted (#7864); the
    universe scan is the one caller left.  Its law (step 8): a backend defect
    is re-raised, a refusal by name is recorded as the function's own
    ``undecided`` row before the scan moves on, and nothing catches
    ``Exception``."""
    source = (
        sugar_lift_py_tests_package_root()
        / "src"
        / "sugar_lift_py_tests"
        / "lift_rpc.py"
    ).read_text(encoding="utf-8")
    marker = "_tree.function_contract_rows("
    assert source.count(marker) == 1
    start = source.index(marker)
    window = source[start : source.index("scan_rows.extend(", start)]
    assert "except Exception" not in window
    assert "except BaseException" not in window
    assert "except:" not in window
    defect = window.index("except BackendDefect:")
    refusal = window.index("except LifterRefusal as refusal:")
    recorded = window.index("_tree.refused_function_row(fn, file_rel, refusal)")
    # The defect arm re-raises, and it is tried first.
    assert defect < refusal
    assert "raise" in window[defect:refusal]
    # The refusal is recorded as the function's row before the scan continues.
    assert refusal < recorded < window.index("continue", refusal)
