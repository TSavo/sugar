#!/usr/bin/env python3
"""The nine-step lane: every file of a pinned corpus through real mint + prove.

One script for every corpus (pandas, numpy, ...). A corpus is a package
directory and a label; nothing here knows which package it is reading.

Seat mode (one slice of the corpus):

    python tools/nine_step_lift_lane.py --corpus-root ROOT --label LABEL \\
        --slice I/K --out-dir DIR

For each enrolled file of slice I of K, the file alone is staged in its own
project directory at its package-relative path and the shipping binary runs
the nine steps on it: ``sugar mint`` (steps 1 to 8, the packaged ``.proof``),
``sugar dump --json`` (reads the members the proof states), and
``sugar prove`` (step 9, reads the packaged proof). One JSON row per file is
appended to ``DIR/rows.jsonl``; a re-run of the same seat skips files that
already have a row (checkpoint resume).

How a seat spends its wall (#8416 follow-up, run 43960179946 took 3 h and
left 822 of 1421 pandas files without a row):

* Files run in parallel inside the seat: ``--workers`` at once (default:
  the CPUs this process may use, bounded by available memory). A new file
  starts only while ``MemAvailable`` stays above ``--mem-floor-gb`` and the
  1-minute load stays under ``--max-load`` x CPUs (one file always runs, so
  the seat never stalls). The lane's processes raise their own
  ``oom_score_adj``, so under memory pressure the kernel takes a lane file
  (re-run once, then recorded) before it takes the runner.
* The slowest files start first: ``--prior`` names rows.jsonl files (or
  directories holding them) from an earlier run, used ONLY to order this
  seat's work (longest first); no result is carried from them. A file the
  prior has not seen is estimated from its size.
* The per-file ceiling (``--file-cap``, the product's 300 s) is one budget
  for the file: ``sugar mint`` gets all of it and ``sugar prove`` gets what
  mint left (before, mint, dump and prove each had 300 s, so one file could
  hold a seat for 900 s). ``sugar dump`` is the instrument reading the proof
  and has its own small cap. Every command runs in its own process group and
  the whole group is killed when the command ends or times out, so a kit
  plugin or solver never outlives its file.
* ``--seat-budget S``: no file starts after S minus (file ceiling + dump cap
  + margin) seconds, so every file that started finishes and is recorded
  before the seat's own cap. Files never started stay without a row and are
  counted missing by the join (never invented).

Every row carries ``status``: ``lifted``, ``refused``, ``timeout`` (mint hit
the file ceiling, or the kit's own plugin transport deadline), or ``crash``
(a panic, a signal, or the instrument's own failure). ``status`` is a label
on the row; the counts below are computed exactly as before.

Join mode (all seats):

    python tools/nine_step_lift_lane.py --join DIR1 DIR2 ... --label LABEL \\
        --enrolled N --out SUMMARY.json --refusals REFUSALS.json

writes SUMMARY.json and REFUSALS.json and prints one line:

    LABEL_lift_files=M/N LABEL_lift_funcs=F/T LABEL_refused=R

Count mode: ``--corpus-root ROOT --count`` prints the enrolled file count.

WHAT THE NUMBERS MEAN

* Enrolled files: every ``*.py`` under the corpus root, by the one
  enumeration the kit itself uses (``SourceTree.paths``: sorted, no
  ``__pycache__``). Tests are enrolled exactly as the pandas corpus enrolls
  them: nothing is excluded.
* A file is LIFTED when mint packaged a ``.proof`` for it and that proof
  states no refusal (no ``undecided`` member whose reason is ``refused``).
  An ``undecided`` member whose reason is ``unanswered`` is a call edge no
  contract in this proof answers: a call into compiled code, another file,
  or another package. That is the boundary, cited with its halt kept, and
  it is not a miss.
* REFUSED counts named refusals: every ``undecided`` member with a
  ``refused`` reason (a function, class or module body the lifter refuses
  by name, with its owner), plus one per file for which mint packaged no
  proof at all (owner ``mint-exit-<rc>`` or ``mint-timeout``).
* Functions: the denominator is every ``def`` / ``async def`` in the
  enrolled files, counted by ``ast`` from the source (independent of the
  lifter). A function is lifted when its file packaged a proof and no
  ``refused`` member names it; a file with no proof lifts none of its
  functions. Refused members with a symbol are subtracted from their file's
  ``def`` count (never below zero).

Exit code is 0 whenever the instrument itself ran; the numbers, not the exit
code, are the measurement.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE_TREE_SRC = REPO / "implementations/python/sugar-source-tree/src"

FILE_CAP_S_DEFAULT = 300  # the product's per-file ceiling (docs/path-forward.md)
DUMP_CAP_S = 120  # the instrument reading a packaged proof
ADMIT_MARGIN_S = 60  # seat-budget slack after the last file may start
KILL_GRACE_S = 10  # reading a killed command's pipes
MEM_FLOOR_GB_DEFAULT = 6.0
WORKER_MEM_GB = 2.0  # assumed peak of one file, for the default worker count
MAX_LOAD_DEFAULT = 1.25  # x CPUs: above this 1-minute load no new file starts
OOM_SCORE_ADJ = 500  # the lane's files go before the runner under OOM
KIT_DEADLINE_MARK = "transport stalled"  # the kit's own plugin deadline
OBSERVED_CHARS = 240
ERROR_CHARS = 400


# --------------------------------------------------------------------------
# Enrollment


def enrolled_files(root: Path) -> list[Path]:
    """The kit's own enumeration (``SourceTree.paths``), never a second one."""
    if str(SOURCE_TREE_SRC) not in sys.path:
        sys.path.insert(0, str(SOURCE_TREE_SRC))
    from sugar_source_tree.tree import SourceTree

    return list(SourceTree(root).paths())


def parse_slice(text: str) -> tuple[int, int]:
    index, _, count = text.partition("/")
    i, k = int(index), int(count)
    if k < 1 or not 0 <= i < k:
        raise argparse.ArgumentTypeError(f"bad --slice {text!r}: want I/K, 0<=I<K")
    return i, k


def defs_in_source(path: Path) -> tuple[int, set[str], str | None]:
    """Every def / async def in the file (count, names), or the parse error."""
    try:
        tree = ast.parse(path.read_bytes(), filename=str(path))
    except (SyntaxError, ValueError, OSError) as exc:
        return 0, set(), f"{type(exc).__name__}: {exc}"[:ERROR_CHARS]
    names: set[str] = set()
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            count += 1
            names.add(node.name)
    return count, names, None


# --------------------------------------------------------------------------
# The binary


def resolve_sugar_bin(explicit: str | None) -> str:
    if explicit:
        return explicit
    env = os.environ.get("SUGAR_BIN")
    if env:
        return env
    result = subprocess.run(
        [str(REPO / "bin/sugarbin"), "--profile", "release"],
        cwd=REPO,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"sugarbin resolve failed: {result.stderr.strip()}")
    return result.stdout.strip()


def kill_group(pgid: int) -> None:
    """SIGKILL every process left in the command's own process group."""
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run(cmd: list[str], *, cwd: Path, timeout: float) -> tuple[int | None, str, str, float]:
    """(rc or None on timeout, stdout, stderr, seconds).

    The command leads its own process group (``start_new_session``); when it
    ends or times out the whole group is killed, so the kit's plugin process
    and any solver it started never outlive the file and keep a CPU busy.
    """
    t0 = time.monotonic()
    if timeout <= 0:
        return None, "", "", 0.0
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        text=True,
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    rc: int | None
    try:
        out, err = proc.communicate(timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        kill_group(proc.pid)
        try:
            out, err = proc.communicate(timeout=KILL_GRACE_S)
        except subprocess.TimeoutExpired:
            # A process that left the group still holds the pipes.
            proc.kill()
            try:
                proc.wait(timeout=KILL_GRACE_S)
            except subprocess.TimeoutExpired:
                pass
            out, err = "", ""
        rc = None
    finally:
        kill_group(proc.pid)
    return rc, out or "", err or "", time.monotonic() - t0


def json_objects(text: str):
    """Every top-level JSON object in mixed output, in order."""
    decoder = json.JSONDecoder()
    at = 0
    while True:
        at = text.find("{", at)
        if at < 0:
            return
        try:
            value, end = decoder.raw_decode(text, at)
        except json.JSONDecodeError:
            at += 1
            continue
        if isinstance(value, dict):
            yield value
        at = end


def first_object_with(text: str, key: str) -> dict | None:
    for value in json_objects(text):
        if key in value:
            return value
    return None


def last_line(text: str) -> str:
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line:
            return line[:ERROR_CHARS]
    return ""


# --------------------------------------------------------------------------
# One file


def read_members(sugar_bin: str, proof: Path, cwd: Path, cap: float) -> tuple[dict | None, str]:
    rc, out, err, _ = run([sugar_bin, "dump", str(proof), "--json"], cwd=cwd, timeout=cap)
    if rc is None:
        return None, "dump timeout"
    if rc != 0:
        return None, f"dump rc={rc}: {last_line(err or out)}"
    payload = first_object_with(out, "members")
    if payload is None:
        return None, "dump printed no members object"
    return payload["members"], ""


def classify_members(members: dict, def_names: set[str], file_rel: str) -> dict:
    contracts = 0
    unanswered = 0
    refusals: list[dict] = []
    for member in members.values():
        header = (member or {}).get("header") or {}
        kind = header.get("kind")
        if kind == "contract":
            contracts += 1
            continue
        if kind != "undecided":
            continue
        reason = header.get("reason") or {}
        if "unanswered" in reason:
            unanswered += 1
            continue
        refused = reason.get("refused")
        if refused is None:
            continue
        symbol = header.get("symbol")
        site = header.get("site") or {}
        observed = refused.get("observed")
        if not isinstance(observed, str):
            observed = json.dumps(observed, sort_keys=True)
        tail = symbol.rsplit(".", 1)[-1] if isinstance(symbol, str) else None
        refusals.append(
            {
                "owner": str(refused.get("owner")),
                "symbol": symbol,
                "isDef": bool(tail and tail in def_names),
                "file": site.get("file") or file_rel,
                "line": site.get("startLine"),
                "observed": observed[:OBSERVED_CHARS],
            }
        )
    return {"contracts": contracts, "unanswered": unanswered, "refusals": refusals}


def lift_one(sugar_bin: str, root: Path, path: Path, work: Path, cap: float) -> dict:
    rel = path.relative_to(root).as_posix()
    defs, def_names, parse_error = defs_in_source(path)
    row: dict = {
        "file": rel,
        "defs": defs,
        "parseError": parse_error,
        "mint": None,
        "minted": False,
        "proof": None,
        "contracts": 0,
        "unanswered": 0,
        "refusals": [],
        "refusedDefs": 0,
        "prove": None,
    }
    t0 = time.monotonic()
    # One scratch directory per file: files of one seat run side by side.
    scratch = Path(tempfile.mkdtemp(prefix="file-", dir=work))
    project = scratch / "project"
    try:
        staged = project / root.name / rel
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, staged)
        rc, out, err, secs = run(
            [sugar_bin, "mint", "--project", str(project), "--out", str(project), "--json"],
            cwd=project,
            timeout=cap,
        )
        mint_secs = secs
        receipt = first_object_with(out, "proofFile") if rc == 0 else None
        proof_file = receipt.get("proofFile") if receipt else None
        proofs = sorted(project.glob("blake3-512_*.proof"))
        proof = Path(proof_file) if proof_file and Path(proof_file).is_file() else (proofs[0] if proofs else None)
        row["mint"] = {
            "rc": rc,
            "seconds": round(secs, 2),
            "error": None if rc == 0 else ("timeout" if rc is None else last_line(err or out)),
        }
        if rc != 0 or proof is None:
            owner = "mint-timeout" if rc is None else f"mint-exit-{rc}"
            if rc == 0:
                owner = "mint-no-proof"
            row["refusals"] = [
                {
                    "owner": owner,
                    "symbol": None,
                    "isDef": False,
                    "file": rel,
                    "line": None,
                    "observed": (row["mint"]["error"] or "")[:OBSERVED_CHARS],
                }
            ]
            row["seconds"] = round(time.monotonic() - t0, 2)
            row["status"] = file_status(row)
            return row
        row["minted"] = True
        row["proof"] = proof.name
        members, dump_error = read_members(sugar_bin, proof, project, min(cap, DUMP_CAP_S))
        if members is None:
            row["dumpTimeout"] = dump_error == "dump timeout"
            row["refusals"] = [
                {
                    "owner": "dump-failed",
                    "symbol": None,
                    "isDef": False,
                    "file": rel,
                    "line": None,
                    "observed": dump_error[:OBSERVED_CHARS],
                }
            ]
        else:
            got = classify_members(members, def_names, f"{root.name}/{rel}")
            row["contracts"] = got["contracts"]
            row["unanswered"] = got["unanswered"]
            row["refusals"] = got["refusals"]
            row["refusedDefs"] = sum(1 for r in got["refusals"] if r["isDef"])
        # mint and prove share the one per-file ceiling: prove gets what
        # mint left of it (the dump above is the instrument, not the file).
        prove_budget = cap - mint_secs
        rc, out, err, secs = run(
            [sugar_bin, "prove", "--allow-failed-components", str(project), "--json"],
            cwd=project,
            timeout=prove_budget,
        )
        report = first_object_with(out, "rows") or first_object_with(out, "verdict") or {}
        row["prove"] = {
            "rc": rc,
            "seconds": round(secs, 2),
            "budget": round(max(prove_budget, 0.0), 2),
            "verdict": report.get("verdict"),
            "byStatus": report.get("byStatus"),
            "owed": report.get("owed"),
            "discharged": report.get("discharged"),
            "error": None if report else ("timeout" if rc is None else last_line(err or out)),
        }
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    row["seconds"] = round(time.monotonic() - t0, 2)
    row["status"] = file_status(row)
    return row


def file_status(row: dict) -> str:
    """lifted / refused / timeout / crash: a label, never a second count.

    ``timeout``: mint hit the file ceiling, the kit's own plugin transport
    deadline fired (``transport stalled``), or the dump timed out. ``crash``:
    the instrument failed, or mint died by a panic or a signal. A file whose
    proof was packaged is lifted or refused by its members, whatever prove
    did with the time left (the prove row says that).
    """
    if "instrumentError" in row:
        return "crash"
    mint = row.get("mint") or {}
    rc = mint.get("rc")
    if not mint or rc is None:
        return "timeout"
    if rc not in (0, 1):
        return "crash"
    if rc == 1 and KIT_DEADLINE_MARK in (mint.get("error") or ""):
        return "timeout"
    if row.get("dumpTimeout"):
        return "timeout"
    if row.get("minted") and not row.get("refusals"):
        return "lifted"
    return "refused"


# --------------------------------------------------------------------------
# The host: how many files at once


def usable_cpus() -> int:
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


def mem_available_gb() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / (1024 * 1024)
    except (OSError, ValueError, IndexError):
        return None
    return None


def load_1m() -> float | None:
    try:
        return os.getloadavg()[0]
    except (AttributeError, OSError):
        return None


def default_workers(mem_floor_gb: float) -> int:
    cpus = usable_cpus()
    mem = mem_available_gb()
    if mem is None:
        return cpus
    return max(1, min(cpus, int((mem - mem_floor_gb) // WORKER_MEM_GB)))


def host_has_room(args: argparse.Namespace, cpus: int) -> tuple[bool, str]:
    mem = mem_available_gb()
    if mem is not None and mem < args.mem_floor_gb:
        return False, f"MemAvailable {mem:.1f} GB < floor {args.mem_floor_gb} GB"
    load = load_1m()
    if load is not None and load > args.max_load * cpus:
        return False, f"load {load:.1f} > {args.max_load} x {cpus} CPUs"
    return True, ""


def raise_own_oom_score() -> None:
    """Children inherit it: under OOM the kernel takes a lane file first."""
    try:
        Path("/proc/self/oom_score_adj").write_text(f"{OOM_SCORE_ADJ}\n", encoding="ascii")
    except OSError:
        pass


# --------------------------------------------------------------------------
# The order: slowest first, by an earlier run's rows (order only)


def prior_rows_files(paths: list[str]) -> list[Path]:
    found: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_file():
            found.append(path)
        elif path.is_dir():
            found.extend(sorted(path.rglob("rows.jsonl")))
    return found


def load_prior(paths: list[str]) -> dict[str, float]:
    """file -> seconds it took in an earlier run (the slowest seen wins)."""
    prior: dict[str, float] = {}
    for path in prior_rows_files(paths):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
                rel, secs = row["file"], float(row["seconds"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            prior[rel] = max(secs, prior.get(rel, 0.0))
    return prior


def slowest_first(root: Path, paths: list[Path], prior: dict[str, float]) -> list[Path]:
    """Longest estimated file first (LPT), so the tail is one short file.

    A file the prior names is estimated by its prior seconds; any other file
    by its size times the prior's seconds per byte (size alone with no prior).
    Ties keep the enrollment order.
    """
    sizes: dict[Path, int] = {}
    for path in paths:
        try:
            sizes[path] = path.stat().st_size
        except OSError:
            sizes[path] = 0
    known_secs = known_bytes = 0.0
    for path in paths:
        rel = path.relative_to(root).as_posix()
        if rel in prior:
            known_secs += prior[rel]
            known_bytes += sizes[path]
    per_byte = known_secs / known_bytes if known_bytes > 0 else 1.0

    def estimate(path: Path) -> float:
        rel = path.relative_to(root).as_posix()
        return prior[rel] if rel in prior else sizes[path] * per_byte

    order = {path: n for n, path in enumerate(paths)}
    return sorted(paths, key=lambda p: (-estimate(p), order[p]))


# --------------------------------------------------------------------------
# One seat


def read_done(rows_path: Path) -> set[str]:
    done: set[str] = set()
    if not rows_path.is_file():
        return done
    for line in rows_path.read_text(encoding="utf-8").splitlines():
        try:
            done.add(json.loads(line)["file"])
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return done


def ends_mid_line(path: Path) -> bool:
    """A seat killed mid-write leaves a partial last line."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                return False
            handle.seek(-1, os.SEEK_END)
            return handle.read(1) != b"\n"
    except OSError:
        return False


def measure(sugar_bin: str, root: Path, path: Path, work: Path, cap: float) -> dict:
    rel = path.relative_to(root).as_posix()
    try:
        return lift_one(sugar_bin, root, path, work, cap)
    except Exception as exc:  # the instrument names its own failure
        return {
            "file": rel,
            "instrumentError": f"{type(exc).__name__}: {exc}"[:ERROR_CHARS],
            "status": "crash",
        }


def killed_by_signal(row: dict) -> bool:
    rc = (row.get("mint") or {}).get("rc")
    return isinstance(rc, int) and rc < 0


def seat(args: argparse.Namespace) -> int:
    t0 = time.monotonic()
    root = Path(args.corpus_root).resolve()
    files = enrolled_files(root)
    i, k = args.slice
    mine = files[i::k]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_path = out_dir / "rows.jsonl"
    done = read_done(rows_path)
    todo = [p for p in mine if p.relative_to(root).as_posix() not in done]
    prior = load_prior(args.prior or [])
    queue = deque(slowest_first(root, todo, prior))
    sugar_bin = resolve_sugar_bin(args.sugar_bin)
    work = out_dir / "work"
    work.mkdir(exist_ok=True)
    cpus = usable_cpus()
    workers = args.workers or default_workers(args.mem_floor_gb)
    last_start = None
    if args.seat_budget:
        last_start = args.seat_budget - (args.file_cap + DUMP_CAP_S + ADMIT_MARGIN_S)
    raise_own_oom_score()
    print(
        f"{args.label} seat {i}/{k}: {len(mine)} of {len(files)} enrolled files, "
        f"{len(done)} already measured (resumed), {len(todo)} to measure; "
        f"workers={workers} cpus={cpus} mem_available_gb={mem_available_gb()} "
        f"prior_files={sum(1 for p in todo if p.relative_to(root).as_posix() in prior)} "
        f"file_cap={args.file_cap}s seat_budget={args.seat_budget or '-'}s bin={sugar_bin}",
        flush=True,
    )
    statuses: Counter[str] = Counter()
    retried: set[str] = set()
    unreached: list[str] = []
    running: dict = {}
    measured = 0
    held_since: float | None = None
    with ThreadPoolExecutor(max_workers=workers) as pool:
        if ends_mid_line(rows_path):
            with rows_path.open("a", encoding="utf-8") as sink:
                sink.write("\n")
        with rows_path.open("a", encoding="utf-8") as sink:
            while queue or running:
                # Start files while there is a worker and the host has room.
                while queue and len(running) < workers:
                    if last_start is not None and time.monotonic() - t0 > last_start:
                        unreached = [p.relative_to(root).as_posix() for p in queue]
                        queue.clear()
                        print(
                            f"seat budget: no file starts after {last_start:.0f}s; "
                            f"{len(unreached)} files unreached (no row, counted missing)",
                            flush=True,
                        )
                        break
                    if running:
                        room, why = host_has_room(args, cpus)
                        if not room:
                            if held_since is None:
                                held_since = time.monotonic()
                                print(f"holding new files: {why}", flush=True)
                            break
                    if held_since is not None:
                        print(f"resuming after {time.monotonic() - held_since:.0f}s held", flush=True)
                        held_since = None
                    path = queue.popleft()
                    future = pool.submit(measure, sugar_bin, root, path, work, args.file_cap)
                    running[future] = path
                if not running:
                    break
                finished, _ = wait(list(running), timeout=5, return_when=FIRST_COMPLETED)
                for future in finished:
                    path = running.pop(future)
                    rel = path.relative_to(root).as_posix()
                    row = future.result()
                    if killed_by_signal(row) and rel not in retried:
                        # Most likely the OOM killer under load: once more.
                        retried.add(rel)
                        queue.append(path)
                        print(f"retry {rel}: mint rc={row['mint']['rc']}", flush=True)
                        continue
                    if rel in retried:
                        row["retried"] = 1
                    sink.write(json.dumps(row, sort_keys=True) + "\n")
                    sink.flush()
                    measured += 1
                    status = row.get("status") or file_status(row)
                    statuses[status] += 1
                    print(
                        f"[{len(done) + measured}/{len(mine)}] {status} {rel} "
                        f"{row.get('seconds', '?')}s running={len(running)}",
                        flush=True,
                    )
    tally = " ".join(f"{name}={statuses[name]}" for name in ("lifted", "refused", "timeout", "crash"))
    print(
        f"{args.label} seat {i}/{k} done in {time.monotonic() - t0:.0f}s: measured={measured} "
        f"{tally} resumed={len(done)} unreached={len(unreached)}",
        flush=True,
    )
    return 0


# --------------------------------------------------------------------------
# Join


def join(args: argparse.Namespace) -> int:
    rows: dict[str, dict] = {}
    for directory in args.join:
        path = Path(directory) / "rows.jsonl"
        if not path.is_file():
            print(f"join: no rows at {path}", file=sys.stderr)
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows[row["file"]] = row
    enrolled = args.enrolled if args.enrolled is not None else len(rows)
    files_lifted = files_minted = funcs_total = funcs_lifted = 0
    instrument_errors = 0
    refusal_rows: list[dict] = []
    # A label per file (lifted / refused / timeout / crash), never a count
    # the numbers below are computed from.
    by_status: Counter[str] = Counter(
        rows[rel].get("status") or file_status(rows[rel]) for rel in rows
    )
    prove_timeouts = sum(
        1 for row in rows.values() if (row.get("prove") or {}).get("error") == "timeout"
    )
    for rel in sorted(rows):
        row = rows[rel]
        if "instrumentError" in row:
            instrument_errors += 1
            continue
        defs = int(row.get("defs") or 0)
        funcs_total += defs
        refusals = row.get("refusals") or []
        refusal_rows.extend(refusals)
        if row.get("minted"):
            files_minted += 1
            funcs_lifted += max(0, defs - int(row.get("refusedDefs") or 0))
            if not refusals:
                files_lifted += 1
    owners = Counter(r["owner"] for r in refusal_rows)
    top = owners.most_common(args.top)
    refusals_top = "; ".join(f"{owner} x{count}" for owner, count in top)
    label = args.label
    summary = {
        "label": label,
        "files_lifted": files_lifted,
        "files_total": enrolled,
        "files_minted": files_minted,
        "files_measured": len(rows),
        "files_missing": max(0, enrolled - len(rows)),
        "instrument_errors": instrument_errors,
        "funcs_lifted": funcs_lifted,
        "funcs_total": funcs_total,
        "refused": len(refusal_rows),
        "unanswered_edges": sum(int(r.get("unanswered") or 0) for r in rows.values()),
        "files_by_status": {
            name: by_status[name] for name in ("lifted", "refused", "timeout", "crash")
        },
        "prove_timeouts": prove_timeouts,
        "refusals_top": refusals_top,
        "line": (
            f"{label}_lift_files={files_lifted}/{enrolled} "
            f"{label}_lift_funcs={funcs_lifted}/{funcs_total} "
            f"{label}_refused={len(refusal_rows)}"
        ),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.refusals:
        by_owner: dict[str, list[dict]] = {}
        for r in refusal_rows:
            by_owner.setdefault(r["owner"], []).append(
                {k: r.get(k) for k in ("symbol", "file", "line", "observed")}
            )
        listing = [
            {"owner": owner, "count": count, "sites": by_owner[owner]}
            for owner, count in owners.most_common()
        ]
        Path(args.refusals).parent.mkdir(parents=True, exist_ok=True)
        Path(args.refusals).write_text(
            json.dumps({"label": label, "refusals": listing}, indent=2) + "\n",
            encoding="utf-8",
        )
    print(summary["line"], flush=True)
    print(f"{label}_refusals_top={refusals_top}", flush=True)
    print(
        f"{label}_files_minted={files_minted} {label}_files_missing={summary['files_missing']} "
        f"{label}_instrument_errors={instrument_errors} "
        f"{label}_unanswered_edges={summary['unanswered_edges']}",
        flush=True,
    )
    status_line = " ".join(f"{name}={count}" for name, count in summary["files_by_status"].items())
    print(
        f"{label}_files_by_status: {status_line} missing={summary['files_missing']} "
        f"prove_timeouts={prove_timeouts}",
        flush=True,
    )
    return 0


# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--corpus-root")
    parser.add_argument("--label", default="corpus")
    parser.add_argument("--slice", type=parse_slice, default=(0, 1))
    parser.add_argument("--out-dir")
    parser.add_argument("--sugar-bin")
    parser.add_argument("--file-cap", type=float, default=FILE_CAP_S_DEFAULT)
    parser.add_argument(
        "--workers", type=int, default=0,
        help="files at once in this seat (0: usable CPUs, bounded by memory)",
    )
    parser.add_argument("--mem-floor-gb", type=float, default=MEM_FLOOR_GB_DEFAULT)
    parser.add_argument("--max-load", type=float, default=MAX_LOAD_DEFAULT)
    parser.add_argument(
        "--seat-budget", type=float, default=0,
        help="seconds this seat may run; no file starts once the rest cannot finish",
    )
    parser.add_argument(
        "--prior", nargs="*", metavar="ROWS",
        help="rows.jsonl files or directories from an earlier run (order only)",
    )
    parser.add_argument("--count", action="store_true", help="print the enrolled file count")
    parser.add_argument("--join", nargs="+", metavar="DIR")
    parser.add_argument("--enrolled", type=int)
    parser.add_argument("--out")
    parser.add_argument("--refusals")
    parser.add_argument("--top", type=int, default=8)
    args = parser.parse_args(argv)
    if args.join:
        if not args.out:
            parser.error("--join needs --out SUMMARY.json")
        return join(args)
    if not args.corpus_root:
        parser.error("--corpus-root is required")
    if args.count:
        print(len(enrolled_files(Path(args.corpus_root).resolve())))
        return 0
    if not args.out_dir:
        parser.error("seat mode needs --out-dir")
    return seat(args)


if __name__ == "__main__":
    raise SystemExit(main())
