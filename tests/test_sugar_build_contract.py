import importlib.util
import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sugar_build_contract", ROOT / "tools/sugar-build/contract.py"
)
contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract)
ContractError = contract.ContractError


def manifest(tmp_path, body):
    path = tmp_path / "sugar-build.toml"
    path.write_text(body)
    return path


def test_core_versions_are_exact(tmp_path):
    result = contract.resolve_environment("docker:core")
    assert result["tools"] == {
        "rust": "1.96.0", "cargo": "1.96.0", "python": "3.12.13",
        "black": "26.5.1", "pyright": "1.1.411", "b3sum": "1.8.1",
        "z3": "4.8.12", "coq": "8.18.0", "numpy": "2.5.1",
        "pandas": "3.0.3", "java": "21", "maven": "3.8.7",
        "node": "22.17.1", "pnpm": "10.13.1", "vampire": "5.0.1",
    }


def test_every_capability_has_an_exact_version_owner():
    tools = contract.tool_versions()
    assert {
        "z3", "coq", "numpy", "pandas", "java", "maven", "node", "pnpm", "vampire",
    } <= tools.keys()
    for name in ("z3", "coq", "numpy", "pandas", "java", "maven", "node", "pnpm", "vampire"):
        assert isinstance(tools[name], str) and tools[name]


@pytest.mark.parametrize("name", [
    "python-unit", "python-lift", "rust-unit", "examples-gate", "pandas-wall",
    "numpy-wall", "restored-suite-scoreboard",
])
def test_initial_named_tasks_always_have_commands(name):
    task = contract.resolve_task(name)
    assert task["command"]


def test_python_unit_is_a_managed_core_task():
    task = contract.resolve_task("python-unit")
    assert task == {
        "binaries": [],
        "capabilities": ["core"],
        "command": ["python", "-m", "pytest"],
        "task": "python-unit",
    }


def test_pyright_private_node_is_not_the_node_capability():
    dockerfile = (ROOT / "tools/sugar-build/Dockerfile").read_text()
    assert "FROM core AS node" in dockerfile
    node_stage = dockerfile.split("FROM core AS node", 1)[1]
    assert "ARG NODE_VERSION=" in node_stage
    assert "PYRIGHT_NODE_VERSION" not in node_stage


def test_docker_capability_defaults_match_contract_versions():
    dockerfile = (ROOT / "tools/sugar-build/Dockerfile").read_text()
    tools = contract.tool_versions()
    for argument, tool in {
        "COQ_VERSION": "coq",
        "NUMPY_VERSION": "numpy",
        "PANDAS_VERSION": "pandas",
        "JAVA_VERSION": "java",
        "MAVEN_VERSION": "maven",
        "NODE_VERSION": "node",
        "PNPM_VERSION": "pnpm",
        "VAMPIRE_VERSION": "vampire",
    }.items():
        assert re.search(rf"^ARG {argument}={re.escape(tools[tool])}$", dockerfile, re.MULTILINE)
    assert f'ARG Z3_DEBIAN_VERSION={tools["z3"]}-3.1' in dockerfile


def test_capability_order_does_not_change_digest_input(tmp_path):
    base = (ROOT / "sugar-build.toml").read_text()
    images = '\n[images."core,python-scientific,solver-z3"]\nreference = "sugar@sha256:' + 'b' * 64 + '"\n'
    path = manifest(tmp_path, base + images)
    assert contract.resolve_environment("docker:solver-z3,python-scientific", path) == contract.resolve_environment("docker:python-scientific,solver-z3", path)


def test_unknown_capability_is_loud():
    with pytest.raises(ContractError, match="unknown capability"):
        contract.resolve_environment("docker:not-real")


def test_bare_docker_environment_is_loud():
    with pytest.raises(ContractError, match="empty capability"):
        contract.resolve_environment("docker")


def test_duplicate_definitions_are_loud(tmp_path):
    path = manifest(tmp_path, "schema=1\n[tools]\nrust='1'\nrust='2'\n")
    with pytest.raises(ContractError, match="duplicate"):
        contract.load_contract(path)


def test_dependency_cycles_are_loud(tmp_path):
    path = manifest(tmp_path, "schema=1\n[tools]\n[capabilities.a]\ndepends=['b']\n[capabilities.b]\ndepends=['a']\n[tasks]\n")
    with pytest.raises(ContractError, match="dependency cycle"):
        contract.resolve_capabilities(["a"], path)


def test_missing_immutable_image_is_loud():
    with pytest.raises(ContractError, match="capability closure has no built image"):
        contract.resolve_environment("docker:solver-z3")


def test_mutable_image_reference_is_loud(tmp_path):
    text = (ROOT / "sugar-build.toml").read_text().replace(
        'reference = "ghcr.io/tsavo/sugar-env@sha256:b8af4d5631bc34bea951a1ed5da391fbdc5efd4763941def40840f05292960a4"',
        'reference = "sugar:latest"',
    )
    path = manifest(tmp_path, text)
    with pytest.raises(ContractError, match="capability closure has no built image"):
        contract.resolve_environment("docker:core", path)


def test_unknown_task_binary_is_loud(tmp_path):
    text = "schema=1\n[tools]\n[capabilities.core]\ndepends=[]\n[tasks.bad]\ncapabilities=['core']\nbinaries=['not-published']\ncommand=['true']\n"
    with pytest.raises(ContractError, match="unknown task binary"):
        contract.resolve_task("bad", manifest(tmp_path, text))


def test_empty_task_command_is_loud(tmp_path):
    text = "schema=1\n[tools]\n[capabilities.core]\ndepends=[]\n[tasks.bad]\ncapabilities=['core']\nbinaries=[]\ncommand=[]\n"
    with pytest.raises(ContractError, match="empty command"):
        contract.resolve_task("bad", manifest(tmp_path, text))


def test_json_is_canonical():
    encoded = contract.canonical_json(contract.resolve_task("examples-gate"))
    assert encoded == json.dumps(json.loads(encoded), sort_keys=True, separators=(",", ":"))
