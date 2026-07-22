from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from corpus_fatal_triage import _child_payload  # noqa: E402
from sugar_lift_py_tests.idd.factory_walk_unclassified_locus import (  # noqa: E402
    LOCUS_FIELD_NAMES,
    locus_is_addressable,
    project_unclassified_locus,
    shape_split_unclassified,
)


def test_construction_panic_routes_through_audit_membrane_as_loud_child_row(
    tmp_path: Path,
) -> None:
    source = tmp_path / "unsupported.py"
    source.write_text("def broken():\n    type T = int\n", encoding="utf-8")

    testimony, returncode = _child_payload(source, "demo/unsupported.py")

    assert returncode == 3
    assert testimony["outcome"] == "factory-panic"
    assert testimony["exception_type"] == "ConstructionPanic"
    assert testimony["file"] == "demo/unsupported.py"
    assert testimony["gap"]["owner"] == "python.factory"
    assert testimony["gap"]["observed"] == "TypeAlias"


def test_completed_child_preserves_typed_effect_testimony() -> None:
    import pandas

    root = Path(pandas.__file__).resolve().parent
    relative = "tests/arrays/masked/test_arithmetic.py"
    testimony, returncode = _child_payload(root / relative, f"pandas/{relative}")

    assert returncode == 0
    assert testimony["outcome"] == "completed"
    effects = testimony["effects"]
    assert effects
    assert all(
        set(effect) == {"effect", "name", "status", "reason"} for effect in effects
    )
    assert any(
        effect["effect"] == "SequenceRepetitionRuntimeEffect"
        and effect["status"] == "runtime-effect"
        and "runtime __index__/length semantics" in effect["reason"]
        for effect in effects
    )
    # Completed testimony always carries the #5252 locus list key (may be empty).
    assert "unclassified_rows" in testimony
    assert "R_factory_walk_unclassified" in testimony
    assert testimony["R_factory_walk_unclassified"] == len(
        testimony["unclassified_rows"]
    )
    for locus in testimony["unclassified_rows"]:
        assert set(LOCUS_FIELD_NAMES) <= set(locus)
        assert locus["status"] == "unclassified"
        assert isinstance(locus["line"], int)


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
