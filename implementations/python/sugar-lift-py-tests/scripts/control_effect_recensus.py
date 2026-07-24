#!/usr/bin/env python3
"""Pandas control/effect construction recensus.

One process. Enumeration only:

    SourceTree(corpus).paths()
      → path_source(path)
      → SourceFile(identity)
      → functions()
      → fn.sugar()

No subprocess. No process pool. No package preconstruction.
Caches and mementos live for the whole run.

I/O split (never mixed):
  --engine-log   sugar engine JSONL (construction telemetry)
  --progress     tqdm bar only
  --json         final result summary
  --checkpoint-jsonl  per-file durable journal
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, TextIO


def _git_commit(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


def _silence_console_logging() -> None:
    """Keep library noise off the progress stream.

    Sugar engine ERROR events otherwise hit logging's lastResort handler on
    stderr and pollute tqdm. Root/other loggers stay quiet too unless the
    caller attached an explicit handler.
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(logging.NullHandler())
    root.setLevel(logging.CRITICAL)
    # lastResort still fires for WARNING+ with no handlers on a logger that
    # propagates to a root with only NullHandler? Actually lastResort is used
    # when lastResort is not None and the record is not handled. With
    # NullHandler, records are "handled". Good.
    logging.lastResort = None  # type: ignore[assignment]


def _configure_engine_log(path: Path) -> None:
    """Engine JSONL only — never stdout/stderr."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Prefer the kit's own sink; also pin env so late imports see it.
    os.environ["SUGAR_ENGINE_LOG"] = str(path.resolve())
    from sugar_lift_py_tests import engine_log

    # Drop any prior live handler (e.g. wrong path from env at import time).
    logger = engine_log.LOGGER
    logger.handlers.clear()
    logger.propagate = False
    engine_log._LIVE_HANDLER = None  # type: ignore[attr-defined]
    engine_log.configure_live_log(str(path.resolve()))
    logger.propagate = False
    logger.setLevel(logging.DEBUG)


def _measure_file(path: Path, *, relative: str) -> dict[str, Any]:
    from sugar_lift_py_tests.audit_only import collect_construction_panic
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.tree import SourceFile

    functions_total = 0
    functions_clean = 0
    families: Counter[str] = Counter()

    def construct():
        nonlocal functions_total, functions_clean
        reporter = CollectingReporter()
        source_file = SourceFile(path_source(str(path)), reporter=reporter)
        for function in source_file.functions():
            functions_total += 1
            try:
                function.sugar()
                functions_clean += 1
            except SugarNotWritten as gap:
                families[type(gap).__name__] += 1
        for _node, panic in reporter.gaps:
            families[type(panic).__name__] += 1
        return reporter

    _reporter, panic_row = collect_construction_panic(relative, construct)
    if panic_row is not None:
        return {
            "category": "construction-panic",
            "panic": {
                "file": relative,
                "type": "ConstructionPanic",
                "message": panic_row.message,
                "gap": panic_row.info,
            },
            "functionsTotal": functions_total,
            "functionsClean": functions_clean,
            "families": dict(families),
        }
    return {
        "category": "completed",
        "functionsTotal": functions_total,
        "functionsClean": functions_clean,
        "families": dict(families),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--commit")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(".sugar/pandas-control-effect"),
        help="default directory for progress/engine/result/checkpoint files",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="final result JSON (default: <out-dir>/recensus.json)",
    )
    parser.add_argument(
        "--checkpoint-jsonl",
        type=Path,
        default=None,
        help="per-file journal (default: <out-dir>/checkpoint.jsonl)",
    )
    parser.add_argument(
        "--engine-log",
        type=Path,
        default=None,
        help="sugar engine JSONL only (default: <out-dir>/engine.jsonl)",
    )
    parser.add_argument(
        "--progress",
        type=Path,
        default=None,
        help="tqdm progress only (default: <out-dir>/progress.log)",
    )
    parser.add_argument(
        "--progress-stdout",
        action="store_true",
        help="also paint tqdm on this process's stderr (still write --progress)",
    )
    args = parser.parse_args()

    if not args.corpus.exists():
        parser.error(f"corpus not found: {args.corpus}")

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    result_path = args.json or (out / "recensus.json")
    checkpoint_path = args.checkpoint_jsonl or (out / "checkpoint.jsonl")
    engine_path = args.engine_log or (out / "engine.jsonl")
    progress_path = args.progress or (out / "progress.log")

    _silence_console_logging()
    _configure_engine_log(engine_path)

    from sugar_source_tree.tree import SourceTree

    tree = SourceTree(args.corpus)
    paths = list(tree.paths())
    if not paths:
        parser.error("corpus contains no Python files")

    if args.corpus.is_dir():
        by_file = {
            f"{args.corpus.name}/{path.relative_to(args.corpus).as_posix()}": path
            for path in paths
        }
    else:
        by_file = {args.corpus.name: args.corpus}

    file_names = sorted(by_file)
    pending: list[str] = list(file_names)

    from pandas_census_checkpoint import Checkpoint

    checkpoint = Checkpoint(
        floor="control-effect",
        files=tuple(file_names),
        path=checkpoint_path,
    )
    pending = list(checkpoint.pending_files())

    defects: list[dict[str, Any]] = []
    construction_panics: list[dict[str, Any]] = []
    floor_rows: list[dict[str, Any]] = []
    families: Counter[str] = Counter()
    files_completed = 0
    functions_total = 0
    functions_clean = 0
    started = time.time()
    measured_now: list[tuple[str, dict[str, Any]]] = []

    try:
        from tqdm import tqdm
    except ImportError as error:  # pragma: no cover
        raise SystemExit(
            "tqdm is required: python3 -m pip install 'tqdm>=4.66'"
        ) from error

    live_done = 0
    live_panic = 0  # ConstructionPanic only (file-level kit panic)
    live_defect = 0
    live_fns = 0
    live_clean = 0
    live_snw = 0  # SugarNotWritten (missing sugar)
    live_other_gaps = 0  # other typed gaps (e.g. RuntimeSelectedContextManager)
    already_done = len(file_names) - len(pending)
    # Seed running totals from checkpoint so resume doesn't look like "0 gaps".
    if checkpoint is not None and already_done:
        for crow in checkpoint.rows():
            raw = crow.get("result") or {}
            cat = str(raw.get("category") or "")
            live_fns += int(raw.get("functionsTotal") or 0)
            live_clean += int(raw.get("functionsClean") or 0)
            families = raw.get("families") or {}
            live_snw += int(families.get("SugarNotWritten") or 0)
            live_other_gaps += sum(
                int(v) for k, v in families.items() if k != "SugarNotWritten"
            )
            if cat == "construction-panic":
                live_panic += 1
            elif cat not in {"completed", ""}:
                live_defect += 1
            live_done += 1

    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_stream: TextIO = progress_path.open("w", encoding="utf-8")
    # Header so `tail -f progress.log` is self-describing.
    progress_stream.write(
        f"# pandas enum progress\n"
        f"# corpus={args.corpus}\n"
        f"# engine_log={engine_path.resolve()}\n"
        f"# checkpoint={checkpoint_path.resolve()}\n"
        f"# result={result_path.resolve()}\n"
        f"# already_done={already_done} pending={len(pending)} total={len(file_names)}\n"
        f"# postfix: file=current path | snw=SugarNotWritten | gaps=other typed | "
        f"cpanic=ConstructionPanic | fn=clean/total functions\n"
    )
    progress_stream.flush()

    bar_format = (
        "{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} "
        "[{elapsed}<{remaining}, {rate_fmt}] {postfix}"
    )

    def _set_bars(postfix: dict[str, object], *, refresh: bool = True) -> None:
        bar.set_postfix(postfix, refresh=refresh)
        if live_bar is not None:
            live_bar.set_postfix(postfix, refresh=refresh)
        progress_stream.flush()

    try:
        bar = tqdm(
            pending,
            total=len(file_names),
            initial=already_done,
            unit="file",
            desc="pandas enum",
            file=progress_stream,
            dynamic_ncols=False,
            ncols=200,
            mininterval=0.15,
            smoothing=0.05,
            bar_format=bar_format,
        )
        # Optional second bar on stderr for an interactive terminal.
        live_bar = None
        if args.progress_stdout and sys.stderr.isatty():
            live_bar = tqdm(
                total=len(file_names),
                initial=already_done,
                unit="file",
                desc="pandas enum",
                file=sys.stderr,
                dynamic_ncols=True,
                mininterval=0.15,
                smoothing=0.05,
                bar_format=bar_format,
            )

        for file in bar:
            path = by_file[file]
            relative = (
                path.relative_to(args.corpus).as_posix()
                if args.corpus.is_dir()
                else path.name
            )
            # Show the file we are about to open — before the work starts.
            _set_bars(
                {
                    "file": relative,
                    "status": "lifting…",
                    "snw": live_snw,
                    "gaps": live_other_gaps,
                    "cpanic": live_panic,
                    "defect": live_defect,
                    "fn": f"{live_clean}/{live_fns}",
                },
                refresh=True,
            )
            t_file = time.perf_counter()
            try:
                row = _measure_file(path, relative=relative)
            except Exception as error:  # noqa: BLE001 -- per-file terminal
                row = {
                    "category": "backend-defect",
                    "defect": {
                        "file": relative,
                        "type": type(error).__name__,
                        "message": str(error),
                    },
                }
            file_s = time.perf_counter() - t_file
            checkpoint.append(file, row)
            measured_now.append((file, row))

            cat = str(row.get("category") or "?")
            fn = int(row.get("functionsTotal") or 0)
            clean = int(row.get("functionsClean") or 0)
            families = row.get("families") or {}
            snw = int(families.get("SugarNotWritten") or 0)
            other = sum(
                int(v) for k, v in families.items() if k != "SugarNotWritten"
            )
            live_fns += fn
            live_clean += clean
            live_snw += snw
            live_other_gaps += other
            live_done += 1
            if cat == "construction-panic":
                live_panic += 1
                status = "cpanic"
            elif cat == "completed":
                status = "done"
            else:
                live_defect += 1
                status = cat

            clean_pct = (100.0 * live_clean / live_fns) if live_fns else 0.0
            _set_bars(
                {
                    "file": relative,
                    "status": status,
                    "last": f"{file_s:.2f}s",
                    "snw": live_snw,
                    "gaps": live_other_gaps,
                    "cpanic": live_panic,
                    "defect": live_defect,
                    "fn": f"{live_clean}/{live_fns}",
                    "clean%": f"{clean_pct:.0f}",
                },
                refresh=True,
            )
            if live_bar is not None:
                live_bar.update(1)

        if live_bar is not None:
            live_bar.close()
        bar.close()
    finally:
        progress_stream.close()

    measured_rows = [(row["file"], row["result"]) for row in checkpoint.rows()]

    for file, raw in measured_rows:
        row = dict(raw)
        category = str(row.get("category"))
        floor_rows.append({"file": file, "category": category})
        functions_total += int(row.get("functionsTotal") or 0)
        functions_clean += int(row.get("functionsClean") or 0)
        families.update(row.get("families") or {})
        if category == "completed":
            files_completed += 1
        elif category == "construction-panic":
            panic = row.get("panic")
            if isinstance(panic, dict):
                construction_panics.append(panic)
            families["ConstructionPanic"] += 1
        else:
            defect = row.get("defect")
            defects.append(
                dict(defect)
                if isinstance(defect, dict)
                else {"file": file, "type": category, "message": category}
            )

    from pandas_floor_summary import floor_summary

    result: dict[str, Any] = {
        "kind": "control-effect-construction-recensus",
        "commit": args.commit or _git_commit(args.repo),
        "corpus": str(args.corpus),
        "door": "enum:path_source→SourceFile→functions→sugar",
        "isolation": "in-process",
        "paths": {
            "engineLog": str(engine_path.resolve()),
            "progress": str(progress_path.resolve()),
            "checkpoint": str(checkpoint_path.resolve()),
            "result": str(result_path.resolve()),
        },
        "filesTotal": len(file_names),
        "filesCompleted": files_completed,
        "defects": defects,
        "constructionPanics": construction_panics,
        "R_construction_panics": len(construction_panics),
        "functionsTotal": functions_total,
        "functionsConstructClean": functions_clean,
        "R": sum(families.values()),
        "families": dict(
            sorted(families.items(), key=lambda item: (-item[1], item[0]))
        ),
        "elapsedSeconds": time.time() - started,
        "python": sys.version,
        "floorSummary": floor_summary(
            floor="control-effect",
            files=file_names,
            rows=floor_rows,
            totals={
                "R_control_effect": sum(families.values()) + len(defects),
                "constructionPanics": len(construction_panics),
                "backendDefectsOrProcessTerminals": len(defects),
            },
            measured=len(floor_rows) == len(file_names),
            unmeasurable_reasons=(),
        ),
    }
    rendered = json.dumps(result, indent=2)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(rendered + "\n")
    # One quiet line on stdout — paths only, no engine dump.
    print(
        f"done files={files_completed}/{len(file_names)} "
        f"result={result_path} progress={progress_path} engine={engine_path}",
        flush=True,
    )
    return (
        1
        if defects or construction_panics or files_completed != len(file_names)
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
