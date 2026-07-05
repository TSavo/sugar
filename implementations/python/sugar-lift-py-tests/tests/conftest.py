# SPDX-License-Identifier: MIT OR Apache-2.0
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.normpath(os.path.join(_HERE, "..", "src"))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
# the tests dir itself, so per-sugar tests can import the shared `factory_reduce`
# harness module.
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from sugar_lift_py_tests.sugar_binary import (  # noqa: E402
    SugarBinaryResolutionError,
    resolve_sugar_binary,
)


@pytest.fixture(scope="session", autouse=True)
def sugar_binary_handoff() -> str:
    try:
        sugar = resolve_sugar_binary()
    except SugarBinaryResolutionError as exc:
        pytest.exit(str(exc), returncode=2)
    os.environ["SUGAR_BIN"] = os.fspath(sugar)
    return os.fspath(sugar)
