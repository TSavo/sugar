from __future__ import annotations

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.factory import build_node
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.ir import term_to_value
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term


def test_constant_sugar_lifts_bytes_literal_in_projected_equality() -> None:
    report = build_literal_call_report(
        source=("def test_stdout(p):\n" "    assert p.stdout == b'I made it!'\n"),
        filename="test_pyinstaller.py",
        memento_file="test_pyinstaller.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.inv == {
        "kind": "atomic",
        "name": "=",
        "args": [
            {
                "kind": "ctor",
                "name": "py.attr",
                "args": [
                    {"kind": "var", "name": "p"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "stdout",
                    },
                ],
            },
            {
                "kind": "ctor",
                "name": "python:bytes",
                "args": [
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "49206d61646520697421",
                    }
                ],
            },
        ],
    }


def test_constant_sugar_lifts_complex_literal_in_call_argument() -> None:
    report = build_literal_call_report(
        source=("def test_logical(t):\n" "    assert t(0j) == 0\n"),
        filename="test_return_logical.py",
        memento_file="test_return_logical.py",
    )

    assert report is not None
    contract = next(c for c in report.payload.ir if c.name.endswith("::assertion"))
    assert contract.inv["args"][0]["args"] == [
        {
            "kind": "ctor",
            "name": "py.complex",
            "args": [
                {
                    "kind": "const",
                    "sort": {"kind": "primitive", "name": "Real"},
                    "value": "0.0",
                },
                {
                    "kind": "const",
                    "sort": {"kind": "primitive", "name": "Real"},
                    "value": "0.0",
                },
            ],
        }
    ]


def test_constant_sugar_lifts_ellipsis_term() -> None:
    result = build_node(
        _first_constant("x = ...\n"),
        filename="test_multiarray.py",
        role=SugarRole.TERM,
    )

    assert result.audit_row.selected == "ConstantSugar"
    assert _term(result.sugar) == '{"args":[],"kind":"ctor","name":"py.ellipsis"}'


def _first_constant(source: str):
    root = SourceFragment.from_source(source, "constant.py")
    return next(fragment for fragment in root.walk() if fragment.observed == "Constant")


def _term(sugar):
    return encode_jcs(
        term_to_value(
            floor_to_term(
                complete_value(sugar.desugar(), owner="constant sugar"),
                owner="constant sugar",
            )
        )
    )
