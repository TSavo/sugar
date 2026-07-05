from __future__ import annotations

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report


def test_isinstance_tuple_type_lifts_as_vendor_disjunction() -> None:
    report = build_literal_call_report(
        source=(
            "def test_alias(alias):\n" "    assert isinstance(alias, (int, str))\n"
        ),
        filename="test_alias.py",
        memento_file="test_alias.py",
    )

    assert report is not None
    assert len(report.payload.ir) == 1
    assert report.payload.ir[0].inv == {
        "kind": "or",
        "operands": [
            {
                "kind": "atomic",
                "name": "is_type",
                "args": [
                    {"kind": "var", "name": "alias"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "int",
                    },
                ],
            },
            {
                "kind": "atomic",
                "name": "is_type",
                "args": [
                    {"kind": "var", "name": "alias"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "str",
                    },
                ],
            },
        ],
    }


def test_isinstance_tuple_type_truthful_concrete_twin_is_true() -> None:
    report = build_literal_call_report(
        source=("def test_alias():\n" "    assert isinstance(1, (str, int))\n"),
        filename="test_alias.py",
        memento_file="test_alias.py",
    )

    assert report is not None
    assert report.payload.ir[0].inv == {
        "kind": "atomic",
        "name": "=",
        "args": [
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "Bool"},
                "value": True,
            },
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "Bool"},
                "value": True,
            },
        ],
    }


def test_isinstance_tuple_type_lying_concrete_twin_is_false() -> None:
    report = build_literal_call_report(
        source=("def test_alias():\n" "    assert isinstance(1, (str, bytes))\n"),
        filename="test_alias.py",
        memento_file="test_alias.py",
    )

    assert report is not None
    assert report.payload.ir[0].inv == {
        "kind": "atomic",
        "name": "=",
        "args": [
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "Bool"},
                "value": False,
            },
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "Bool"},
                "value": True,
            },
        ],
    }


def test_isinstance_runtime_classinfo_is_typed_red() -> None:
    report = build_literal_call_report(
        source=(
            "def pick_type():\n"
            "    return int\n"
            "def test_alias(alias):\n"
            "    assert isinstance(alias, (int, pick_type()))\n"
        ),
        filename="test_alias.py",
        memento_file="test_alias.py",
    )

    assert report is not None
    assert len(report.payload.effects) == 1
    effect = report.payload.effects[0].effect
    assert type(effect).__name__ == "RuntimeEffect"
    assert "isinstance classinfo runtime boundary" in effect.reason
    assert "observed=Call" in effect.reason


def test_isinstance_assertion_lifts_as_python_builtin_fact() -> None:
    report = build_literal_call_report(
        source=(
            "import types\n"
            "def test_alias(alias):\n"
            "    assert isinstance(alias, types.GenericAlias)\n"
        ),
        filename="test_alias.py",
        memento_file="test_alias.py",
    )

    assert report is not None
    assert len(report.payload.ir) == 1
    contract = report.payload.ir[0]
    assert contract.name == "test_alias::test_alias::assert:3:4::assertion"
    assert contract.inv == {
        "kind": "atomic",
        "name": "is_type",
        "args": [
            {"kind": "var", "name": "alias"},
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "String"},
                "value": "types.GenericAlias",
            },
        ],
    }
    assert contract.source_warrants[0].role == "python.isinstance-assertion-sugar"
    assert [row.selected for row in report.payload.factory_walk] == [
        "IsInstanceAssertionSugar"
    ]
    assert report.payload.factory_walk[0].requested_role == "AssertionSurface"


def test_isinstance_assertion_lifts_call_subject_with_keywords_symbolically() -> None:
    report = build_literal_call_report(
        source=(
            "import numpy as np\n"
            "def test_array():\n"
            "    assert isinstance(np.array([1], dtype=np.int64), np.ndarray)\n"
        ),
        filename="test_array.py",
        memento_file="test_array.py",
    )

    assert report is not None
    fact = report.payload.ir[0].inv
    assert fact["name"] == "is_type"
    assert fact["args"][0] == {
        "kind": "ctor",
        "name": "call:numpy.array",
        "args": [
            {
                "kind": "ctor",
                "name": "array",
                "args": [
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": 1,
                    }
                ],
            },
            {
                "kind": "ctor",
                "name": "kw:dtype",
                "args": [
                    {
                        "kind": "ctor",
                        "name": "py.attr",
                        "args": [
                            {"kind": "var", "name": "np"},
                            {
                                "kind": "const",
                                "sort": {"kind": "primitive", "name": "String"},
                                "value": "int64",
                            },
                        ],
                    }
                ],
            },
        ],
    }
    assert fact["args"][1]["value"] == "np.ndarray"
