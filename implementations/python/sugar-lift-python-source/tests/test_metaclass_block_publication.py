"""RED: enum's source metaclass return is projected before publication."""

from __future__ import annotations

import ast
import enum

import pytest

from sugar_lift_python_source.dependency_artifact import AuthenticatedModuleSourceV1
from sugar_lift_python_source.manager_construction import _module_prefix_outcome
from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.floor import BlockValue, TermValue
from sugar_lift_py_tests.floor.decorated_class_value import _floor_cid
from sugar_lift_py_tests.floor.raise_value import RaiseValue
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_py_tests.effect import RaiseEffect


def test_enum_metaclass_publication_projects_completed_final_class() -> None:
    source, seat, source_cid = path_source(enum.__file__)
    parsed = ast.parse(source, filename=seat)
    definition = next(
        node
        for node in parsed.body
        if isinstance(node, ast.ClassDef) and node.name == "Enum"
    )
    module = AuthenticatedModuleSourceV1(
        module_name="enum",
        source_seat=seat,
        source_cid=source_cid,
        source=source,
    )

    exits = _module_prefix_outcome(module, definition)

    assert len(exits.exits) == 1
    completed = exits.exits[0]
    assert isinstance(completed, Completed)
    published = completed.value.context.temporal.value_if_bound("Enum")
    assert published.publication.final_class is not published.publication.raw_class
    assert type(published.publication.final_class) is not BlockValue
    assert published.publication.source_cid == source_cid


@pytest.mark.parametrize(
    "lying_final",
    (
        BlockValue((TermValue("foreign"),)),
        BlockValue((ReturnValue(TermValue("malformed")),), can_fall_through=False),
        BlockValue(
            (RaiseValue(RaiseEffect(exception_name="RuntimeError")),),
            can_fall_through=False,
        ),
    ),
)
def test_raw_block_final_class_controls_remain_loud(lying_final) -> None:
    with pytest.raises(
        ConstructionPanic,
        match="owner=decorated class publication blame=BlockValue",
    ):
        _floor_cid(lying_final)
