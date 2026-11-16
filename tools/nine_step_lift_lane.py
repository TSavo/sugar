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
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE_TREE_SRC = REPO / "implementations/python/sugar-source-tree/src"

FILE_CAP_S_DEFAULT = 300  # the product's per-file ceiling (docs/path-forward.md)
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


def run(cmd: list[str], *, cwd: Path, timeout: float) -> tuple[int | None, str, str, float]:
    """(rc or None on timeout, stdout, stderr, seconds)."""
    t0 = time.monotonic()
    try:
        done = subprocess.run(
            cmd,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return None, out, err, time.monotonic() - t0
    return done.returncode, done.stdout, done.stderr, time.monotonic() - t0


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
    project = work / "project"
    if project.exists():
        shutil.rmtree(project)
    staged = project / root.name / rel
    staged.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, staged)
    try:
        rc, out, err, secs = run(
            [sugar_bin, "mint", "--project", str(project), "--out", str(project), "--json"],
            cwd=project,
            timeout=cap,
        )
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
            return row
        row["minted"] = True
        row["proof"] = proof.name
        members, dump_error = read_members(sugar_bin, proof, project, cap)
        if members is None:
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
        rc, out, err, secs = run(
            [sugar_bin, "prove", "--allow-failed-components", str(project), "--json"],
            cwd=project,
            timeout=cap,
        )
        report = first_object_with(out, "rows") or first_object_with(out, "verdict") or {}
        row["prove"] = {
            "rc": rc,
            "seconds": round(secs, 2),
            "verdict": report.get("verdict"),
            "byStatus": report.get("byStatus"),
            "owed": report.get("owed"),
            "discharged": report.get("discharged"),
            "error": None if report else ("timeout" if rc is None else last_line(err or out)),
        }
    finally:
        shutil.rmtree(project, ignore_errors=True)
    row["seconds"] = round(time.monotonic() - t0, 2)
    return row


def seat(args: argparse.Namespace) -> int:
    root = Path(args.corpus_root).resolve()
    files = enrolled_files(root)
    i, k = args.slice
    mine = files[i::k]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_path = out_dir / "rows.jsonl"
    done: set[str] = set()
    if rows_path.is_file():
        for line in rows_path.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["file"])
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
    sugar_bin = resolve_sugar_bin(args.sugar_bin)
    work = out_dir / "work"
    work.mkdir(exist_ok=True)
    print(
        f"{args.label} seat {i}/{k}: {len(mine)} of {len(files)} enrolled files, "
        f"{len(done)} already measured, bin={sugar_bin}",
        flush=True,
    )
    t0 = time.monotonic()
    with rows_path.open("a", encoding="utf-8") as sink:
        for n, path in enumerate(mine, 1):
            rel = path.relative_to(root).as_posix()
            if rel in done:
                continue
            try:
                row = lift_one(sugar_bin, root, path, work, args.file_cap)
            except Exception as exc:  # the instrument names its own failure
                row = {
                    "file": rel,
                    "instrumentError": f"{type(exc).__name__}: {exc}"[:ERROR_CHARS],
                }
            sink.write(json.dumps(row, sort_keys=True) + "\n")
            sink.flush()
            state = (
                "INSTRUMENT" if "instrumentError" in row
                else "lifted" if row["minted"] and not row["refusals"]
                else "minted" if row["minted"]
                else "no-proof"
            )
            print(f"[{n}/{len(mine)}] {state} {rel} {row.get('seconds', '?')}s", flush=True)
    print(f"{args.label} seat {i}/{k} done in {time.monotonic() - t0:.0f}s", flush=True)
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
