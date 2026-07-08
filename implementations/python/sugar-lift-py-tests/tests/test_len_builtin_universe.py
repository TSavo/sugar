from __future__ import annotations

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report

_LEN_ASSERTION_SOURCE = (
    "def test_len_seam():\n"
    "    assert len([1, 2, 3]) == 3\n"
)

_NO_LEN_ASSERTION_SOURCE = (
    "def test_no_len_seam():\n"
    "    assert 1 + 2 == 3\n"
)


def _len_universe_rows(report) -> list[dict]:
    return [
        row.to_rpc()
        for row in report.payload.ir
        if row.bridge_source_symbol == "call:len"
    ]


def test_len_assertion_mints_bridge_resolvable_universe() -> None:
    """A vendor suite asserting `len(x) == N` is, per doctrine, len's own spec (no
    Python body exists anywhere to dig): the lift must mint a `call:len::universe`
    FunctionContract carrying formals so `collect_ambient_posts` has a bridge target."""
    report = build_literal_call_report(
        source=_LEN_ASSERTION_SOURCE,
        filename="test_len_seam.py",
        memento_file="test_len_seam.py",
    )

    assert report is not None
    rows = _len_universe_rows(report)

    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "function-contract"
    assert row["bridgeSourceSymbol"] == "call:len"
    assert row["formals"] == []
    assert row["post"] == {
        "kind": "atomic",
        "name": "=",
        "args": [
            {"kind": "var", "name": "out"},
            {"kind": "const", "sort": {"kind": "primitive", "name": "Int"}, "value": 3},
        ],
    }
    assert [warrant["role"] for warrant in row["sourceWarrants"]] == [
        "python.builtin-call-universe"
    ]


def test_no_len_assertion_mints_no_len_bridge() -> None:
    """No vendor assertion on `len` means no fact was ever stated about it -- vendor
    tests ARE the spec, so absence of the assertion means absence of the bridge. No
    fabrication: a suite that never asserts len must not get a len universe."""
    report = build_literal_call_report(
        source=_NO_LEN_ASSERTION_SOURCE,
        filename="test_no_len_seam.py",
        memento_file="test_no_len_seam.py",
    )

    assert report is not None
    assert _len_universe_rows(report) == []
