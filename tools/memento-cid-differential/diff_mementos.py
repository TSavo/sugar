#!/usr/bin/env python3
"""diff_mementos.py -- compare two JSONL memento streams produced by
memento_walker.py and report divergences by file:node_path.

Usage: diff_mementos.py <backend_a_label> <a.jsonl> <backend_b_label> <b.jsonl>

Exits 0 if the two backends agree on every node_path (same cid, same raw
span fields) across every file in the corpus. Exits 1 on any divergence,
printing each divergence as:

    DIVERGE <file>:<node_path> kind=<kind>
      <label_a>: span=(start_line,start_col)-(end_line,end_col) cid=<cid>
      <label_b>: span=(start_line,start_col)-(end_line,end_col) cid=<cid>

Also reports node_paths present in one stream but not the other (a
structural divergence -- the corresponding shape does not even exist by the
same address in the other backend), which is louder than a CID mismatch and
never silently dropped.
"""

from __future__ import annotations

import json
import sys


def load(path: str) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            record = json.loads(line)
            key = (record["file"], record["node_path"])
            if key in out:
                raise AssertionError(f"duplicate node_path key {key} in {path} -- node_path is not a valid address")
            out[key] = record
    return out


def span_tuple(record: dict) -> tuple:
    return (record["start_line"], record["start_col"], record["end_line"], record["end_col"])


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print("usage: diff_mementos.py <label_a> <a.jsonl> <label_b> <b.jsonl>", file=sys.stderr)
        return 2
    label_a, path_a, label_b, path_b = argv[1:5]
    records_a = load(path_a)
    records_b = load(path_b)

    keys_a = set(records_a)
    keys_b = set(records_b)
    only_a = sorted(keys_a - keys_b)
    only_b = sorted(keys_b - keys_a)
    common = sorted(keys_a & keys_b)

    divergences = 0

    for file, node_path in only_a:
        divergences += 1
        print(f"STRUCTURAL-ONLY-IN {label_a}: {file}:{node_path} kind={records_a[(file, node_path)]['kind']}")
    for file, node_path in only_b:
        divergences += 1
        print(f"STRUCTURAL-ONLY-IN {label_b}: {file}:{node_path} kind={records_b[(file, node_path)]['kind']}")

    for key in common:
        ra = records_a[key]
        rb = records_b[key]
        if ra["cid"] != rb["cid"] or span_tuple(ra) != span_tuple(rb) or ra["kind"] != rb["kind"]:
            divergences += 1
            file, node_path = key
            print(f"DIVERGE {file}:{node_path} kind_a={ra['kind']} kind_b={rb['kind']}")
            print(f"  {label_a}: span=({ra['start_line']},{ra['start_col']})-({ra['end_line']},{ra['end_col']}) cid={ra['cid']}")
            print(f"  {label_b}: span=({rb['start_line']},{rb['start_col']})-({rb['end_line']},{rb['end_col']}) cid={rb['cid']}")

    total_common = len(common)
    print(f"# compared: {total_common} common node_paths, {len(only_a)} only-in-{label_a}, {len(only_b)} only-in-{label_b}, {divergences} divergences")

    return 1 if divergences else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
