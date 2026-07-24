from __future__ import annotations

import ast
import importlib
import json
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "loop_construction"
EXPECTED_CASES = {
    "continue_backedge",
    "break_exit",
    "for_else_exhaustion",
    "for_else_break",
    "while_else_exhaustion",
    "while_else_break",
    "nested_break",
    "nested_continue",
    "concrete_bounded",
    "symbolic_break",
    "guarded_break_join",
    "guarded_continue_join",
}


@pytest.fixture
def loops(monkeypatch):
    monkeypatch.syspath_prepend(str(FIXTURES))
    sys.modules.pop("arbitrary_iteration_module", None)
    return importlib.import_module("arbitrary_iteration_module")


def _matrix():
    return json.loads((FIXTURES / "cases.json").read_text())


def test_truth_set_is_complete_and_structural():
    manifest = _matrix()
    assert manifest["schemaVersion"] == 1
    assert manifest["moduleGraph"] == ["arbitrary_iteration_module.py"]
    assert {case["case"] for case in manifest["cases"]} == EXPECTED_CASES
    required_case_fields = {
        "case",
        "construct",
        "loopKind",
        "constructionVerdict",
        "truthfulVerdict",
        "lyingVerdict",
        "lyingDisposition",
    }
    assert all(required_case_fields <= case.keys() for case in manifest["cases"])
    assert all(
        case["truthfulVerdict"] != case["lyingVerdict"] for case in manifest["cases"]
    )
    assert all(
        case["lyingDisposition"] in {"reject", "typed-loud"}
        for case in manifest["cases"]
    )

    source_path = FIXTURES / "arbitrary_iteration_module.py"
    source_text = source_path.read_text()
    tree = ast.parse(source_text)
    functions = {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    assert EXPECTED_CASES <= functions.keys()
    assert any(isinstance(node, ast.For) for node in ast.walk(tree))
    assert any(isinstance(node, ast.While) for node in ast.walk(tree))
    assert any(isinstance(node, ast.Break) for node in ast.walk(tree))
    assert any(isinstance(node, ast.Continue) for node in ast.walk(tree))

    combined = source_text + json.dumps(manifest, sort_keys=True)
    for forbidden in (
        "pytest",
        "pandas",
        "numpy",
        "vendor",
        "provider",
        "enrollment",
        "catalog",
    ):
        assert forbidden not in combined.lower()


def test_continue_routes_to_backedge_and_skips_tail(loops):
    actual = loops.continue_backedge()
    assert actual == {
        "head": (0, 1, 2, 3),
        "tail": (1, 3),
        "post": 4,
    }
    assert actual != {"head": (0, 1, 2, 3), "tail": (0, 1, 2, 3), "post": 4}


def test_break_exit_state_excludes_unvisited_elements(loops):
    actual = loops.break_exit()
    assert actual == {
        "visited": (0, 1, 2),
        "completed_tail": (0, 1),
        "post": 2,
    }
    assert actual != {
        "visited": (0, 1, 2, 3, 4),
        "completed_tail": (0, 1, 3, 4),
        "post": 4,
    }


@pytest.mark.parametrize(
    ("function_name", "expected"),
    [
        ("for_else_exhaustion", ("body:0", "body:1", "else")),
        ("for_else_break", ("body:0", "body:1")),
        ("while_else_exhaustion", ("body:0", "body:1", "else")),
        ("while_else_break", ("body:0", "body:1")),
    ],
)
def test_loop_else_runs_only_on_normal_exhaustion(loops, function_name, expected):
    assert getattr(loops, function_name)() == expected


def test_nested_break_targets_nearest_loop(loops):
    actual = loops.nested_break()
    assert actual == (
        ("outer", 0),
        ("inner", 0, 0),
        ("after-inner", 0),
        ("outer", 1),
        ("inner", 1, 0),
        ("after-inner", 1),
        ("outer-complete",),
    )


def test_nested_continue_targets_nearest_loop(loops):
    actual = loops.nested_continue()
    assert actual == (
        ("head", 0, 0),
        ("head", 0, 1),
        ("tail", 0, 1),
        ("after-inner", 0),
        ("head", 1, 0),
        ("head", 1, 1),
        ("tail", 1, 1),
        ("after-inner", 1),
    )


def test_concrete_bounded_loop_threads_exact_iteration_state(loops):
    assert loops.concrete_bounded() == (
        (0, 1),
        (1, 3),
        (2, 6),
        (3, 10),
    )


def test_symbolic_break_runtime_twin_rejects_whole_iterable_claim(loops):
    actual = loops.symbolic_break((2, 4, 7, 9), 7)
    assert actual == {"visited": (2, 4, 7), "stopped": True}
    assert actual["visited"] != (2, 4, 7, 9)
    with pytest.raises(AssertionError):
        loops.symbolic_break_lying((2, 4, 7, 9), 7)
    case = next(case for case in _matrix()["cases"] if case["case"] == "symbolic_break")
    assert case["lyingFunction"] == "symbolic_break_lying"
    assert case["constructionVerdict"] == "opaque-loop-with-typed-break-obligation"
    assert case["lyingVerdict"] == "universal-over-entire-iterable"
    assert case["lyingDisposition"] == "typed-loud"


@pytest.mark.parametrize("guard", [False, True])
def test_guarded_break_join_preserves_guarded_state(loops, guard):
    expected = (
        {"visited": (0, 1, 2), "tail": (0, 1, 2), "post": 2}
        if not guard
        else {"visited": (0, 1), "tail": (0,), "post": 1}
    )
    assert loops.guarded_break_join(guard) == expected


@pytest.mark.parametrize("guard", [False, True])
def test_guarded_continue_join_preserves_guarded_state(loops, guard):
    expected = (
        {"visited": (0, 1, 2), "tail": (0, 1, 2), "post": 3}
        if not guard
        else {"visited": (0, 1, 2), "tail": (0, 2), "post": 3}
    )
    assert loops.guarded_continue_join(guard) == expected
