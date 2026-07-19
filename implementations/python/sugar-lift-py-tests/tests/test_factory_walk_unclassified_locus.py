"""Unit tests for row-addressable unclassified locus projection (#5252)."""

from __future__ import annotations

from sugar_lift_py_tests.idd.factory_walk_unclassified_locus import (
    extract_locus_list,
    locus_is_addressable,
    project_unclassified_loci,
    project_unclassified_locus,
    shape_split_unclassified,
)
from sugar_lift_py_tests.kit_rpc.factory_walk_row_dto import (
    FactoryWalkCompleteRowDto,
    FactoryWalkRedRowDto,
    FactoryWalkStatus,
)


def test_green_row_projects_to_none() -> None:
    row = FactoryWalkCompleteRowDto(
        file="wall.py",
        line=7,
        requested_role="term",
        ast_kind="Call",
        selected="CallSugar",
        status=FactoryWalkStatus.WARRANTED,
        output={},
        source_memento={"kind": "source-memento"},
    )
    assert project_unclassified_locus(row) is None


def test_red_unclassified_dto_projects_to_locus() -> None:
    row = FactoryWalkRedRowDto(
        file="numpy/core/fromnumeric.py",
        line=99,
        requested_role="term",
        ast_kind="ListComp",
        selected=None,
        status=FactoryWalkStatus.UNCLASSIFIED,
        output="gap",
        source_memento={"kind": "source-memento"},
        reason="source-to-factory conservation owner disappeared",
    )
    locus = project_unclassified_locus(row)
    assert locus is not None
    assert locus["status"] == "unclassified"
    assert locus["file"] == "numpy/core/fromnumeric.py"
    assert locus["line"] == 99
    assert locus["ast_kind"] == "ListComp"
    assert locus["role"] == "term"
    assert locus["selected"] == ""
    assert locus["reason"] == "source-to-factory conservation owner disappeared"
    assert locus_is_addressable(locus)


def test_project_unclassified_loci_filters() -> None:
    rows = [
        {
            "status": "warranted",
            "file": "a.py",
            "line": 1,
            "ast_kind": "Call",
            "selected": "CallSugar",
            "requested_role": "term",
        },
        {
            "status": "unclassified",
            "file": "b.py",
            "line": 2,
            "ast_kind": "ListComp",
            "selected": "",
            "requested_role": "term",
            "reason": "no owner",
        },
    ]
    loci = project_unclassified_loci(rows)
    assert len(loci) == 1
    assert loci[0]["file"] == "b.py"


def test_extract_locus_list_keys() -> None:
    payload = {
        "factory_walk_statuses": {"unclassified": 50},
        "factory_walk_unclassified_rows": [
            {
                "status": "unclassified",
                "file": "x.py",
                "line": 1,
                "ast_kind": "Call",
                "role": "term",
                "selected": "",
                "reason": "gap",
            }
        ],
    }
    loci = extract_locus_list(payload)
    assert loci is not None
    assert len(loci) == 1


def test_shape_split_empty() -> None:
    assert shape_split_unclassified([]) == []
