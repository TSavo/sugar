"""Producer-minted enrollment values for tests. No test mints its own.

`TargetPatternEnrolledV1` / `TargetPatternNotEnrolledV1` (#7348) are guarded by
an authority sentinel: only `SourceUnit.target_pattern_enrollment` may
construct them. That is the point, so these helpers ASK the producer rather
than fabricating a stand-in -- a hand-rolled double here would be a second
enrollment authority wearing a test costume.
"""

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.nodes import TargetPatternEnrolledV1, TargetPatternNotEnrolledV1
from sugar_source_tree.tree import SourceFile


def enrollment_source_file(source: str, label: str = "tests/enrollment_fixture.py"):
    return SourceFile(
        (source, label, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def producer_not_enrolled():
    """A real, producer-minted `TargetPatternNotEnrolledV1`."""
    source = "def build(items):\n    return items\n"
    node = next(
        candidate
        for candidate in enrollment_source_file(source).nodes()
        if candidate.kind == "Return"
    )
    answer = node.unit.target_pattern_enrollment(node)
    assert isinstance(answer, TargetPatternNotEnrolledV1), answer
    return answer


def producer_enrolled(source: str, kind: str):
    """A real, producer-minted `TargetPatternEnrolledV1` for `kind` in `source`."""
    node = next(
        candidate
        for candidate in enrollment_source_file(source).nodes()
        if candidate.kind == kind
    )
    answer = node.unit.target_pattern_enrollment(node)
    assert isinstance(answer, TargetPatternEnrolledV1), answer
    return node, answer
