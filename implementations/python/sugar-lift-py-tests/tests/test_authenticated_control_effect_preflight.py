from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.authenticated_pytest import ExecutionEnvironmentMismatch


def _result(commit: str = "a" * 40, **overrides):
    denominator = {
        "complete": True,
        "enrolled": 1421,
        "terminalRows": 1421,
        "completed": 1421,
        "missingFiles": [],
        "duplicateFiles": [],
        "malformedRows": [],
    }
    denominator.update(overrides.pop("denominator", {}))
    return {
        "commit": commit,
        "sourceStamp": {"commit": commit},
        "denominator": denominator,
        **overrides,
    }


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


def test_all_census_packages_resolve_from_the_synced_checkout():
    module = _module()

    sources = module.require_synced_source_packages(module._REPO)

    assert set(sources) == {
        "sugar_lift_py_tests",
        "sugar_lift_python_source",
        "sugar_source_tree",
    }
    assert all(
        (module._REPO / "implementations/python").resolve()
        in Path(path).resolve().parents
        for path in sources.values()
    )


@pytest.mark.parametrize(
    "package",
    ("sugar_lift_py_tests", "sugar_lift_python_source", "sugar_source_tree"),
)
def test_one_image_global_package_makes_preflight_loud(monkeypatch, package: str):
    module = _module()
    monkeypatch.setitem(
        sys.modules,
        package,
        SimpleNamespace(__file__=f"/image/site-packages/{package}/__init__.py"),
    )

    with pytest.raises(ExecutionEnvironmentMismatch, match=package):
        module.require_synced_source_packages(module._REPO)


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
    run_kwargs = []

    def run(command, **kwargs):
        calls.append(command)
        run_kwargs.append(kwargs)
        (launch.output / "recensus.json").write_text(
            __import__("json").dumps(_result()), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, stdout="done files=1421/1421", stderr="")

    assert module.execute(authenticate=lambda: launch, runner=run) == 0
    assert len(calls) == 1
    rendered = " ".join(map(str, calls[0]))
    assert "heavy_measurement_lease.py" in rendered
    assert "control_effect_recensus.py" in rendered
    child_paths = run_kwargs[0]["env"]["PYTHONPATH"].split(__import__("os").pathsep)
    assert child_paths == [str(path) for path in module._SOURCE_ROOTS]


def test_census_failure_propagates_after_writing_receipt(tmp_path: Path):
    module, launch = _launch(tmp_path)

    def run(command, **kwargs):
        (launch.output / "recensus.json").write_text(
            __import__("json").dumps(_result(red=True)), encoding="utf-8"
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
            __import__("json").dumps(_result()), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    assert module.execute(authenticate=lambda: launch, runner=run) == module.EX_IOERR


def test_stale_terminals_are_removed_while_checkpoint_survives(tmp_path: Path):
    module, launch = _launch(tmp_path)
    checkpoint = launch.output / "checkpoint.jsonl"
    checkpoint.write_text('{"file":"first.py"}\n', encoding="utf-8")
    for name in module.TERMINAL_ARTIFACTS:
        (launch.output / name).write_text("stale", encoding="utf-8")

    def run(command, **kwargs):
        assert checkpoint.read_text(encoding="utf-8") == '{"file":"first.py"}\n'
        assert all(
            not (launch.output / name).exists()
            for name in module.TERMINAL_ARTIFACTS
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    assert module.execute(authenticate=lambda: launch, runner=run) == module.EX_IOERR
    assert checkpoint.is_file()


@pytest.mark.parametrize("foreign_seat", ("commit", "sourceStamp"))
def test_foreign_result_commit_is_refused(tmp_path: Path, foreign_seat: str):
    import json

    module, launch = _launch(tmp_path)

    def run(command, **kwargs):
        payload = _result()
        if foreign_seat == "commit":
            payload["commit"] = "b" * 40
        else:
            payload["sourceStamp"]["commit"] = "b" * 40
        (launch.output / "recensus.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        return subprocess.CompletedProcess(
            command, 0, stdout="done files=1421/1421", stderr=""
        )

    assert module.execute(authenticate=lambda: launch, runner=run) == module.EX_IOERR


@pytest.mark.parametrize(
    "forgery",
    (
        {"enrolled": 1400},
        {"terminalRows": 1420},
        {"completed": 1400},
        {"missingFiles": ["lost.py"]},
        {"duplicateFiles": ["twice.py"]},
        {"malformedRows": ["bad row"]},
    ),
)
def test_complete_flag_cannot_forge_denominator_conservation(
    tmp_path: Path, forgery: dict
):
    import json

    module, launch = _launch(tmp_path)

    def run(command, **kwargs):
        (launch.output / "recensus.json").write_text(
            json.dumps(_result(denominator=forgery)), encoding="utf-8"
        )
        return subprocess.CompletedProcess(
            command, 0, stdout="done files=1421/1421", stderr=""
        )

    assert module.execute(authenticate=lambda: launch, runner=run) == module.EX_IOERR
