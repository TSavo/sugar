# SPDX-License-Identifier: Apache-2.0
#
# THE CAPSTONE, as a committed CLI-level E2E (skips cleanly when the toolchain
# isn't present). A numpy VENDOR mints a `.proof` carrying `np.add(2,3)==5`, lifted
# by the ONE assertion lifter (sugar_lift_py_tests.assertion_lsp) which learns
# numpy's vocabulary from the file's imports + the workspace's externalized
# `.sugar/vocab-exceptions/numpy.testing.json`. A CONSUMER stages the proof in
# `.sugar/imports/` and runs `prove`: the consumer asserting the WRONG value is
# REFUSED, the one that agrees is PROVEN. The consumer inherits numpy's correctness
# and is caught contradicting it.
#
# Hermetic + clean-room: everything in tmp_path, no shared/stale state.
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[4]
_BIN = _REPO / "implementations" / "rust" / "target" / "debug" / "sugar"
_PYSRC = ":".join(
    str(_REPO / "implementations" / "python" / pkg / "src")
    for pkg in ("sugar-lift-py-tests", "sugar-lift-python-source")
)

# numpy.testing's externalized vocab exception (the structurally-opaque remainder).
_NUMPY_EXCEPTION = {
    "overrides": {"equality": ["assert_equal", "assert_equals"], "truth": ["assert_"]},
    "tolerances": [
        {"name": "assert_almost_equal", "decimal_default": 7},
        {"name": "assert_array_almost_equal", "decimal_default": 6},
    ],
}


def _have(binary: str) -> bool:
    return shutil.which(binary) is not None


_numpy_ok = True
try:  # the lifter imports numpy when it RUNS the assertion lift; z3 discharges.
    import numpy  # noqa: F401
except Exception:
    _numpy_ok = False

pytestmark = pytest.mark.skipif(
    not (_BIN.exists() and _numpy_ok and _have("z3")),
    reason="needs the built sugar CLI + numpy + z3 on PATH",
)

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _run(args, cwd):
    # SUGAR_COMPONENT_PATH: expose the worktree's smt-lib ir-compiler component so
    # the sugar CLI discovers it even when the project lives in tmp_path (outside
    # the worktree's ancestor chain).  The manifest uses paths relative to its own
    # directory, so discovery via this env var resolves correctly.
    _COMPONENTS = str(_REPO / ".sugar" / "components")
    env = dict(os.environ, PYTHONPATH=_PYSRC, SUGAR_COMPONENT_PATH=_COMPONENTS)
    return subprocess.run(
        [str(_BIN), *args], cwd=str(cwd), env=env, capture_output=True, text=True
    )


def _manifest(surface: str, module: str, workdir: Path) -> str:
    return (
        f'name = "{surface}-lift"\nversion = "0.1.0"\nkind = "lift"\n'
        f'command = ["{sys.executable}", "-m", "{module}"]\n'
        f'working_dir = "{workdir}"\n'
        "[capabilities]\n"
        f'authoring_surfaces = ["{surface}"]\n'
    )


_SOLVERS = (
    "[solvers]\ndefault = \"z3\"\n[solvers.dispatch]\n"
    "linear_arithmetic = \"z3\"\ndefault = \"z3\"\n"
    "[solvers.z3]\nbinary = \"z3\"\nflags = [\"-smt2\", \"-in\"]\n"
)


def _project(tmp: Path, surface: str, module: str, exceptions: dict = None) -> Path:
    d = tmp
    (d / ".sugar" / "lift" / surface).mkdir(parents=True, exist_ok=True)
    (d / ".sugar" / "imports").mkdir(parents=True, exist_ok=True)
    (d / ".sugar" / "config.toml").write_text(
        f'[[plugins]]\nname = "{surface}-lift"\nkind = "lift"\nsurface = "{surface}"\n{_SOLVERS}'
    )
    (d / ".sugar" / "lift" / surface / "manifest.toml").write_text(
        _manifest(surface, module, d)
    )
    if exceptions:
        vx = d / ".sugar" / "vocab-exceptions"
        vx.mkdir(parents=True, exist_ok=True)
        for mod, data in exceptions.items():
            (vx / f"{mod}.json").write_text(json.dumps(data))
    return d


def _one_proof(d: Path) -> Path:
    proofs = list(d.glob("blake3-512_*.proof"))
    assert len(proofs) == 1, [p.name for p in proofs]
    return proofs[0]


def _verdict(out: str):
    text = _ANSI.sub("", out)
    disc = re.search(r"discharged\s*:\s*(\d+)", text)
    viol = re.search(r"violations\s*:\s*(\d+)", text)
    return (int(disc.group(1)) if disc else -1, int(viol.group(1)) if viol else -1)


@pytest.fixture
def numpy_vendor_proof(tmp_path: Path) -> Path:
    """A numpy VENDOR `.proof` carrying the callsite-keyed contract np.add(2,3)==5,
    minted by the ONE assertion lifter (DIRECT form so it keys to the callsite)."""
    v = _project(
        tmp_path / "vendor", "python-testing", "sugar_lift_py_tests.assertion_lsp",
        exceptions={"numpy.testing": _NUMPY_EXCEPTION},
    )
    (v / "test_vendor.py").write_text(
        "import numpy as np\nfrom numpy.testing import assert_equal\n"
        "def test_vendor():\n    assert_equal(np.add(2, 3), 5)\n"
    )
    r = _run(["mint", "--out", ".", "--quiet"], v)
    assert r.returncode == 0, r.stderr
    return _one_proof(v)


@pytest.mark.parametrize(
    "asserted, expect_refused",
    [(5, False), (6, True)],
    ids=["consumer-agrees-PROVEN", "consumer-contradicts-REFUSED"],
)
def test_consumer_inherits_numpy_contract(tmp_path, numpy_vendor_proof, asserted, expect_refused):
    c = _project(tmp_path / "consumer", "python-tests", "sugar_lift_py_tests.lsp")
    shutil.copy(numpy_vendor_proof, c / ".sugar" / "imports")
    (c / "test_consumer.py").write_text(
        f"import numpy as np\ndef test_c():\n    assert np.add(2, 3) == {asserted}\n"
    )
    assert _run(["mint", "--out", ".", "--quiet"], c).returncode == 0
    out = _run(["prove", "."], c).stdout
    _disc, viol = _verdict(out)
    if expect_refused:
        assert viol >= 1, f"consumer asserting =={asserted} must be REFUSED (inherits ==5):\n{_ANSI.sub('', out)}"
        assert "contradictory" in _ANSI.sub("", out)
    else:
        assert viol == 0, f"consumer asserting =={asserted} (agrees with numpy) must be PROVEN:\n{_ANSI.sub('', out)}"
