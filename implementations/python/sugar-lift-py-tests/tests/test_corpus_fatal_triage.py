from __future__ import annotations

import sys
from pathlib import Path
import json
import subprocess

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import corpus_fatal_triage  # noqa: E402
from corpus_fatal_triage import (  # noqa: E402
    _child_payload,
    _classify_child,
    _is_fatal_category,
)
from sugar_lift_py_tests.idd.factory_walk_unclassified_locus import (  # noqa: E402
    LOCUS_FIELD_NAMES,
    locus_is_addressable,
    project_unclassified_locus,
    shape_split_unclassified,
)


def test_unwritten_construction_is_counted_typed_gap_not_fatal_crash(
    tmp_path: Path,
) -> None:
    source = tmp_path / "unsupported.py"
    source.write_text("def broken():\n    type T = int\n", encoding="utf-8")

    testimony, returncode = _child_payload(source, "demo/unsupported.py")

    assert returncode == 0
    assert testimony["outcome"] == "typed-gap"
    assert testimony["file"] == "demo/unsupported.py"
    assert testimony["typed_gap_count"] == 1
    typed = testimony["typed_gaps"][0]
    assert typed["exception_type"] == "SugarNotWritten"
    assert typed["gap"]["owner"] == "TypeAlias.sugar"
    assert "TypeAlias" in typed["gap"]["observed"]


def test_renamed_unwritten_manager_is_counted_typed_gap_not_bare_exception(
    tmp_path: Path,
) -> None:
    source = tmp_path / "renamed.py"
    source.write_text(
        "class ArbitraryDoor:\n"
        "    pass\n"
        "def exercise():\n"
        "    with ArbitraryDoor():\n"
        "        pass\n",
        encoding="utf-8",
    )

    testimony, returncode = _child_payload(source, "demo/renamed.py")

    assert returncode == 0
    assert testimony["outcome"] == "typed-gap"
    assert testimony["typed_gap_count"] == 1
    typed = testimony["typed_gaps"][0]
    assert typed["exception_type"] == "ContextManagerResolutionConstructionGap"
    assert typed["gap"]["owner"] == "With._construct_sugar"


def test_typed_gap_child_testimony_classifies_nonfatal() -> None:
    result = subprocess.CompletedProcess(
        args=["child"],
        returncode=0,
        stdout=json.dumps(
            {
                "outcome": "typed-gap",
                "file": "demo/renamed.py",
                "exception_type": "SugarNotWritten",
                "gap": {"owner": "ArbitraryNode"},
            }
        ),
        stderr="",
    )

    row = _classify_child(
        rel="demo/renamed.py",
        result=result,
        timed_out=False,
        timeout_seconds=30,
    )

    assert row["category"] == "typed-gap"
    assert not _is_fatal_category(row["category"])


def test_genuine_python_bug_remains_bare_exception(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "bug.py"
    source.write_text("def exercise():\n    return 1\n", encoding="utf-8")

    def broken_lift(*_args, **_kwargs):
        raise RuntimeError("planted construction bug")

    import _production_lift_child as production_child

    monkeypatch.setattr(production_child, "production_lift_testimony", broken_lift)
    testimony, returncode = corpus_fatal_triage._child_payload(source, "demo/bug.py")

    assert returncode == 3
    assert testimony["outcome"] == "exception"
    assert testimony["exception_type"] == "RuntimeError"
    result = subprocess.CompletedProcess(
        args=["child"],
        returncode=returncode,
        stdout=json.dumps(testimony),
        stderr="",
    )
    row = _classify_child(
        rel="demo/bug.py",
        result=result,
        timed_out=False,
        timeout_seconds=30,
    )
    assert row["category"] == "bare-exception"


def test_completed_child_uses_the_same_production_terminal_shape(
    tmp_path: Path,
) -> None:
    source = tmp_path / "clean.py"
    source.write_text("def identity(value):\n    return value\n", encoding="utf-8")
    testimony, returncode = _child_payload(source, "demo/clean.py")

    assert returncode == 0
    assert testimony["outcome"] == "completed"
    assert testimony["typed_gap_count"] == 0
    assert testimony["typed_gaps"] == []


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
        "resolution_kind": "",
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
