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
        "z3": "4.8.12", "coq": "8.16.1", "numpy": "2.5.1",
        "pandas": "3.0.3", "java": "21.0.9", "maven": "3.8.7",
        "node": "22.17.1", "pnpm": "10.13.1", "vampire": "5.0.1",
        "pytest": "9.1.1",
    }


def test_every_capability_has_an_exact_version_owner():
    tools = contract.tool_versions()
    assert {
        "z3", "coq", "numpy", "pandas", "java", "maven", "node", "pnpm", "vampire",
    } <= tools.keys()
    for name in ("z3", "coq", "numpy", "pandas", "java", "maven", "node", "pnpm", "vampire"):
        assert isinstance(tools[name], str) and tools[name]


def test_declared_tool_versions_have_exact_syntax_and_capability_mapping(tmp_path):
    assert contract.capability_tool_owners() == {
        "core": ("black", "b3sum", "cargo", "pyright", "python", "rust"),
        "java": ("java", "maven"),
        "node": ("node", "pnpm"),
        "python-scientific": ("numpy", "pandas"),
        "python-test": ("pytest",),
        "solver-coq": ("coq",),
        "solver-z3": ("z3",),
        "vampire": ("vampire",),
    }
    text = (ROOT / "sugar-build.toml").read_text().replace('z3 = "4.8.12"', 'z3 = ">=4.8"')
    with pytest.raises(ContractError, match="non-exact tool version: z3"):
        contract.tool_versions(manifest(tmp_path, text))


@pytest.mark.parametrize(("name", "capabilities", "digest", "binaries", "command"), [
    ("python-unit", ["core", "python-test"], "12ca8a6768630ae70afb37d63a48b5035da365c4c2fe4cd99117ae4327932674", ["sugar"], ["python", "-m", "pytest"]),
    ("python-lift", ["core", "python-scientific", "python-test", "solver-z3"], "f96731de7b4eb9a5660a6f8a14fc37f23ead4a0a9221667e9073ee0853070db3", ["sugar"], ["python", "-m", "pytest"]),
    ("rust-unit", ["core", "solver-z3"], "ea84add5822935318b6be07dba38980b81d947b077b077ca7e6f70febdf2d497", [], ["cargo", "test", "--manifest-path", "implementations/rust/Cargo.toml"]),
    ("examples-gate", ["core", "java", "node", "python-scientific", "python-test", "solver-coq", "solver-z3", "vampire"], "f3474a1e1badba67f3daaf5c589f2844da28a7be6beda929ca5f7f2e5d95785e", ["sugar", "sugar-ir-smt-lib"], ["make", "examples-gate"]),
    ("pandas-wall", ["core", "python-scientific", "python-test", "solver-z3"], "f96731de7b4eb9a5660a6f8a14fc37f23ead4a0a9221667e9073ee0853070db3", ["sugar"], ["python", "tools/pandas_wall.py"]),
    ("numpy-wall", ["core", "python-scientific", "python-test", "solver-z3"], "f96731de7b4eb9a5660a6f8a14fc37f23ead4a0a9221667e9073ee0853070db3", ["sugar"], ["python", "tools/numpy_wall.py"]),
    ("restored-suite-scoreboard", ["core", "python-scientific", "python-test", "solver-z3"], "f96731de7b4eb9a5660a6f8a14fc37f23ead4a0a9221667e9073ee0853070db3", ["sugar"], ["bash", "scripts/test-3809-dod-scoreboard.sh"]),
])
def test_named_tasks_have_published_closures(name, capabilities, digest, binaries, command):
    task = contract.resolve_task(name)
    assert task == {"task": name, "capabilities": capabilities, "binaries": binaries, "command": command}
    environment = contract.resolve_environment("docker:" + ",".join(task["capabilities"]))
    assert environment["capabilities"] == capabilities
    assert environment["image"] == f"ghcr.io/tsavo/sugar-env@sha256:{digest}"


@pytest.mark.parametrize(("capability", "digest"), [
    ("python-scientific", "d8230b980eb505e45273c01d8226bb1e5552e9db27d6e489688aecefd2e0ec38"),
    ("solver-coq", "fe99753e98c05ebb18d5ef1ee8c3475b04ca6caaed176489dd7ad757545782fe"),
    ("java", "3fc127b88e7175268bdfd125e502ffb17a4841f4e4932abc963a0f1a09fb2bb2"),
    ("node", "0cdfae5249ffbd4232f4675230b4e414bfe8de3541db936711e02ff35f2b143a"),
    ("vampire", "d5a3076102ad9e57a0022f52de95f8047df448ba689b1d9afc96d519a35ebe86"),
])
def test_direct_capabilities_have_published_images(capability, digest):
    environment = contract.resolve_environment(f"docker:{capability}")
    assert environment["capabilities"] == ["core", capability]
    assert environment["image"] == f"ghcr.io/tsavo/sugar-env@sha256:{digest}"


def test_python_unit_has_a_distinct_published_test_runtime():
    task = contract.resolve_task("python-unit")
    assert task == {
        "binaries": ["sugar"],
        "capabilities": ["core", "python-test"],
        "command": ["python", "-m", "pytest"],
        "task": "python-unit",
    }
    environment = contract.resolve_environment("docker:" + ",".join(task["capabilities"]))
    assert environment["image"] == "ghcr.io/tsavo/sugar-env@sha256:12ca8a6768630ae70afb37d63a48b5035da365c4c2fe4cd99117ae4327932674"


def test_bpytest_selects_published_python_unit_task():
    wrapper = (ROOT / "bin/bpytest").read_text()
    assert 'exec "$sugarbin" run --host bx --task python-unit -- "$@"' in wrapper


def test_pyright_private_node_is_not_the_node_capability():
    dockerfile = (ROOT / "tools/sugar-build/Dockerfile").read_text()
    node_stage = dockerfile.split("FROM python-lift-closure AS examples-closure", 1)[1]
    assert "ARG NODE_VERSION=" in node_stage
    assert "PYRIGHT_NODE_VERSION" not in node_stage


def test_coq_and_java_capabilities_have_executable_docker_stages():
    dockerfile = (ROOT / "tools/sugar-build/Dockerfile").read_text()
    assert " AS examples-closure" in dockerfile
    assert 'coq="${COQ_DEBIAN_VERSION}"' in dockerfile
    assert 'maven="${MAVEN_DEBIAN_VERSION}"' in dockerfile
    assert "java --version" in dockerfile and "mvn --version" in dockerfile
    assert "coqc --version" in dockerfile


def assert_all_docker_args(dockerfile, expected):
    for argument, value in expected.items():
        occurrences = re.findall(rf"^ARG {re.escape(argument)}=([^\s]+)$", dockerfile, re.MULTILINE)
        assert occurrences, f"missing Docker ARG {argument}"
        assert occurrences == [value] * len(occurrences), (
            f"Docker ARG {argument} drifted: {occurrences} != {value}"
        )


def test_docker_capability_defaults_match_contract_versions():
    tools = contract.tool_versions()
    expected = {
        "RUST_VERSION": tools["rust"],
        "PYTEST_VERSION": tools["pytest"],
        "Z3_DEBIAN_VERSION": tools["z3"] + "-3.1",
        "NUMPY_VERSION": tools["numpy"],
        "PANDAS_VERSION": tools["pandas"],
        "JAVA_VERSION": tools["java"],
        "NODE_VERSION": tools["node"],
        "PNPM_VERSION": tools["pnpm"],
        "VAMPIRE_VERSION": tools["vampire"],
    }
    assert_all_docker_args((ROOT / "tools/sugar-build/Dockerfile").read_text(), expected)


def test_docker_package_revisions_and_archives_are_contract_owned():
    packages = contract.load_contract()["packages"]
    expected = {
        "COQ_DEBIAN_VERSION": "coq_debian",
        "MAVEN_DEBIAN_VERSION": "maven_debian",
        "JAVA_RELEASE_SUFFIX": "java_release_suffix",
        "JAVA_ARCHIVE_SHA256": "java_archive_sha256",
        "NODE_ARCHIVE_SHA256": "node_archive_sha256",
        "VAMPIRE_ARCHIVE_SHA256": "vampire_archive_sha256",
    }
    assert_all_docker_args(
        (ROOT / "tools/sugar-build/Dockerfile").read_text(),
        {argument: packages[package] for argument, package in expected.items()},
    )


def test_second_docker_arg_occurrence_cannot_drift():
    dockerfile = (ROOT / "tools/sugar-build/Dockerfile").read_text()
    declaration = "ARG NODE_VERSION=22.17.1"
    assert dockerfile.count(declaration) == 2
    drifted = "ARG NODE_VERSION=99.0.0".join(dockerfile.rsplit(declaration, 1))
    with pytest.raises(AssertionError, match="NODE_VERSION drifted"):
        assert_all_docker_args(drifted, {"NODE_VERSION": contract.tool_versions()["node"]})


def test_loaded_contract_exactly_matches_capability_tool_owners():
    data = contract.load_contract()
    owners = contract.capability_tool_owners()
    assert set(data["capabilities"]) == set(owners)
    assert set(data["tools"]) == {tool for tools in owners.values() for tool in tools}


def test_named_task_closures_have_explicit_build_targets():
    dockerfile = (ROOT / "tools/sugar-build/Dockerfile").read_text()
    for target in ("python-test", "solver-z3", "python-scientific", "solver-coq", "java", "node", "vampire", "python-lift-closure", "examples-closure"):
        assert f" AS {target}" in dockerfile


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
    path = manifest(tmp_path, "schema=1\n[tools]\n[capabilities.core]\ndepends=['python-test']\n[capabilities.python-test]\ndepends=['core']\n[tasks]\n")
    with pytest.raises(ContractError, match="dependency cycle"):
        contract.resolve_capabilities(["core"], path)


def test_missing_immutable_image_is_loud():
    with pytest.raises(ContractError, match="capability closure has no built image"):
        contract.resolve_environment("docker:java,node")


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
