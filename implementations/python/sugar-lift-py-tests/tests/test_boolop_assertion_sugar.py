from __future__ import annotations

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report


def test_boolop_assertion_composes_child_assertions() -> None:
    report = build_literal_call_report(
        source=(
            "def test_dtype(dt):\n"
            "    assert not hasattr(dt, 'na_object') and dt.coerce is True\n"
        ),
        filename="test_stringdtype.py",
        memento_file="test_stringdtype.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == "python.boolop-assertion-sugar"
    assert contract.inv == {
        "kind": "and",
        "operands": [
            {
                "kind": "not",
                "operands": [
                    {
                        "kind": "atomic",
                        "name": "py.truthy",
                        "args": [
                            {
                                "kind": "ctor",
                                "name": "call:hasattr",
                                "args": [
                                    {"kind": "var", "name": "dt"},
                                    {
                                        "kind": "const",
                                        "sort": {
                                            "kind": "primitive",
                                            "name": "String",
                                        },
                                        "value": "na_object",
                                    },
                                ],
                            }
                        ],
                    }
                ],
            },
            {
                "kind": "atomic",
                "name": "identity",
                "args": [
                    {
                        "kind": "ctor",
                        "name": "call:coerce",
                        "args": [{"kind": "var", "name": "dt"}],
                    },
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Bool"},
                        "value": True,
                    },
                ],
            },
        ],
    }
    assert [row.selected for row in report.payload.factory_walk] == [
        "BoolOpAssertionSugar"
    ]
