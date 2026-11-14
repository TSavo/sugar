from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import ObjectValue, ReturnValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile

from frame_fresh import FRAME_FRESH


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
def test_a_store_on_a_receiver_that_arrived_reads_back_undecided(
    selector: str,
    annotation: str,
) -> None:
    """``receiver`` reached ``enter`` by binding: its fields are not current
    (``object_identity.contents_current``), nor are its post-state's, so the
    read after the store -- whatever the field is spelled -- is the
    undecided attribute read over the object's identity, never a recorded
    value (#7757).  It was ``7``, read off the post-state's fields."""
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.outcome import Completed

    frame = _frame(
        "def enter(receiver):\n"
        f"    receiver.{selector}{annotation} = 7\n"
        f"    return receiver.{selector}\n"
    )
    coordinate = frame.formal_coordinates[0]
    temporal = TemporalContext.empty().bind_value(
        coordinate.cid,
        ObjectValue(
            "RenamedManager", (), identity=coordinate.cid, allocation=FRAME_FRESH
        ),
    )

    outcome = frame.body.desugar(_ReduceCtx(temporal))

    returned = [
        face.value.statements[-1]
        for face in outcome.exits
        if isinstance(face, Completed)
    ]
    assert returned and all(type(entry) is ReturnValue for entry in returned)
    assert all(type(entry.value) is CallSiteValue for entry in returned)
    assert all(entry.value.target_name == selector for entry in returned)


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
        .bind_value(
            first.cid,
            ObjectValue("Manager", (), identity=first.cid, allocation=FRAME_FRESH),
        )
        .bind_value(
            second.cid,
            ObjectValue("Manager", (), identity=second.cid, allocation=FRAME_FRESH),
        )
    )

    with pytest.raises(ConstructionPanic):
        frame.body.desugar(_ReduceCtx(temporal))
