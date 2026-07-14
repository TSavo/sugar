#!/usr/bin/env python3.12
"""Strict resolver for the checked-in Sugar build contract."""

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "sugar-build.toml"
PUBLISHED_BINARIES = frozenset({"sugar", "sugar-ir-smt-lib"})
IMMUTABLE_IMAGE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
EXACT_TOOL_VERSION = {
    "rust": re.compile(r"\d+\.\d+\.\d+"),
    "cargo": re.compile(r"\d+\.\d+\.\d+"),
    "python": re.compile(r"\d+\.\d+\.\d+"),
    "black": re.compile(r"\d+\.\d+\.\d+"),
    "pyright": re.compile(r"\d+\.\d+\.\d+"),
    "b3sum": re.compile(r"\d+\.\d+\.\d+"),
    "pytest": re.compile(r"\d+\.\d+\.\d+"),
    "z3": re.compile(r"\d+\.\d+\.\d+"),
    "coq": re.compile(r"\d+\.\d+\.\d+"),
    "numpy": re.compile(r"\d+\.\d+\.\d+"),
    "pandas": re.compile(r"\d+\.\d+\.\d+"),
    "java": re.compile(r"\d+\.\d+\.\d+"),
    "maven": re.compile(r"\d+\.\d+\.\d+"),
    "node": re.compile(r"\d+\.\d+\.\d+"),
    "pnpm": re.compile(r"\d+\.\d+\.\d+"),
    "vampire": re.compile(r"\d+\.\d+\.\d+"),
}
CAPABILITY_TOOL_OWNERS = {
    "core": ("black", "b3sum", "cargo", "pyright", "python", "rust"),
    "java": ("java", "maven"),
    "node": ("node", "pnpm"),
    "python-scientific": ("numpy", "pandas"),
    "python-test": ("pytest",),
    "solver-coq": ("coq",),
    "solver-z3": ("z3",),
    "vampire": ("vampire",),
}


class ContractError(ValueError):
    pass


def load_contract(path=DEFAULT_CONTRACT):
    try:
        with Path(path).open("rb") as stream:
            data = tomllib.load(stream)
    except tomllib.TOMLDecodeError as exc:
        message = str(exc)
        if "overwrite" in message.lower():
            message = f"duplicate definition: {message}"
        raise ContractError(message) from exc
    if set(data) - {"schema", "tools", "packages", "capabilities", "tasks", "images"}:
        raise ContractError("unknown top-level contract key")
    if data.get("schema") != 1:
        raise ContractError("unsupported contract schema")
    for section in ("tools", "capabilities", "tasks"):
        if not isinstance(data.get(section), dict):
            raise ContractError(f"missing {section} table")
    tools = data["tools"]
    for name, version in tools.items():
        pattern = EXACT_TOOL_VERSION.get(name)
        if pattern is None:
            raise ContractError(f"unknown tool version owner: {name}")
        if not isinstance(version, str) or pattern.fullmatch(version) is None:
            raise ContractError(f"non-exact tool version: {name}")
    if "packages" in data and not isinstance(data["packages"], dict):
        raise ContractError("invalid packages table")
    declared_capabilities = set(data["capabilities"])
    owner_capabilities = set(CAPABILITY_TOOL_OWNERS)
    if not declared_capabilities <= owner_capabilities:
        missing = sorted(declared_capabilities - owner_capabilities)[0]
        raise ContractError(f"capability tool owner mismatch: {missing}")
    owned_tools = {tool for owners in CAPABILITY_TOOL_OWNERS.values() for tool in owners}
    if not set(tools) <= owned_tools:
        missing = sorted(set(tools) - owned_tools)[0]
        raise ContractError(f"tool capability owner mismatch: {missing}")
    return data


def _closure(names, data):
    capabilities = data["capabilities"]
    visiting, visited = set(), set()

    def visit(name):
        if name not in capabilities:
            raise ContractError(f"unknown capability: {name}")
        if name in visiting:
            raise ContractError(f"dependency cycle at capability: {name}")
        if name in visited:
            return
        definition = capabilities[name]
        if set(definition) != {"depends"} or not isinstance(definition["depends"], list):
            raise ContractError(f"invalid capability definition: {name}")
        visiting.add(name)
        for dependency in definition["depends"]:
            if not isinstance(dependency, str):
                raise ContractError(f"invalid capability dependency: {name}")
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for name in names:
        visit(name)
    return sorted(visited)


def resolve_capabilities(names, path=DEFAULT_CONTRACT):
    data = load_contract(path)
    return _closure(names, data)


def resolve_environment(environment, path=DEFAULT_CONTRACT):
    if environment == "docker":
        requested = []
    elif environment.startswith("docker:"):
        requested = environment.removeprefix("docker:").split(",")
    else:
        raise ContractError(f"unsupported environment: {environment}")
    if not requested or any(not name for name in requested):
        raise ContractError("empty capability")
    data = load_contract(path)
    capabilities = _closure(requested, data)
    image_key = ",".join(capabilities)
    image = data.get("images", {}).get(image_key, {})
    reference = image.get("reference") if isinstance(image, dict) else None
    if not isinstance(reference, str) or not IMMUTABLE_IMAGE.fullmatch(reference):
        raise ContractError(f"capability closure has no built image: {image_key}")
    return {"capabilities": capabilities, "image": reference, "tools": dict(sorted(data["tools"].items()))}


def resolve_task(name, path=DEFAULT_CONTRACT):
    data = load_contract(path)
    task = data["tasks"].get(name)
    if task is None:
        raise ContractError(f"unknown task: {name}")
    if set(task) != {"capabilities", "binaries", "command", "network"}:
        raise ContractError(f"invalid task definition: {name}")
    for key in ("capabilities", "binaries", "command"):
        if not isinstance(task[key], list) or any(not isinstance(item, str) for item in task[key]):
            raise ContractError(f"invalid task {key}: {name}")
    if not task["command"]:
        raise ContractError(f"empty command array for task: {name}")
    if task["network"] not in ("none", "required"):
        raise ContractError(f"invalid task network policy: {name}")
    unknown = sorted(set(task["binaries"]) - PUBLISHED_BINARIES)
    if unknown:
        raise ContractError(f"unknown task binary: {unknown[0]}")
    return {"binaries": sorted(set(task["binaries"])), "capabilities": _closure(task["capabilities"], data), "command": task["command"], "network": task["network"], "task": name}


def tool_versions(path=DEFAULT_CONTRACT):
    return dict(sorted(load_contract(path)["tools"].items()))


def capability_tool_owners():
    return dict(CAPABILITY_TOOL_OWNERS)


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def main(argv=None):
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("tool-versions")
    environment = subparsers.add_parser("resolve-environment")
    environment.add_argument("environment")
    task = subparsers.add_parser("resolve-task")
    task.add_argument("task")
    args = parser.parse_args(argv)
    try:
        if args.command == "tool-versions": result = tool_versions()
        elif args.command == "resolve-environment": result = resolve_environment(args.environment)
        else: result = resolve_task(args.task)
    except ContractError as exc:
        print(f"sugar-build: {exc}", file=sys.stderr)
        return 2
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
