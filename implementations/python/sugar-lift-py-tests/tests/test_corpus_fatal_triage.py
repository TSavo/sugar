from __future__ import annotations

from sugar_lift_py_tests.idd.factory_walk_unclassified_locus import (  # noqa: E402
    LOCUS_FIELD_NAMES,
    locus_is_addressable,
    project_unclassified_locus,
    shape_split_unclassified,
)


def test_project_unclassified_locus_schema() -> None:
    locus = project_unclassified_locus(
        {
            "status": "unresolved",
            "file": "numpy/core/numeric.py",
            "line": 12,
            "ast_kind": "ListComp",
            "selected": None,
            "requested_role": "term",
            "reason": "source-to-factory conservation owner disappeared",
        }
    )
    assert locus == {
        "status": "unclassified",
        "selected": "",
        "ast_kind": "ListComp",
        "role": "term",
        "reason": "source-to-factory conservation owner disappeared",
        "file": "numpy/core/numeric.py",
        "line": 12,
    }
    assert locus_is_addressable(locus)


def test_shape_split_groups_by_ast_role_selected_reason() -> None:
    rows = [
        {
            "status": "unclassified",
            "file": "a.py",
            "line": 1,
            "ast_kind": "ListComp",
            "selected": "",
            "role": "term",
            "reason": "no owner",
        },
        {
            "status": "unclassified",
            "file": "b.py",
            "line": 2,
            "ast_kind": "ListComp",
            "selected": "",
            "role": "term",
            "reason": "no owner",
        },
        {
            "status": "unclassified",
            "file": "c.py",
            "line": 3,
            "ast_kind": "Call",
            "selected": "CallSugar",
            "role": "term",
            "reason": "no universe",
        },
    ]
    split = shape_split_unclassified(rows)
    assert split[0]["count"] == 2
    assert split[0]["ast_kind"] == "ListComp"
    assert split[0]["examples"] == ["a.py:1", "b.py:2"]
    assert split[1]["count"] == 1
    assert split[1]["ast_kind"] == "Call"
