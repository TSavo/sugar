from dataclasses import replace
from pathlib import Path
import tempfile

import pytest

from sugar_lift_py_tests.generator_construction import (
    GeneratorConstructionV1,
    YieldEffect,
)
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _steps(source: str):
    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False, dir=Path.cwd()
    ) as handle:
        handle.write(source)
        path = handle.name
    function = next(
        SourceFile(workspace_path_source(path, root=str(Path.cwd()))).functions()
    )
    return function._source_visible_generator_steps_from(function.body)


def test_generator_assert_true_advances_to_yield():
    steps = _steps("def g():\n    assert True\n    yield 7\n")
    assert type(steps[0]).__name__ == "AssertStepV1"
    outcome = GeneratorConstructionV1.allocate(
        allocation_coordinate="enter:assert-true",
        frame_coordinate="frame:assert-true",
        binding_state=(),
        steps=steps,
    ).resume()
    assert isinstance(outcome, YieldEffect)


def test_generator_assert_retains_its_exact_occurrence_coordinate():
    steps = _steps("def g():\n    assert True\n    yield 7\n")
    assertion = steps[0]
    span = assertion.occurrence.line_col_span
    assert assertion.assert_coordinate.source_cid == assertion.occurrence.source_cid
    assert assertion.assert_coordinate.start_line == span.start_line
    assert assertion.assert_coordinate.start_col == span.start_col
    assert assertion.assert_coordinate.end_line == span.end_line
    assert assertion.assert_coordinate.end_col == span.end_col


def test_generator_assert_rejects_a_foreign_occurrence():
    truthful = _steps("def g():\n    assert True\n    yield 7\n")[0]
    foreign = _steps("def h():\n    assert True\n    yield 8\n")[0]
    with pytest.raises(TypeError, match="assert occurrence does not match"):
        replace(truthful, occurrence=foreign.occurrence)
