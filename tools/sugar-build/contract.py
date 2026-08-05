#!/usr/bin/env python3.12
"""Strict resolver for the checked-in Sugar build contract."""

import argparse
import importlib
import json
import re
import sys
import tomllib
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
from sugar_repo_root import resolve_repo_root  # noqa: E402

ROOT = resolve_repo_root()
DEFAULT_CONTRACT = ROOT / "sugar-build.toml"
PUBLISHED_BINARIES = frozenset({"sugar", "sugar-ir-smt-lib"})
TASK_KEYS = frozenset({"capabilities", "binaries", "command", "network"})
TASK_IMAGE_KEYS = frozenset({"preflight", "reference"})
CLOSURE_KEYS = frozenset(
    {
        "adjacent_manifests",
        "artifacts",
        "kind",
        "path",
        "required_commands",
        "retirements",
        "variable",
    }
)
PROFILED_ARTIFACT = re.compile(r"^(debug|release):([A-Za-z0-9._-]+)$")
PACKAGE_TOKEN = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")
IMMUTABLE_IMAGE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
TASK_IMAGE_PREFLIGHTS = frozenset({"managed-entrypoint/v1"})
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
    if set(data) - {
        "schema",
        "tools",
        "packages",
        "capabilities",
        "tasks",
        "images",
        "task-images",
    }:
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
    task_images = data.get("task-images", {})
    if not isinstance(task_images, dict):
        raise ContractError("invalid task-images table")
    for name, task_image in task_images.items():
        if name not in data["tasks"]:
            raise ContractError(f"task image has no task owner: {name}")
        if not isinstance(task_image, dict) or set(task_image) != TASK_IMAGE_KEYS:
            raise ContractError(f"invalid task image definition: {name}")
        reference = task_image.get("reference")
        if not isinstance(reference, str) or IMMUTABLE_IMAGE.fullmatch(reference) is None:
            raise ContractError(f"task image reference is not immutable: {name}")
        preflight = task_image.get("preflight")
        if preflight not in TASK_IMAGE_PREFLIGHTS:
            raise ContractError(f"unknown task image preflight protocol: {name}")
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
    if set(task) not in (TASK_KEYS, TASK_KEYS | {"closure"}):
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
    result = {"binaries": sorted(set(task["binaries"])), "capabilities": _closure(task["capabilities"], data), "command": task["command"], "network": task["network"], "task": name}
    if "closure" in task:
        result["closure"] = _validate_task_closure(name, task["closure"])
    return result


def resolve_task_environment(name, path=DEFAULT_CONTRACT):
    data = load_contract(path)
    task = resolve_task(name, path)
    environment = resolve_environment(
        "docker:" + ",".join(task["capabilities"]), path
    )
    task_image = data.get("task-images", {}).get(name)
    if task_image is None:
        return {
            **environment,
            "preflight": "workspace-wrapper/v1",
            "task": name,
        }
    if "closure" not in task:
        raise ContractError(f"task image has no declared command closure: {name}")
    return {
        **environment,
        "image": task_image["reference"],
        "preflight": task_image["preflight"],
        "task": name,
    }


def _string_list(value, label):
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ContractError(f"invalid task closure {label}")
    if len(value) != len(set(value)):
        raise ContractError(f"duplicate task closure {label}")
    return list(value)


def _validate_task_closure(name, closure):
    if not isinstance(closure, dict) or set(closure) != CLOSURE_KEYS:
        raise ContractError(f"invalid task closure: {name}")
    if closure.get("kind") != "make-roster":
        raise ContractError(f"unsupported task closure kind: {name}")
    for key in ("path", "variable", "retirements"):
        if not isinstance(closure.get(key), str) or not closure[key]:
            raise ContractError(f"invalid task closure {key}: {name}")
    adjacent = _string_list(closure.get("adjacent_manifests"), "adjacent_manifests")
    commands = _string_list(closure.get("required_commands"), "required_commands")
    artifacts = _string_list(closure.get("artifacts"), "artifacts")
    parsed_artifacts = []
    for artifact in artifacts:
        match = PROFILED_ARTIFACT.fullmatch(artifact)
        if match is None:
            raise ContractError(f"invalid profiled task artifact: {artifact}")
        parsed_artifacts.append({"profile": match.group(1), "name": match.group(2)})
    return {
        "adjacent_manifests": adjacent,
        "artifacts": parsed_artifacts,
        "kind": "make-roster",
        "path": closure["path"],
        "required_commands": commands,
        "retirements": closure["retirements"],
        "variable": closure["variable"],
    }


def _run_authority_module():
    tools = ROOT / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    return importlib.import_module("run_authority")


def build_run_authority_testimony(argv, task, image, preflight, plan_json):
    """Canonical run-authority/v1 testimony for one dispatched command.

    ``task`` empty means the command ran ad-hoc: the testimony says so
    explicitly and durably rather than leaving its authority unstated.
    """
    module = _run_authority_module()
    plan = None
    if plan_json:
        try:
            plan = json.loads(plan_json)
        except ValueError as exc:
            raise ContractError(f"managed precondition plan is not JSON: {exc}") from exc
    try:
        return module.build_run_authority(
            argv,
            image=image,
            task=task or None,
            preflight_protocol=preflight or None,
            precondition_plan=plan,
        )
    except module.RunAuthorityRefusal as exc:
        raise ContractError(str(exc)) from exc


def _showcase_authority_module():
    tools = ROOT / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    return importlib.import_module("showcase_scope")


def _toolchain_checks(repo_root, active, manifest_names):
    checks = []
    discovered = {name: [] for name in manifest_names}
    for enrolled_path in active:
        parent = (repo_root / enrolled_path).parent
        for manifest_name in manifest_names:
            manifest_path = parent / manifest_name
            if manifest_path.is_file():
                discovered[manifest_name].append(manifest_path)
    for manifest_name, paths in discovered.items():
        if not paths:
            raise ContractError(f"task closure adjacent manifest absent: {manifest_name}")
        for manifest_path in sorted(set(paths)):
            try:
                data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
                raise ContractError(f"task closure manifest unreadable: {manifest_path}") from exc
            toolchain = data.get("toolchain")
            if not isinstance(toolchain, dict):
                raise ContractError(f"task closure manifest lacks toolchain: {manifest_path}")
            channel = toolchain.get("channel")
            components = toolchain.get("components")
            if not isinstance(channel, str) or not channel:
                raise ContractError(f"task closure manifest lacks channel: {manifest_path}")
            components = _string_list(components, "toolchain components")
            source = manifest_path.relative_to(repo_root).as_posix()
            for component in components:
                checks.append(
                    {
                        "channel": channel,
                        "kind": "toolchain-component",
                        "name": component,
                        "source": source,
                    }
                )
    return checks


def _route_checks(host, task):
    if host != "bx":
        raise ContractError(f"unsupported precondition host: {host}")
    return [
        {"kind": "cache-access", "mode": "read-write", "name": "binary-cache", "source": "route:bx-cache"},
        {"kind": "shelf-access", "mode": "declared", "name": "binary-shelf", "source": "route:bx-shelf"},
        {"kind": "rebuild-lock", "mode": "finite", "name": "binary-rebuild", "source": "route:bx-cache"},
        {"kind": "process-lifetime", "mode": "foreground", "name": "ssh-child", "source": "route:bx-foreground"},
        {"command": task["command"], "kind": "declared-interpreter", "name": task["command"][0], "source": "task.command"},
    ]


def resolve_task_preconditions(name, host, repo_root, path=DEFAULT_CONTRACT):
    task = resolve_task(name, path)
    closure = task.get("closure")
    if closure is None:
        raise ContractError(f"task has no declared command closure: {name}")
    repo_root = Path(repo_root).resolve()
    roster_path = repo_root / closure["path"]
    retirement_path = repo_root / closure["retirements"]
    authority = _showcase_authority_module()
    try:
        enrolled = authority.makefile_showcase_roster(roster_path)
        retirements = authority.load_manifest(retirement_path, enrolled)
    except authority.ScopeRefusal as exc:
        raise ContractError(f"task closure authority refused: {exc}") from exc
    active = [item for item in enrolled if item not in retirements]
    checks = [
        *(
            {
                "kind": "command",
                "name": command,
                "source": "task.closure.required_commands",
            }
            for command in closure["required_commands"]
        ),
        *_toolchain_checks(repo_root, active, closure["adjacent_manifests"]),
    ]
    for artifact in closure["artifacts"]:
        for kind in ("artifact-manifest", "artifact-abi"):
            checks.append(
                {
                    "kind": kind,
                    "name": artifact["name"],
                    "profile": artifact["profile"],
                    "source": "task.closure.artifacts",
                }
            )
    checks.extend(_route_checks(host, task))
    checks.sort(
        key=lambda row: (
            row["kind"], row["source"], row.get("profile", ""), row["name"]
        )
    )
    return {
        "checks": checks,
        "host": host,
        "roster": {
            "active": len(active),
            "enrolled": len(enrolled),
            "retired": len(retirements),
            "source": closure["path"],
        },
        "schemaVersion": 1,
        "task": name,
    }


def resolve_task_image_build(name, repo_root, path=DEFAULT_CONTRACT):
    plan = resolve_task_preconditions(name, "bx", repo_root, path)
    packages = sorted(
        {
            check["name"]
            for check in plan["checks"]
            if check["kind"] == "command"
        }
    )
    invalid_package = next(
        (package for package in packages if PACKAGE_TOKEN.fullmatch(package) is None),
        None,
    )
    if invalid_package is not None:
        raise ContractError(f"managed command has no Debian package identity: {invalid_package}")
    component_checks = [
        check
        for check in plan["checks"]
        if check["kind"] == "toolchain-component"
    ]
    channels = sorted({check["channel"] for check in component_checks})
    if len(channels) != 1:
        raise ContractError(
            "task image requires exactly one Rust toolchain: " + ",".join(channels)
        )
    rust_version = load_contract(path)["tools"]["rust"]
    if channels[0] != rust_version:
        raise ContractError(
            f"task image Rust toolchain {channels[0]} differs from core {rust_version}"
        )
    if PACKAGE_TOKEN.fullmatch(name) is None:
        raise ContractError(f"task image has invalid target identity: {name}")
    return {
        "aptPackages": packages,
        "rustComponents": sorted({check["name"] for check in component_checks}),
        "rustToolchain": channels[0],
        "schemaVersion": 1,
        "target": f"{name}-closure",
        "task": name,
    }


def match_task_command(argv, path=DEFAULT_CONTRACT):
    data = load_contract(path)
    matches = []
    for name in sorted(data["tasks"]):
        task = resolve_task(name, path)
        command = task["command"]
        if list(argv[: len(command)]) == command:
            matches.append(name)
    if len(matches) > 1:
        raise ContractError(f"command closure has multiple owners: {','.join(matches)}")
    return matches[0] if matches else None


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
    task_environment = subparsers.add_parser("resolve-task-environment")
    task_environment.add_argument("task")
    preconditions = subparsers.add_parser("resolve-preconditions")
    preconditions.add_argument("task")
    preconditions.add_argument("--host", required=True)
    preconditions.add_argument("--repo-root", required=True)
    image_build = subparsers.add_parser("resolve-task-image-build")
    image_build.add_argument("task")
    image_build.add_argument("--repo-root", required=True)
    matcher = subparsers.add_parser("match-command")
    matcher.add_argument("argv", nargs=argparse.REMAINDER)
    authority = subparsers.add_parser("run-authority")
    authority.add_argument("--task", default="")
    authority.add_argument("--image", required=True)
    authority.add_argument("--preflight", default="")
    authority.add_argument("--plan-json", default="")
    authority.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.command == "tool-versions": result = tool_versions()
        elif args.command == "resolve-environment": result = resolve_environment(args.environment)
        elif args.command == "resolve-task": result = resolve_task(args.task)
        elif args.command == "resolve-task-environment": result = resolve_task_environment(args.task)
        elif args.command == "resolve-preconditions": result = resolve_task_preconditions(args.task, args.host, args.repo_root)
        elif args.command == "resolve-task-image-build": result = resolve_task_image_build(args.task, args.repo_root)
        elif args.command == "run-authority":
            command_argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
            result = build_run_authority_testimony(
                command_argv, args.task, args.image, args.preflight, args.plan_json
            )
        else:
            argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
            result = {"task": match_task_command(argv)}
    except ContractError as exc:
        print(f"sugar-build: {exc}", file=sys.stderr)
        return 2
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
