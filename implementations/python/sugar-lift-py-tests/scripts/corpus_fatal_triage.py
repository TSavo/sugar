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

from sugar_lift_py_tests.idd.construction_panic_fronts import (
    fingerprint_from_gap,
    rank_construction_panic_fronts,
)
from sugar_lift_py_tests.idd.factory_walk_unclassified_locus import (
    project_unclassified_loci,
    shape_split_unclassified,
)

PACKAGES = ("numpy", "pandas")
DEFAULT_FILE_TIMEOUT_SECONDS = 30
# Cap retained loci in --compact parent reports; full emission stays default.
COMPACT_LOCUS_LIMIT = 200
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
        from sugar_lift_py_tests.audit_only import collect_construction_panic
        from sugar_lift_py_tests.effect import effect_reason, effect_status
        from sugar_lift_py_tests.lift_rpc import lift_file_payload
        from sugar_lift_py_tests.kit_manifest import (
            load_kit_manifest_from_env,
        )

        # #5907: load a declared kit/bridge contract into THIS process before
        # lift, so a real corpus row can authenticate under it. With no
        # SUGAR_KIT_MANIFEST set, this loads nothing — protocol tables stay
        # empty by construction and rows stay loud (the law, not a bug).
        kit_provenance = load_kit_manifest_from_env()
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source = path.read_text(encoding="utf-8", errors="replace")
        if progress:
            with reduction_span(sugar="lift_file_payload", role="file", site=rel):
                payload, panic_gap = collect_construction_panic(
                    rel,
                    lambda: lift_file_payload(source, rel),
                )
        else:
            payload, panic_gap = collect_construction_panic(
                rel,
                lambda: lift_file_payload(source, rel),
            )
        if panic_gap is not None:
            return {
                "outcome": "factory-panic",
                "file": rel,
                "exception_type": "ConstructionPanic",
                "reason": panic_gap.message.splitlines()[-1][:1000],
                "gap": panic_gap.info,
                "kit_manifest": (
                    kit_provenance.to_json() if kit_provenance is not None else None
                ),
            }, 3
        assert payload is not None
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
    # Row-addressable unclassified evidence (#5252): completed files dump
    # every unclassified walk locus so next recensus is shape-split capable.
    unclassified_rows = project_unclassified_loci(payload.factory_walk)
    return {
        "outcome": "completed",
        "file": rel,
        "facts": len(payload.ir),
        "factory_walk_rows": len(payload.factory_walk),
        "R_factory_walk_unclassified": len(unclassified_rows),
        "unclassified_rows": unclassified_rows,
        # #5907: which kit manifest (if any) was loaded into this child
        # process before lift — provenance, not silent ambient state.
        "kit_manifest": (
            kit_provenance.to_json() if kit_provenance is not None else None
        ),
        "effects": [
            {
                "effect": type(row.effect).__name__,
                "name": row.name,
                "status": effect_status(row.effect),
                "reason": effect_reason(row.effect),
            }
            for row in payload.effects
        ],
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
    floor_rows: list[dict[str, Any]] = []
    representatives: dict[str, list[str]] = defaultdict(list)
    construction_panic_rows: list[dict[str, Any]] = []
    effect_occurrence_counts: Counter[str] = Counter()
    effect_file_counts: Counter[str] = Counter()
    effect_examples: dict[str, list[str]] = defaultdict(list)
    effect_reason_examples: dict[str, list[str]] = defaultdict(list)
    factory_walk_unclassified_rows: list[dict[str, Any]] = []
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
            floor_rows.append({"file": rel, "category": "completed-no-assertions"})
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
        if args.kit_manifest:
            # #5907: propagate the declared kit manifest to the child process
            # that actually mints this file. Absolute path so the child's cwd
            # cannot silently change which contract loads.
            env["SUGAR_KIT_MANIFEST"] = str(Path(args.kit_manifest).resolve())
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
        floor_rows.append({"file": rel, "category": category})
        categories[category] += 1
        if len(representatives[category]) < 10:
            representatives[category].append(rel)
        if category != "completed":
            terminal_rows.append(row)
        if category == "factory-construction-panic":
            fingerprint = _factory_fingerprint(row)
            testimony = row.get("testimony") or {}
            gap = testimony.get("gap") if isinstance(testimony, dict) else {}
            construction_panic_rows.append(
                {
                    "file": rel,
                    "owner": fingerprint[0] or "unknown",
                    "gap": gap if isinstance(gap, dict) else {},
                    "fingerprint": list(fingerprint),
                }
            )
        if category == "completed":
            testimony = row.get("testimony") or {}
            effects = testimony.get("effects") or []
            seen_effects: set[str] = set()
            for effect in effects:
                effect_class = str(effect.get("effect") or "")
                if not effect_class:
                    continue
                effect_occurrence_counts[effect_class] += 1
                reason = str(effect.get("reason") or "")
                if (
                    reason
                    and reason not in effect_reason_examples[effect_class]
                    and len(effect_reason_examples[effect_class]) < 5
                ):
                    effect_reason_examples[effect_class].append(reason)
                seen_effects.add(effect_class)
            for effect_class in seen_effects:
                effect_file_counts[effect_class] += 1
                if len(effect_examples[effect_class]) < 5:
                    effect_examples[effect_class].append(rel)
            # Collect row-addressable unclassified loci from completed files.
            loci = testimony.get("unclassified_rows") or []
            if isinstance(loci, list):
                for locus in loci:
                    if isinstance(locus, dict):
                        factory_walk_unclassified_rows.append(locus)
        if index % 25 == 0:
            print(f"triaged {index}/{len(paths)} files", file=sys.stderr)

    ranking = rank_construction_panic_fronts(construction_panic_rows)
    factory_fronts = ranking["exact_fronts"]
    owner_families = ranking["owner_families"]
    completed_effect_fronts = [
        {
            "effect": effect_class,
            "file_count": effect_file_counts[effect_class],
            "occurrence_count": occurrence_count,
            "representative_files": effect_examples[effect_class],
            "reason_examples": effect_reason_examples[effect_class],
        }
        for effect_class, occurrence_count in sorted(
            effect_occurrence_counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    r_unclassified = len(factory_walk_unclassified_rows)
    shape_split = shape_split_unclassified(factory_walk_unclassified_rows)
    retained_loci = factory_walk_unclassified_rows
    if args.compact and len(retained_loci) > COMPACT_LOCUS_LIMIT:
        retained_loci = retained_loci[:COMPACT_LOCUS_LIMIT]
    report: dict[str, Any] = {
        "package_versions": versions,
        # #5907: which kit manifest (path only — the child recomputes and
        # records its own sha256) governed this run. null means every child
        # minted with no contract: empty-by-construction, rows stay loud.
        "kit_manifest": (
            str(Path(args.kit_manifest).resolve()) if args.kit_manifest else None
        ),
        "shard": {"index": args.shard_index, "count": args.shard_count},
        "census": dict(sorted(assertion_counts.items())),
        "terminal_categories": dict(sorted(categories.items())),
        "category_representatives": dict(sorted(representatives.items())),
        "construction_panic_front_count": len(factory_fronts),
        "construction_panic_fronts": (
            factory_fronts[: args.front_limit] if args.compact else factory_fronts
        ),
        # Structured owner ranking — same payload live isolation emits so
        # fatal recensus (#4775) can merge isolation + triage without re-parsing.
        "R_live_construction_panic_files": ranking["R_live_construction_panic_files"],
        "owner_family_count": ranking["owner_family_count"],
        "owner_families": (
            owner_families[: args.front_limit] if args.compact else owner_families
        ),
        "owners": ranking["owners"],
        "completed_effect_front_count": len(completed_effect_fronts),
        "completed_effect_fronts": completed_effect_fronts,
        # Permanent baseline-free floor + row-addressable evidence (#5252).
        # Conserves: R == len(factory_walk_unclassified_rows) == statuses map.
        "R_factory_walk_unclassified": r_unclassified,
        "factory_walk_statuses": {
            "unclassified": r_unclassified,
        },
        "factory_walk_unclassified_shape_split": shape_split,
        "factory_walk_unclassified_rows": retained_loci,
    }
    from pandas_floor_summary import floor_summary

    all_files = sorted(
        f"{package}/{path.relative_to(root).as_posix()}"
        for package, root, path in paths
    )
    fatal_r = sum(
        count for category, count in categories.items() if category != "completed"
    )
    report["floorSummary"] = floor_summary(
        floor="fatal-triage",
        files=all_files,
        rows=floor_rows,
        totals={"R_fatal_triage": fatal_r, **dict(categories)},
        measured=len(floor_rows) == len(all_files),
        unmeasurable_reasons=(),
    )
    if args.compact and r_unclassified > COMPACT_LOCUS_LIMIT:
        report["factory_walk_unclassified_rows_truncated"] = True
        report["factory_walk_unclassified_rows_retained"] = COMPACT_LOCUS_LIMIT
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
    parser.add_argument(
        "--kit-manifest",
        help=(
            "Path to a kit/bridge contract manifest (#5907) whose declared "
            "coordinates load into every mint child process before lift. "
            "Omit to mint with no contract — the empty-by-construction "
            "default; rows without a matching recognizer stay loud."
        ),
    )
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
