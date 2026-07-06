from __future__ import annotations

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report

_URLSAFE_SOURCE = (
    "import base64\n"
    "\n"
    "def test_urlsafe_seam():\n"
    '    assert base64.urlsafe_b64encode(b"provekit~seam") == '
    'b"cHJvdmVraXR-c2VhbQ=="\n'
)


def test_urlsafe_b64encode_mints_bridge_resolvable_alphabet_universe() -> None:
    report = build_literal_call_report(
        source=_URLSAFE_SOURCE,
        filename="test_urlsafe_seam.py",
        memento_file="test_urlsafe_seam.py",
    )

    assert report is not None
    rows = [
        row.to_rpc()
        for row in report.payload.ir
        if row.bridge_source_symbol == "call:base64.urlsafe_b64encode"
    ]

    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "function-contract"
    assert row["bridgeSourceSymbol"] == "call:base64.urlsafe_b64encode"
    assert row["formals"] == ["s"]
    assert row["post"] == {
        "kind": "atomic",
        "name": "str.chars-not-in-set",
        "args": [
            {"kind": "var", "name": "out"},
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "String"},
                "value": "+/",
            },
        ],
    }
    assert [warrant["role"] for warrant in row["sourceWarrants"]] == [
        "python.urlsafe-translate-universe"
    ]
