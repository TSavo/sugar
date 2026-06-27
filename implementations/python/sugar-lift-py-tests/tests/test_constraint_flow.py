from __future__ import annotations

import ast

from sugar_lift_py_tests.constraint_flow import (
    ConstraintDigRequest,
    recognize_callsite_fact,
    walk_constraint_universe,
)


def test_vendor_callsite_fact_triggers_dig_and_body_universe_walk() -> None:
    test_tree = ast.parse("def test_age():\n    assert User(age=21).age >= 18\n")
    assert_stmt = test_tree.body[0].body[0]

    fact = recognize_callsite_fact(
        assert_stmt,
        source_memento={"file": "test_model.py", "line": 2, "col": 4},
    )

    assert fact is not None
    assert fact.sugar_name == "python.vendor-test.callsite-assert"
    assert fact.callsite == "User(age=21)"
    assert fact.subject == "User.age"
    assert fact.fact == {
        "kind": "atomic",
        "name": ">=",
        "args": [
            {"kind": "field", "owner": "User", "name": "age"},
            {"kind": "int", "value": 18},
        ],
    }
    assert fact.source_memento["file"] == "test_model.py"

    dig = fact.trigger_dig()
    assert isinstance(dig, ConstraintDigRequest)
    assert dig.fact_subject == "User.age"
    assert dig.target_symbol == "User"
    assert dig.reason == "vendor callsite fact warrants constraint-universe dig for User"

    body_tree = ast.parse("class User:\n    age: int = Field(..., ge=18)\n")
    universe = walk_constraint_universe(
        body_tree,
        dig,
        source_memento={"file": "model.py", "line": 1, "col": 0},
        resolved_names={"Field": "pydantic.Field"},
    )

    assert universe.sugar_chain == [
        "python.term.int-literal",
        "python.constraint.field-keyword",
        "python.body-universe.class",
    ]
    assert universe.predicates == [fact.fact]
    assert universe.warranted_by == dig
    assert universe.proofir == [
        {
            "kind": "contract",
            "name": "User.age::universe",
            "post": fact.fact,
            "source": {"file": "model.py", "line": 1, "col": 0},
            "warrantedBy": dig.to_json(),
        }
    ]
    assert universe.source_memento["file"] == "model.py"


def test_model_class_without_constraint_shape_emits_no_universe_predicates() -> None:
    tree = ast.parse("class User(BaseModel):\n    age: int\n")
    dig = ConstraintDigRequest(
        fact_subject="User.age",
        target_symbol="User",
        source_memento={"file": "test_model.py", "line": 2, "col": 4},
        reason="vendor callsite fact warrants constraint-universe dig for User",
    )

    universe = walk_constraint_universe(
        tree,
        dig,
        source_memento={"file": "model.py", "line": 1, "col": 0},
        resolved_names={"BaseModel": "pydantic.BaseModel"},
    )

    assert universe.predicates == []
    assert universe.proofir == []
    assert universe.effects == []
    assert universe.warranted_by == dig
