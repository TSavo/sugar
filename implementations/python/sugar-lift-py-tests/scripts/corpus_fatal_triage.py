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

from sugar_lift_py_tests.idd.factory_panic_fronts import (
    fingerprint_from_gap,
    rank_factory_panic_fronts,
)

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


def _child_payload(path: Path, rel: str) -> tuple[dict[str, Any], int]:
    logging.disable(logging.CRITICAL)
    try:
        from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
        from sugar_lift_py_tests.lift_rpc import lift_file_payload

        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source = path.read_text(encoding="utf-8", errors="replace")
        payload = lift_file_payload(source, rel)
    except KeyboardInterrupt:
        raise
    except BaseException as error:
        terminal: dict[str, Any] = {
            "outcome": "exception",
            "file": rel,
            "exception_type": type(error).__name__,
            "reason": (str(error).splitlines() or [repr(error)])[-1][:1000],
        }
        if "FactoryPanic" in locals() and isinstance(error, FactoryPanic):
            terminal["outcome"] = "factory-panic"
            terminal["gap"] = error.info.to_json()
        return terminal, 3
    return {
        "outcome": "completed",
        "file": rel,
        "facts": len(payload.ir),
        "factory_walk_rows": len(payload.factory_walk),
    }, 0


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
    if testimony is not None and testimony.get("outcome") == "factory-panic":
        return {
            "file": rel,
            "category": "factory-construction-panic",
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


def _factory_fingerprint(row: dict[str, Any]) -> tuple[str, ...]:
    """Exact-front identity; shared with live isolation ranking."""
    testimony = row.get("testimony") or {}
    gap = testimony.get("gap") or {}
    return fingerprint_from_gap(gap if isinstance(gap, dict) else {})


def _run_parent(args: argparse.Namespace) -> int:
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
    representatives: dict[str, list[str]] = defaultdict(list)
    factory_panic_rows: list[dict[str, Any]] = []
    script = Path(__file__).resolve()

    for index, (package, root, path) in enumerate(paths, start=1):
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source = path.read_text(encoding="utf-8", errors="replace")
        rel = f"{package}/{path.relative_to(root).as_posix()}"
        tree = ast.parse(source, filename=rel)
        assertion_count = sum(isinstance(node, ast.Assert) for node in ast.walk(tree))
        assertion_counts["files_total"] += 1
        assertion_counts["assertions_total"] += assertion_count
        if assertion_count == 0:
            assertion_counts["files_without_assertions"] += 1
            continue
        assertion_counts["files_with_assertions"] += 1
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

        category = str(row["category"])
        categories[category] += 1
        if len(representatives[category]) < 10:
            representatives[category].append(rel)
        if category != "completed":
            terminal_rows.append(row)
        if category == "factory-construction-panic":
            fingerprint = _factory_fingerprint(row)
            testimony = row.get("testimony") or {}
            gap = testimony.get("gap") if isinstance(testimony, dict) else {}
            factory_panic_rows.append(
                {
                    "file": rel,
                    "owner": fingerprint[0] or "unknown",
                    "gap": gap if isinstance(gap, dict) else {},
                    "fingerprint": list(fingerprint),
                }
            )
        if index % 25 == 0:
            print(f"triaged {index}/{len(paths)} files", file=sys.stderr)

    ranking = rank_factory_panic_fronts(factory_panic_rows)
    factory_fronts = ranking["exact_fronts"]
    owner_families = ranking["owner_families"]
    report: dict[str, Any] = {
        "package_versions": versions,
        "shard": {"index": args.shard_index, "count": args.shard_count},
        "census": dict(sorted(assertion_counts.items())),
        "terminal_categories": dict(sorted(categories.items())),
        "category_representatives": dict(sorted(representatives.items())),
        "factory_panic_front_count": len(factory_fronts),
        "factory_panic_fronts": (
            factory_fronts[: args.front_limit] if args.compact else factory_fronts
        ),
        # Structured owner ranking — same payload live isolation emits so
        # fatal recensus (#4775) can merge isolation + triage without re-parsing.
        "R_live_factory_panic_files": ranking["R_live_factory_panic_files"],
        "owner_family_count": ranking["owner_family_count"],
        "owner_families": (
            owner_families[: args.front_limit] if args.compact else owner_families
        ),
        "owners": ranking["owners"],
    }
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
