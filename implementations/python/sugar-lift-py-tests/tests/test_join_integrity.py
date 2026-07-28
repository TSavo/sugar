from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sugar_lift_py_tests.join_integrity import (
    DroppedCallerFinding,
    JoinIntegrityError,
    SemanticFieldLossFinding,
    TextualConflictFinding,
    OpenPullRequest,
    _adjacent_pairs,
    _named_law_losses,
    _parse_conflicts,
    check_git_join,
    main,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo, text=True, stderr=subprocess.STDOUT
    ).strip()


def _write(repo: Path, relative: str, source: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.name=T Savo",
        "-c",
        "user.email=evilgenius@nefariousplan.com",
        "commit",
        "-m",
        message,
    )
    return _git(repo, "rev-parse", "HEAD")


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _write(
        repo,
        "implementations/python/demo/src/demo/model.py",
        "from dataclasses import dataclass\n\n@dataclass\nclass Step:\n    kind: str\n",
    )
    _write(
        repo,
        "implementations/python/demo/src/demo/builders.py",
        "from .model import Step\n\ndef build_plain():\n    return Step('plain')\n",
    )
    return repo, _commit(repo, "base")


def _branch(repo: Path, base: str, name: str) -> None:
    _git(repo, "switch", "-q", "-C", name, base)


def test_clean_adjacent_join_has_zero_findings(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    _branch(repo, base, "left")
    _write(
        repo,
        "implementations/python/demo/src/demo/left.py",
        "def left():\n    return 1\n",
    )
    left = _commit(repo, "left")
    _branch(repo, base, "right")
    _write(
        repo,
        "implementations/python/demo/src/demo/right.py",
        "def right():\n    return 2\n",
    )
    right = _commit(repo, "right")

    report = check_git_join(repo, base=base, left=left, right=right)

    assert report.adjacent_packages == ("demo",)
    assert report.findings == ()


def test_dropped_caller_in_merged_tree_is_red(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    _write(
        repo,
        "implementations/python/demo/src/demo/helper.py",
        "def _helper():\n    return 1\n\ndef caller():\n    return _helper()\n",
    )
    base = _commit(repo, "live helper")
    _branch(repo, base, "left")
    _write(
        repo,
        "implementations/python/demo/src/demo/left.py",
        "VALUE = 1\n",
    )
    left = _commit(repo, "left adjacent")
    _branch(repo, base, "right")
    _write(
        repo,
        "implementations/python/demo/src/demo/helper.py",
        "def _helper():\n    return 1\n",
    )
    right = _commit(repo, "drop caller")

    report = check_git_join(repo, base=base, left=left, right=right)

    assert len(report.findings) == 1
    assert isinstance(report.findings[0], DroppedCallerFinding)
    assert report.findings[0].symbol == "_helper"
    with pytest.raises(JoinIntegrityError, match=r"_helper.*ZERO_REFERENCES_AFTER"):
        report.require_clean()


def test_auto_merge_new_constructor_must_carry_other_branch_field(
    tmp_path: Path,
) -> None:
    """#6439/#6445 twin: both tips are green; their clean join is red."""
    repo, base = _repo(tmp_path)
    _branch(repo, base, "field-law")
    _write(
        repo,
        "implementations/python/demo/src/demo/model.py",
        "from dataclasses import dataclass\n\n@dataclass\nclass Step:\n"
        "    kind: str\n    carries_suspension: bool = False\n",
    )
    left = _commit(repo, "thread suspension field")
    _branch(repo, base, "new-shape")
    _write(
        repo,
        "implementations/python/demo/src/demo/builders.py",
        "from .model import Step\n\ndef build_plain():\n    return Step('plain')\n\n"
        "def build_if():\n    return Step('If')\n",
    )
    right = _commit(repo, "add If constructor")

    report = check_git_join(repo, base=base, left=left, right=right)

    losses = [f for f in report.findings if isinstance(f, SemanticFieldLossFinding)]
    assert len(losses) == 1
    assert losses[0].constructor == "Step"
    assert losses[0].field == "carries_suspension"
    assert losses[0].path.endswith("builders.py")
    with pytest.raises(JoinIntegrityError, match="carries_suspension"):
        report.require_clean()


def test_semantic_twin_bites_only_at_the_join(tmp_path: Path) -> None:
    """The instrument must not falsely claim either individual tip is the join."""
    repo, base = _repo(tmp_path)
    _branch(repo, base, "field-law")
    _write(
        repo,
        "implementations/python/demo/src/demo/model.py",
        "from dataclasses import dataclass\n\n@dataclass\nclass Step:\n"
        "    kind: str\n    carries_suspension: bool = False\n",
    )
    left = _commit(repo, "field")
    _branch(repo, base, "new-shape")
    _write(
        repo,
        "implementations/python/demo/src/demo/builders.py",
        "from .model import Step\n\ndef build_plain():\n    return Step('plain')\n\n"
        "def build_if():\n    return Step('If')\n",
    )
    right = _commit(repo, "shape")

    assert check_git_join(repo, base=base, left=left, right=base).findings == ()
    assert check_git_join(repo, base=base, left=base, right=right).findings == ()
    assert check_git_join(repo, base=base, left=left, right=right).findings


def test_nonadjacent_code_tips_do_not_claim_a_join_measurement(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    _branch(repo, base, "left")
    _write(repo, "implementations/python/one/src/one/a.py", "A = 1\n")
    left = _commit(repo, "one")
    _branch(repo, base, "right")
    _write(repo, "implementations/python/two/src/two/b.py", "B = 2\n")
    right = _commit(repo, "two")

    report = check_git_join(repo, base=base, left=left, right=right)

    assert report.adjacent_packages == ()
    assert report.measured_packages == 0


def test_cli_exits_red_and_prints_test_names_and_counts(tmp_path: Path, capsys) -> None:
    repo, base = _repo(tmp_path)
    _write(
        repo,
        "implementations/python/demo/src/demo/helper.py",
        "def _helper():\n    return 1\n\ndef caller():\n    return _helper()\n",
    )
    base = _commit(repo, "live helper")
    _branch(repo, base, "left")
    _write(repo, "implementations/python/demo/src/demo/left.py", "VALUE = 1\n")
    left = _commit(repo, "left")
    _branch(repo, base, "right")
    _write(
        repo,
        "implementations/python/demo/src/demo/helper.py",
        "def _helper():\n    return 1\n",
    )
    right = _commit(repo, "right")

    status = main(
        [
            "--repo",
            str(repo),
            "--base",
            base,
            "--left",
            left,
            "--right",
            right,
        ]
    )

    output = capsys.readouterr().out
    assert status == 1
    assert "droppedCaller=1 semanticFieldLoss=0" in output
    assert "test=dropped-caller" in output


def test_live_6540_6541_conflict_testimony_names_hunks_and_markers() -> None:
    """Fixture captured from the live pair; every marker is counted."""
    path = (
        "implementations/python/sugar-lift-py-tests/src/"
        "sugar_lift_py_tests/no_call_body_attribution.py"
    )
    testimony = f"""changed in both
  base   100644 000000 {path}
  our    100644 111111 {path}
  their  100644 222222 {path}
@@ -106,11 +113,29 @@ class AttributionOutcomeSummary:
+<<<<<<< .our
+=======
+>>>>>>> .their
@@ -125,6 +150,30 @@ class AttributionReport:
+<<<<<<< .our
+=======
+>>>>>>> .their
"""

    findings = _parse_conflicts(testimony)

    assert [item.path for item in findings] == [path, path]
    assert [item.hunk_header for item in findings] == [
        "@@ -106,11 +113,29 @@ class AttributionOutcomeSummary:",
        "@@ -125,6 +150,30 @@ class AttributionReport:",
    ]
    assert sum(item.marker_count for item in findings) == 6


def test_textual_conflict_join_is_red_with_exact_file_and_hunk(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    target = "implementations/python/demo/src/demo/builders.py"
    _branch(repo, base, "left")
    _write(
        repo,
        target,
        "from .model import Step\n\ndef build_plain():\n    return Step('left')\n",
    )
    left = _commit(repo, "left")
    _branch(repo, base, "right")
    _write(
        repo,
        target,
        "from .model import Step\n\ndef build_plain():\n    return Step('right')\n",
    )
    right = _commit(repo, "right")

    report = check_git_join(repo, base=base, left=left, right=right)

    conflicts = [
        item for item in report.findings if isinstance(item, TextualConflictFinding)
    ]
    assert report.merged_tree is None
    assert len(conflicts) == 1
    assert conflicts[0].path == target
    assert conflicts[0].hunk_header.startswith("@@")
    assert conflicts[0].marker_count == 3
    with pytest.raises(JoinIntegrityError, match="test=textual-conflict"):
        report.require_clean()


def test_named_laws_and_denominator_survive_as_one_join_contract() -> None:
    test_source = "\n".join(
        f"def {name}():\n    pass"
        for name in (
            "test_escaped_construction_panic_remains_a_separate_loud_axis",
            "test_silent_completion_stays_a_separate_loud_discrepancy",
            "test_population_selection_never_reads_manager_target_symbol",
        )
    )
    sources = {
        "implementations/python/sugar-lift-py-tests/tests/test_no_call_body_attribution.py": test_source,
        "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/no_call_body_attribution.py": "FAMILY_DENOMINATORS = {'a': 1000, 'b': 8}\n",
    }
    assert _named_law_losses("sugar-lift-py-tests", sources) == ()

    mutated = dict(sources)
    mutated[next(iter(mutated))] = test_source.replace(
        "test_silent_completion_stays_a_separate_loud_discrepancy", "deleted_law"
    )
    losses = _named_law_losses("sugar-lift-py-tests", mutated)
    assert [loss.law for loss in losses] == [
        "test_silent_completion_stays_a_separate_loud_discrepancy"
    ]


def test_every_common_file_open_pr_pair_is_selected_without_a_cap() -> None:
    pulls = (
        OpenPullRequest(1, "one", "main", frozenset({"shared.py", "one.py"})),
        OpenPullRequest(2, "two", "main", frozenset({"shared.py"})),
        OpenPullRequest(3, "three", "main", frozenset({"other.py"})),
    )
    assert [(left.number, right.number) for left, right in _adjacent_pairs(pulls)] == [
        (1, 2)
    ]
