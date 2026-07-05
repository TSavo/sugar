from __future__ import annotations

import pytest

from sugar_lift_py_tests.kit_rpc.factory_walk_row_dto import FactoryWalkRowDto


def test_unknown_status_panics_instead_of_defaulting():
    with pytest.raises(TypeError, match="brand-new-status"):
        FactoryWalkRowDto(
            file="f.py",
            line=1,
            requested_role="TERM",
            ast_kind="Call",
            selected=None,
            status="brand-new-status",
            output=None,
            source_memento={},
        )


def test_red_row_without_grounds_is_unconstructible() -> None:
    with pytest.raises(TypeError, match="red verdict carries no grounds"):
        FactoryWalkRowDto(
            file="wall.py",
            line=7,
            requested_role="term",
            ast_kind="Call",
            selected="CallSugar",
            status="factory-gap",
            output={},
            source_memento={"kind": "source-memento"},
        )


def test_red_row_with_grounds_constructs() -> None:
    row = FactoryWalkRowDto(
        file="wall.py",
        line=7,
        requested_role="term",
        ast_kind="Call",
        selected="CallSugar",
        status="factory-gap",
        output={},
        source_memento={"kind": "source-memento"},
        reason="via unresolved call `op` at wall.py:3",
    )
    assert row.reason is not None


def test_green_row_needs_no_grounds() -> None:
    row = FactoryWalkRowDto(
        file="wall.py",
        line=7,
        requested_role="term",
        ast_kind="Call",
        selected="CallSugar",
        status="warranted",
        output={},
        source_memento={"kind": "source-memento"},
    )
    assert row.status == "warranted"
