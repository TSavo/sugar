# SPDX-License-Identifier: MIT OR Apache-2.0
"""Opposing teeth on the vendored-corpus boundary (#6260).

T's ruling naming the category:

    Vendored source fixtures are authenticated corpus data, not executable
    pytest modules.

`tests/vendor/**` is hash-pinned LIFT CORPUS. The suite reads those files as
BYTES and parses them as AST; it never imports them. Their sha256 pins are the
law, so they may not be edited. Because several are named `test_*.py`, pytest
used to collect and import them — which both aborted collection when a
third-party package was absent AND silently counted eight third-party
assertions (numpy/pandas/requests) as Sugar passes.

`tests/conftest.py` now carries `collect_ignore_glob = ["vendor/*/*.py"]`.

These five teeth are deliberately OPPOSING. Tooth 1 asserts pytest does NOT
see the corpus. Tooth 2 asserts the corpus loader DOES read every byte of it
and verifies the pin. A change that satisfies one by breaking the other must
turn something red here.

Nothing in this module ever writes to the committed tree. Tooth 4 mutates a
byte only in a `tmp_path` copy; tooth 5 builds its nested source only in a
`tmp_path` structure.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import conftest as suite_conftest
from claim_mass_corpus import ClaimMassPin
from test_claim_mass_tripwires import PINS, _source_digest

TESTS_DIR = Path(__file__).resolve().parent
VENDOR_DIR = TESTS_DIR / "vendor"
PACKAGE_ROOT = TESTS_DIR.parent


def _collect_only(target: Path, *, rootdir: Path) -> list[str]:
    """Return the node IDs pytest collects under ``target``.

    Runs a real out-of-process `pytest --collect-only`, because the thing under
    test is pytest's own collection behaviour, not our model of it.
    """
    env = dict(os.environ)
    # Collection must not depend on a resolved sugar binary or on ambient pool
    # state; it only imports conftest.
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(target),
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
        ],
        cwd=str(rootdir),
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        # A vendored corpus module that pytest tries to IMPORT is the exact
        # failure #6260 removed: collection aborts on the third-party import
        # before any node ID is printed. Name that, don't report a return code.
        vendor_errors = [
            line.strip()
            for line in proc.stdout.splitlines()
            if "ERROR" in line and "vendor/" in line.replace(os.sep, "/")
        ]
        assert not vendor_errors, (
            "pytest tried to IMPORT hash-pinned vendored corpus and collection "
            f"aborted: {vendor_errors}; vendored source fixtures are "
            "authenticated corpus data, not executable pytest modules. "
            "replacement=widen `tests/conftest.py::collect_ignore_glob` — never "
            "edit a vendor file to make it importable"
        )
        raise AssertionError(
            "pytest --collect-only failed for reasons unrelated to the vendor "
            f"boundary.\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    node_ids = [
        line.strip()
        for line in proc.stdout.splitlines()
        if "::" in line and not line.startswith(" ")
    ]
    assert node_ids, (
        "collection produced no node IDs at all; a suite that collects nothing "
        f"cannot witness this boundary.\nstdout:\n{proc.stdout}"
    )
    return node_ids


def _vendor_node_ids(node_ids: list[str]) -> list[str]:
    return [
        node_id
        for node_id in node_ids
        if "vendor/" in node_id.split("::", 1)[0].replace(os.sep, "/")
    ]


# --------------------------------------------------------------------------
# Tooth 1 — pytest does NOT see the corpus.
# --------------------------------------------------------------------------
def test_pytest_collects_no_vendor_node_ids() -> None:
    """`pytest --collect-only` contains no `tests/vendor/**` node IDs.

    Neutral: asserts the vendor slice is EMPTY, never a count of vendor files.
    """
    node_ids = _collect_only(TESTS_DIR, rootdir=PACKAGE_ROOT)
    offenders = _vendor_node_ids(node_ids)
    assert offenders == [], (
        "pytest collected hash-pinned vendored corpus as test modules: "
        f"{offenders}; vendored source fixtures are authenticated corpus data, "
        "not executable pytest modules. replacement=widen "
        "`tests/conftest.py::collect_ignore_glob` to cover them — never edit a "
        "vendor file to make it collectable"
    )


# --------------------------------------------------------------------------
# Tooth 2 — the corpus loader DOES read every vendor artifact, and verifies
# its pin. This is the opposing tooth to #1: non-collection must not have
# blinded the corpus tooling.
# --------------------------------------------------------------------------
def _pinned_files() -> set[Path]:
    covered: set[Path] = set()
    for pin in PINS:
        path = VENDOR_DIR / pin.relative_path
        assert path.exists(), (
            f"pin {pin.name!r} names a missing corpus artifact {path}; "
            "replacement=restore the artifact or retire the pin loudly"
        )
        covered.update(sorted(path.rglob("*.py")) if path.is_dir() else [path])
    return covered


def test_every_vendor_artifact_is_still_read_and_pinned() -> None:
    """Every `.py` byte under `tests/vendor` is claimed by a corpus pin.

    Neutral: compares two derived SETS. It never hardcodes how many vendor
    files exist, so adding corpus is free — adding UNPINNED corpus is not.
    """
    on_disk = set(VENDOR_DIR.rglob("*.py"))
    assert on_disk, (
        f"no vendored corpus found under {VENDOR_DIR}; the boundary this module "
        "guards would be vacuous"
    )
    unpinned = sorted(
        str(path.relative_to(VENDOR_DIR)) for path in on_disk - _pinned_files()
    )
    assert unpinned == [], (
        f"vendored corpus is present but read by no pin: {unpinned}. Excluding "
        "`tests/vendor/**` from pytest collection must not make it invisible to "
        "the corpus loader. replacement=enroll each file in a `ClaimMassPin` in "
        "`tests/test_claim_mass_tripwires.py`"
    )


@pytest.mark.parametrize("pin", PINS, ids=lambda pin: pin.name)
def test_corpus_loader_verifies_the_pinned_hash(pin: ClaimMassPin) -> None:
    """The loader reads the real bytes and the pinned digest still matches."""
    path = VENDOR_DIR / pin.relative_path
    files = sorted(path.rglob("*.py")) if path.is_dir() else [path]
    assert files, f"pin {pin.name!r} covers no files under {path}"
    assert _source_digest(path, files) == pin.sha256, (
        f"{pin.name} corpus drifted from its pin; replacement=re-pin the hash, "
        "assertion count, and lifted loci in the same PR"
    )


# --------------------------------------------------------------------------
# Tooth 4 — mutating a vendor byte breaks the corpus hash law even though
# pytest ignores the file. The mutation happens ONLY in a tmp copy.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("pin", PINS, ids=lambda pin: pin.name)
def test_a_flipped_vendor_byte_still_breaks_the_pin(
    pin: ClaimMassPin, tmp_path: Path
) -> None:
    """Non-collection must not weaken the pin.

    Copies the corpus, flips one byte in the copy, and shows the loader's
    digest law rejects it. The committed tree is never touched.
    """
    mirror = tmp_path / "vendor"
    shutil.copytree(VENDOR_DIR, mirror)
    path = mirror / pin.relative_path
    files = sorted(path.rglob("*.py")) if path.is_dir() else [path]

    assert _source_digest(path, files) == pin.sha256, (
        "the untouched tmp mirror must reproduce the pin exactly, otherwise "
        "this tooth cannot attribute the mismatch to the flipped byte"
    )

    victim = files[0]
    original = victim.read_bytes()
    # A comment byte: parseable Python, different bytes. The point is the pin,
    # not the parse.
    victim.write_bytes(original + b"\n# corpus tamper probe\n")

    assert _source_digest(path, files) != pin.sha256, (
        f"{pin.name}: a changed vendor byte did NOT break the corpus hash law. "
        "The pin is the only thing holding this corpus authentic now that "
        "pytest does not collect it"
    )


# --------------------------------------------------------------------------
# Teeth 3 and 5 — the glob's SHAPE. Reuses the suite's real
# `collect_ignore_glob` value so this can never drift from the boundary it
# describes.
# --------------------------------------------------------------------------
_SIBLING_OWNED_TEST = "test_claim_mass_tripwires.py"


def test_owned_tests_adjacent_to_vendor_remain_collected() -> None:
    """Tooth 3: the glob must not over-reach onto our own modules.

    Asserts the sibling owned module that OWNS the vendor pins is still
    collected — the exclusion removes corpus, not the tooling that reads it.
    """
    node_ids = _collect_only(TESTS_DIR, rootdir=PACKAGE_ROOT)
    owned = [node_id for node_id in node_ids if _SIBLING_OWNED_TEST in node_id]
    assert owned, (
        f"{_SIBLING_OWNED_TEST} is no longer collected; "
        "`collect_ignore_glob` has over-reached from vendored corpus onto our "
        f"own tests. collected={len(node_ids)}"
    )


def test_a_new_nested_vendor_source_cannot_become_a_pytest_test(
    tmp_path: Path,
) -> None:
    """Tooth 5: the boundary holds for corpus files that do not exist yet.

    The glob's DEPTH is the thing under test. `tests/vendor` today holds both
    `<dist>/test_x.py` (depth 2) and `<dist>/<pkg>/*.py` (depth 3, the
    vendored `requests` package). A future nested corpus module named
    `test_*.py` must not become collectable.

    Built entirely in tmp_path, with the suite's REAL glob value.
    """
    glob = suite_conftest.collect_ignore_glob
    root = tmp_path / "tests"
    (root / "vendor" / "somepkg-1.0" / "somepkg" / "deep").mkdir(parents=True)
    (root / "conftest.py").write_text(f"collect_ignore_glob = {glob!r}\n")
    (root / "test_owned.py").write_text("def test_owned():\n    assert True\n")

    nested = [
        root / "vendor" / "somepkg-1.0" / "test_shallow.py",
        root / "vendor" / "somepkg-1.0" / "somepkg" / "test_nested.py",
        root / "vendor" / "somepkg-1.0" / "somepkg" / "deep" / "test_deeper.py",
    ]
    for source in nested:
        source.write_text(
            "import definitely_not_installed_third_party\n\n\n"
            "def test_vendor_owned_assertion():\n    assert True\n"
        )

    node_ids = _collect_only(root, rootdir=tmp_path)

    offenders = _vendor_node_ids(node_ids)
    assert offenders == [], (
        f"a nested vendored source became a pytest test: {offenders}. "
        f"collect_ignore_glob={glob!r} does not cover this depth; "
        "replacement=widen the glob (e.g. `vendor/**/*.py`) — corpus at ANY "
        "depth is data, not our test suite"
    )
    assert any("test_owned.py" in node_id for node_id in node_ids), (
        f"collect_ignore_glob={glob!r} over-reached and swallowed an owned "
        f"sibling test. collected={node_ids}"
    )
