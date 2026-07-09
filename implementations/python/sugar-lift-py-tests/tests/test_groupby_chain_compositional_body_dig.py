"""groupby().sum() compositional coordinate body dig (Part of #3809).

Narrative: vendor law threads through the pipe — every link is a nested
``call:`` coordinate, body dig mints the full nest, discrimination is
witness-EXECUTION.

Lift-probe on main (post #3929/#3933/#3935) — no refuse on any link:

| Seed | Shape | DIG for A |
|------|-------|-----------|
| ``def A(df): return df.groupby('k').sum()`` value-eq | universe ``out == call:sum(call:groupby(df, 'k'))`` | none |
| ``assert A(<DF>).shape == …`` | ``call:shape(call:A(DF))`` (outer only) | none |
| ``assert len(A(<DF>)) == 2`` dual-assert | shared euf → unsat | none |
| direct ``len(DF.groupby.sum())`` | ``call:len(call:sum(call:groupby(...)))`` | n/a |

Locator is FOL ``call:`` (not ``method:``) for each chain link. Opaque DF result:
``computed=None``; no fabricated DataFrame companion.

No production change — composition already grounds end-to-end after Batch A +
formal-method dig. Instruments pin the composition story + dual-assert receipt.
"""

from __future__ import annotations

import re
from pathlib import Path

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_NEST = ("call:groupby", "call:sum")

_FORMAL_VALUE_EQ = (
    "import pandas as pd\n"
    "\n"
    "def A(df):\n"
    '    return df.groupby("k").sum()\n'
    "\n"
    "def test_a():\n"
    '    assert A(pd.DataFrame({"k": [1, 1, 2], "v": [10, 20, 30]}))'
    ' == A(pd.DataFrame({"k": [1, 1, 2], "v": [10, 20, 30]}))\n'
)

_FORMAL_LEN_DUAL = (
    "import pandas as pd\n"
    "\n"
    "def A(df):\n"
    '    return df.groupby("k").sum()\n'
    "\n"
    "def t_true():\n"
    '    assert len(A(pd.DataFrame({"k": [1, 1, 2], "v": [10, 20, 30]}))) == 2\n'
    "\n"
    "def t_lie():\n"
    '    assert len(A(pd.DataFrame({"k": [1, 1, 2], "v": [10, 20, 30]}))) == 9\n'
)

_ZERO_ARG_LEN_DUAL = (
    "import pandas as pd\n"
    "\n"
    "def A():\n"
    '    return pd.DataFrame({"k": [1, 1, 2], "v": [10, 20, 30]}).groupby("k").sum()\n'
    "\n"
    "def t_true():\n"
    "    assert len(A()) == 2\n"
    "\n"
    "def t_lie():\n"
    "    assert len(A()) == 9\n"
)


def _coords(report) -> set[str]:
    return set(re.findall(r"call:[A-Za-z_][A-Za-z0-9_.]*", repr(report.payload.ir)))


def _callable_post(report) -> str:
    row = next(r for r in report.payload.ir if (r.name or "").endswith("::callable"))
    return repr(row.post)


def _dig_refuses_a(report) -> list[str]:
    return [
        d.get("reason", "")
        for d in (report.payload.diagnostics or [])
        if isinstance(d, dict)
        and d.get("kind") == "dig-boundary"
        and d.get("callee") == "A"
    ]


def test_formal_groupby_sum_universe_post_is_nested_call_sum_groupby() -> None:
    """Vendor pipe: out == call:sum(call:groupby(df, 'k')) — every link a call: coordinate."""
    report = build_literal_call_report(
        source=_FORMAL_VALUE_EQ, filename="t.py", memento_file="t.py"
    )
    assert report is not None
    assert any((r.name or "").endswith("::callable") for r in report.payload.ir)
    assert not _dig_refuses_a(report), _dig_refuses_a(report)
    post = _callable_post(report)
    assert "'name': 'call:sum'" in post or "call:sum" in post, post
    assert "'name': 'call:groupby'" in post or "call:groupby" in post, post
    # Nest: sum wraps groupby (groupby is arg of sum)
    assert set(_NEST) <= _coords(report)
    for reason in _dig_refuses_a(report):
        assert "call-method:" not in reason, reason
        assert "function universe body walker refused" not in reason, reason


def test_formal_groupby_sum_value_eq_truthful_sat(tmp_path: Path) -> None:
    """Opaque DF chain: solo value-equality sat; nested coords in lift IR."""
    result = run_source_through_real_solver(tmp_path / "formal-gb-eq", _FORMAL_VALUE_EQ)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "sat", (result.verdict, statuses)
    assert "refused" not in statuses
    blob = repr(result.lift_doc.get("ir", []))
    assert "call:groupby" in blob and "call:sum" in blob, blob


def test_formal_groupby_sum_len_dual_assert_refutes_lie(tmp_path: Path) -> None:
    """Composition discrimination: shared euf on len(A(DF)) → unsat via witness.

    Assertion IR is ``call:len(call:A(DF))`` — the nested sum/groupby lives in the
    universe post (value-eq dig surface), not re-expanded under every consumer.
    """
    report = build_literal_call_report(
        source=_FORMAL_LEN_DUAL, filename="t.py", memento_file="t.py"
    )
    assert report is not None
    assert not _dig_refuses_a(report), _dig_refuses_a(report)
    coords = _coords(report)
    assert "call:len" in coords and "call:A" in coords, coords

    result = run_source_through_real_solver(tmp_path / "formal-gb-len-dual", _FORMAL_LEN_DUAL)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    # Shared euf key on call:len(call:A(...)) — discrimination without expanding
    # the groupby nest into every consumer (nest is pinned on value-eq dig).
    assert result.verdict == "unsat", (result.verdict, statuses)


def test_zero_arg_groupby_sum_len_dual_assert_refutes_lie(tmp_path: Path) -> None:
    """Zero-arg composition path: dual-assert unsat via shared len(A()) euf key."""
    report = build_literal_call_report(
        source=_ZERO_ARG_LEN_DUAL, filename="t.py", memento_file="t.py"
    )
    assert report is not None
    coords = _coords(report)
    assert "call:len" in coords and "call:A" in coords, coords

    result = run_source_through_real_solver(
        tmp_path / "zeroarg-gb-len-dual", _ZERO_ARG_LEN_DUAL
    )
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
