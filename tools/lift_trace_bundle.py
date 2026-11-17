#!/usr/bin/env python3
"""The lift-trace artifact: one file's refusals, the kit's trace, its proof.

``.github/workflows/lift-trace.yml`` puts ONE corpus file through the lane
(``tools/nine_step_lift_lane.py --only``: ``sugar mint`` then ``sugar
prove``) with the kit's refusal trace on (``SUGAR_KIT_TRACE_REFUSALS=1``,
``sugar_lift_py_tests.refusal_trace``) and then runs this script, which
writes a SMALL directory for a fix agent that can only drive CI:

* ``refusals.json``: the file's row as the lane wrote it (mint and prove
  blocks, status) and every refusal record whole (owner, symbol, file:line,
  ``observed`` to 4 KB, the kit's diagnostic for a file mint refused), each
  marked ``inFunction`` when ``--function`` is given.
* ``kit-trace.jsonl``: one line per refusal the kit raised while minting the
  file (``refusal_trace``): the testimony whole, the refusing door's names
  (``detail``: name, key, construct-time evaluation), the live items, every
  key bound on the path at the refusing read (``bindings``), the bound keys
  that share the read's evaluation (``near``), and the Python frames from the
  lift's entry to the panic (``trace``). With ``--function``, only the
  refusals whose coordinate falls inside that function (a record whose
  coordinate cannot be read is kept).
* ``kit-trace-summary.json``: the same records without ``bindings`` and
  ``trace``, for a first read.
* ``proof-dump.json``: ``sugar dump --json`` of the file's proof, trimmed to
  the members whose site lies inside the function (``--function``), or inside
  the functions the proof refuses (no ``--function``).
* ``kit-profile/``: the kit's stack sampler aggregate for the mint
  (``SUGAR_KIT_PROFILE_DIR``), when small.
* ``manifest.json``: the inputs, the counts, and what the size cap dropped.

The whole directory is kept under ``--cap-bytes`` (default 20 MB): the
refusal list first, then the trace, then the dump; whatever would cross the
cap is dropped and counted in the manifest, never cut mid-record.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import nine_step_lift_lane as lane  # noqa: E402

CAP_BYTES_DEFAULT = 20 * 1024 * 1024
PROFILE_CAP_BYTES = 2 * 1024 * 1024
BLAME_LINE_RE = re.compile(r":(\d+):(\d+)(?:-\d+:\d+)?(?:\[[^\]]*\])?\s*$")


def corpus_rel(root: Path, path: str) -> str:
    """``path`` relative to the corpus root (with or without the package)."""
    rel = path.strip("/")
    if rel.startswith(f"{root.name}/"):
        rel = rel[len(root.name) + 1:]
    return rel


def function_ranges(source: Path) -> list[tuple[str, int, int]]:
    """Every def in the file: (dotted qualname, first line, last line)."""
    try:
        tree = ast.parse(source.read_bytes(), filename=str(source))
    except (SyntaxError, ValueError, OSError):
        return []
    out: list[tuple[str, int, int]] = []

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                if not isinstance(child, ast.ClassDef):
                    first = min([child.lineno, *(d.lineno for d in child.decorator_list)])
                    out.append((name, first, child.end_lineno or child.lineno))
                walk(child, f"{name}.")
            else:
                walk(child, prefix)

    walk(tree, "")
    return out


def wanted_ranges(defs: list[tuple[str, int, int]], function: str) -> list[tuple[int, int]]:
    """The lines of ``function``: its dotted qualname (``DataFrame.merge``),
    or, when no def has that qualname, every def of that bare name."""
    exact = [(a, b) for name, a, b in defs if name == function]
    if exact:
        return exact
    tail = function.rsplit(".", 1)[-1]
    return [(a, b) for name, a, b in defs if name.rsplit(".", 1)[-1] == tail]


def innermost(defs: list[tuple[str, int, int]], line: int) -> tuple[int, int] | None:
    best = None
    for _, a, b in defs:
        if a <= line <= b and (best is None or b - a < best[1] - best[0]):
            best = (a, b)
    return best


def inside(line: int | None, ranges: list[tuple[int, int]]) -> bool:
    return line is not None and any(a <= line <= b for a, b in ranges)


def blame_line(blame: object, rel: str) -> int | None:
    """The line of a ``file:line:col`` coordinate in ``rel``; None when it
    names another file or no line."""
    if not isinstance(blame, str):
        return None
    match = BLAME_LINE_RE.search(blame)
    if not match:
        return None
    head = blame[: match.start()]
    if head and not head.endswith(rel):
        return None
    return int(match.group(1))


def site_line(member: dict) -> int | None:
    site = lane.member_field(member, "site")
    if isinstance(site, dict):
        line = site.get("startLine")
        return line if isinstance(line, int) else None
    return None


class Budget:
    def __init__(self, cap: int):
        self.left = cap
        self.dropped: dict[str, int] = {}

    def take(self, what: str, size: int) -> bool:
        if size > self.left:
            self.dropped[what] = self.dropped.get(what, 0) + 1
            return False
        self.left -= size
        return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--path", required=True, help="the corpus file, e.g. pandas/core/frame.py")
    parser.add_argument("--function", default="", help="dotted qualname or bare name (optional)")
    parser.add_argument("--state", required=True, help="the lane's --out-dir")
    parser.add_argument("--kit-trace", required=True, help="SUGAR_KIT_TRACE_DIR")
    parser.add_argument("--kit-profile", help="SUGAR_KIT_PROFILE_DIR")
    parser.add_argument("--out", required=True)
    parser.add_argument("--sugar-bin")
    parser.add_argument("--cap-bytes", type=int, default=CAP_BYTES_DEFAULT)
    args = parser.parse_args(argv)

    root = Path(args.corpus_root).resolve()
    rel = corpus_rel(root, args.path)
    staged_rel = f"{root.name}/{rel}"
    source = root / rel
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    budget = Budget(args.cap_bytes)
    defs = function_ranges(source)
    function = args.function.strip()
    ranges = wanted_ranges(defs, function) if function else []
    manifest: dict = {
        "corpusRoot": str(root),
        "path": staged_rel,
        "function": function or None,
        "functionLines": [list(r) for r in ranges],
        "capBytes": args.cap_bytes,
    }
    if function and not ranges:
        manifest["functionNote"] = f"no def named {function!r} in {staged_rel}: nothing filtered by function"

    # 1. The lane's row and its refusals, whole.
    # The final row (after prove), else the mint row (prove never wrote one).
    row = (
        lane.read_rows(Path(args.state) / "rows.jsonl").get(rel)
        or lane.read_rows(Path(args.state) / "minted.jsonl").get(rel)
    )
    refusals = list((row or {}).get("refusals") or [])
    for refusal in refusals:
        if ranges:
            refusal["inFunction"] = inside(refusal.get("line"), ranges)
    listing = {
        "path": staged_rel,
        "row": {k: v for k, v in (row or {}).items() if k not in ("refusals", "edges", "answers", "dispatchEdges")},
        "refusals": refusals,
    }
    text = json.dumps(listing, indent=2, sort_keys=True) + "\n"
    budget.take("refusals.json", len(text.encode()))  # always written: it is the point
    (out / "refusals.json").write_text(text, encoding="utf-8")
    manifest["row"] = row is not None
    manifest["refusals"] = len(refusals)

    # 2. The kit's refusal trace, filtered to the function.
    records: list[dict] = []
    for path in sorted(Path(args.kit_trace).glob("refusals-*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            at = blame_line(record.get("blame"), staged_rel)
            record["blameLine"] = at
            if ranges and at is not None and not inside(at, ranges):
                continue
            records.append(record)
    summary = [
        {k: v for k, v in record.items() if k not in ("bindings", "trace")} for record in records
    ]
    text = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if budget.take("kit-trace-summary.json", len(text.encode())):
        (out / "kit-trace-summary.json").write_text(text, encoding="utf-8")
    kept = 0
    with (out / "kit-trace.jsonl").open("w", encoding="utf-8") as sink:
        for record in records:
            line = json.dumps(record, sort_keys=True) + "\n"
            if budget.take("kit-trace record", len(line.encode())):
                sink.write(line)
                kept += 1
    manifest["kitTraceRecords"] = len(records)
    manifest["kitTraceKept"] = kept

    # 3. The proof, dumped, trimmed to the function (or the refused ones).
    stored = (row or {}).get("stored")
    proof = Path(args.state) / "store" / stored if stored else None
    if proof is None or not proof.is_file():
        manifest["proofDump"] = "no proof (mint packaged none, or the lane removed it)"
    else:
        sugar_bin = lane.resolve_sugar_bin(args.sugar_bin)
        members, error = lane.read_members(sugar_bin, proof, proof.parent, lane.DUMP_CAP_S)
        if members is None:
            manifest["proofDump"] = error
        else:
            keep_ranges = ranges
            if not keep_ranges:
                keep_ranges = [
                    r for r in (
                        innermost(defs, line) for line in (r.get("line") for r in refusals)
                        if isinstance(line, int)
                    ) if r is not None
                ]
            trimmed: dict = {}
            for cid, member in members.items():
                member = member or {}
                if not inside(site_line(member), keep_ranges):
                    continue
                size = len(json.dumps(member, sort_keys=True).encode())
                if budget.take("proof member", size):
                    trimmed[cid] = member
            dump = {
                "proof": proof.name,
                "membersTotal": len(members),
                "membersKept": len(trimmed),
                "lines": [list(r) for r in keep_ranges],
                "members": trimmed,
            }
            (out / "proof-dump.json").write_text(
                json.dumps(dump, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            manifest["proofDump"] = f"{len(trimmed)} of {len(members)} members"

    # 4. The kit's stack profile, when small.
    if args.kit_profile and Path(args.kit_profile).is_dir():
        files = [p for p in Path(args.kit_profile).rglob("*") if p.is_file()]
        size = sum(p.stat().st_size for p in files)
        if files and size <= PROFILE_CAP_BYTES and budget.take("kit-profile", size):
            shutil.copytree(args.kit_profile, out / "kit-profile", dirs_exist_ok=True)

    manifest["droppedForCap"] = budget.dropped
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"lift-trace {staged_rel} function={function or '-'}: refusals={len(refusals)} "
        f"kit_trace={kept}/{len(records)} proof_dump={manifest.get('proofDump')} "
        f"dropped_for_cap={budget.dropped or '-'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
