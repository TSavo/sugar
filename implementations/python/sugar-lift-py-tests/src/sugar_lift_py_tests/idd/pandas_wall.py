from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Optional, Sequence

from sugar_lift_py_tests.repo_root import RepoRootUnresolved, resolve_repo_root

from .collect_panic_audit import (
    _cached_audit_workspace,
    _resolve_installed_package_path,
    CachedAuditWorkspace,
)
from .command_result import CommandResult
from .recovered_frontier import mint_recovered_frontier
from .numpy_wall import (
    _resolve_sugar_bin,
    _run_subprocess,
    _wall_env,
)

RunCommand = Callable[[list[str], Path, dict[str, str]], CommandResult]
PackagePathResolver = Callable[[str], Path]


@dataclass(frozen=True)
class PandasWallSummary:
    """The wall is the recovered construction audit's frontier counts.

    `sugar lift --report` is not a driver of the Python kit (#7806), so the
    wall has no report body or report failure text to summarize; the
    recovered-audit lane is its only measurement.
    """

    frontier: dict[str, Any]
    mode: Literal["frontier"] = "frontier"

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PandasWallFloors:
    # Recovered-frontier ratchet ceilings (#4489 re-baseline): while the wall
    # is red, independent panic and suppressed-descendant counts may only fall
    # from the pinned baseline. None means the ceiling is unpinned.
    frontier_independent_panics: Optional[int] = None
    frontier_suppressed_descendants: Optional[int] = None

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]) -> "PandasWallFloors":
        floors = data.get("floors", data)
        if not isinstance(floors, Mapping):
            raise TypeError("pandas wall floors must be a mapping")
        ceilings = floors.get("frontier_ceilings")
        if ceilings is not None and not isinstance(ceilings, Mapping):
            raise TypeError("pandas wall frontier_ceilings must be a mapping")
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
        ceilings: dict[str, Any] = {}
        if self.frontier_independent_panics is not None:
            ceilings["independent_panics"] = self.frontier_independent_panics
        if self.frontier_suppressed_descendants is not None:
            ceilings["suppressed_descendants"] = self.frontier_suppressed_descendants
        return {"frontier_ceilings": ceilings} if ceilings else {}


@dataclass(frozen=True)
class PandasWallResult:
    summary: PandasWallSummary
    breaches: tuple[str, ...]
    summary_path: Path
    frontier_path: Path
    workspace_path: Path
    cache_key: str
    cache_hit: bool


def load_pandas_wall_floors(path: Path) -> PandasWallFloors:
    return PandasWallFloors.from_json_dict(json.loads(path.read_text(encoding="utf-8")))


def summarize_pandas_recovered_frontier(
    frontier_json: Mapping[str, Any],
) -> PandasWallSummary:
    if frontier_json.get("kind") != "recovered-construction-audit":
        raise RuntimeError("pandas wall frontier artifact has the wrong kind")
    if frontier_json.get("recoveryOverride") is not True:
        raise RuntimeError("pandas wall frontier artifact lacks recovery override")
    panics = frontier_json.get("panics")
    effects = frontier_json.get("effects")
    suppressed = frontier_json.get("suppressedDescendants")
    if not isinstance(panics, list) or not all(
        isinstance(panic, Mapping) for panic in panics
    ):
        raise RuntimeError("pandas wall frontier panics must be an array of objects")
    if not isinstance(effects, list) or not all(
        isinstance(effect, Mapping) for effect in effects
    ):
        raise RuntimeError("pandas wall frontier effects must be an array of objects")
    if not isinstance(suppressed, list) or not all(
        isinstance(locus, Mapping) for locus in suppressed
    ):
        raise RuntimeError(
            "pandas wall frontier suppressedDescendants must be an array of objects"
        )
    return PandasWallSummary(
        frontier={
            "kind": "recovered-construction-audit",
            "status": frontier_json.get("status", ""),
            "independentPanicCount": len(panics),
            "effectCount": len(effects),
            "suppressedDescendantCount": len(suppressed),
        },
    )


def check_pandas_wall_floors(
    summary: PandasWallSummary, floors: PandasWallFloors
) -> list[str]:
    breaches: list[str] = []
    independent_panics = summary.frontier.get("independentPanicCount", 0)
    # #4489 recovered-audit stage: when ceilings are pinned, non-zero panics
    # are the measured residue (status=failed is expected). Absolute red only
    # applies when no ceiling is pinned.
    has_ceilings = (
        floors.frontier_independent_panics is not None
        or floors.frontier_suppressed_descendants is not None
    )
    if (
        not has_ceilings
        and isinstance(independent_panics, int)
        and independent_panics > 0
    ):
        breaches.append(
            "recovered construction audit is red: "
            f"independent_panics={independent_panics}"
        )
    # #4489 re-baseline ratchet: frontier counts may only fall from the pin.
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


def build_pandas_wall(
    *,
    root: Path,
    output_dir: Path,
    floors: PandasWallFloors,
    package_path_resolver: Optional[PackagePathResolver] = None,
    run_command: Optional[RunCommand] = None,
    profile: str = "release",
    cache_root: Optional[Path] = None,
) -> PandasWallResult:
    root = root.resolve()
    output_dir = output_dir.resolve()
    runner = run_command or _run_subprocess
    resolver = package_path_resolver or _resolve_installed_package_path

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    sugar_bin = _resolve_sugar_bin(root, profile, runner)
    package_path = resolver("pandas").resolve()
    cached = _cached_workspace(package_path, root, cache_root)
    workspace = cached.workspace
    env = _wall_env(root, sugar_bin, workspace)

    workspace_receipt = output_dir / "workspace.json"
    workspace_receipt.write_text(
        json.dumps(
            {
                "kind": "pandas-wall-audit-workspace",
                "cacheHit": cached.hit,
                "cacheKey": cached.cache_key,
                "workspace": os.fspath(workspace),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    frontier_json = mint_recovered_frontier(
        label="pandas wall",
        sugar_bin=sugar_bin,
        workspace=workspace,
        root=root,
        env=env,
        output_dir=output_dir,
        runner=runner,
    )
    summary = summarize_pandas_recovered_frontier(frontier_json)
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary.to_json_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return PandasWallResult(
        summary=summary,
        breaches=tuple(check_pandas_wall_floors(summary, floors)),
        summary_path=summary_path,
        frontier_path=output_dir / "frontier.json",
        workspace_path=workspace,
        cache_key=cached.cache_key,
        cache_hit=cached.hit,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Build and ratchet-check the installed pandas recovered frontier."
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
    output_dir = args.output_dir or (root / ".sugar" / "pandas-wall")
    floors_path = args.floors or (root / "tools" / "pandas-wall-floors.json")
    result = build_pandas_wall(
        root=root,
        output_dir=output_dir,
        floors=load_pandas_wall_floors(floors_path),
        profile=args.profile,
    )
    print(json.dumps(result.summary.to_json_dict(), indent=2, sort_keys=True))
    if result.breaches:
        print("pandas wall ratchet breached:", file=sys.stderr)
        for breach in result.breaches:
            print(f"- {breach}", file=sys.stderr)
        print(f"summary: {result.summary_path}", file=sys.stderr)
        print(f"frontier: {result.frontier_path}", file=sys.stderr)
        return 1
    print(f"pandas wall ratchet PASS: {result.summary_path}", file=sys.stderr)
    return 0


def _int_field(data: Mapping[str, Any], field: str) -> int:
    value = data.get(field)
    if not isinstance(value, int) or value < 0:
        raise TypeError(f"pandas wall floor `{field}` must be a non-negative integer")
    return value


def _cached_workspace(
    package_path: Path, root: Path, cache_root: Optional[Path]
) -> CachedAuditWorkspace:
    if cache_root is None:
        return _cached_audit_workspace(package_path, root)
    previous = os.environ.get("SUGAR_PANIC_AUDIT_WORKSPACE_CACHE_DIR")
    os.environ["SUGAR_PANIC_AUDIT_WORKSPACE_CACHE_DIR"] = os.fspath(cache_root)
    try:
        return _cached_audit_workspace(package_path, root)
    finally:
        if previous is None:
            os.environ.pop("SUGAR_PANIC_AUDIT_WORKSPACE_CACHE_DIR", None)
        else:
            os.environ["SUGAR_PANIC_AUDIT_WORKSPACE_CACHE_DIR"] = previous
