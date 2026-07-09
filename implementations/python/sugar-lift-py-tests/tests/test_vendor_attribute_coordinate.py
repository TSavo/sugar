"""Vendor attribute access as a coordinate (df.shape) — soundness.

`receiver.attr == expected` lifts to the euf-keyed coordinate
`call:<attr>(receiver)`, same door method calls use. A lying swear about the
same coordinate refutes a truthful one because they share the euf key.
Opaque-only: no computed companion for the attribute itself.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_VENDOR_SHAPE_TRUE = (
    "import pandas as pd\n"
    "def t_true():\n"
    "    assert pd.DataFrame().shape == (0, 0)\n"
)

_VENDOR_SHAPE_PAIR = (
    "import pandas as pd\n"
    "def t_true():\n"
    "    assert pd.DataFrame().shape == (0, 0)\n"
    "def t_lie():\n"
    "    assert pd.DataFrame().shape == (1, 1)\n"
)

_METHOD_SUM = (
    "import numpy as np\n"
    "def t():\n"
    "    assert np.array([1, 2, 3]).sum() == 6\n"
)

_SHAPE_EUF = "shape#euf#c:call:shape(c:call:pandas.DataFrame())::assertion"
_SUM_EUF = "sum#euf#c:call:sum(c:call:numpy.array(c:array(i:1,i:2,i:3)))::assertion"


def _euf_names(report) -> list[str]:
    return [row.name for row in report.payload.ir if "#euf#" in (row.name or "")]


def _ir_blob(report) -> str:
    return str([row.inv for row in report.payload.ir])


def test_vendor_shape_lifts_to_coordinate_euf_key() -> None:
    report = build_literal_call_report(
        source=_VENDOR_SHAPE_TRUE,
        filename="t.py",
        memento_file="t.py",
    )
    assert report is not None
    assert _SHAPE_EUF in _euf_names(report)
    assert "py.attr" not in _ir_blob(report)
    contract = next(row for row in report.payload.ir if row.name == _SHAPE_EUF)
    assert contract.inv == {
        "kind": "atomic",
        "name": "=",
        "args": [
            {
                "kind": "ctor",
                "name": "call:shape",
                "args": [
                    {
                        "kind": "ctor",
                        "name": "call:pandas.DataFrame",
                        "args": [],
                    }
                ],
            },
            {
                "kind": "ctor",
                "name": "tuple",
                "args": [
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": 0,
                    },
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": 0,
                    },
                ],
            },
        ],
    }


def test_vendor_shape_truth_and_lie_share_euf_key() -> None:
    """Discrimination setup: two swears about the same coordinate share one key.

    Location-keyed py.attr named each assert site differently so they never
    conjoined; a lying shape==(1,1) could not refute a truthful shape==(0,0).
    """
    report = build_literal_call_report(
        source=_VENDOR_SHAPE_PAIR,
        filename="t.py",
        memento_file="t.py",
    )
    assert report is not None
    names = _euf_names(report)
    assert names == [_SHAPE_EUF, _SHAPE_EUF]
    assert "py.attr" not in _ir_blob(report)
    rhs_values = [
        row.inv["args"][1]["args"][0]["value"] for row in report.payload.ir
    ]
    assert sorted(rhs_values) == [0, 1]


def test_vendor_shape_opaque_only_no_computed_companion() -> None:
    report = build_literal_call_report(
        source=_VENDOR_SHAPE_TRUE,
        filename="t.py",
        memento_file="t.py",
    )
    assert report is not None
    # One sworn fact only — no derived companion row for the attribute.
    assert len(report.payload.ir) == 1
    assert all("#euf#" in (row.name or "") for row in report.payload.ir)
    # No fabricated computed row such as call:shape(...) == N outside the swear.
    assert len(_euf_names(report)) == 1


def test_method_sum_euf_name_unchanged() -> None:
    report = build_literal_call_report(
        source=_METHOD_SUM,
        filename="t.py",
        memento_file="t.py",
    )
    assert report is not None
    assert _euf_names(report) == [_SUM_EUF]


def test_vendor_empty_attribute_is_coordinate() -> None:
    report = build_literal_call_report(
        source=(
            "import pandas as pd\n"
            "def t():\n"
            "    assert pd.DataFrame().empty == True\n"
        ),
        filename="t.py",
        memento_file="t.py",
    )
    assert report is not None
    assert (
        "empty#euf#c:call:empty(c:call:pandas.DataFrame())::assertion"
        in _euf_names(report)
    )
    assert "py.attr" not in _ir_blob(report)


def test_vendor_attribute_discrimination_through_real_solver(
    tmp_path: Path,
) -> None:
    """Core soundness DoD: shared euf key → lying swear refutes truthful swear.

    Before this work, dual asserts about `df.empty` used distinct location-keyed
    contract names and the consistency checker refused both (no shared key to
    conjoin). After: one euf key, structural contradiction → unsat.
    """
    pair = (
        "import pandas as pd\n"
        "def t_true():\n"
        "    assert pd.DataFrame().empty == True\n"
        "def t_lie():\n"
        "    assert pd.DataFrame().empty == False\n"
    )
    result = run_source_through_real_solver(tmp_path, pair)
    assert result.verdict == "unsat"
    names = [
        row.get("name")
        for row in result.lift_doc.get("ir", [])
        if isinstance(row, dict)
    ]
    assert names == [
        "empty#euf#c:call:empty(c:call:pandas.DataFrame())::assertion",
        "empty#euf#c:call:empty(c:call:pandas.DataFrame())::assertion",
    ]
    reason = result.prove_doc.get("rows", [{}])[0].get("reason", "")
    assert "contradictory" in reason


_VENDOR_SHAPE_BODY_DIG = (
    "import pandas as pd\n"
    "\n"
    "def A():\n"
    "    return pd.DataFrame().shape\n"
    "\n"
    "def test_a():\n"
    "    assert A() == (0, 0)\n"
)

_VENDOR_SHAPE_BODY_DIG_LIE = (
    "import pandas as pd\n"
    "\n"
    "def A():\n"
    "    return pd.DataFrame().shape\n"
    "\n"
    "def test_a():\n"
    "    assert A() == (1, 1)\n"
)


def test_vendor_shape_body_dig_emits_universe_coordinate() -> None:
    """Body dig of `return pd.DataFrame().shape` must state out == call:shape(...).

    #3905 routes direct `df.shape == expected` through the assertion euf door.
    Without import aliases on the body universe mint, symbolic_term left free
    var `pd` and the universe was refused — call:shape never appeared (same
    refuse family as opaque hash-in-body).
    """
    report = build_literal_call_report(
        source=_VENDOR_SHAPE_BODY_DIG,
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
    assert "call:shape" in post_blob, post_blob
    assert "call:pandas.DataFrame" in post_blob, post_blob
    assert "py.attr" not in post_blob
    dig_reasons = [
        item.get("reason", "")
        for item in (report.payload.diagnostics or [])
        if isinstance(item, dict) and item.get("kind") == "dig-boundary"
    ]
    assert not any("open non-formal" in reason for reason in dig_reasons), dig_reasons


def test_vendor_shape_body_dig_truthful_sat_through_real_solver(
    tmp_path: Path,
) -> None:
    """Body dig of opaque attr: universe coordinate + sworn A()==(0,0) → sat.

    Opaque-only (no companion). Lying A()==(1,1) alone also stays sat — there is
    no fabricated shape value to form a refutation twin (same honest limit as
    free hash body dig). Refuse regression is the gate this seed pins.
    """
    truthful = run_source_through_real_solver(
        tmp_path / "truthful", _VENDOR_SHAPE_BODY_DIG
    )
    statuses = [
        row.get("status") for row in truthful.prove_doc.get("rows", [])
    ]
    assert truthful.verdict == "sat", (truthful.verdict, statuses)
    assert "refused" not in statuses
    ir_blob = repr(truthful.lift_doc.get("ir", []))
    assert "call:shape" in ir_blob

    lying = run_source_through_real_solver(tmp_path / "lying", _VENDOR_SHAPE_BODY_DIG_LIE)
    lying_statuses = [row.get("status") for row in lying.prove_doc.get("rows", [])]
    # Honest limitation: no companion → no refutation twin for free opaque shape.
    assert lying.verdict == "sat", (lying.verdict, lying_statuses)
    assert "refused" not in lying_statuses
    assert "call:shape" in repr(lying.lift_doc.get("ir", []))
