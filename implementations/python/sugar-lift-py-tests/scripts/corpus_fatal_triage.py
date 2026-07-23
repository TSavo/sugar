from __future__ import annotations

import argparse
import ast
import importlib.metadata
import importlib.util
import json
import logging
import os
import signal
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PACKAGES = ("numpy", "pandas")
DEFAULT_FILE_TIMEOUT_SECONDS = 30
TRANSPORT_MARKERS = (
    "closed stdout",
    "transport",
    "json-rpc",
    "jsonrpc",
    "broken pipe",
)


def package_root(package: str) -> Path:
    spec = importlib.util.find_spec(package)
    assert spec is not None and spec.origin is not None
    return Path(spec.origin).resolve().parent


def python_files(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*.py") if "__pycache__" not in path.parts
    )


def _progress_logging_enabled() -> bool:
    """Macro hotspot progress is opt-in via SUGAR_ENGINE_LOG or SUGAR_ENGINE_PROGRESS=1.

    Default corpus triage stays quiet (logging disabled). Timeout classification
    sets SUGAR_ENGINE_LOG so heartbeats name the live sugar/site stack on kill.
    """
    if os.environ.get("SUGAR_ENGINE_LOG"):
        return True
    flag = (os.environ.get("SUGAR_ENGINE_PROGRESS") or "").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def _child_payload(path: Path, rel: str) -> tuple[dict[str, Any], int]:
    progress = _progress_logging_enabled()
    if not progress:
        logging.disable(logging.CRITICAL)
    else:
        # Re-enable in case parent left logging disabled; attach live JSONL sink.
        logging.disable(logging.NOTSET)
        from sugar_lift_py_tests.engine_log import configure_live_log, reduction_span

        configure_live_log()
    try:
        from _production_lift_child import production_lift_testimony
        if progress:
            with reduction_span(sugar="production_lift", role="file", site=rel):
                terminal = production_lift_testimony(path, rel)
        else:
            terminal = production_lift_testimony(path, rel)
    except KeyboardInterrupt:
        raise
    except Exception as error:
        terminal: dict[str, Any] = {
            "outcome": "exception",
            "file": rel,
            "exception_type": type(error).__name__,
            "reason": (str(error).splitlines() or [repr(error)])[-1][:1000],
        }
        return terminal, 3
    return terminal, 0


def _run_child(args: argparse.Namespace) -> int:
    terminal, returncode = _child_payload(Path(args.child_file), args.child_rel)
    print(json.dumps(terminal, sort_keys=True), flush=True)
    return returncode


def _parse_child_stdout(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "outcome" in value:
            return value
    return None


def _transport_text(*parts: str) -> bool:
    text = "\n".join(parts).lower()
    return any(marker in text for marker in TRANSPORT_MARKERS)


def _classify_child(
    *,
    rel: str,
    result: subprocess.CompletedProcess[str] | None,
    timed_out: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    if timed_out:
        return {
            "file": rel,
            "category": "timeout-or-hang",
            "reason": f"child exceeded {timeout_seconds}s",
        }
    assert result is not None
    signal_number = -result.returncode if result.returncode < 0 else None
    if signal_number is not None:
        try:
            signal_name = signal.Signals(signal_number).name
        except ValueError:
            signal_name = f"signal-{signal_number}"
        return {
            "file": rel,
            "category": "process-crash-or-overflow",
            "returncode": result.returncode,
            "signal": signal_name,
            "reason": result.stderr[-2000:],
        }

    testimony = _parse_child_stdout(result.stdout)
    if testimony is not None and testimony.get("outcome") == "completed":
        return {"file": rel, "category": "completed", "testimony": testimony}
    if testimony is not None and testimony.get("outcome") == "typed-gap":
        return {
            "file": rel,
            "category": "typed-gap",
            "testimony": testimony,
        }
    reason = ""
    if testimony is not None:
        reason = str(testimony.get("reason") or "")
    if _transport_text(reason, result.stdout, result.stderr):
        category = "transport-disconnect"
    else:
        category = "bare-exception"
    return {
        "file": rel,
        "category": category,
        "returncode": result.returncode,
        "testimony": testimony,
        "reason": reason or result.stderr[-2000:] or "child emitted no testimony",
    }


def _is_fatal_category(category: str) -> bool:
    return category not in {"completed", "typed-gap"}


def _run_parent(args: argparse.Namespace) -> int:
    if args.file_timeout > 30:
        raise ValueError("per-file timeout may not exceed 30 seconds")
    packages = tuple(args.packages) or PACKAGES
    versions = {package: importlib.metadata.version(package) for package in packages}
    all_paths = [
        (package, root, path)
        for package in packages
        for root in (package_root(package),)
        for path in python_files(root)
    ]
    paths = [
        item
        for index, item in enumerate(all_paths)
        if index % args.shard_count == args.shard_index
    ]
    categories: Counter[str] = Counter()
    assertion_counts: Counter[str] = Counter()
    terminal_rows: list[dict[str, Any]] = []
    floor_rows: list[dict[str, Any]] = []
    representatives: dict[str, list[str]] = defaultdict(list)
    typed_gap_classes: Counter[str] = Counter()
    typed_gap_owners: Counter[str] = Counter()
    script = Path(__file__).resolve()
    by_rel = {
        f"{package}/{path.relative_to(root).as_posix()}": (path, root)
        for package, root, path in paths
    }

    def measure_unchecked(rel: str) -> dict[str, Any]:
        path, _root = by_rel[rel]
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=rel)
        assertion_count = sum(isinstance(node, ast.Assert) for node in ast.walk(tree))
        command = [
            sys.executable,
            str(script),
            "--child-file",
            str(path),
            "--child-rel",
            rel,
        ]
        env = dict(os.environ)
        env["PYTHONFAULTHANDLER"] = "1"
        try:
            result = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=args.file_timeout,
                env=env,
                check=False,
            )
            row = _classify_child(
                rel=rel,
                result=result,
                timed_out=False,
                timeout_seconds=args.file_timeout,
            )
        except subprocess.TimeoutExpired:
            row = _classify_child(
                rel=rel,
                result=None,
                timed_out=True,
                timeout_seconds=args.file_timeout,
            )
        return {"assertionCount": assertion_count, "terminal": row}

    def measure(rel: str) -> dict[str, Any]:
        try:
            return measure_unchecked(rel)
        except Exception as error:
            return {
                "assertionCount": 0,
                "terminal": {
                    "file": rel,
                    "category": "backend-defect",
                    "reason": f"{type(error).__name__}: {error}",
                },
            }

    if args.checkpoint_jsonl:
        from pandas_census_checkpoint import Checkpoint, run_pending

        checkpoint = Checkpoint(
            floor="fatal-triage",
            files=tuple(by_rel),
            path=Path(args.checkpoint_jsonl),
        )
        journal_rows = run_pending(checkpoint, measure, workers=1)
        measured = [dict(row["result"]) for row in journal_rows]
    else:
        measured = [measure(rel) for rel in sorted(by_rel)]

    for index, (rel, measured_row) in enumerate(
        zip(sorted(by_rel), measured, strict=True), start=1
    ):
        assertion_count = int(measured_row["assertionCount"])
        assertion_counts["files_total"] += 1
        assertion_counts["assertions_total"] += assertion_count
        assertion_counts[
            "files_with_assertions" if assertion_count else "files_without_assertions"
        ] += 1
        row = measured_row["terminal"]
        if not isinstance(row, dict):
            raise ValueError(f"invalid fatal checkpoint testimony for {rel}")

        category = str(row["category"])
        floor_rows.append({"file": rel, "category": category})
        categories[category] += 1
        if len(representatives[category]) < 10:
            representatives[category].append(rel)
        if _is_fatal_category(category):
            terminal_rows.append(row)
        if category == "typed-gap":
            testimony = row.get("testimony") or {}
            for typed in testimony.get("typed_gaps") or []:
                if not isinstance(typed, dict):
                    continue
                typed_gap_classes[str(typed.get("exception_type") or "unknown")] += 1
                gap = typed.get("gap") or {}
                if isinstance(gap, dict):
                    typed_gap_owners[str(gap.get("owner") or "unknown")] += 1
        if index % 25 == 0:
            print(f"triaged {index}/{len(paths)} files", file=sys.stderr)

    report: dict[str, Any] = {
        "package_versions": versions,
        "shard": {"index": args.shard_index, "count": args.shard_count},
        "census": dict(sorted(assertion_counts.items())),
        "terminal_categories": dict(sorted(categories.items())),
        "category_representatives": dict(sorted(representatives.items())),
        "R_live_construction_panic_files": 0,
        "typed_gap_classes": dict(sorted(typed_gap_classes.items())),
        "typed_gap_owners": dict(
            sorted(typed_gap_owners.items(), key=lambda item: (-item[1], item[0]))
        ),
    }
    from pandas_floor_summary import floor_summary

    all_files = sorted(
        f"{package}/{path.relative_to(root).as_posix()}"
        for package, root, path in paths
    )
    fatal_r = sum(
        count for category, count in categories.items() if _is_fatal_category(category)
    )
    report["floorSummary"] = floor_summary(
        floor="fatal-triage",
        files=all_files,
        rows=floor_rows,
        totals={"R_fatal_triage": fatal_r, **dict(categories)},
        measured=len(floor_rows) == len(all_files),
        unmeasurable_reasons=(),
    )
    if not args.compact:
        report["terminal_rows"] = terminal_rows
    rendered = json.dumps(report, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("packages", nargs="*", choices=PACKAGES)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--front-limit", type=int, default=100)
    parser.add_argument(
        "--file-timeout", type=int, default=DEFAULT_FILE_TIMEOUT_SECONDS
    )
    parser.add_argument("--output")
    parser.add_argument("--checkpoint-jsonl")
    parser.add_argument("--child-file")
    parser.add_argument("--child-rel")
    args = parser.parse_args()
    if args.child_file or args.child_rel:
        if not args.child_file or not args.child_rel:
            parser.error("child mode requires --child-file and --child-rel")
        return _run_child(args)
    if not 0 <= args.shard_index < args.shard_count:
        parser.error("shard index must be in [0, shard count)")
    return _run_parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
