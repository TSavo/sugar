# SPDX-License-Identifier: MIT OR Apache-2.0
"""Regression guard: ambient sugar pool poison must not reach hermetic prove.

Closes the class of bug tracked by #3902: without SUGAR_HOME isolation, the
sugar binary discovers components relative to its own checkout (and ambient
SUGAR_COMPONENT_PATH), so aggregate witness runs share a pool and lies can
return sat. This test plants ambient poison that *would* be visible on the
non-hermetic path and asserts a known-lying witness still refutes under the
one-door hermetic recipe.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    hermetic_sugar_env,
    run_source_through_real_solver,
)


def _write_poison_component(root: Path) -> Path:
    """A component that hard-fails plan — visible only if ambient discovery runs."""
    components = root / "components" / "hermeticity-poison"
    components.mkdir(parents=True)
    script = components / "component.sh"
    # Always error on plan so a non-hermetic mint would refuse the workspace.
    script.write_text(
        "#!/bin/sh\n"
        "while IFS= read -r line; do\n"
        "  case \"$line\" in\n"
        "    *'\"method\":\"initialize\"'*)\n"
        "      printf '%s\\n' "
        "'{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":"
        "{\"name\":\"hermeticity-poison\",\"protocol_version\":\"sugar-component/1\","
        "\"capabilities\":{}}}' ;;\n"
        "    *'\"method\":\"sugar.component.plan\"'*)\n"
        "      printf '%s\\n' "
        "'{\"jsonrpc\":\"2.0\",\"id\":2,\"error\":"
        "{\"code\":-32000,\"message\":\"ambient pool poison: non-hermetic discovery\"}}' ;;\n"
        "    *'\"method\":\"shutdown\"'*)\n"
        "      printf '%s\\n' '{\"jsonrpc\":\"2.0\",\"id\":3,\"result\":null}'; exit 0 ;;\n"
        "  esac\n"
        "done\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    (components / "manifest.toml").write_text(
        'name = "hermeticity-poison"\n'
        'protocol_version = "sugar-component/1"\n'
        f'command = ["/bin/sh", "{script}"]\n',
        encoding="utf-8",
    )
    return root / "components"


def test_hermetic_lying_witness_ignores_ambient_component_path_poison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ambient SUGAR_COMPONENT_PATH poison must not be readable under SUGAR_HOME."""
    ambient = tmp_path / "ambient-home"
    poison_components = _write_poison_component(ambient)
    # Without hermetic_sugar_env, this would be a discovery root and mint would fail.
    monkeypatch.setenv("SUGAR_COMPONENT_PATH", str(poison_components))

    # Residue-shaped lie: body dig derives call:len == 3; stated A() == 2 must unsat.
    lying_source = (
        "def A():\n"
        "    return len([1, 2, 3])\n"
        "\n"
        "def test_a():\n"
        "    assert A() == 2\n"
    )
    result = run_source_through_real_solver(tmp_path / "lie-project", lying_source)

    assert result.verdict == "unsat", (
        "hermetic lying witness must refute; ambient SUGAR_COMPONENT_PATH poison "
        f"must not be read. prove_doc={result.prove_doc!r}"
    )


def test_run_sugar_cli_is_the_one_door_sets_sugar_home(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".sugar").mkdir()
    # `sugar version` is enough to exercise env wiring without a full mint stage.
    # If SUGAR_HOME were missing, the conftest refuse_non_hermetic_sugar_cli
    # fixture would not fire (version is not a project subcommand); assert env
    # shape directly.
    env = hermetic_sugar_env(project)
    assert env["SUGAR_HOME"] == str((project / ".sugar").resolve())
    assert "SUGAR_COMPONENT_PATH" not in env


def test_run_sugar_cli_drops_ambient_component_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUGAR_COMPONENT_PATH", str(tmp_path / "should-not-leak"))
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".sugar").mkdir()
    env = hermetic_sugar_env(project)
    assert env.get("SUGAR_HOME") == str((project / ".sugar").resolve())
    assert "SUGAR_COMPONENT_PATH" not in env


def test_conftest_refuses_bare_sugar_mint_without_sugar_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The suite-level guard: bare sugar mint without SUGAR_HOME is a hard error."""
    import subprocess

    from sugar_lift_py_tests.witness_harness import ensure_sugar_bin

    sugar = ensure_sugar_bin()
    # Bypass hermetic_sugar_env deliberately — must be refused by conftest.
    env = dict(os.environ)
    env.pop("SUGAR_HOME", None)
    env.pop("SUGAR_COMPONENT_PATH", None)
    with pytest.raises(AssertionError, match="without SUGAR_HOME"):
        subprocess.run(
            [str(sugar), "mint", "--out", ".", "--quiet"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )


def test_no_duplicate_mint_prove_doors_outside_witness_harness() -> None:
    """Static guard: suite sources must not re-implement bare sugar mint/prove."""
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        # The one door lives here.
        if path.name == "witness_harness.py":
            continue
        # This file asserts the guard itself.
        if path.name == "test_hermetic_sugar_pool.py":
            continue
        text = path.read_text(encoding="utf-8")
        if '["mint", "--out"' in text or "['mint', '--out'" in text:
            offenders.append(str(path.relative_to(root)))
        if '"prove", ".", "--json"' in text or "'prove', '.', '--json'" in text:
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], (
        "bare sugar mint/prove argv found outside witness_harness; "
        f"route through run_sugar_cli / mint_and_prove: {offenders}"
    )
