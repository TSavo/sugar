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

_TWO_LEN_INSTANCES_SOURCE = (
    "def test_len_seam_a():\n"
    "    assert len([1, 2, 3]) == 3\n"
    "\n"
    "def test_len_seam_b():\n"
    "    assert len([4, 5]) == 2\n"
)


def _len_universe_rows(report) -> list[dict]:
    return [
        row.to_rpc()
        for row in report.payload.ir
        if row.bridge_source_symbol == "call:len"
    ]


def test_len_assertion_mints_one_operator_level_universe() -> None:
    """The universe is OPERATOR-level, not instance-level (T's correction): what's
    true of `len` ITSELF (its signature -- one argument, non-negative Int result),
    not any one call's concrete value. The vendor's `len([1,2,3]) == 3` is a FACT,
    carried untouched by the existing EqualityFact/ground-callsite-fact path (the
    'Vendor fact' line already renders without this function) -- this universe is
    the axiom that backs every len callsite, mirroring how the 5 dig-derived
    universes and `_urlsafe_translate_function_universe` state a law over formals
    the post itself never references."""
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
    assert row["name"] == "len::builtin-universe"
    # Arity matches len's one argument (required for the verifier's
    # `linked_ambient_post_instances_for_inv` to even consider this post), but the
    # post is the DOMAIN axiom, independent of the formal and of any instance value.
    assert row["formals"] == ["x"]
    assert row["post"] == {
        "kind": "atomic",
        "name": "≥",
        "args": [
            {"kind": "var", "name": "out"},
            {"kind": "const", "sort": {"kind": "primitive", "name": "Int"}, "value": 0},
        ],
    }
    assert [warrant["role"] for warrant in row["sourceWarrants"]] == [
        "python.builtin-call-universe"
    ]


def test_two_len_instances_mint_exactly_one_universe() -> None:
    """Two different len callsites in the same lift must collapse to ONE universe
    contract (deduped by symbol, threaded via `builtin_universes_emitted`) -- this is
    the fix for the earlier per-instance design: one operator-level universe
    legitimately attaches to every len callsite in the file, it is not re-minted per
    assertion."""
    report = build_literal_call_report(
        source=_TWO_LEN_INSTANCES_SOURCE,
        filename="test_len_seam_two.py",
        memento_file="test_len_seam_two.py",
    )

    assert report is not None
    rows = _len_universe_rows(report)
    assert len(rows) == 1
    assert rows[0]["name"] == "len::builtin-universe"


def test_no_len_assertion_mints_no_len_bridge() -> None:
    """No vendor assertion on `len` means no fact was ever stated about it -- vendor
    tests ARE the spec, so absence of the assertion means absence of the universe. No
    fabrication: a suite that never asserts len must not get a len universe."""
    report = build_literal_call_report(
        source=_NO_LEN_ASSERTION_SOURCE,
        filename="test_no_len_seam.py",
        memento_file="test_no_len_seam.py",
    )

    assert report is not None
    assert _len_universe_rows(report) == []
