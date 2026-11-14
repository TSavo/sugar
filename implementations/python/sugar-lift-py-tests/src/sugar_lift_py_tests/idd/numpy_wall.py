from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Optional, Sequence

from sugar_lift_py_tests.repo_root import RepoRootUnresolved, resolve_repo_root

from .collect_panic_audit import (
    _prepare_audit_workspace,
    _resolve_installed_package_path,
)
from .command_result import CommandResult
from .recovered_frontier import mint_recovered_frontier

RunCommand = Callable[[list[str], Path, dict[str, str]], CommandResult]
PackagePathResolver = Callable[[str], Path]


@dataclass(frozen=True)
class NumpyWallSummary:
    """The wall is the recovered construction audit's frontier counts.

    `sugar lift --report` is not a driver of the Python kit (#7806), so the
    wall has no report body to summarize; the recovered-audit lane is its
    only measurement.
    """

    frontier: dict[str, Any] = field(default_factory=dict)
    mode: Literal["frontier"] = "frontier"

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NumpyWallFloors:
    # Recovered-frontier ratchet ceilings (#4489 re-baseline): while the wall
    # is red, independent panic and suppressed-descendant counts may only fall
    # from the pinned baseline. None means the ceiling is unpinned.
    frontier_independent_panics: Optional[int] = None
    frontier_suppressed_descendants: Optional[int] = None

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]) -> "NumpyWallFloors":
        floors = data.get("floors", data)
        if not isinstance(floors, Mapping):
            raise TypeError("numpy wall floors must be a mapping")
        ceilings = floors.get("frontier_ceilings")
        if ceilings is not None and not isinstance(ceilings, Mapping):
            raise TypeError("numpy wall frontier_ceilings must be a mapping")
        return cls(
            frontier_independent_panics=(
                None if ceilings is None else _int_field(ceilings, "independent_panics")
            ),
            frontier_suppressed_descendants=(
                None
                if ceilings is None
                else _int_field(ceilings, "suppressed_descendants")
            ),
        )

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NumpyWallResult:
    summary: NumpyWallSummary
    breaches: tuple[str, ...]
    summary_path: Path
    frontier_path: Path


def load_wall_floors(path: Path) -> NumpyWallFloors:
    return NumpyWallFloors.from_json_dict(json.loads(path.read_text(encoding="utf-8")))


def check_frontier_ceilings(
    summary: NumpyWallSummary, floors: NumpyWallFloors
) -> list[str]:
    """Ratchet the recovered frontier: counts may only fall from the pin."""
    breaches: list[str] = []
    for label, key, ceiling in (
        (
            "independent_panics",
            "independentPanicCount",
            floors.frontier_independent_panics,
        ),
        (
            "suppressed_descendants",
            "suppressedDescendantCount",
            floors.frontier_suppressed_descendants,
        ),
    ):
        if ceiling is None:
            continue
        observed = summary.frontier.get(key, 0)
        if isinstance(observed, int) and observed > ceiling:
            breaches.append(
                f"frontier {label} ceiling breached: observed={observed} "
                f"ceiling={ceiling} delta={observed - ceiling}"
            )
    return breaches


def build_numpy_wall(
    *,
    root: Path,
    output_dir: Path,
    floors: NumpyWallFloors,
    package_path_resolver: Optional[PackagePathResolver] = None,
    run_command: Optional[RunCommand] = None,
    profile: str = "release",
) -> NumpyWallResult:
    root = root.resolve()
    output_dir = output_dir.resolve()
    runner = run_command or _run_subprocess
    resolver = package_path_resolver or _resolve_installed_package_path

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    sugar_bin = _resolve_sugar_bin(root, profile, runner)
    package_path = resolver("numpy").resolve()
    workspace = output_dir / "workspace" / package_path.name
    _prepare_audit_workspace(package_path, root, workspace, audit_only=False)
    env = _wall_env(root, sugar_bin, workspace)

    frontier_json = mint_recovered_frontier(
        label="numpy wall",
        sugar_bin=sugar_bin,
        workspace=workspace,
        root=root,
        env=env,
        output_dir=output_dir,
        runner=runner,
    )
    summary = NumpyWallSummary(
        frontier={
            "kind": frontier_json["kind"],
            "independentPanicCount": len(frontier_json["panics"]),
            "suppressedDescendantCount": len(frontier_json["suppressedDescendants"]),
            "effectCount": len(frontier_json["effects"]),
        },
    )
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary.to_json_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    red = (
        ("recovered construction audit is red",)
        if summary.frontier["independentPanicCount"] > 0
        else ()
    )
    return NumpyWallResult(
        summary=summary,
        breaches=(*red, *check_frontier_ceilings(summary, floors)),
        summary_path=summary_path,
        frontier_path=output_dir / "frontier.json",
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Build and ratchet-check the installed NumPy recovered frontier."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="repository root (default: resolve via sugar-build.toml door)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="directory for frontier.json and summary.json",
    )
    parser.add_argument(
        "--floors",
        type=Path,
        default=None,
        help="ratchet ceiling JSON fixture",
    )
    parser.add_argument(
        "--profile",
        choices=("debug", "release"),
        default="release",
        help="sugarbin profile to resolve",
    )
    args = parser.parse_args(argv)

    try:
        root = args.root.resolve() if args.root is not None else resolve_repo_root()
    except RepoRootUnresolved as error:
        parser.error(str(error))
    output_dir = args.output_dir or (root / ".sugar" / "numpy-wall")
    floors_path = args.floors or (root / "tools" / "numpy-wall-floors.json")
    result = build_numpy_wall(
        root=root,
        output_dir=output_dir,
        floors=load_wall_floors(floors_path),
        profile=args.profile,
    )
    print(json.dumps(result.summary.to_json_dict(), indent=2, sort_keys=True))
    if result.breaches:
        print("numpy wall ratchet breached:", file=sys.stderr)
        for breach in result.breaches:
            print(f"- {breach}", file=sys.stderr)
        print(f"summary: {result.summary_path}", file=sys.stderr)
        print(f"frontier: {result.frontier_path}", file=sys.stderr)
        # A red recovered frontier is diagnostic (exit 0) unless the frontier
        # ratchet ceilings are breached: counts may only fall from the pin.
        return (
            1 if any("ceiling breached" in breach for breach in result.breaches) else 0
        )
    print(f"numpy wall ratchet PASS: {result.summary_path}", file=sys.stderr)
    return 0


def _int_field(data: Mapping[str, Any], field: str) -> int:
    value = data.get(field)
    if not isinstance(value, int) or value < 0:
        raise TypeError(f"numpy wall floor `{field}` must be a non-negative integer")
    return value


def _resolve_sugar_bin(root: Path, profile: str, runner: RunCommand) -> Path:
    if os.name == "nt":
        # The POSIX broker is not a Windows executable.  Keep wall acquisition
        # on the same platform-aware route used by the witness harness so
        # Battleaxe builds locally and other Windows hosts use their broker.
        from sugar_lift_py_tests.sugar_binary import resolve_sugar_binary

        return resolve_sugar_binary(profile=profile).resolve()

    resolver_env = os.environ.copy()
    # A wall is evidence about this checkout. Runner services may carry an
    # ambient handoff from an earlier job, but the stamp-addressed broker must
    # own binary selection here; otherwise current Python can speak to a stale
    # Rust wire schema and the resulting wall has no source provenance.
    resolver_env.pop("SUGAR_BIN", None)
    resolver_env.pop("SUGAR_BINARY_DIR", None)
    result = runner(
        [str(root / "bin/sugarbin"), "--profile", profile], root, resolver_env
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"bin/sugarbin --profile {profile} failed exit={result.returncode}: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    sugar = Path(result.stdout.strip().splitlines()[-1]).resolve()
    return sugar


def _wall_env(
    root: Path, sugar_bin: Path, workspace: Path | None = None
) -> dict[str, str]:
    # Hermetic pool: when a staged workspace is known, SUGAR_HOME is the one door
    # so ambient checkout/.sugar components cannot poison the wall lift.
    if workspace is not None:
        from sugar_lift_py_tests.witness_harness import hermetic_sugar_env

        env = hermetic_sugar_env(workspace)
    else:
        env = os.environ.copy()
        env.pop("SUGAR_COMPONENT_PATH", None)
    env["SUGAR_BIN"] = os.fspath(sugar_bin)
    source_paths = [
        root / "implementations/python/sugar-lift-py-tests/src",
        root / "implementations/python/sugar-lift-python-source/src",
    ]
    existing = env.get("PYTHONPATH")
    if existing:
        source_paths.append(Path(existing))
    env["PYTHONPATH"] = os.pathsep.join(str(path) for path in source_paths)
    return env


def _run_subprocess(
    command: list[str], cwd: Path, env: dict[str, str]
) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return CommandResult(127, "", f"unable to execute {command[0]}: {exc}")
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)
