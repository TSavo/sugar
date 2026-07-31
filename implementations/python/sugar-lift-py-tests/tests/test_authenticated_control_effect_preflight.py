from pathlib import Path
import subprocess
import sys

import pytest

from sugar_lift_py_tests.authenticated_pytest import ExecutionEnvironmentMismatch


def _module():
    import importlib.util

    path = (
        Path(__file__).parents[1]
        / "scripts/authenticated_control_effect_preflight.py"
    )
    spec = importlib.util.spec_from_file_location("census_preflight", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_launch_coordinates_require_exact_synced_commit_and_durable_output():
    commit = "a" * 40
    _module().require_launch_coordinates(
        commit,
        commit + ":tracked-manifest:pid:nonce",
        Path(f"/root/.cache/sugar/measurements/pandas-control-effect/{commit}"),
    )


@pytest.mark.parametrize(
    ("commit", "proof", "output", "needle"),
    [
        ("branch-name", "branch-name:x", "/root/.cache/sugar/measurements/x", "malformed"),
        ("a" * 40, "b" * 40 + ":x", "/root/.cache/sugar/measurements/x", "mount proof"),
        ("a" * 40, "a" * 40 + ":x", "/workspace/sugar/.sugar/census", "durable"),
    ],
)
def test_launch_coordinates_refuse_each_unauthenticated_face(
    commit: str, proof: str, output: str, needle: str
):
    with pytest.raises(ExecutionEnvironmentMismatch, match=needle):
        _module().require_launch_coordinates(commit, proof, Path(output))


def _launch(tmp_path: Path):
    module = _module()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tools").mkdir()
    (repo / "implementations/python/sugar-lift-py-tests/scripts").mkdir(
        parents=True
    )
    output = tmp_path / "out"
    output.mkdir()
    return module, module.CensusLaunch(
        "a" * 40, repo, tmp_path / "pandas", tmp_path / "pin.json", output
    )


def test_preflight_refusal_never_calls_census():
    module = _module()
    calls = []

    def refused():
        raise ExecutionEnvironmentMismatch("wrong runtime")

    assert module.execute(authenticate=refused, runner=lambda *a, **k: calls.append(a)) == 78
    assert calls == []


def test_preflight_success_calls_one_lease_wrapped_authoritative_census(tmp_path: Path):
    module, launch = _launch(tmp_path)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        (launch.output / "recensus.json").write_text(
            '{"denominator":{"complete":true}}', encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, stdout="done files=1421/1421", stderr="")

    assert module.execute(authenticate=lambda: launch, runner=run) == 0
    assert len(calls) == 1
    rendered = " ".join(map(str, calls[0]))
    assert "heavy_measurement_lease.py" in rendered
    assert "control_effect_recensus.py" in rendered


def test_census_failure_propagates_after_writing_receipt(tmp_path: Path):
    module, launch = _launch(tmp_path)

    def run(command, **kwargs):
        (launch.output / "recensus.json").write_text(
            '{"denominator":{"complete":true},"red":true}', encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 23, stdout="done files=1421/1421", stderr="")

    assert module.execute(authenticate=lambda: launch, runner=run) == 23


def test_missing_census_json_is_a_named_failure(tmp_path: Path):
    module, launch = _launch(tmp_path)
    run = lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout="", stderr="")
    assert module.execute(authenticate=lambda: launch, runner=run) == module.EX_IOERR


def test_missing_completion_summary_is_a_named_failure(tmp_path: Path):
    module, launch = _launch(tmp_path)

    def run(command, **kwargs):
        (launch.output / "recensus.json").write_text(
            '{"denominator":{"complete":true}}', encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    assert module.execute(authenticate=lambda: launch, runner=run) == module.EX_IOERR
