import importlib.util
import json
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
    path = manifest(tmp_path, (ROOT / "sugar-build.toml").read_text() + '\n[images."core"]\nreference = "sugar@sha256:' + 'a' * 64 + '"\n')
    result = contract.resolve_environment("docker:core", path)
    assert result["tools"] == {
        "rust": "1.96.0", "cargo": "1.96.0", "python": "3.12.13",
        "black": "26.5.1", "pyright": "1.1.411", "b3sum": "1.8.1",
    }


def test_capability_order_does_not_change_digest_input(tmp_path):
    base = (ROOT / "sugar-build.toml").read_text()
    images = '\n[images."core,python-scientific,solver-z3"]\nreference = "sugar@sha256:' + 'b' * 64 + '"\n'
    path = manifest(tmp_path, base + images)
    assert contract.resolve_environment("docker:solver-z3,python-scientific", path) == contract.resolve_environment("docker:python-scientific,solver-z3", path)


def test_unknown_capability_is_loud():
    with pytest.raises(ContractError, match="unknown capability"):
        contract.resolve_environment("docker:not-real")


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
        contract.resolve_environment("docker:core")


def test_mutable_image_reference_is_loud(tmp_path):
    path = manifest(tmp_path, (ROOT / "sugar-build.toml").read_text() + '\n[images."core"]\nreference = "sugar:latest"\n')
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
