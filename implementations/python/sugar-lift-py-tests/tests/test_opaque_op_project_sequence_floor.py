"""OpaqueOpCallsite.project_sequence_with — construction gap drain (Part of #3809).

Lift-probe (before fix):

    s = pd.Series([1, 2, 2, 3])
    codes, uniques = s.factorize()
    assert len(uniques) == 3

Refuse: FactoryGap · owner=TupleUnpackProjection · observed=OpaqueOpCallsite
· requested=project_sequence_with.

Mechanism: factorize() mints OpaqueOpCallsite; tuple-unpack projects indices
via SequenceProjectionOperation; floor had no project_sequence_with. Not a
missing AST recognizer — SymbolicValue already mints py.unpack(term, i).

Fix: OpaqueOpCallsite.project_sequence_with → _downstream() (SymbolicValue
py.unpack path; computed=None for opaque). Discrimination: dual-assert
witness EXECUTION.
"""

from __future__ import annotations

import re
from pathlib import Path

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _blob(report) -> str:
    return repr(report.payload.ir)


def _calls(report) -> set[str]:
    return set(re.findall(r"call:[A-Za-z_][A-Za-z0-9_.]*", _blob(report)))


def test_factorize_tuple_unpack_no_project_sequence_gap() -> None:
    src = (
        "import pandas as pd\n"
        "def t():\n"
        "    s = pd.Series([1, 2, 2, 3])\n"
        "    codes, uniques = s.factorize()\n"
        "    assert len(uniques) == 3\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    coords = _calls(report)
    assert "call:factorize" in coords or "call:len" in coords, coords
    assert "call:pandas.Series" in coords, coords
    blob = repr(report.payload)
    assert "requested=project_sequence_with" not in blob
    # py.unpack should appear for the projected elements
    assert "py.unpack" in blob or "call:len" in coords, blob[:400]


def test_factorize_unpack_lifts_len_coordinate() -> None:
    src = (
        "import pandas as pd\n"
        "def t():\n"
        "    s = pd.Series([1, 2, 2, 3])\n"
        "    codes, uniques = s.factorize()\n"
        "    assert len(uniques) == 3\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert "call:len" in _calls(report)


def test_factorize_unpack_dual_assert_refutes_lie_via_witness(tmp_path: Path) -> None:
    src = (
        "import pandas as pd\n"
        "def t_true():\n"
        "    s = pd.Series([1, 2, 2, 3])\n"
        "    codes, uniques = s.factorize()\n"
        "    assert len(uniques) == 3\n"
        "def t_lie():\n"
        "    s = pd.Series([1, 2, 2, 3])\n"
        "    codes, uniques = s.factorize()\n"
        "    assert len(uniques) == 9\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert "call:len" in _calls(report)

    result = run_source_through_real_solver(tmp_path / "factorize-unpack-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses
