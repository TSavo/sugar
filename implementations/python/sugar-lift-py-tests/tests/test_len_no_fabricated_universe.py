from __future__ import annotations

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report

# `len` is an opaque operator, not a contracted thing we dig. Wrapping a callsite in
# `len` does not warrant a floor, a reduction, or a fabricated domain axiom -- it
# NAMES a different contract at a composed coordinate. `assert len(x) == N` is one
# sworn EqualityFact at `call:len(<x>)`; that is the whole emission. There is no
# `len::builtin-universe` FunctionContract, because the vendor never swore an
# operator-level `out >= 0` law -- inventing one is fabrication (vendor tests ARE the
# spec; no assertion, no row). See the callsite-lifting model: one callsite, two (or
# more) contracts, universe invariant, the postcondition NAME carries the opaque
# wrapper.

_LEN_LITERAL_SOURCE = (
    "def test_len_seam():\n"
    "    assert len([1, 2, 3]) == 3\n"
)

_LEN_VENDOR_SOURCE = (
    "import pandas as pd\n"
    "def test_len_vendor():\n"
    "    assert len(pd.DataFrame()) == 0\n"
)


def _len_bridge_rows(report) -> list[dict]:
    return [
        row.to_rpc()
        for row in report.payload.ir
        if getattr(row, "bridge_source_symbol", None) == "call:len"
    ]


def _euf_names(report) -> list[str]:
    return [row.name for row in report.payload.ir if "#euf#" in (row.name or "")]


def test_len_literal_emits_sworn_fact_and_no_fabricated_universe() -> None:
    report = build_literal_call_report(
        source=_LEN_LITERAL_SOURCE,
        filename="test_len_seam.py",
        memento_file="test_len_seam.py",
    )
    assert report is not None

    # The sworn coordinate is named by the full term, len opaque, arg carried:
    assert "len#euf#c:call:len(c:array(i:1,i:2,i:3))::assertion" in _euf_names(report)
    # No fabricated operator-level universe.
    assert _len_bridge_rows(report) == []
    assert all(
        row.name != "len::builtin-universe" for row in report.payload.ir
    )


def test_len_of_vendor_call_emits_composed_coordinate_no_universe() -> None:
    report = build_literal_call_report(
        source=_LEN_VENDOR_SOURCE,
        filename="test_len_vendor.py",
        memento_file="test_len_vendor.py",
    )
    assert report is not None

    # len(pd.DataFrame()) == 0 seals the vendor call opaque inside the coordinate name.
    assert (
        "len#euf#c:call:len(c:call:pandas.DataFrame())::assertion"
        in _euf_names(report)
    )
    # No dig of pd.DataFrame, no fabricated len universe: just the one sworn fact.
    assert _len_bridge_rows(report) == []
