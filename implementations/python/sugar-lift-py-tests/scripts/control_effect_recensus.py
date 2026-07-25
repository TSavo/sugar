#!/usr/bin/env python3
"""Pandas control/effect construction + desugar-layer recensus.

One process. Two named axes (never merged into one R):

    SourceTree(corpus).paths()
      → provisional_contract_refs_from_demands(corpus)  (once)
      → open_source_file_for_construction (context + source-derived CM refs)
      → functions()
      → fn.sugar()                    # axis 1: construction families
      → sugar.desugar(None)           # axis 2: desugar refusals + typed red

Construction R answers "is the tree total?". Desugar R answers "is meaning
reducible?". Yield/YieldFrom construct then refuse at desugar — correct; they
must stay on the board under axis 2 (see #6243).

Occurrence identity: one gap = (kind, file, line, col). Construction families
are tallied only from ``reporter.gaps`` (catch+reporter type double-count is
presentation duplication — e.g. mid-band With CM residual ≈213 sites, not
~2×). Demand/resolution ``BackendDefect``s are a separate hygiene axis
(``R_backend_defects``), never merged into construction R.

Behind the desugar door the membrane (sugar_lift_py_tests.desugar_axis) keeps
three quantities apart: ``R_desugar`` (typed refusals + typed red effects, keyed
by authenticated effect occurrence), ``desugarConstructionPanics``
(construction-law None arms — ``ConstructionPanic`` is a ``BaseException``,
caught BY NAME) and ``desugarDefects`` (ordinary exceptions and named audit /
instrument gaps). The last two are red and are never semantic R.

No subprocess. No process pool. Construction context is required: bare
``fn.sugar()`` with ``construction_context is None`` paints every With as
``RuntimeSelectedContextManager`` regardless of resolvability (instrument
defect). The real lift pipeline injects the same door via lift_rpc.

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
from typing import Any, Callable, TextIO


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


def _occurrence_key(
    kind: str,
    relative: str,
    *,
    node: object | None = None,
    line: object = "?",
    col: object = -1,
) -> tuple[str, str, object, object]:
    """One gap/effect occurrence = (kind, file, line, col). Never double-tally."""
    if node is not None:
        try:
            lc = node.line_col_span()  # type: ignore[attr-defined]
            return (kind, relative, lc.start_line, lc.start_col)
        except Exception:  # noqa: BLE001 -- fall back to hints
            pass
    return (kind, relative, line, col)


def _backend_defect_key(exc: object) -> str:
    """Classify demand/resolution table hygiene — never construction mass.

    The mid-band With probe surfaces two distinct BackendDefects that are
    table bijection failures, not residual construction mass:

    1. enrolled context-manager demand missing from resolution table
    2. enrolled call demand missing from resolution table

    Preserve them as separate keys so the board can track each to zero
    without conflating either with ContextManagerResolutionConstructionGap.
    """
    text = str(exc)
    name = type(exc).__name__ if not isinstance(exc, str) else "BackendDefect"
    observed = getattr(exc, "observed", None)
    if isinstance(observed, str) and observed:
        text = f"{text} {observed}"
    lowered = text.lower()
    if "context-manager demand missing" in lowered or (
        "context-manager" in lowered and "missing from resolution" in lowered
    ):
        return "BackendDefect:cm-demand-missing-from-resolution"
    if "call demand missing" in lowered or (
        "call demand" in lowered and "missing from resolution" in lowered
    ):
        return "BackendDefect:call-demand-missing-from-resolution"
    if "BackendDefect" in name or "backend defect" in lowered:
        # Always keyed `BackendDefect:<what>` — a bare "BackendDefect" would
        # collide with the axis label itself and made this key unreadable as a
        # row (its own twin asserted the prefix and was red).
        return f"BackendDefect:{name}" if name != "BackendDefect" else (
            "BackendDefect:unclassified"
        )
    return f"BackendDefect:{name}"


# The desugar membrane lives in ONE place — sugar_lift_py_tests.desugar_axis —
# so this script and `python -m sugar_lift_py_tests.census` cannot drift into
# two different definitions of R_desugar. It also owns the three separations:
# ConstructionPanic (BaseException, caught BY NAME) and ordinary defects are
# kept out of semantic R, and rows are keyed by the authenticated effect
# occurrence rather than the enclosing function's line.


def _measure_file(
    path: Path,
    *,
    relative: str,
    workspace_root: Path | None = None,
    contract_refs=None,
    on_function: "Callable[[int, int, str, float | None], None] | None" = None,
) -> dict[str, Any]:
    from sugar_lift_py_tests.audit_only import collect_construction_panic
    from sugar_lift_py_tests.desugar_axis import DesugarAxis
    from sugar_lift_py_tests.lift_rpc import (
        open_source_file_for_construction,
        tree_construction_context_for_workspace,
    )
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.reporter import CollectingReporter

    functions_total = 0
    functions_clean = 0
    families: Counter[str] = Counter()
    construction_seen: set[tuple[str, str, object, object]] = set()
    backend_defects: Counter[str] = Counter()
    desugar_axis = DesugarAxis()
    root = workspace_root if workspace_root is not None else path.parent

    def tally_construction(kind: str, node: object | None = None, line: object = "?") -> None:
        key = _occurrence_key(kind, relative, node=node, line=line)
        if key in construction_seen:
            return
        construction_seen.add(key)
        families[kind] += 1

    def construct():
        nonlocal functions_total, functions_clean
        reporter = CollectingReporter()
        # Fresh context per file so source_derived refs stay file-local; the
        # demand/gap table (contract_refs) may be shared across the census.
        construction_context = tree_construction_context_for_workspace(
            root, contract_refs=contract_refs
        )
        try:
            source_file = open_source_file_for_construction(
                path,
                root=root,
                reporter=reporter,
                construction_context=construction_context,
                populate_derived=True,
            )
        except SugarNotWritten as gap:
            # Derivation can hit a real missing sugar before any function walk.
            tally_construction(type(gap).__name__, line=0)
            return reporter
        for function in source_file.functions():
            functions_total += 1
            try:
                span = function.line_col_span()
                line: object = span.start_line
                where = f"{relative}:{span.start_line}:{span.start_col}"
            except Exception:  # noqa: BLE001 -- name is best-effort display
                line = "?"
                where = f"{relative}:?"
            fn_name = f"{getattr(function, 'name', '?')}:{line}"
            # Announce the function BEFORE constructing it (elapsed=None), so a
            # hang shows the exact function it is stuck on -- not the one before.
            if on_function is not None:
                on_function(functions_total - 1, functions_clean, fn_name, None)
            t_fn = time.perf_counter()
            try:
                sugar = function.sugar()
                functions_clean += 1
            except SugarNotWritten:
                # Do NOT tally type here — report_gap already recorded the
                # occurrence on the reporter. Catch+reporter double-tally is
                # what turned 196 With gaps into a false 392.
                sugar = None
            if sugar is not None:
                desugar_axis.measure(sugar, where=where)
            fn_s = time.perf_counter() - t_fn
            # Report completion WITH this function's own construction time, so
            # `last=` is per-function and a slow/blowup function is obvious.
            if on_function is not None:
                on_function(functions_total, functions_clean, fn_name, fn_s)
        # Sole construction-gap source: reporter occurrences, site-deduped.
        # BackendDefect is table hygiene — own counter, never construction R.
        for node, panic in reporter.gaps:
            kind = type(panic).__name__
            if kind == "BackendDefect" or "BackendDefect" in kind:
                backend_defects[_backend_defect_key(panic)] += 1
                continue
            tally_construction(kind, node=node)
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
            "backendDefects": dict(backend_defects),
            "R_backend_defects": sum(backend_defects.values()),
            **desugar_axis.row(),
        }
    return {
        "category": "completed",
        "functionsTotal": functions_total,
        "functionsClean": functions_clean,
        "families": dict(families),
        "backendDefects": dict(backend_defects),
        "R_backend_defects": sum(backend_defects.values()),
        **desugar_axis.row(),
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
        workspace_root = args.corpus
    else:
        by_file = {args.corpus.name: args.corpus}
        workspace_root = args.corpus.parent

    file_names = sorted(by_file)
    pending: list[str] = list(file_names)

    # One provisional demand→gap table for the whole corpus. Shared across files;
    # each file still gets a fresh TreeConstructionContextV1 so source-derived
    # manager refs do not leak between files.
    from sugar_lift_py_tests.lift_rpc import provisional_contract_refs_from_demands

    contract_refs = provisional_contract_refs_from_demands(workspace_root)

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
    desugar_families: Counter[str] = Counter()
    backend_defects: Counter[str] = Counter()
    # Three disjoint desugar-layer quantities; the two below are NEVER folded
    # into R_desugar and both make the run red.
    desugar_construction_panics: list[dict[str, Any]] = []
    desugar_defects: list[dict[str, Any]] = []
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
            # NOT `families`: that name is main's accumulating Counter, and
            # rebinding it to this plain dict made the later
            # `families["ConstructionPanic"] += 1` a KeyError crash — the whole
            # run lost, at the exact moment a panic row appeared.
            row_families = raw.get("families") or {}
            live_snw += int(row_families.get("SugarNotWritten") or 0)
            live_other_gaps += sum(
                int(v) for k, v in row_families.items() if k != "SugarNotWritten"
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
            ncols=320,
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

            fn_stat = {
                "slow_s": 0.0,
                "slow_name": "-",
                "fn_seen": 0,
                "fn_time": 0.0,
                "file_start": time.perf_counter(),
            }

            def _on_function(
                in_total: int, in_clean: int, fn_name: str, elapsed: "float | None"
            ) -> None:
                # live_clean/live_fns are the completed-file base; add this
                # file's running counts so `fn=` climbs per function, live.
                shown_fns = live_fns + in_total
                shown_clean = live_clean + in_clean
                clean_pct = (100.0 * shown_clean / shown_fns) if shown_fns else 0.0
                if elapsed is not None:
                    fn_stat["fn_seen"] += 1
                    fn_stat["fn_time"] += elapsed
                    if elapsed > fn_stat["slow_s"]:
                        fn_stat["slow_s"] = elapsed
                        fn_stat["slow_name"] = fn_name
                seen = fn_stat["fn_seen"] or 1
                avg = fn_stat["fn_time"] / seen
                wall = time.perf_counter() - fn_stat["file_start"]
                rate = fn_stat["fn_seen"] / wall if wall > 0 else 0.0
                post = {
                    "file": relative,
                    "func": fn_name,
                    "status": "lifting…" if elapsed is None else "ok",
                    "last": "…" if elapsed is None else f"{elapsed:.3f}s",
                    "avg": f"{avg:.3f}s",
                    "fn/s": f"{rate:.1f}",
                    "slowest": f"{fn_stat['slow_name']} {fn_stat['slow_s']:.2f}s",
                    "snw": live_snw,
                    "gaps": live_other_gaps,
                    "cpanic": live_panic,
                    "defect": live_defect,
                    "fn": f"{shown_clean}/{shown_fns}",
                    "clean%": f"{clean_pct:.0f}",
                }
                _set_bars(post, refresh=True)

            try:
                row = _measure_file(
                    path,
                    relative=relative,
                    workspace_root=workspace_root,
                    contract_refs=contract_refs,
                    on_function=_on_function,
                )
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
            other = sum(int(v) for k, v in families.items() if k != "SugarNotWritten")
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
        desugar_families.update(row.get("desugarFamilies") or {})
        backend_defects.update(row.get("backendDefects") or {})
        desugar_construction_panics.extend(row.get("desugarConstructionPanics") or [])
        desugar_defects.extend(row.get("desugarDefects") or [])
        if category == "completed":
            files_completed += 1
        elif category == "construction-panic":
            panic = row.get("panic")
            if isinstance(panic, dict):
                construction_panics.append(panic)
            # Occurrence-keyed already if present in families; avoid a bare +1
            # that has no site identity.
            if "ConstructionPanic" not in (row.get("families") or {}):
                families["ConstructionPanic"] += 1
        else:
            defect = row.get("defect")
            defects.append(
                dict(defect)
                if isinstance(defect, dict)
                else {"file": file, "type": category, "message": category}
            )
            # Demand/resolution table hygiene — own counter, not mass residual.
            # Keep CM-demand vs call-demand bijection failures separate.
            if isinstance(defect, dict):
                msg = f"{defect.get('type', '')}: {defect.get('message', '')}"
            else:
                msg = str(category)
            if "BackendDefect" in msg or "backend defect" in msg.lower() or (
                isinstance(defect, dict)
                and "BackendDefect" in str(defect.get("type", ""))
            ):
                backend_defects[_backend_defect_key(msg)] += 1
            elif category == "backend-defect":
                backend_defects[_backend_defect_key(msg)] += 1

    from pandas_floor_summary import floor_summary

    r_construction = sum(families.values())
    r_desugar = sum(desugar_families.values())
    r_backend = sum(backend_defects.values())
    result: dict[str, Any] = {
        "kind": "control-effect-construction-recensus",
        "commit": args.commit or _git_commit(args.repo),
        "corpus": str(args.corpus),
        "door": "enum:path_source→SourceFile→functions→sugar→desugar",
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
        # Axis 1 — construction totality (tree owned). Occurrence-deduped.
        # Never merge with R_desugar. Never double-count catch+reporter.
        "R": r_construction,
        "R_construction": r_construction,
        "families": dict(
            sorted(families.items(), key=lambda item: (-item[1], item[0]))
        ),
        # Axis 2 — desugar refusals + typed red (#6243). Separate quantity.
        "R_desugar": r_desugar,
        "desugarFamilies": dict(
            sorted(desugar_families.items(), key=lambda item: (-item[1], item[0]))
        ),
        # Table hygiene — not residual mass (probe: 2 BackendDefect files).
        "R_backend_defects": r_backend,
        "backendDefects": dict(
            sorted(backend_defects.items(), key=lambda item: (-item[1], item[0]))
        ),
        # Neither of these is semantic R. A construction-law None arm during
        # desugar is a construction gap; an ordinary exception is an
        # implementation defect. Both are red, separately.
        "desugarConstructionPanics": desugar_construction_panics,
        "R_desugar_construction_panics": len(desugar_construction_panics),
        "desugarDefects": desugar_defects,
        "R_desugar_defects": len(desugar_defects),
        "elapsedSeconds": time.time() - started,
        "python": sys.version,
        "floorSummary": floor_summary(
            floor="control-effect",
            files=file_names,
            rows=floor_rows,
            totals={
                "R_control_effect": r_construction + len(defects),
                "R_desugar": r_desugar,
                "R_backend_defects": r_backend,
                "desugarConstructionPanics": len(desugar_construction_panics),
                "desugarDefects": len(desugar_defects),
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
        if defects
        or construction_panics
        or desugar_construction_panics
        or desugar_defects
        or files_completed != len(file_names)
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
