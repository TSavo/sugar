"""Vendor method body dig as an opaque call: coordinate (arr.sum()).

`return np.array([1,2,3]).sum()` must mint the body universe post
`out == call:sum(call:numpy.array(...))` — same opaque-coordinate family as
builtins (#3908) and attributes (#3909). Direct `arr.sum() == 6` already worked
via the assertion euf door; body dig was missing MethodCallStrategy for
constructed receivers and SymbolicValue method floors.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_VENDOR_SUM_BODY_DIG = (
    "import numpy as np\n"
    "\n"
    "def A():\n"
    "    return np.array([1, 2, 3]).sum()\n"
    "\n"
    "def test_a():\n"
    "    assert A() == 6\n"
)

_VENDOR_SUM_BODY_DIG_LIE = (
    "import numpy as np\n"
    "\n"
    "def A():\n"
    "    return np.array([1, 2, 3]).sum()\n"
    "\n"
    "def test_a():\n"
    "    assert A() == 7\n"
)


def test_vendor_sum_body_dig_emits_universe_coordinate() -> None:
    report = build_literal_call_report(
        source=_VENDOR_SUM_BODY_DIG,
        filename="probe.py",
        memento_file="probe.py",
    )
    assert report is not None
    names = [row.name for row in report.payload.ir]
    assert any((name or "").endswith("::callable") for name in names), names
    callable_row = next(
        row for row in report.payload.ir if (row.name or "").endswith("::callable")
    )
    post_blob = repr(callable_row.post)
    assert "call:sum" in post_blob, post_blob
    assert "call:numpy.array" in post_blob, post_blob
    dig_reasons = [
        item.get("reason", "")
        for item in (report.payload.diagnostics or [])
        if isinstance(item, dict) and item.get("kind") == "dig-boundary"
    ]
    assert not any("call-builtin:sum" in reason for reason in dig_reasons), dig_reasons
    assert not any(
        "function universe body walker refused" in reason
        and "call-builtin:sum" in reason
        for reason in dig_reasons
    ), dig_reasons


def test_vendor_sum_body_dig_truthful_sat_through_real_solver(
    tmp_path: Path,
) -> None:
    """Opaque vendor method body dig: universe coordinate + sworn A()==6 → sat.

    Lying A()==7 alone also stays sat — no companion value for free opaque sum
    (same honest limit as free hash / free df.shape body dig). Refuse regression
    is the gate this seed pins.
    """
    truthful = run_source_through_real_solver(
        tmp_path / "truthful", _VENDOR_SUM_BODY_DIG
    )
    statuses = [row.get("status") for row in truthful.prove_doc.get("rows", [])]
    assert truthful.verdict == "sat", (truthful.verdict, statuses)
    assert "refused" not in statuses
    assert "call:sum" in repr(truthful.lift_doc.get("ir", []))

    lying = run_source_through_real_solver(
        tmp_path / "lying", _VENDOR_SUM_BODY_DIG_LIE
    )
    lying_statuses = [row.get("status") for row in lying.prove_doc.get("rows", [])]
    assert lying.verdict == "sat", (lying.verdict, lying_statuses)
    assert "refused" not in lying_statuses
    assert "call:sum" in repr(lying.lift_doc.get("ir", []))
