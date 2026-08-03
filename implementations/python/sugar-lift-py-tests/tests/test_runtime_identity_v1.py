"""The recensus runtime is producer identity, not host-noise metadata."""

from __future__ import annotations

import dataclasses
import pathlib
import re
import sys

import pytest

import sugar_lift_py_tests.authenticated_pytest as authority


def _require_v1_api() -> None:
    assert hasattr(authority, "RuntimeIdentityV1"), (
        "runtimeIdentity/v1 is not implemented at the authenticated interpreter door"
    )
    assert hasattr(authority, "observe_runtime_identity_v1")
    assert hasattr(authority, "runtime_cid_for_identity")
    assert hasattr(authority, "authenticate_runtime_identity_v1")


def _observe_with_base(
    monkeypatch: pytest.MonkeyPatch,
    *,
    invoked: pathlib.Path,
    base: pathlib.Path,
):
    _require_v1_api()
    monkeypatch.setattr(sys, "executable", str(invoked))
    monkeypatch.setattr(sys, "_base_executable", str(base), raising=False)
    return authority.observe_runtime_identity_v1()


def test_identical_runtime_bytes_moved_to_another_path_keep_runtime_cid(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first" / "python3.12"
    second = tmp_path / "second" / "python3.12"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"same interpreter bytes")
    second.write_bytes(first.read_bytes())

    left = _observe_with_base(
        monkeypatch,
        invoked=tmp_path / "venv-a" / "bin" / "python",
        base=first,
    )
    left_cid = authority.runtime_cid_for_identity(left)
    right = _observe_with_base(
        monkeypatch,
        invoked=tmp_path / "venv-b" / "bin" / "python",
        base=second,
    )
    right_cid = authority.runtime_cid_for_identity(right)

    assert left.resolved_base_executable != right.resolved_base_executable
    assert left.invoked_executable != right.invoked_executable
    assert left.executable_sha256 == right.executable_sha256
    assert left_cid == right_cid


def test_changed_runtime_bytes_change_hash_and_runtime_cid(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "python-a"
    second = tmp_path / "python-b"
    first.write_bytes(b"interpreter build A")
    second.write_bytes(b"interpreter build B")

    left = _observe_with_base(monkeypatch, invoked=first, base=first)
    right = _observe_with_base(monkeypatch, invoked=second, base=second)

    assert left.executable_sha256 != right.executable_sha256
    assert authority.runtime_cid_for_identity(left) != authority.runtime_cid_for_identity(
        right
    )


def test_runtime_identity_wire_matches_observed_v1_shape(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "python3.12"
    executable.write_bytes(b"identity fixture")
    identity = _observe_with_base(
        monkeypatch,
        invoked=tmp_path / "venv" / "bin" / "python",
        base=executable,
    )
    wire = identity.to_wire()

    assert wire == {
        "schema": "runtimeIdentity/v1",
        "implementation": sys.implementation.name,
        "version": (
            f"{sys.version_info.major}.{sys.version_info.minor}."
            f"{sys.version_info.micro}"
        ),
        "sysVersion": sys.version,
        "cacheTag": sys.implementation.cache_tag,
        "SOABI": identity.soabi,
        "hexVersion": hex(sys.hexversion),
        "platformTag": identity.platform_tag,
        "invokedExecutable": str((tmp_path / "venv" / "bin" / "python").absolute()),
        "resolvedBaseExecutable": str(executable.resolve()),
        "executableSha256": identity.executable_sha256,
    }
    assert re.fullmatch(r"[0-9a-f]{64}", identity.executable_sha256)
    assert authority.runtime_cid_for_identity(wire).startswith("blake3-512:")


def test_wrong_version_refuses_after_preserving_full_observed_identity(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "python3.12"
    executable.write_bytes(b"runtime")
    observed = _observe_with_base(monkeypatch, invoked=executable, base=executable)
    wrong = dataclasses.replace(observed, version="3.14.4")

    with pytest.raises(
        authority.ExecutionEnvironmentMismatch,
        match=r"required cpython-3\.12\.13; observed cpython-3\.14\.4",
    ):
        authority.authenticate_runtime_identity_v1(wrong)

    assert wrong.to_wire()["executableSha256"] == observed.executable_sha256
    assert "invokedExecutable" in wrong.to_wire()


def test_missing_base_executable_is_identity_failure_not_unavailable_marker(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _require_v1_api()
    missing = tmp_path / "missing-python"
    monkeypatch.setattr(sys, "executable", str(tmp_path / "invoked"))
    monkeypatch.setattr(sys, "_base_executable", str(missing), raising=False)

    with pytest.raises(authority.RuntimeIdentityResolutionFailure):
        authority.observe_runtime_identity_v1()
