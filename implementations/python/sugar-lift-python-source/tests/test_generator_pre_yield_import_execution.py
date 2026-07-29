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


def test_generator_import_advances_to_yield():
    steps = _steps("def g():\n    import math\n    yield 7\n")
    assert type(steps[0]).__name__ == "ImportStepV1"
    outcome = GeneratorConstructionV1.allocate(
        allocation_coordinate="enter:import",
        frame_coordinate="frame:import",
        binding_state=(),
        steps=steps,
    ).resume()
    assert isinstance(outcome, YieldEffect)


def test_generator_import_retains_exact_occurrence():
    step = _steps("def g():\n    import math\n    yield 7\n")[0]
    span = step.occurrence.line_col_span
    assert step.coordinate.source_cid == step.occurrence.source_cid
    assert (step.coordinate.start_line, step.coordinate.start_col) == (
        span.start_line,
        span.start_col,
    )
    assert (step.coordinate.end_line, step.coordinate.end_col) == (
        span.end_line,
        span.end_col,
    )


def test_generator_import_rejects_foreign_occurrence():
    truthful = _steps("def g():\n    import math\n    yield 7\n")[0]
    foreign = _steps("def h():\n    import math\n    yield 8\n")[0]
    with pytest.raises(TypeError, match="import occurrence does not match"):
        replace(truthful, occurrence=foreign.occurrence)
