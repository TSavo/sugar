"""Source-stamp provisioning must refuse before executing a partial toolset."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
STAMP = ROOT / "tools" / "sugar_source_stamp.py"


def _executable(path: Path, *, marker: Path) -> None:
    path.write_text(
        "#!/bin/sh\n"
        f"printf called > {os.fspath(marker)!r}\n"
        "exit 99\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


@pytest.mark.parametrize(
    ("present_tool", "missing_tool"),
    (("cargo", "b3sum"), ("b3sum", "cargo")),
)
def test_source_stamp_refuses_missing_required_tool_before_execution(
    tmp_path: Path, present_tool: str, missing_tool: str
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "tool-was-called"
    _executable(fake_bin / present_tool, marker=marker)
    env = os.environ.copy()
    env["PATH"] = os.fspath(fake_bin)

    completed = subprocess.run(
        [sys.executable, os.fspath(STAMP), "--repo-root", os.fspath(tmp_path)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert (
        f"source stamping refused: missing required tool: {missing_tool}"
        in completed.stderr
    )
    assert f"{missing_tool} is required for source stamping" in completed.stderr
    assert "FileNotFoundError" not in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not marker.exists(), "preflight executed a partial source-stamp toolset"


def test_source_stamp_names_every_missing_required_tool(tmp_path: Path) -> None:
    fake_bin = tmp_path / "empty-bin"
    fake_bin.mkdir()
    env = os.environ.copy()
    env["PATH"] = os.fspath(fake_bin)

    completed = subprocess.run(
        [sys.executable, os.fspath(STAMP), "--repo-root", os.fspath(tmp_path)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert (
        "source stamping refused: missing required tools: b3sum, cargo"
        in completed.stderr
    )
    assert "b3sum and cargo are required for source stamping" in completed.stderr
    assert "FileNotFoundError" not in completed.stderr
    assert "Traceback" not in completed.stderr


def test_source_stamp_never_hashes_a_failed_cargo_preimage(tmp_path: Path) -> None:
    rust_workspace = tmp_path / "implementations" / "rust"
    rust_workspace.mkdir(parents=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "cargo").write_text("#!/bin/sh\nexit 41\n", encoding="utf-8")
    (fake_bin / "b3sum").write_text(
        "#!/bin/sh\n/bin/cat >/dev/null\nprintf '%0128d\\n' 0\n",
        encoding="utf-8",
    )
    (fake_bin / "cargo").chmod(0o755)
    (fake_bin / "b3sum").chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = os.fspath(fake_bin)

    completed = subprocess.run(
        [sys.executable, os.fspath(STAMP), "--repo-root", os.fspath(tmp_path)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "cargo could not construct the source-stamp preimage" in completed.stderr
    assert "cargo is required for source stamping" in completed.stderr
