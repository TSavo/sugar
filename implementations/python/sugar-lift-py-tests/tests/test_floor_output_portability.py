"""Floor instruments emit their Unicode reports under legacy host locales."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_vendor_floor_emits_arrows_under_cp1252(tmp_path: Path) -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "vendor_special_case_law.py"
    )
    surface = tmp_path / "surface"
    surface.mkdir()
    (surface / "planted.py").write_text(
        "def dispatch(name):\n    return name == 'numpy'\n", encoding="utf-8"
    )
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp1252"

    result = subprocess.run(
        [sys.executable, str(script), str(surface)],
        env=env,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1, result.stderr.decode("utf-8", errors="replace")
    output = result.stdout.decode("utf-8")
    assert "source shape → registered Sugar → SugarBody children → floor" in output
