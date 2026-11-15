from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

SCRIPT = sugar_lift_py_tests_package_root() / "scripts" / "private_orphan_transition.py"


def _load_audit():
    spec = importlib.util.spec_from_file_location("private_orphan_transition", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _transitions(before: dict[str, str], after: dict[str, str]):
    audit = _load_audit()
    return audit.compare_package_sources("demo", before, after)


def test_surviving_private_definition_that_loses_last_reference_is_reported() -> None:
    before = {
        "src/demo/manager.py": (
            "def _classify(value):\n"
            "    return value\n\n"
            "def build(value):\n"
            "    return _classify(value)\n"
        )
    }
    after = {
        "src/demo/manager.py": (
            "def _classify(value):\n"
            "    return value\n\n"
            "def build(value):\n"
            "    return value\n"
        )
    }

    findings = _transitions(before, after)

    assert [finding.definition.name for finding in findings] == ["_classify"]
    assert [(site.path, site.line) for site in findings[0].lost_references] == [
        ("src/demo/manager.py", 5)
    ]


def test_removing_private_definition_with_its_caller_is_lawful() -> None:
    before = {
        "src/demo/manager.py": (
            "def _classify(value):\n"
            "    return value\n\n"
            "def build(value):\n"
            "    return _classify(value)\n"
        )
    }
    after = {"src/demo/manager.py": "def build(value):\n    return value\n"}

    assert _transitions(before, after) == ()


@pytest.mark.parametrize(
    ("before_source", "registered_source"),
    [
        (
            "def _registered():\n    return 1\n\nVALUE = _registered()\n",
            "__all__ = ['_registered']\n\ndef _registered():\n    return 1\n",
        ),
        (
            "def register(function):\n    return function\n\n"
            "def _registered():\n    return 1\n\nVALUE = _registered()\n",
            "def register(function):\n    return function\n\n"
            "@register\ndef _registered():\n    return 1\n",
        ),
    ],
)
def test_new_exported_or_registered_private_definition_is_lawful(
    before_source: str,
    registered_source: str,
) -> None:
    before = {"src/demo/hooks.py": before_source}
    after = {"src/demo/hooks.py": registered_source}

    assert _transitions(before, after) == ()


def test_replacing_direct_reference_with_import_reexport_preserves_reference() -> None:
    before = {
        "src/demo/manager.py": "def _classify(value):\n    return value\n",
        "src/demo/api.py": "from .manager import _classify\n\nVALUE = _classify(1)\n",
    }
    after = {
        "src/demo/manager.py": "def _classify(value):\n    return value\n",
        "src/demo/api.py": "from .manager import _classify as classify\n\n__all__ = ['classify']\n",
    }

    assert _transitions(before, after) == ()


def test_second_private_helper_is_not_special_cased() -> None:
    before = {
        "src/demo/other.py": (
            "def _normalize(value):\n"
            "    return value\n\n"
            "NORMALIZERS = {'default': _normalize}\n"
        )
    }
    after = {
        "src/demo/other.py": (
            "def _normalize(value):\n" "    return value\n\n" "NORMALIZERS = {}\n"
        )
    }

    findings = _transitions(before, after)

    assert [finding.definition.name for finding in findings] == ["_normalize"]
    assert findings[0].lost_references[0].line == 4


def _run_cli(repo: Path, before: str, after: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(repo),
            "--before",
            before,
            "--after",
            after,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


# The CLI reads two revisions of a repository.  The revisions are built here:
# a checkout holds no history to name (CI clones one commit), and a commit of
# a deleted branch exists nowhere.
_MODULE = "implementations/python/demo-dist/src/demo/manager.py"
_CALLED = (
    "def _classify(value):\n"
    "    return value\n\n"
    "def build(value):\n"
    "    return _classify(value)\n"
)
_ORPHANED = (
    "def _classify(value):\n"
    "    return value\n\n"
    "def build(value):\n"
    "    return value\n"
)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=orphan-transition-test",
            "-c",
            "user.email=orphan-transition-test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _two_revisions(tmp_path: Path) -> tuple[Path, str, str]:
    """A repository whose second commit drops ``_classify``'s last reference
    and keeps its definition: ``(repo, before, after)``."""
    repo = tmp_path / "repo"
    module = repo / _MODULE
    module.parent.mkdir(parents=True)
    _git(repo, "init", "-q")
    module.write_text(_CALLED, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-verify", "-m", "before")
    before = _git(repo, "rev-parse", "HEAD")
    module.write_text(_ORPHANED, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-verify", "-m", "after")
    after = _git(repo, "rev-parse", "HEAD")
    return repo, before, after


def test_cli_truthful_twin_is_green(tmp_path: Path) -> None:
    repo, before, _after = _two_revisions(tmp_path)
    completed = _run_cli(repo, before, before)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "orphan_transitions=0" in completed.stdout


def test_cli_names_the_orphaned_helper_and_its_lost_reference(tmp_path: Path) -> None:
    repo, before, after = _two_revisions(tmp_path)
    completed = _run_cli(repo, before, after)

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "_classify" in completed.stdout
    assert f"{_MODULE}:1:" in completed.stdout
    assert "lost reference" in completed.stdout
    assert f"{_MODULE}:5:" in completed.stdout
    assert "orphan_transitions=1" in completed.stdout

    # The reverse transition gains a reference: nothing is orphaned.
    regained = _run_cli(repo, after, before)
    assert regained.returncode == 0, regained.stdout + regained.stderr
    assert "orphan_transitions=0" in regained.stdout


def test_cli_refuses_a_revision_the_repository_does_not_have(tmp_path: Path) -> None:
    repo, before, _after = _two_revisions(tmp_path)
    completed = _run_cli(repo, before, "0" * 40)

    assert completed.returncode != 0, completed.stdout + completed.stderr
    assert "git diff failed" in completed.stderr
    # No verdict line: a revision it cannot read is not a count of zero.
    assert "orphan_transitions=" not in completed.stdout
