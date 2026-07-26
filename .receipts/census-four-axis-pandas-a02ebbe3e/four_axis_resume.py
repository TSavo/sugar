#!/usr/bin/env python3
"""Resumable, per-file-isolated four-axis corpus census.

WHY THIS EXISTS
===============

``sugar_lift_py_tests.census`` is one process over the whole corpus. That shape
cannot answer three questions this measurement must answer:

1. ``R(timeout)`` -- a per-file wall bound needs a per-file boundary to cross.
   In one process a slow file is indistinguishable from a slow run, and the
   deadline that used to absorb ``pandas/core/generic.py`` (index 121) absorbed
   with it EVERY panic and defect row that file would have produced.
2. resume -- a killed run loses every row it measured.
3. conservation -- there is no key to reconcile two runs by.

So the parent here owns only scheduling and terminal classification; the child
is the ORIGINAL instrument, unmodified: ``fn.sugar()`` for the construction
axis and ``DesugarAxis.measure`` for the desugar axis. A ``fn.sugar()``-only
sweep reports a FALSE ZERO -- floor arms execute only inside ``measure``.

ROW IDENTITY
============

``(corpusCid, idx, rel, sha256)``. Position is not identity: the sha256 of the
file's bytes authenticates the thing measured, so a reconciliation across runs
cannot silently pair two different files that happened to sort into one slot.

Desugar rows are persisted as the (owner, occurrence) PAIRS the axis actually
deduped on -- never as a family-name histogram. The four-way split of the mixed
``R_desugar`` number is derived from the authenticated occurrence-key PREFIX
(``desugar-call:`` / ``site:`` / ``occurrence:`` / ``occurrence-cid:`` /
``boundary:`` / ``blame:``), because family-name matching cannot tell an
accounted semantic effect from an owed obligation.

TERMINAL STATUS
===============

``completed`` | ``timeout`` | ``crash`` | ``malformed``. Only ``completed``
rows may support any axis claim. A ``timeout`` row is NOT a zero -- it is an
unmeasured file, and it is counted on its own axis.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SENTINEL = "@@FOURAXIS@@"


# --------------------------------------------------------------------------
# corpus identity
# --------------------------------------------------------------------------


def corpus_files(root: Path) -> list[Path]:
    """The census's own enumeration, byte-identical in order."""
    return sorted(root.rglob("*.py"))


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def corpus_cid(root: Path, files: list[Path]) -> str:
    h = hashlib.sha256()
    for f in files:
        h.update(str(f.relative_to(root)).encode())
        h.update(b"\0")
        h.update(sha256_of(f).encode())
        h.update(b"\n")
    return h.hexdigest()


# --------------------------------------------------------------------------
# child: ONE file, the original instrument
# --------------------------------------------------------------------------


def child(root: Path, rel: str) -> int:
    sys.setrecursionlimit(100000)
    from sugar_lift_py_tests.audit_only.collect_construction_gaps import (
        collect_construction_panic,
    )
    from sugar_lift_py_tests.desugar_axis import DesugarAxis
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.tree import SourceFile

    axis = DesugarAxis()
    state = {"totalFns": 0, "cleanFns": 0, "gaps": [], "rawGapCount": 0}

    def _measure_file():
        reporter = CollectingReporter()
        sf = SourceFile.from_path(str(root / rel), reporter=reporter)
        for fn in sf.functions():
            state["totalFns"] += 1
            try:
                span = fn.line_col_span()
                where = f"{rel}:{span.start_line}:{span.start_col}"
            except Exception:  # noqa: BLE001
                where = f"{rel}:?"
            try:
                sugar = fn.sugar()  # ONE construction; nested gaps self-report
                state["cleanFns"] += 1
            except SugarNotWritten:
                sugar = None
            if sugar is not None:
                # THE desugar-inclusive door. Floor arms live only behind it.
                axis.measure(sugar, where=where)
        seen = set()
        for node, _p in reporter.gaps:
            lc = node.line_col_span()
            key = (node.kind, lc.start_line, lc.start_col)
            if key not in seen:
                seen.add(key)
                state["gaps"].append([node.kind, lc.start_line, lc.start_col])
        state["rawGapCount"] = len(reporter.gaps)
        return len(reporter.gaps)

    row: dict = {
        "rel": rel,
        "status": "completed",
        "fileConstructionPanic": None,
        "fileCrash": None,
    }
    try:
        # Sole ConstructionPanic membrane, exactly as census.py holds it.
        _, panic_row = collect_construction_panic(rel, _measure_file)
    except Exception as exc:  # noqa: BLE001 -- a crash is a DEFECT row
        row["status"] = "crash"
        row["fileCrash"] = f"{type(exc).__name__}: {exc}"
    else:
        if panic_row is not None:
            info = panic_row.info if isinstance(panic_row.info, dict) else {}
            row["fileConstructionPanic"] = {
                "owner": info.get("owner", "ConstructionPanic"),
                "message": panic_row.message,
            }

    row["totalFns"] = state["totalFns"]
    row["cleanFns"] = state["cleanFns"]
    row["constructionGaps"] = state["gaps"]
    row["rawGapCount"] = state["rawGapCount"]
    # The pairs the axis deduped on -- the authenticated occurrence identity.
    row["desugarPairs"] = sorted([list(p) for p in axis._seen])
    row["desugarPanics"] = axis.construction_panics
    row["desugarDefects"] = axis.defects
    sys.stdout.write(SENTINEL + json.dumps(row) + "\n")
    sys.stdout.flush()
    return 0


# --------------------------------------------------------------------------
# parent: scheduling, terminal classification, durable append
# --------------------------------------------------------------------------


def _load() -> float:
    try:
        return round(os.getloadavg()[0], 2)
    except OSError:
        return -1.0


def run_one(
    root: Path, idx: int, path: Path, rel: str, timeout: float, self_path: Path
) -> dict:
    key = {
        "idx": idx,
        "rel": rel,
        "sha256": sha256_of(path),
    }
    t0 = time.time()
    load_before = _load()
    cmd = [sys.executable, str(self_path), "--child", str(root), rel]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except subprocess.TimeoutExpired:
        return {
            **key,
            "status": "timeout",
            "wall": round(time.time() - t0, 2),
            "timeoutBound": timeout,
            "loadBefore": load_before,
            "loadAfter": _load(),
        }
    wall = round(time.time() - t0, 2)
    line = next(
        (
            ln[len(SENTINEL) :]
            for ln in proc.stdout.splitlines()
            if ln.startswith(SENTINEL)
        ),
        None,
    )
    if line is None:
        return {
            **key,
            "status": "malformed",
            "wall": wall,
            "exit": proc.returncode,
            "stderrTail": proc.stderr[-4000:],
            "loadBefore": load_before,
            "loadAfter": _load(),
        }
    try:
        row = json.loads(line)
    except json.JSONDecodeError as exc:
        return {
            **key,
            "status": "malformed",
            "wall": wall,
            "exit": proc.returncode,
            "decodeError": str(exc),
            "loadBefore": load_before,
            "loadAfter": _load(),
        }
    row.update(key)
    row["wall"] = wall
    row["exit"] = proc.returncode
    row["loadBefore"] = load_before
    row["loadAfter"] = _load()
    if proc.stderr.strip():
        row["stderrTail"] = proc.stderr[-2000:]
    return row


def load_checkpoint(path: Path, cid: str) -> dict[tuple[int, str, str], dict]:
    """Strict load: a foreign corpus CID or a malformed line is fatal."""
    rows: dict[tuple[int, str, str], dict] = {}
    if not path.exists():
        return rows
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        if not raw.strip():
            continue
        rec = json.loads(raw)  # a decode failure is fatal, by design
        if rec.get("corpusCid") != cid:
            raise SystemExit(
                f"REFUSED: {path}:{n} carries corpusCid={rec.get('corpusCid')!r}, "
                f"run corpus is {cid!r}. A resume across two corpora is not a resume."
            )
        key = (rec["idx"], rec["rel"], rec["sha256"])
        if key in rows:
            raise SystemExit(f"REFUSED: duplicate checkpoint key at {path}:{n}: {key}")
        rows[key] = rec
    return rows


def parent(args) -> int:
    root = Path(args.root).resolve()
    files = corpus_files(root)
    cid = corpus_cid(root, files)
    out = Path(args.checkpoint)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = load_checkpoint(out, cid)
    done_keys = set(done)

    lo, hi = args.start, args.end if args.end >= 0 else len(files) - 1
    self_path = Path(__file__).resolve()

    pending = []
    for idx in range(lo, min(hi, len(files) - 1) + 1):
        path = files[idx]
        rel = str(path.relative_to(root))
        key = (idx, rel, sha256_of(path))
        if key in done_keys:
            continue
        pending.append((idx, path, rel))

    print(
        f"corpusCid={cid}\ncorpusFiles={len(files)}\nrange=[{lo},{hi}]\n"
        f"alreadyDurable={len(done)}\npending={len(pending)}\n"
        f"timeoutBound={args.timeout}s workers={args.workers} load={_load()}",
        flush=True,
    )

    written = 0
    with open(out, "a") as sink, ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(run_one, root, i, p, r, args.timeout, self_path): (i, r)
            for i, p, r in pending
        }
        for fut in as_completed(futures):
            row = fut.result()  # infrastructure exceptions propagate: never a row
            row["corpusCid"] = cid
            row["measuredCommit"] = args.commit
            sink.write(json.dumps(row) + "\n")
            sink.flush()
            os.fsync(sink.fileno())
            written += 1
            i, r = futures[fut]
            print(
                f"[{written}/{len(pending)}] idx={i} {row['status']:9s} "
                f"{row.get('wall', 0):7.1f}s load={row.get('loadAfter')} {r}",
                flush=True,
            )

    print(f"=== SUMMARY === wrote={written} durableTotal={len(done) + written}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--child", action="store_true")
    ap.add_argument("root")
    ap.add_argument("rel", nargs="?")
    ap.add_argument("--checkpoint")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=-1)
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--commit", default="unknown")
    args = ap.parse_args()
    if args.child:
        return child(Path(args.root), args.rel)
    return parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
