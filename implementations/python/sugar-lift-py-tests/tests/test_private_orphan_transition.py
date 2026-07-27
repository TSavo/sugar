from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "private_orphan_transition.py"
REPO = Path(__file__).parents[4]


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


def _run_cli(before: str, after: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(REPO),
            "--before",
            before,
            "--after",
            after,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_current_main_truthful_twin_is_green() -> None:
    completed = _run_cli("b7feb76b8", "b7feb76b8")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "orphan_transitions=0" in completed.stdout


def test_real_branch_loss_names_helper_and_deleted_reference() -> None:
    completed = _run_cli("b7feb76b8", "b273c4d05")

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "_has_non_higher_order_return" in completed.stdout
    assert "manager_construction.py:1134" in completed.stdout
    assert "lost reference" in completed.stdout
    assert "manager_construction.py:836" in completed.stdout
