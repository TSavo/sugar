from __future__ import annotations

import json
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Optional, Sequence

from .collect_panic_audit import (
    _cached_audit_workspace,
    _prepare_audit_workspace,
    _resolve_installed_package_path,
    CachedAuditWorkspace,
)
from .command_result import CommandResult
from .numpy_wall import (
    _resolve_sugar_bin,
    _run_subprocess,
    _wall_env,
    _write_command_receipt,
    summarize_numpy_wall,
)

RunCommand = Callable[[list[str], Path, dict[str, str]], CommandResult]
PackagePathResolver = Callable[[str], Path]
PandasWallMode = Literal["construction-gaps", "frontier", "complete"]

_GAP_BUCKETS = ("Constructor", "Floor", "ProofIR", "Sugar")
_RPC_ERROR_MARKER = "lift plugin returned error:"
_FRONTIER_FIELD = re.compile(
    r"(crime|owner|shape|replacement|blame)=([^;]+?)(?=;\s(?:crime|owner|shape|replacement|blame)=|$)"
)


@dataclass(frozen=True)
class PandasWallSummary:
    mode: PandasWallMode
    gaps_total: int
    gaps_by_bucket: dict[str, int]
    gap_templates: dict[str, int]
    frontier: dict[str, str]
    green: int
    red_reasoned: int
    red_bare: int
    contracts: int
    pre_bearing: int
    call_edges_resolved: int
    implications: int

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PandasWallFloors:
    mode: PandasWallMode
    gaps_total_ceiling: int
    gap_template_ceilings: dict[str, int]
    green: int
    pre_bearing: int
    implications: int
    frontier_needle: str
    frontier_owner: str
    frontier_shape: str

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]) -> "PandasWallFloors":
        floors = data.get("floors", data)
        if not isinstance(floors, Mapping):
            raise TypeError("pandas wall floors must be a mapping")
        mode = _mode_field(floors)
        construction = floors.get("construction_gaps", {})
        if not isinstance(construction, Mapping):
            raise TypeError("pandas wall construction_gaps must be a mapping")
        complete = floors.get("complete_floors", floors)
        if not isinstance(complete, Mapping):
            raise TypeError("pandas wall complete_floors must be a mapping")
        frontier = floors.get("frontier", {})
        if not isinstance(frontier, Mapping):
            raise TypeError("pandas wall frontier must be a mapping")
        templates = construction.get("templates", {})
        if not isinstance(templates, Mapping):
            raise TypeError("pandas wall gap templates must be a mapping")
        return cls(
            mode=mode,
            gaps_total_ceiling=_int_field(construction, "total_ceiling"),
            gap_template_ceilings={
                str(key): _int_value(value, f"gap template `{key}`")
                for key, value in templates.items()
            },
            green=_int_field(complete, "green"),
            pre_bearing=_int_field(complete, "pre_bearing"),
            implications=_int_field(complete, "implications"),
            frontier_needle=str(frontier.get("message_needle", "")),
            frontier_owner=str(frontier.get("owner", "")),
            frontier_shape=str(frontier.get("shape", "")),
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "construction_gaps": {
                "total_ceiling": self.gaps_total_ceiling,
                "templates": dict(sorted(self.gap_template_ceilings.items())),
            },
            "complete_floors": {
                "green": self.green,
                "pre_bearing": self.pre_bearing,
                "implications": self.implications,
            },
            "frontier": {
                "message_needle": self.frontier_needle,
                "owner": self.frontier_owner,
                "shape": self.frontier_shape,
            },
        }


@dataclass(frozen=True)
class PandasWallResult:
    summary: PandasWallSummary
    breaches: tuple[str, ...]
    visual_path: Path
    report_path: Optional[Path]
    summary_path: Path
    gaps_path: Optional[Path]
    frontier_path: Optional[Path]
    workspace_path: Path
    cache_key: str
    cache_hit: bool


def load_pandas_wall_floors(path: Path) -> PandasWallFloors:
    return PandasWallFloors.from_json_dict(json.loads(path.read_text(encoding="utf-8")))


def summarize_pandas_construction_gaps(output_text: str) -> PandasWallSummary:
    gap_rows = _structured_gap_rows(output_text)
    by_bucket = {bucket: 0 for bucket in _GAP_BUCKETS}
    templates: dict[str, int] = {}
    for row in gap_rows:
        bucket = _gap_bucket(row)
        if bucket not in by_bucket:
            continue
        by_bucket[bucket] += 1
        template = _gap_template(row, bucket)
        templates[template] = templates.get(template, 0) + 1
    return PandasWallSummary(
        mode="construction-gaps",
        gaps_total=sum(by_bucket.values()),
        gaps_by_bucket=dict(sorted(by_bucket.items())),
        gap_templates=dict(sorted(templates.items())),
        frontier={},
        green=0,
        red_reasoned=0,
        red_bare=0,
        contracts=0,
        pre_bearing=0,
        call_edges_resolved=0,
        implications=0,
    )


def summarize_pandas_frontier_error(output_text: str) -> Optional[PandasWallSummary]:
    frontier = _frontier_error(output_text)
    if frontier is None:
        return None
    return PandasWallSummary(
        mode="frontier",
        gaps_total=0,
        gaps_by_bucket={bucket: 0 for bucket in _GAP_BUCKETS},
        gap_templates={},
        frontier=frontier,
        green=0,
        red_reasoned=0,
        red_bare=0,
        contracts=0,
        pre_bearing=0,
        call_edges_resolved=0,
        implications=0,
    )


def summarize_pandas_completed_wall(
    report_json: Mapping[str, Any],
) -> PandasWallSummary:
    # Criterion 14 (#3706): green/red_reasoned/red_bare come from the JSON
    # report's `lineAccounting`, never a scrape of the `--visual` render.
    summary = summarize_numpy_wall(report_json)
    return PandasWallSummary(
        mode="complete",
        gaps_total=0,
        gaps_by_bucket={bucket: 0 for bucket in _GAP_BUCKETS},
        gap_templates={},
        frontier={},
        green=summary.green,
        red_reasoned=summary.red_reasoned,
        red_bare=summary.red_bare,
        contracts=summary.contracts,
        pre_bearing=summary.pre_bearing,
        call_edges_resolved=summary.call_edges_resolved,
        implications=summary.implications,
    )


def check_pandas_wall_floors(
    summary: PandasWallSummary, floors: PandasWallFloors
) -> list[str]:
    if summary.mode == "construction-gaps":
        return _check_construction_gap_floors(summary, floors)
    if summary.mode == "frontier":
        return _check_frontier_floors(summary, floors)
    return _check_completed_wall_floors(summary, floors)


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
    cached = _workspace_for_mode(package_path, root, output_dir, floors, cache_root)
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

    visual_result = runner(
        [os.fspath(sugar_bin), "lift", "--report", "--visual", str(workspace)],
        root,
        env,
    )
    visual_path = output_dir / "wall.txt"
    _write_command_receipt(visual_path, visual_result)
    if visual_result.returncode != 0:
        summary = summarize_pandas_construction_gaps(_combined_output(visual_result))
        if summary.gaps_total == 0:
            frontier_summary = summarize_pandas_frontier_error(
                _combined_output(visual_result)
            )
            if frontier_summary is None:
                raise RuntimeError(
                    "pandas wall visual render failed without structured "
                    "construction gaps or a named frontier "
                    f"exit={visual_result.returncode}; see {visual_path}"
                )
            frontier_path = output_dir / "frontier.json"
            frontier_path.write_text(
                json.dumps(frontier_summary.frontier, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            summary_path = _write_summary(output_dir, frontier_summary)
            return PandasWallResult(
                summary=frontier_summary,
                breaches=tuple(check_pandas_wall_floors(frontier_summary, floors)),
                visual_path=visual_path,
                report_path=None,
                summary_path=summary_path,
                gaps_path=None,
                frontier_path=frontier_path,
                workspace_path=workspace,
                cache_key=cached.cache_key,
                cache_hit=cached.hit,
            )
        gaps_path = _write_construction_gaps(output_dir, summary)
        summary_path = _write_summary(output_dir, summary)
        return PandasWallResult(
            summary=summary,
            breaches=tuple(check_pandas_wall_floors(summary, floors)),
            visual_path=visual_path,
            report_path=None,
            summary_path=summary_path,
            gaps_path=gaps_path,
            frontier_path=None,
            workspace_path=workspace,
            cache_key=cached.cache_key,
            cache_hit=cached.hit,
        )

    report_result = runner(
        [os.fspath(sugar_bin), "lift", "--report", "--json", str(workspace)],
        root,
        env,
    )
    report_path = output_dir / "report.json"
    _write_command_receipt(report_path, report_result)
    if report_result.returncode != 0:
        raise RuntimeError(
            "pandas wall json report failed "
            f"exit={report_result.returncode}; see {report_path}"
        )
    try:
        report_json = json.loads(report_result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"pandas wall json report was not valid JSON: {exc}"
        ) from exc
    if not isinstance(report_json, Mapping):
        raise RuntimeError("pandas wall json report must be a JSON object")

    summary = summarize_pandas_completed_wall(report_json)
    summary_path = _write_summary(output_dir, summary)
    return PandasWallResult(
        summary=summary,
        breaches=tuple(check_pandas_wall_floors(summary, floors)),
        visual_path=visual_path,
        report_path=report_path,
        summary_path=summary_path,
        gaps_path=None,
        frontier_path=None,
        workspace_path=workspace,
        cache_key=cached.cache_key,
        cache_hit=cached.hit,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Build and ratchet-check the installed pandas lift wall."
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
        if result.report_path is not None:
            print(f"report: {result.report_path}", file=sys.stderr)
        if result.gaps_path is not None:
            print(f"construction gaps: {result.gaps_path}", file=sys.stderr)
        if result.frontier_path is not None:
            print(f"frontier: {result.frontier_path}", file=sys.stderr)
        print(f"visual: {result.visual_path}", file=sys.stderr)
        return 1
    print(f"pandas wall ratchet PASS: {result.summary_path}", file=sys.stderr)
    return 0


def _write_construction_gaps(output_dir: Path, summary: PandasWallSummary) -> Path:
    gaps_path = output_dir / "construction-gaps.json"
    gaps_path.write_text(
        json.dumps(
            {
                "gapsByBucket": summary.gaps_by_bucket,
                "gapTemplates": summary.gap_templates,
                "gapsTotal": summary.gaps_total,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return gaps_path


def _check_construction_gap_floors(
    summary: PandasWallSummary, floors: PandasWallFloors
) -> list[str]:
    breaches: list[str] = []
    if summary.gaps_total > floors.gaps_total_ceiling:
        breaches.append(
            "construction gap ceiling breached: "
            f"observed={summary.gaps_total} "
            f"ceiling={floors.gaps_total_ceiling} "
            f"delta={summary.gaps_total - floors.gaps_total_ceiling}"
        )
    for template, observed in sorted(summary.gap_templates.items()):
        ceiling = floors.gap_template_ceilings.get(template, 0)
        if observed > ceiling:
            breaches.append(
                "construction gap template ceiling breached: "
                f"template={template} observed={observed} "
                f"ceiling={ceiling} delta={observed - ceiling}"
            )
    return breaches


def _check_frontier_floors(
    summary: PandasWallSummary, floors: PandasWallFloors
) -> list[str]:
    breaches: list[str] = []
    if floors.mode != "frontier":
        breaches.append(
            "pandas wall stopped at a named frontier; switch "
            "tools/pandas-wall-floors.json to mode=frontier and pin the frontier"
        )
    message = summary.frontier.get("message", "")
    owner = summary.frontier.get("owner", "")
    shape = summary.frontier.get("shape", "")
    if floors.frontier_needle and floors.frontier_needle not in message:
        breaches.append(
            "pandas wall frontier needle breached: "
            f"needle={floors.frontier_needle!r} message={message!r}"
        )
    if floors.frontier_owner and owner != floors.frontier_owner:
        breaches.append(
            "pandas wall frontier owner breached: "
            f"observed={owner!r} expected={floors.frontier_owner!r}"
        )
    if floors.frontier_shape and shape != floors.frontier_shape:
        breaches.append(
            "pandas wall frontier shape breached: "
            f"observed={shape!r} expected={floors.frontier_shape!r}"
        )
    return breaches


def _check_completed_wall_floors(
    summary: PandasWallSummary, floors: PandasWallFloors
) -> list[str]:
    breaches: list[str] = []
    if floors.mode != "complete":
        breaches.append(
            "pandas wall completed; switch tools/pandas-wall-floors.json "
            "to mode=complete and pin completed-wall floors"
        )
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


def _write_summary(output_dir: Path, summary: PandasWallSummary) -> Path:
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary.to_json_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary_path


def _combined_output(result: CommandResult) -> str:
    return (
        result.stdout
        + ("\n" if result.stdout and result.stderr else "")
        + result.stderr
    )


def _structured_gap_rows(output_text: str) -> tuple[Mapping[str, Any], ...]:
    rows: list[Mapping[str, Any]] = []
    for line in output_text.splitlines():
        if _RPC_ERROR_MARKER not in line:
            continue
        decoded = _rpc_error_payload(line)
        if decoded is None:
            continue
        data = decoded.get("data")
        if not isinstance(data, Mapping):
            continue
        gap_rows = data.get("auditOnlyGaps")
        if not isinstance(gap_rows, list):
            continue
        for row in gap_rows:
            if isinstance(row, Mapping):
                rows.append(row)
    return tuple(rows)


def _frontier_error(output_text: str) -> Optional[dict[str, str]]:
    for line in output_text.splitlines():
        if _RPC_ERROR_MARKER not in line:
            continue
        decoded = _rpc_error_payload(line)
        if decoded is None:
            continue
        message = decoded.get("message")
        if not isinstance(message, str) or not message:
            continue
        fields = {key: value.strip() for key, value in _FRONTIER_FIELD.findall(message)}
        return {
            "kind": "json-rpc-frontier",
            "message": message,
            "crime": fields.get("crime", ""),
            "owner": fields.get("owner", ""),
            "shape": fields.get("shape", ""),
            "replacement": fields.get("replacement", ""),
            "blame": fields.get("blame", ""),
        }
    return None


def _rpc_error_payload(line: str) -> Optional[Mapping[str, Any]]:
    if _RPC_ERROR_MARKER not in line:
        return None
    payload = _json_object_prefix(line.split(_RPC_ERROR_MARKER, 1)[1].strip())
    if payload is None:
        return None
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, Mapping):
        return None
    return decoded


def _json_object_prefix(payload: str) -> Optional[str]:
    start = payload.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(payload)):
        char = payload[idx]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return payload[start : idx + 1]
            if depth < 0:
                return None
    return None


def _gap_info(row: Mapping[str, Any]) -> Mapping[str, Any]:
    gap = row.get("gap")
    if isinstance(gap, Mapping):
        return gap
    return row


def _gap_bucket(row: Mapping[str, Any]) -> str:
    info = _gap_info(row)
    raw_kind = _text(info.get("gap_kind"))
    if not raw_kind:
        raw_kind = _status_kind(_text(row.get("status")))
    return _canonical_gap_bucket(raw_kind)


def _gap_template(row: Mapping[str, Any], bucket: str) -> str:
    info = _gap_info(row)
    owner = _text(info.get("owner")) or "unknown-owner"
    observed = _text(info.get("observed")) or "unknown-observed"
    requested = _text(info.get("requested")) or "unknown-requested"
    return f"{bucket}|{owner}|{observed}|{requested}"


def _canonical_gap_bucket(raw_kind: str) -> str:
    key = raw_kind.replace("_", "").replace("-", "").lower()
    if key == "proofir":
        return "ProofIR"
    if key == "constructor":
        return "Constructor"
    if key == "floor":
        return "Floor"
    if key == "sugar":
        return "Sugar"
    return raw_kind


def _status_kind(status: str) -> str:
    if status.endswith("-gap"):
        return status[: -len("-gap")]
    return status


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def _mode_field(data: Mapping[str, Any]) -> PandasWallMode:
    mode = data.get("mode")
    if mode in ("construction-gaps", "frontier", "complete"):
        return mode
    raise TypeError(
        "pandas wall floor `mode` must be `construction-gaps`, "
        "`frontier`, or `complete`"
    )


def _int_field(data: Mapping[str, Any], field: str) -> int:
    return _int_value(data.get(field), f"`{field}`")


def _int_value(value: object, label: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise TypeError(f"pandas wall floor {label} must be a non-negative integer")
    return value


def _workspace_for_mode(
    package_path: Path,
    root: Path,
    output_dir: Path,
    floors: PandasWallFloors,
    cache_root: Optional[Path],
) -> CachedAuditWorkspace:
    if floors.mode == "complete":
        workspace = output_dir / "workspace" / package_path.name
        _prepare_audit_workspace(package_path, root, workspace, audit_only=False)
        return CachedAuditWorkspace(
            workspace=workspace,
            cache_key="complete-report-workspace",
            hit=False,
        )
    return _cached_workspace(package_path, root, cache_root)


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
