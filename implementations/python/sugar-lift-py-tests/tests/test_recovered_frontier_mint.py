from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.idd.command_result import CommandResult
from sugar_lift_py_tests.idd.recovered_frontier import mint_recovered_frontier


def _payload(
    *,
    source_files: int,
    body_demands: int,
    completed_leaves: int,
    panics: int = 0,
    status: str,
) -> dict[str, object]:
    return {
        "kind": "recovered-construction-audit",
        "recoveryOverride": True,
        "status": status,
        "census": {
            "kind": "recovered-frontier-census",
            "sourceFilesEnumerated": source_files,
            "sourceBodiesDemanded": body_demands,
            "auditLeavesCompleted": completed_leaves,
        },
        "panics": [{"kind": "factory-panic"} for _ in range(panics)],
        "effects": [],
        "suppressedDescendants": [],
    }


def _mint(tmp_path: Path, payload: dict[str, object], returncode: int):
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    def runner(command: list[str], _cwd: Path, _env: dict[str, str]) -> CommandResult:
        frontier_path = Path(command[command.index("-o") + 1])
        frontier_path.write_text(json.dumps(payload), encoding="utf-8")
        return CommandResult(returncode, "", "producer terminal telemetry")

    return output_dir, lambda: mint_recovered_frontier(
        label="fixture wall",
        sugar_bin=tmp_path / "sugar",
        workspace=tmp_path / "workspace",
        root=tmp_path,
        env={},
        output_dir=output_dir,
        runner=runner,
    )


def test_producer_terminal_state_refuses_artifact_even_if_file_was_written(
    tmp_path: Path,
) -> None:
    output_dir, mint = _mint(
        tmp_path,
        _payload(
            source_files=1,
            body_demands=1,
            completed_leaves=0,
            status="producer-fatal",
        ),
        7,
    )

    with pytest.raises(RuntimeError, match="terminal.*incomplete"):
        mint()

    assert not (output_dir / "frontier.json").exists()


def test_producer_death_deletes_stale_artifact_but_keeps_typed_fatal_telemetry(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    frontier_path = output_dir / "frontier.json"
    frontier_path.write_text(
        json.dumps(
            _payload(
                source_files=9,
                body_demands=9,
                completed_leaves=9,
                status="complete",
            )
        ),
        encoding="utf-8",
    )
    fatal = json.dumps(
        {
            "kind": "producer-fatal",
            "phase": "source-body-demand",
            "message": "enumerator exited before terminal census",
        }
    )

    def runner(_command: list[str], _cwd: Path, _env: dict[str, str]) -> CommandResult:
        assert (
            not frontier_path.exists()
        ), "stale frontier must be deleted before launch"
        return CommandResult(70, "", fatal)

    with pytest.raises(RuntimeError, match="failed without frontier.json.*exit=70"):
        mint_recovered_frontier(
            label="fixture wall",
            sugar_bin=tmp_path / "sugar",
            workspace=tmp_path / "workspace",
            root=tmp_path,
            env={},
            output_dir=output_dir,
            runner=runner,
        )

    assert not frontier_path.exists()
    assert (output_dir / "wall.frontier.txt").read_text(encoding="utf-8") == fatal


def test_known_nonempty_zero_without_body_demand_is_unrepresentable(
    tmp_path: Path,
) -> None:
    output_dir, mint = _mint(
        tmp_path,
        _payload(
            source_files=1,
            body_demands=0,
            completed_leaves=0,
            status="complete",
        ),
        0,
    )

    with pytest.raises(RuntimeError, match="source body census mismatch"):
        mint()

    assert not (output_dir / "frontier.json").exists()


@pytest.mark.parametrize("bad_value", [-1, True, "1"])
def test_malformed_census_count_is_rejected(tmp_path: Path, bad_value: object) -> None:
    payload = _payload(
        source_files=1,
        body_demands=1,
        completed_leaves=1,
        status="complete",
    )
    census = payload["census"]
    assert isinstance(census, dict)
    census["auditLeavesCompleted"] = bad_value
    output_dir, mint = _mint(tmp_path, payload, 0)

    with pytest.raises(RuntimeError, match="must be a non-negative integer"):
        mint()

    assert not (output_dir / "frontier.json").exists()


def test_genuinely_empty_corpus_has_explicit_valid_empty_receipt(
    tmp_path: Path,
) -> None:
    _output_dir, mint = _mint(
        tmp_path,
        _payload(
            source_files=0,
            body_demands=0,
            completed_leaves=0,
            status="valid-empty",
        ),
        0,
    )

    artifact = mint()

    assert artifact["status"] == "valid-empty"
    assert artifact["census"] == {
        "kind": "recovered-frontier-census",
        "sourceFilesEnumerated": 0,
        "sourceBodiesDemanded": 0,
        "auditLeavesCompleted": 0,
    }


def test_successful_nonzero_frontier_mint_keeps_red_exit_artifact(
    tmp_path: Path,
) -> None:
    output_dir, mint = _mint(
        tmp_path,
        _payload(
            source_files=1,
            body_demands=1,
            completed_leaves=1,
            panics=1,
            status="failed",
        ),
        2,
    )

    artifact = mint()

    assert len(artifact["panics"]) == 1
    assert (output_dir / "frontier.json").is_file()
