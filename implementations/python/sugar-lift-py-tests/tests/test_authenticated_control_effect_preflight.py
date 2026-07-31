from pathlib import Path

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
