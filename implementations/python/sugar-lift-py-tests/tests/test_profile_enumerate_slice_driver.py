"""Driver (measurement, not a tooth): run the census-entrance category profile.

Not a guard. It exists so ``bin/bpytest`` can carry the profiler onto the box
that holds the authenticated corpus. Skipped unless ``PROFILE_SLICE`` is set,
so it never runs in an ordinary suite.

    PROFILE_SLICE=start:stride[:limit] bin/bpytest tests/test_profile_enumerate_slice_driver.py -s
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

import pytest

SPEC = os.environ.get("PROFILE_SLICE")


@pytest.mark.skipif(not SPEC, reason="PROFILE_SLICE not set")
def test_profile_slice() -> None:
    scripts = sugar_lift_py_tests_package_root() / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import profile_enumerate_slice

    parts = str(SPEC).split(":")
    argv = ["--start", parts[0], "--stride", parts[1]]
    if len(parts) > 2 and parts[2]:
        argv += ["--limit", parts[2]]
    out = os.environ.get("PROFILE_OUT") or "/tmp/profile-slice.json"
    argv += ["--out", out]
    assert profile_enumerate_slice.main(argv) == 0
