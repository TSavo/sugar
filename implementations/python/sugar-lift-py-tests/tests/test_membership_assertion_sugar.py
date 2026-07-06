from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ObjectMethodValue,
    ObjectValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import (
    atomic,
    bool_const,
    ctor,
    eq,
    make_var,
    not_,
    num,
    str_const,
)
from sugar_lift_py_tests.operations import ContainsOperation, perform_operation
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

TRUE_CONST = {
    "kind": "const",
    "sort": {"kind": "primitive", "name": "Bool"},
    "value": True,
}
FALSE_CONST = {
    "kind": "const",
    "sort": {"kind": "primitive", "name": "Bool"},
    "value": False,
}


def _reduce_assertion_with_operation_log(source: str, binds: dict | None = None):
    temporal = TemporalContext.empty()
    for name, value in (binds or {}).items():
        temporal = temporal.bind_value(name, value)
    build_ctx = FactoryBuildContext(
        filename="test_contains.py", catalog=default_catalog()
    )
    build_ctx = replace(build_ctx, temporal=temporal)
    statement = ast.parse(source).body[0]
    body = build_ctx.build_body(statement, SugarRole.ASSERTION)
    reduce_ctx = ReduceContext(temporal=temporal)
    return body.reduce(reduce_ctx), reduce_ctx.operation_log


def test_membership_assertion_uses_string_floor_contains() -> None:
    report = build_literal_call_report(
        source=("def test_string_membership():\n" "    assert 'mp' in 'numpy'\n"),
        filename="test_contains.py",
        memento_file="test_contains.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == "python.membership-assertion-sugar"
    assert contract.inv == {
        "kind": "atomic",
        "name": "=",
        "args": [TRUE_CONST, TRUE_CONST],
    }
    assert [row.selected for row in report.payload.factory_walk] == [
        "MembershipAssertionSugar"
    ]


def test_membership_assertion_uses_shared_operation_dispatch_path() -> None:
    formula, operation_log = _reduce_assertion_with_operation_log(
        "assert 'mp' in 'numpy'"
    )

    assert formula == eq(bool_const(True), bool_const(True))
    assert operation_log == [
        ("MembershipAssertionSugar", "contains_with", "ContainsOperation"),
    ]


def test_membership_contains_operation_dispatches_object_contains_method() -> None:
    method_body = SugarBody(sugar=object(), role=SugarRole.TERM)
    item = TermValue(42)
    bag = ObjectValue(
        class_name="Bag",
        fields=(),
        methods=(
            ObjectMethodValue(
                name="__contains__",
                parameters=("self", "item"),
                body=method_body,
            ),
        ),
        identity="test_contains.py:1:0",
    )

    outcome = perform_operation(
        owner="MembershipAssertionSugar",
        blame="test_contains.py:7:4",
        receiver=bag,
        operation=ContainsOperation(
            item=item,
            owner="MembershipAssertionSugar",
            blame="test_contains.py:7:4",
        ),
        ctx=ReduceContext(temporal=TemporalContext.empty()),
    )
    callsite = complete_value(outcome, owner="object contains dispatch")

    assert isinstance(callsite, CallSiteValue)
    assert callsite.target_name == "Bag.__contains__"
    assert callsite.arg_values == (bag, item)
    assert callsite.parameters == ("self", "item")
    assert callsite.term == ctor(
        "call:Bag.__contains__",
        [
            ctor(
                "py.object.identity",
                [str_const("Bag"), str_const("test_contains.py:1:0")],
            ),
            num(42),
        ],
    )
    assert callsite.body is method_body


def test_membership_assertion_emits_symbolic_contains_predicate() -> None:
    formula, operation_log = _reduce_assertion_with_operation_log(
        "assert 'needle' in haystack",
        {"haystack": SymbolicValue(make_var("haystack"))},
    )

    assert formula == atomic("contains", [make_var("haystack"), str_const("needle")])
    assert operation_log == [
        ("MembershipAssertionSugar", "contains_with", "ContainsOperation")
    ]


def test_membership_assertion_emits_string_contains_symbolic_item_predicate() -> None:
    formula, operation_log = _reduce_assertion_with_operation_log(
        "assert needle in 'abcdef'",
        {"needle": SymbolicValue(make_var("needle"))},
    )

    assert formula == atomic("contains", [str_const("abcdef"), make_var("needle")])
    assert operation_log == [
        ("MembershipAssertionSugar", "contains_with", "ContainsOperation")
    ]


def test_membership_assertion_negates_symbolic_not_in_predicate() -> None:
    formula, operation_log = _reduce_assertion_with_operation_log(
        "assert 'needle' not in haystack",
        {"haystack": SymbolicValue(make_var("haystack"))},
    )

    assert formula == not_(
        atomic("contains", [make_var("haystack"), str_const("needle")])
    )
    assert operation_log == [
        ("MembershipAssertionSugar", "contains_with", "ContainsOperation")
    ]


def test_membership_assertion_emits_symbolic_bytes_contains_predicate() -> None:
    formula, operation_log = _reduce_assertion_with_operation_log(
        "assert b'_multiarray_umath' not in payload",
        {"payload": SymbolicValue(make_var("payload"))},
    )

    assert formula == not_(
        atomic(
            "contains",
            [
                make_var("payload"),
                ctor(
                    "python:bytes",
                    [str_const("5f6d756c746961727261795f756d617468")],
                ),
            ],
        )
    )
    assert operation_log == [
        ("MembershipAssertionSugar", "contains_with", "ContainsOperation")
    ]


def test_membership_assertion_uses_array_floor_contains() -> None:
    report = build_literal_call_report(
        source=("def test_array_membership():\n" "    assert 2 in [1, 2, 3]\n"),
        filename="test_contains.py",
        memento_file="test_contains.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.inv == {
        "kind": "atomic",
        "name": "=",
        "args": [TRUE_CONST, TRUE_CONST],
    }


def test_membership_assertion_emits_symbolic_array_contains_predicate() -> None:
    formula, operation_log = _reduce_assertion_with_operation_log(
        "assert result_year in [1973, 1999]",
        {"result_year": SymbolicValue(make_var("result_year"))},
    )

    assert formula == atomic(
        "contains",
        [ctor("array", [num(1973), num(1999)]), make_var("result_year")],
    )
    assert operation_log == [
        ("MembershipAssertionSugar", "contains_with", "ContainsOperation")
    ]


def test_membership_assertion_negates_symbolic_array_not_in_predicate() -> None:
    formula, operation_log = _reduce_assertion_with_operation_log(
        "assert result_year not in [1973, 1999]",
        {"result_year": SymbolicValue(make_var("result_year"))},
    )

    assert formula == not_(
        atomic(
            "contains",
            [ctor("array", [num(1973), num(1999)]), make_var("result_year")],
        )
    )
    assert operation_log == [
        ("MembershipAssertionSugar", "contains_with", "ContainsOperation")
    ]


def test_membership_assertion_array_symbolic_contains_reaches_production_cli(
    tmp_path: Path,
) -> None:
    result = run_source_through_real_solver(
        tmp_path / "array-symbolic-membership",
        "def test_array_symbolic_membership(result_year):\n"
        "    assert result_year in [1973, 1999]\n",
    )

    assert "MembershipAssertionSugar" in result.selected_sugars
    assert _first_contract_inv(result.lift_doc) == {
        "kind": "atomic",
        "name": "contains",
        "args": [
            {
                "kind": "ctor",
                "name": "array",
                "args": [_int_const(1973), _int_const(1999)],
            },
            {"kind": "var", "name": "result_year"},
        ],
    }
    assert _prove_statuses(result.prove_doc) == ["refused"]


def test_membership_assertion_uses_tuple_floor_contains() -> None:
    formula, operation_log = _reduce_assertion_with_operation_log(
        "assert 2 in (1, 2, 3)"
    )

    assert formula == eq(bool_const(True), bool_const(True))
    assert operation_log == [
        (
            "TupleLiteralSugar",
            "construct_sequence_with",
            "SequenceConstructionOperation",
        ),
        ("MembershipAssertionSugar", "contains_with", "ContainsOperation"),
    ]


def test_membership_assertion_negates_not_in_after_tuple_floor_contains() -> None:
    formula, operation_log = _reduce_assertion_with_operation_log(
        "assert 'missing' not in ('left', 'right')"
    )

    assert formula == eq(bool_const(True), bool_const(True))
    assert operation_log == [
        (
            "TupleLiteralSugar",
            "construct_sequence_with",
            "SequenceConstructionOperation",
        ),
        ("MembershipAssertionSugar", "contains_with", "ContainsOperation"),
    ]


def test_membership_assertion_emits_symbolic_tuple_contains_predicate() -> None:
    formula, operation_log = _reduce_assertion_with_operation_log(
        "assert result_year in (-19999, 1973)",
        {"result_year": SymbolicValue(make_var("result_year"))},
    )

    assert formula == atomic(
        "contains",
        [ctor("tuple", [num(-19999), num(1973)]), make_var("result_year")],
    )
    assert operation_log == [
        ("UnaryOpSugar", "unary_operator_with", "UnaryOperatorOperation"),
        (
            "TupleLiteralSugar",
            "construct_sequence_with",
            "SequenceConstructionOperation",
        ),
        ("MembershipAssertionSugar", "contains_with", "ContainsOperation"),
    ]


def test_membership_assertion_tuple_floor_reaches_production_cli_with_flipping_twin(
    tmp_path: Path,
) -> None:
    truthful = run_source_through_real_solver(
        tmp_path / "tuple-membership-truthful",
        "def test_tuple_membership_truthful():\n" "    assert 2 in (1, 2, 3)\n",
    )
    lying = run_source_through_real_solver(
        tmp_path / "tuple-membership-lying",
        "def test_tuple_membership_lying():\n" "    assert 9 in (1, 2, 3)\n",
    )

    assert "MembershipAssertionSugar" in truthful.selected_sugars
    assert "MembershipAssertionSugar" in lying.selected_sugars
    assert _first_contract_inv(truthful.lift_doc) == {
        "kind": "atomic",
        "name": "=",
        "args": [TRUE_CONST, TRUE_CONST],
    }
    assert _first_contract_inv(lying.lift_doc) == {
        "kind": "atomic",
        "name": "=",
        "args": [FALSE_CONST, TRUE_CONST],
    }
    assert _prove_statuses(truthful.prove_doc) == ["refused"]
    assert _prove_statuses(lying.prove_doc) == ["refused"]
    assert "single constraint has no sibling" in truthful.prove_doc["rows"][0]["reason"]
    assert "single constraint has no sibling" in lying.prove_doc["rows"][0]["reason"]


def test_membership_assertion_uses_set_floor_contains() -> None:
    formula, operation_log = _reduce_assertion_with_operation_log(
        "assert 2 in {1, 2, 3}"
    )

    assert formula == eq(bool_const(True), bool_const(True))
    assert operation_log == [
        ("MembershipAssertionSugar", "contains_with", "ContainsOperation")
    ]


def test_membership_assertion_negates_not_in_after_set_floor_contains() -> None:
    formula, operation_log = _reduce_assertion_with_operation_log(
        "assert 9 not in {1, 2, 3}"
    )

    assert formula == eq(bool_const(True), bool_const(True))
    assert operation_log == [
        ("MembershipAssertionSugar", "contains_with", "ContainsOperation")
    ]


def test_membership_assertion_preserves_symbolic_set_contains_predicate() -> None:
    formula, operation_log = _reduce_assertion_with_operation_log(
        "assert 1 in {x}",
        {"x": SymbolicValue(make_var("x"))},
    )

    assert formula == atomic("contains", [ctor("python:set", [make_var("x")]), num(1)])
    assert operation_log == [
        ("MembershipAssertionSugar", "contains_with", "ContainsOperation")
    ]


def test_membership_assertion_negates_not_in_after_floor_contains() -> None:
    report = build_literal_call_report(
        source=("def test_not_in():\n" "    assert 9 not in [1, 2, 3]\n"),
        filename="test_contains.py",
        memento_file="test_contains.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.inv == {
        "kind": "atomic",
        "name": "=",
        "args": [TRUE_CONST, TRUE_CONST],
    }


def test_membership_assertion_projects_constructor_bound_string_field() -> None:
    report = build_literal_call_report(
        source=(
            "class Record:\n"
            "    def __init__(self):\n"
            "        self.filename = 'test_random.py'\n"
            "\n"
            "def test_constructor_field_membership():\n"
            "    rec = Record()\n"
            "    assert 'test_random' in rec.filename\n"
        ),
        filename="test_record.py",
        memento_file="test_record.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == "python.membership-assertion-sugar"
    assert contract.inv == {
        "kind": "atomic",
        "name": "=",
        "args": [TRUE_CONST, TRUE_CONST],
    }


def test_membership_assertion_curries_constructor_arguments_into_fields() -> None:
    report = build_literal_call_report(
        source=(
            "class Record:\n"
            "    def __init__(self, filename):\n"
            "        self.filename = filename\n"
            "\n"
            "def test_constructor_field_membership():\n"
            "    rec = Record('test_random.py')\n"
            "    assert 'test_random' in rec.filename\n"
        ),
        filename="test_record.py",
        memento_file="test_record.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == "python.membership-assertion-sugar"
    assert contract.inv == {
        "kind": "atomic",
        "name": "=",
        "args": [TRUE_CONST, TRUE_CONST],
    }


def test_membership_assertion_ignores_unused_prior_assignment() -> None:
    report = build_literal_call_report(
        source=(
            "def test_unused_setup_membership():\n"
            "    scratch = {}\n"
            "    assert 'mp' in 'numpy'\n"
        ),
        filename="test_contains.py",
        memento_file="test_contains.py",
    )

    assert report is not None
    assert report.payload.ir[0].inv == {
        "kind": "atomic",
        "name": "=",
        "args": [TRUE_CONST, TRUE_CONST],
    }


def test_membership_assertion_panics_when_receiver_floor_cannot_contains() -> None:
    with pytest.raises(FactoryGap) as exc:
        build_literal_call_report(
            source=("def test_bad_membership():\n" "    assert 1 in 3\n"),
            filename="test_contains.py",
            memento_file="test_contains.py",
        )

    assert exc.value.info["observed"] == "TermValue"
    assert exc.value.info["requested"] == "contains_with"


def _first_contract_inv(lift_doc: dict) -> dict:
    contracts = [row for row in lift_doc.get("ir", []) if row.get("kind") == "contract"]
    assert contracts
    return contracts[0]["inv"]


def _int_const(value: int) -> dict:
    return {
        "kind": "const",
        "sort": {"kind": "primitive", "name": "Int"},
        "value": value,
    }


def _prove_statuses(prove_doc: dict) -> list[str]:
    return [row["status"] for row in prove_doc.get("rows", [])]
