"""Bounded #5137 replay instrument for the eight recensus representatives."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPRESENTATIVES = (
    ("numpy", "_core/tests/test_deprecations.py", "ImportAliasValue"),
    (
        "pandas",
        "tests/indexes/timedeltas/test_indexing.py",
        "ImportAliasValue",
    ),
    ("pandas", "tests/internals/test_api.py", "ImportAliasValue"),
    ("pandas", "tests/scalar/test_nat.py", "ImportAliasValue"),
    (
        "pandas",
        "tests/scalar/timestamp/test_constructors.py",
        "ImportAliasValue",
    ),
    ("pandas", "tests/series/test_arithmetic.py", "ImportAliasValue"),
    (
        "pandas",
        "tests/computation/test_compat.py",
        "ImportAliasValue.truth",
    ),
    ("pandas", "tests/extension/test_arrow.py", "ImportAliasValue.truth"),
)


def _package_file(package: str, relative: str) -> Path:
    spec = importlib.util.find_spec(package)
    assert spec is not None and spec.origin is not None
    return Path(spec.origin).resolve().parent / relative


def _terminal_testimony(stdout: str) -> dict[str, object] | None:
    for line in reversed(stdout.splitlines()):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "outcome" in parsed:
            return parsed
    return None


@pytest.mark.skipif(
    os.environ.get("SUGAR_FATAL_CORPUS_REPLAY") != "1",
    reason="bounded live-corpus receipt; enable explicitly",
)
@pytest.mark.parametrize(("package", "relative", "retired_owner"), REPRESENTATIVES)
def test_import_alias_named_representative_advances_loudly_or_completes(
    package: str,
    relative: str,
    retired_owner: str,
) -> None:
    path = _package_file(package, relative)
    script = Path(__file__).resolve().parents[1] / "scripts" / "corpus_fatal_triage.py"
    rel = f"{package}/{relative}"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--child-file",
            str(path),
            "--child-rel",
            rel,
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    testimony = _terminal_testimony(result.stdout)
    assert testimony is not None, f"{rel}: child emitted no terminal testimony"
    outcome = str(testimony["outcome"])
    gap = testimony.get("gap") or {}
    owner = str(gap.get("owner") or "")
    blame = str(gap.get("blame") or "")
    print(
        f"REPLAY {rel} outcome={outcome} owner={owner or '-'} " f"blame={blame or '-'}"
    )

    assert owner != retired_owner, f"{rel}: #5137 owner remains live: {retired_owner}"
    assert outcome in {"completed", "factory-panic"}
