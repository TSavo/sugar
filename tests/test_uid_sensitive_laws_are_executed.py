"""A skipped law is an unrun law, and an unrun law reported as green is a lie.

``bpytest`` runs as root on battleaxe. Root bypasses the DAC mode checks that
uid-sensitive laws are about, so a test guarding on ``os.getuid() == 0`` and
skipping is unfalsifiable there: it can never fail, no matter how broken the
code under it becomes. Two permission laws in ``test_heavy_measurement_lease``
skipped on the box while passing locally, and nobody noticed, because the suite
did not go red -- it went *smaller*.

That is the same defect class as a collection error that shrinks the
denominator. The colour is not the instrument; the executed count is.

These are the teeth against that class:

    1. No uid-guarded test may degrade to a skip. Structural, over the whole
       corpus, so the class cannot regrow one test at a time.

    2. The privilege-drop mechanism must actually deny something HERE. A
       mechanism that quietly no-ops under root would restore the exact
       unfalsifiability it was written to remove -- so it is tested by
       provoking a real EACCES, not by inspection.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from unprivileged_identity import (
    UnprivilegedIdentityUnavailable,
    reachable_by_unprivileged,
    run_unprivileged,
    unprivileged_identity,
)

TESTS = Path(__file__).resolve().parent
SELF = Path(__file__).name


def _uid_guarded_skips():
    """Every test function that both consults the uid and calls ``pytest.skip``."""
    offenders = []
    for path in sorted(TESTS.rglob("*.py")):
        if path.name == SELF:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            consults_uid = False
            skips = False
            for inner in ast.walk(node):
                if isinstance(inner, ast.Attribute) and inner.attr in {
                    "getuid",
                    "geteuid",
                }:
                    consults_uid = True
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "skip"
                ):
                    skips = True
            if consults_uid and skips:
                offenders.append(
                    f"{path.relative_to(TESTS.parent)}:{node.lineno}: {node.name}"
                )
    return offenders


def test_no_uid_sensitive_law_degrades_to_a_skip():
    """A uid guard that skips makes the law unfalsifiable wherever it matters.

    The suite runs as root under ``bpytest``, which is precisely the identity
    such a guard excludes -- so the law would be skipped in the one environment
    that is supposed to run it. Run it under a dropped identity instead
    (``tests/unprivileged_identity.py``); never skip it.
    """
    offenders = _uid_guarded_skips()
    assert not offenders, (
        f"R={len(offenders)} uid-sensitive laws degrade to a skip and are "
        "therefore unfalsifiable under the root identity bpytest runs as:\n"
        + "\n".join(offenders)
        + "\nreplacement: run the law under a non-root identity with "
        "unprivileged_identity.run_unprivileged / unprivileged_preexec, or "
        "fail by name -- a skip reports an unrun law as green"
    )


def test_the_privilege_drop_actually_denies_something_here(tmp_path):
    """The positive control: without this, the mechanism could silently no-op.

    A privilege drop that failed to take effect would leave every law using it
    passing vacuously under root -- exactly the unfalsifiability being removed,
    now hidden one layer deeper. So provoke a real EACCES and require it.
    """
    reachable_by_unprivileged(tmp_path)
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    target = locked / "denied.txt"

    def write():
        target.write_text("x")
        return "wrote"

    with pytest.raises(PermissionError):
        run_unprivileged(write)

    assert not target.exists(), "the write must not have landed"
    locked.chmod(0o700)


def test_the_dropped_identity_is_not_root():
    """Whatever identity the law runs under, the kernel must be checking it."""
    assert run_unprivileged(os.getuid) != 0
    assert run_unprivileged(os.geteuid) != 0


def test_an_unavailable_identity_refuses_by_name_rather_than_skipping():
    """The refusal is named and is an error, never a silently smaller suite."""
    assert issubclass(UnprivilegedIdentityUnavailable, Exception)
    assert not issubclass(UnprivilegedIdentityUnavailable, pytest.skip.Exception), (
        "an unavailable identity must fail, never register as a skip"
    )

    identity = unprivileged_identity()
    if identity is not None:
        uid, _ = identity
        assert uid != 0, "a 'dropped' identity of uid 0 would prove nothing"
