"""The recensus authenticates its producer before it can select corpus work."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

import sugar_lift_py_tests.authenticated_pytest as runtime_authority


_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_SCRIPT = _SCRIPTS / "control_effect_recensus.py"


def _load():
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    spec = importlib.util.spec_from_file_location("control_effect_recensus", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _identity(*, version: str = "3.12.12"):
    return runtime_authority.RuntimeIdentityV1(
        implementation="cpython",
        version=version,
        sys_version=f"{version} test build",
        cache_tag="cpython-312",
        soabi="cpython-312-x86_64-linux-gnu",
        hex_version="0x30c0cf0",
        platform_tag="Linux-test-x86_64-with-glibc2.39",
        invoked_executable="/test/venv/bin/python",
        resolved_base_executable="/test/runtime/bin/python3.12",
        executable_sha256="a" * 64,
    )


def _invoke(module, *, corpus: Path, receipt: Path) -> int:
    saved = sys.argv
    sys.argv = [
        "control_effect_recensus.py",
        str(corpus),
        "--json",
        str(receipt),
        "--out-dir",
        str(receipt.parent / "run"),
    ]
    try:
        return int(module.main())
    finally:
        sys.argv = saved


def test_wrong_runtime_refuses_before_even_missing_corpus_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    observed = _identity()
    monkeypatch.setattr(
        runtime_authority, "observe_runtime_identity_v1", lambda: observed
    )

    def refuse(_identity):
        raise runtime_authority.ExecutionEnvironmentMismatch(
            "Python runtime authority mismatch: required cpython-3.12.13; "
            "observed cpython-3.12.12 at /test/venv/bin/python"
        )

    monkeypatch.setattr(runtime_authority, "authenticate_runtime_identity_v1", refuse)
    monkeypatch.setattr(
        runtime_authority,
        "declared_interpreter_runtime",
        lambda: "cpython-3.12.13",
    )
    receipt = tmp_path / "wrong-runtime.json"

    assert _invoke(module, corpus=tmp_path / "corpus-does-not-exist", receipt=receipt) == 2
    body = json.loads(receipt.read_text(encoding="utf-8"))
    assert body["kind"] == "control-effect-recensus-unmeasured/v1"
    assert body["status"] == "unmeasured"
    assert body["measured"] is False
    assert body["requiredRuntime"] == "cpython-3.12.13"
    assert body["runtimeIdentity"] == observed.to_wire()
    assert body["runtimeCid"] == runtime_authority.runtime_cid_for_identity(observed)
    assert "observed cpython-3.12.12" in body["runtimeIdentityMismatch"]
    assert "frontierWidth" not in body
    assert "measurementClass" not in body


def test_runtime_hash_failure_is_separate_and_never_fabricates_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()

    def fail_resolution():
        raise runtime_authority.RuntimeIdentityResolutionFailure(
            "runtimeIdentity/v1 could not hash resolved base executable"
        )

    monkeypatch.setattr(
        runtime_authority, "observe_runtime_identity_v1", fail_resolution
    )
    monkeypatch.setattr(
        runtime_authority,
        "declared_interpreter_runtime",
        lambda: "cpython-3.12.13",
    )
    receipt = tmp_path / "identity-failure.json"

    assert _invoke(module, corpus=tmp_path / "corpus-does-not-exist", receipt=receipt) == 2
    body = json.loads(receipt.read_text(encoding="utf-8"))
    assert body["status"] == "unmeasured"
    assert body["requiredRuntime"] == "cpython-3.12.13"
    assert "could not hash" in body["runtimeIdentityFailure"]
    assert "runtimeIdentity" not in body
    assert "runtimeCid" not in body
    assert "frontierWidth" not in body
    assert "measurementClass" not in body
