from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import ObjectValue, ReturnValue, TermValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile


def _frame(source: str):
    from sugar_lift_python_source.canonical import blake3_512_of

    tree = SourceFile(
        (source, "renamed_fixture.py", blake3_512_of(source.encode("utf-8")))
    )
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function.source_visible_call_frame()


class _ReduceCtx:
    def __init__(self, temporal: TemporalContext) -> None:
        self.temporal = temporal


@pytest.mark.parametrize(
    ("selector", "annotation"),
    [("renamed_field", ""), ("another_name", ": object")],
)
def test_authenticated_receiver_store_projects_exact_rhs_to_later_read(
    selector: str,
    annotation: str,
) -> None:
    """Removing Assign's projection or matching a fixed spelling breaks this."""
    frame = _frame(
        "def enter(receiver):\n"
        f"    receiver.{selector}{annotation} = 7\n"
        f"    return receiver.{selector}\n"
    )
    coordinate = frame.formal_coordinates[0]
    temporal = TemporalContext.empty().bind_value(
        coordinate.cid,
        ObjectValue("RenamedManager", (), identity=coordinate.cid),
    )

    block = frame.body.desugar(_ReduceCtx(temporal)).value

    assert isinstance(block.statements[-1], ReturnValue)
    assert block.statements[-1].value == TermValue(7)


def test_different_authenticated_receiver_does_not_consume_projection() -> None:
    """Dropping receiver-coordinate discrimination makes this lying twin green."""
    frame = _frame(
        "def enter(receiver, other):\n"
        "    receiver.renamed_field = 7\n"
        "    return other.renamed_field\n"
    )
    first, second = frame.formal_coordinates
    temporal = (
        TemporalContext.empty()
        .bind_value(first.cid, ObjectValue("Manager", (), identity=first.cid))
        .bind_value(second.cid, ObjectValue("Manager", (), identity=second.cid))
    )

    with pytest.raises(ConstructionPanic):
        frame.body.desugar(_ReduceCtx(temporal))
