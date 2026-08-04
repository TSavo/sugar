"""Producer-side teeth for the additive showcase terminal witness wire."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from repo_root_test_support import resolve_repo_root

ROOT = resolve_repo_root()
sys.path.insert(0, str(ROOT / "tools"))

import showcase_terminal_identity  # noqa: E402
import showcase_scope  # noqa: E402


IDENTITY = {
    "schemaVersion": 1,
    "kind": "construction-panic",
    "owner": "ComparisonOpSugar.Eq",
    "coordinate": "fixture.py:4:11",
    "observed": "undecided binary compare",
    "requested": "authenticated exception coordinate",
    "entrance": "sugar.enumerate:facts:auditFrontier",
}


EQ_PRODUCERS = (
    "examples/zlib-crc32/run-logo-receipt.sh",
    "examples/struct-calcsize/run-logo-receipt.sh",
    "examples/itsdangerous-token-padding/run.sh",
    "examples/python-urlsafe-seam/run.sh",
    "examples/itsdangerous-token-padding/run-logo-receipt.sh",
    "examples/binascii-hexlify/run-logo-receipt.sh",
    "examples/sklearn-showcase/run.sh",
    "examples/stdlib-base64-padding/run-logo-receipt.sh",
    "examples/hmac-compare-digest/run-logo-receipt.sh",
    "examples/hashlib-sha256-hexdigest/run-logo-receipt.sh",
    "examples/stdlib-base32-padding/run-logo-receipt.sh",
    "examples/hashlib-sha256-digest-length/run-logo-receipt.sh",
    "examples/pandas-showcase/run.sh",
)


def test_writer_is_additive_noop_before_consumer_supplies_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SHOWCASE_TERMINAL_WITNESS", raising=False)

    assert showcase_terminal_identity.write_from_environment(IDENTITY) is False


def test_writer_emits_exact_validated_identity_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "terminal.json"
    monkeypatch.setenv("SHOWCASE_TERMINAL_WITNESS", str(output))

    assert showcase_terminal_identity.write_from_environment(IDENTITY) is True
    assert json.loads(output.read_text(encoding="utf-8")) == IDENTITY


def test_writer_refuses_empty_or_unknown_identity_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "terminal.json"
    monkeypatch.setenv("SHOWCASE_TERMINAL_WITNESS", str(output))
    empty_owner = dict(IDENTITY)
    empty_owner["owner"] = ""
    unknown = dict(IDENTITY)
    unknown["normalizedCategory"] = "panic"

    with pytest.raises(
        showcase_terminal_identity.TerminalIdentityRefusal,
        match="nonempty owner",
    ):
        showcase_terminal_identity.write_from_environment(empty_owner)
    with pytest.raises(
        showcase_terminal_identity.TerminalIdentityRefusal,
        match="unsupported fields",
    ):
        showcase_terminal_identity.write_from_environment(unknown)
    assert not output.exists()


def test_writer_refuses_to_replace_a_prior_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "terminal.json"
    monkeypatch.setenv("SHOWCASE_TERMINAL_WITNESS", str(output))
    assert showcase_terminal_identity.write_from_environment(IDENTITY) is True

    with pytest.raises(
        showcase_terminal_identity.TerminalIdentityRefusal,
        match="already exists",
    ):
        showcase_terminal_identity.write_from_environment(IDENTITY)


def test_rpc_terminal_projection_preserves_raw_identity_and_canonical_coordinate(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "checkout"
    repo.mkdir()
    diagnostic = {
        "code": -32603,
        "message": "construction refused",
        "data": {
            "exception_type": "ConstructionPanic",
            "stage": "dispatch",
            "diagnostic": {
                "owner": "ComparisonOpSugar.Eq",
                "blame": str(repo / "examples/demo/test_logo.py:4:11"),
                "observed": "undecided binary compare",
                "requested": "authenticated exception coordinate",
            },
        },
    }

    assert showcase_terminal_identity.identity_from_rpc_text(
        "prefix " + json.dumps(diagnostic) + " suffix",
        repo_root=repo,
        entrance="sugar.mint",
    ) == {
        "schemaVersion": 1,
        "kind": "ConstructionPanic",
        "owner": "ComparisonOpSugar.Eq",
        "coordinate": "examples/demo/test_logo.py:4:11",
        "observed": "undecided binary compare",
        "requested": "authenticated exception coordinate",
        "entrance": "sugar.mint",
    }


def test_rpc_terminal_projection_refuses_generic_error_without_owner(
    tmp_path: Path,
) -> None:
    diagnostic = {
        "code": -32603,
        "message": "RuntimeError: opaque failure",
        "data": {"exception_type": "RuntimeError", "stage": "dispatch"},
    }

    with pytest.raises(
        showcase_terminal_identity.TerminalIdentityRefusal,
        match="lacks diagnostic owner",
    ):
        showcase_terminal_identity.identity_from_rpc_text(
            json.dumps(diagnostic),
            repo_root=tmp_path,
            entrance="sugar.mint",
        )


def test_scope_runner_supplies_additive_channel_without_consuming_it(
    tmp_path: Path,
) -> None:
    script_name = "examples/failing/run.sh"
    script = tmp_path / script_name
    script.parent.mkdir(parents=True)
    script.write_text(
        "#!/usr/bin/env sh\n"
        f"python3 {ROOT / 'tools/showcase_terminal_identity.py'} "
        "--kind construction-panic --owner PlantedOwner "
        "--coordinate fixture.py:1:0\n"
        "exit 7\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    manifest = tmp_path / "retirements.json"
    manifest.write_text(
        '{"schemaVersion":1,"retirements":[]}\n', encoding="utf-8"
    )
    attr_dir = tmp_path / "attr"
    receipt = tmp_path / "scope.json"

    assert (
        showcase_scope.run_shard(
            repo_root=tmp_path,
            manifest_path=manifest,
            enrolled=[script_name],
            shard_count=1,
            shard_index=0,
            attr_dir=attr_dir,
            receipt_path=receipt,
        )
        == 1
    )
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["outcomes"] == [
        {"path": script_name, "outcome": "failed", "exitCode": 7}
    ]
    terminal_files = list(attr_dir.glob("*.terminal-witness"))
    assert len(terminal_files) == 1
    assert json.loads(terminal_files[0].read_text(encoding="utf-8")) == {
        "schemaVersion": 1,
        "kind": "construction-panic",
        "owner": "PlantedOwner",
        "coordinate": "fixture.py:1:0",
    }


def test_shell_wrapper_publishes_selected_rpc_terminal_and_preserves_exit(
    tmp_path: Path,
) -> None:
    output = tmp_path / "terminal.json"
    diagnostic = {
        "code": -32603,
        "message": "construction refused",
        "data": {
            "exception_type": "ConstructionPanic",
            "stage": "dispatch",
            "diagnostic": {
                "owner": "ComparisonOpSugar.Eq",
                "blame": str(ROOT / "examples/demo/test_logo.py:4:11"),
                "observed": "undecided binary compare",
                "requested": "authenticated exception coordinate",
            },
        },
    }
    command = (
        f"source {ROOT / 'scripts/showcase-terminal-identity.sh'}; "
        "showcase_run_with_terminal sugar.mint bash -c "
        # Quote for the outer shell without allowing it to expand the planted
        # JSON.  The selected child, not its parent, owns the raw diagnostic.
        + shlex.quote("printf '%s\\n' \"$PLANTED_RPC_ERROR\" >&2; exit 7")
    )
    completed = subprocess.run(
        ["bash", "-c", command],
        text=True,
        capture_output=True,
        check=False,
        env={
            "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
            "SHOWCASE_TERMINAL_WITNESS": str(output),
            "PLANTED_RPC_ERROR": json.dumps(diagnostic),
        },
    )

    assert completed.returncode == 7
    assert json.loads(output.read_text(encoding="utf-8"))["owner"] == (
        "ComparisonOpSugar.Eq"
    )
    assert json.loads(output.read_text(encoding="utf-8"))["coordinate"] == (
        "examples/demo/test_logo.py:4:11"
    )


@pytest.mark.parametrize("relative_path", EQ_PRODUCERS)
def test_eq_producer_routes_its_selected_mint_through_raw_terminal_writer(
    relative_path: str,
) -> None:
    script = (ROOT / relative_path).read_text(encoding="utf-8")

    assert script.count('source "$REPO/scripts/showcase-terminal-identity.sh"') == 1
    assert script.count("showcase_run_with_terminal sugar.mint ") == 1
    assert "ComparisonOpSugar.Eq" not in script


def test_shell_wrapper_reads_structured_stdout_and_replays_both_streams(
    tmp_path: Path,
) -> None:
    output = tmp_path / "terminal.json"
    diagnostic = {
        "code": -32001,
        "message": "sugar not written",
        "data": {
            "exception_type": "SugarNotWritten",
            "stage": "dispatch",
            "diagnostic": {
                "owner": "binary_operation_exception_floor",
                "observed": "CallSiteValue >> TermValue",
                "requested": "authenticated exceptional exit",
            },
        },
    }
    command = (
        f"source {ROOT / 'scripts/showcase-terminal-identity.sh'}; "
        "showcase_run_with_terminal sugar.mint bash -c "
        + shlex.quote(
            "printf 'stdout-before\\n'; "
            "printf '%s\\n' \"$PLANTED_RPC_ERROR\"; "
            "printf 'stderr-before\\n' >&2; exit 17"
        )
    )
    completed = subprocess.run(
        ["bash", "-c", command],
        text=True,
        capture_output=True,
        check=False,
        env={
            "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
            "SHOWCASE_TERMINAL_WITNESS": str(output),
            "PLANTED_RPC_ERROR": json.dumps(diagnostic),
        },
    )

    assert completed.returncode == 17
    assert "stdout-before\n" in completed.stdout
    assert json.dumps(diagnostic) in completed.stdout
    assert "stderr-before\n" in completed.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["owner"] == (
        "binary_operation_exception_floor"
    )


def test_shell_wrapper_publication_refusal_preserves_selected_exit(
    tmp_path: Path,
) -> None:
    output = tmp_path / "terminal.json"
    command = (
        f"source {ROOT / 'scripts/showcase-terminal-identity.sh'}; "
        "showcase_run_with_terminal sugar.mint bash -c "
        + shlex.quote(
            "printf 'ordinary stdout\\n'; "
            "printf 'ownerless failure\\n' >&2; exit 19"
        )
    )
    completed = subprocess.run(
        ["bash", "-c", command],
        text=True,
        capture_output=True,
        check=False,
        env={
            "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
            "SHOWCASE_TERMINAL_WITNESS": str(output),
        },
    )

    assert completed.returncode == 19
    assert completed.stdout == "ordinary stdout\n"
    assert "ownerless failure\n" in completed.stderr
    assert "REFUSED: selected command emitted no structured RPC error" in (
        completed.stderr
    )
    assert not output.exists()
