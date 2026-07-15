from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Optional, Sequence

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
    green: int
    red_reasoned: int
    red_bare: int
    contracts: int
    pre_bearing: int
    call_edges_resolved: int
    implications: int

    mode: Literal["report", "frontier"] = "report"
    frontier: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NumpyWallFloors:
    green: int
    pre_bearing: int
    implications: int

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]) -> "NumpyWallFloors":
        floors = data.get("floors", data)
        if not isinstance(floors, Mapping):
            raise TypeError("numpy wall floors must be a mapping")
        return cls(
            green=_int_field(floors, "green"),
            pre_bearing=_int_field(floors, "pre_bearing"),
            implications=_int_field(floors, "implications"),
        )

    def to_json_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class NumpyWallResult:
    summary: NumpyWallSummary
    breaches: tuple[str, ...]
    report_path: Optional[Path]
    summary_path: Path
    frontier_path: Optional[Path]


def load_wall_floors(path: Path) -> NumpyWallFloors:
    return NumpyWallFloors.from_json_dict(json.loads(path.read_text(encoding="utf-8")))


def summarize_numpy_wall(report_json: Mapping[str, Any]) -> NumpyWallSummary:
    """Summarize a wall from `sugar lift --report --json`'s `lineAccounting`
    (implementations/rust/sugar-cli/src/line_accounting.rs), never the
    `--visual` ANSI render -- Criterion 14 (#3706) retires that scrape.

    green         -- lines classified `warrant` or `support`: proofir-bearing
                      or affirmatively inert, the total non-effect coverage.
    red_reasoned  -- lines classified `effect`: a named typed effect with
                      grounds anchored to the line.
    red_bare      -- effect lines with no grounds. `line_accounting`
                      always attaches grounds (the refusal reason, or the
                      callee name as a fallback), so this is 0 by
                      construction; kept as a field so the invariant stays
                      visible and the floor check below still fires if that
                      construction is ever broken.
    """
    entries = _json_array(report_json, "lineAccounting")
    green = sum(1 for e in entries if e.get("class") in ("warrant", "support"))
    red_reasoned = sum(
        1
        for e in entries
        if e.get("class") == "effect" and str(e.get("grounds") or "").strip()
    )
    red_bare = sum(
        1
        for e in entries
        if e.get("class") == "effect" and not str(e.get("grounds") or "").strip()
    )
    contracts = _json_array(report_json, "contracts")
    call_edges = _json_array(report_json, "callEdges")
    return NumpyWallSummary(
        mode="report",
        green=green,
        red_reasoned=red_reasoned,
        red_bare=red_bare,
        contracts=len(contracts),
        pre_bearing=sum(
            1 for contract in contracts if _contract_has_pre_slot(contract)
        ),
        call_edges_resolved=sum(
            1 for edge in call_edges if _resolved_regular_call_edge(edge)
        ),
        implications=sum(1 for edge in call_edges if _implication_edge(edge)),
        frontier={},
    )


def check_wall_floors(summary: NumpyWallSummary, floors: NumpyWallFloors) -> list[str]:
    breaches: list[str] = []
    if summary.red_bare != 0:
        breaches.append(
            "red_bare invariant breached: "
            f"observed={summary.red_bare} expected=0; "
            "replacement=thread a typed effect/gap reason into every red wall row"
        )
    for field in ("green", "pre_bearing", "implications"):
        observed = getattr(summary, field)
        floor = getattr(floors, field)
        if observed < floor:
            breaches.append(
                f"{field} floor breached: observed={observed} "
                f"floor={floor} delta={observed - floor}"
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
    mode: Literal["report", "frontier"] = "frontier",
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

    # Criterion 14 (#3706): the wall consumes `--report --json`'s
    # `lineAccounting` only. It no longer runs `--report --visual` at all --
    # that ANSI render is a human-facing product, not eligible evidence, and
    # scraping it here is exactly the practice this criterion retires.
    report_result = runner(
        [os.fspath(sugar_bin), "lift", "--report", "--json", str(workspace)],
        root,
        env,
    )
    report_path = output_dir / "report.json"
    _write_command_receipt(report_path, report_result)
    if report_result.returncode != 0:
        if mode == "frontier":
            report_path.unlink(missing_ok=True)
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
                mode="frontier",
                green=0,
                red_reasoned=0,
                red_bare=0,
                contracts=0,
                pre_bearing=0,
                call_edges_resolved=0,
                implications=0,
                frontier={
                    "kind": frontier_json["kind"],
                    "independentPanicCount": len(frontier_json["panics"]),
                    "suppressedDescendantCount": len(
                        frontier_json["suppressedDescendants"]
                    ),
                    "effectCount": len(frontier_json["effects"]),
                },
            )
            summary_path = output_dir / "summary.json"
            summary_path.write_text(
                json.dumps(summary.to_json_dict(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return NumpyWallResult(
                summary=summary,
                breaches=("recovered construction audit is red",),
                report_path=None,
                summary_path=summary_path,
                frontier_path=output_dir / "frontier.json",
            )
        raise RuntimeError(
            "numpy wall json report failed "
            f"exit={report_result.returncode}; see {report_path}"
        )
    try:
        report_json = json.loads(report_result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"numpy wall json report was not valid JSON: {exc}") from exc
    if not isinstance(report_json, Mapping):
        raise RuntimeError("numpy wall json report must be a JSON object")

    summary = summarize_numpy_wall(report_json)
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary.to_json_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    breaches = tuple(check_wall_floors(summary, floors))
    return NumpyWallResult(
        summary=summary,
        breaches=breaches,
        report_path=report_path,
        summary_path=summary_path,
        frontier_path=None,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Build and ratchet-check the installed NumPy lift wall."
    )
    parser.add_argument(
        "--mode",
        choices=("report", "frontier"),
        default="frontier",
        help="strict report or recovered diagnostic frontier",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[5],
        help="repository root",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="directory for wall.txt and summary.json",
    )
    parser.add_argument(
        "--floors",
        type=Path,
        default=None,
        help="ratchet floor JSON fixture",
    )
    parser.add_argument(
        "--profile",
        choices=("debug", "release"),
        default="release",
        help="sugarbin profile to resolve",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    output_dir = args.output_dir or (root / ".sugar" / "numpy-wall")
    floors_path = args.floors or (root / "tools" / "numpy-wall-floors.json")
    result = build_numpy_wall(
        root=root,
        output_dir=output_dir,
        floors=load_wall_floors(floors_path),
        profile=args.profile,
        mode=args.mode,
    )
    print(json.dumps(result.summary.to_json_dict(), indent=2, sort_keys=True))
    if result.breaches:
        print("numpy wall ratchet breached:", file=sys.stderr)
        for breach in result.breaches:
            print(f"- {breach}", file=sys.stderr)
        print(f"summary: {result.summary_path}", file=sys.stderr)
        if result.report_path is not None:
            print(f"report: {result.report_path}", file=sys.stderr)
        if result.frontier_path is not None:
            print(f"frontier: {result.frontier_path}", file=sys.stderr)
        return 0 if result.summary.mode == "frontier" else 1
    print(f"numpy wall ratchet PASS: {result.summary_path}", file=sys.stderr)
    return 0


def _json_array(
    report_json: Mapping[str, Any], field: str
) -> tuple[Mapping[str, Any], ...]:
    value = report_json.get(field)
    if value is None:
        return ()
    if not isinstance(value, list):
        raise TypeError(f"numpy wall report field `{field}` must be a JSON array")
    rows: list[Mapping[str, Any]] = []
    for index, row in enumerate(value):
        if not isinstance(row, Mapping):
            raise TypeError(
                f"numpy wall report field `{field}` row {index} must be a JSON object"
            )
        rows.append(row)
    return tuple(rows)


def _contract_has_pre_slot(contract: Mapping[str, Any]) -> bool:
    pre = contract.get("pre")
    if pre is None:
        return False
    if isinstance(pre, str):
        return bool(pre.strip())
    if isinstance(pre, (list, dict)):
        return bool(pre)
    return True


def _resolved_regular_call_edge(edge: Mapping[str, Any]) -> bool:
    if edge.get("kind") != "call-edge":
        return False
    target_cid = edge.get("targetContractCid")
    return isinstance(target_cid, str) and bool(target_cid.strip())


def _implication_edge(edge: Mapping[str, Any]) -> bool:
    return edge.get("kind") == "implication"


def _int_field(data: Mapping[str, Any], field: str) -> int:
    value = data.get(field)
    if not isinstance(value, int) or value < 0:
        raise TypeError(f"numpy wall floor `{field}` must be a non-negative integer")
    return value


def _resolve_sugar_bin(root: Path, profile: str, runner: RunCommand) -> Path:
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


def _write_command_receipt(path: Path, result: CommandResult) -> None:
    if result.returncode == 0:
        path.write_text(result.stdout, encoding="utf-8")
        return
    path.write_text(
        result.stdout
        + ("\n" if result.stdout and result.stderr else "")
        + result.stderr,
        encoding="utf-8",
    )
