#!/usr/bin/env python3
"""Post (or update) this run's row on the "Main scorecard" issue.

WHY THIS EXISTS

The first scorecard run posted nothing for over an hour: the row was written
by one final job that waited for the slowest measure (the pandas board). Now
every measuring job posts as soon as it has its own number:

    main_scorecard_post.py --runs DIR --put board=board.json ...

``--put`` banks the measure's result in DIR (one directory per run on the
runner host, shared by every runner), then the row is rebuilt from every
result banked so far and written to the issue: created by the first job to
finish, edited in place by each later one. A measure that has not reported is
``?`` and named ``pending``; pending is never compared. The final job passes
``--final``: a measure that never reported is then unmeasured, and that is
compared.

Two workflows post rows: main-scorecard.yml (suite, twins, federation, rust,
tree, source) on
every merge, and main-scorecard-board.yml (the pandas board) in its own lane, so a
slow board never holds the per-merge numbers back. Each names what it measures
in SCORECARD_MEASURES. A measure outside that set is written ``-`` in the row:
it is not this workflow's number, so it is never pending, never unmeasured and
never compared. Each number is still compared with the newest earlier row that
measured it, whichever workflow wrote that row.

Regression alarm: each number is compared with the newest earlier row (another
run) where that number was measured. Any number that got worse, or that was
measured before and is unmeasured now, makes the comment start with
REGRESSION: and makes this invocation exit 1. For the suite, twins, rust, tree
and source "worse" is more failing tests; and for every measure with a total, a total
(passed + failed) more than SCORECARD_TOTAL_DROP_TOLERANCE (default 2%) below
the last measured total is a regression too (``suite total 5667 -> 4212
(shard lost?)``): counting failures alone let a lost shard post as OK (#8416).

Sticky alarm: comparing only with the previous row let a regression go
unread. The pandas board fell from 1420/1421 cpanic=0 to 1235 cpanic=181;
that row said REGRESSION once (9bd3d4dde), and every later row at 1237
cpanic=179 said OK for eight hours, because 1237 is not worse than 1235. So
each number is also compared with its best measured value since the baseline:
the lowest failing count (suite, twins, rust, tree, source), the highest total (with
the same SCORECARD_TOTAL_DROP_TOLERANCE allowance, so deleted tests do not
stick), the highest board completed, the lowest cpanic, and federation PASS.
Any number worse than its best makes the comment start ``STILL REGRESSED:``,
naming the number, its best and the row where the best was measured
(``board 1237 < best 1420 @4c041edf1; cpanic 179 > best 0 @4c041edf1``),
and this invocation exit 1; it never says OK. A fresh drop against the
previous row still starts ``REGRESSION:`` (and a number already named there
is not repeated under STILL REGRESSED). Best is read per measure from the rows
that measured it, so the board's best comes from the board lane's rows and the
suite's from the fast lane's rows.

Baseline: best is read from every row on the issue (all comments are paged
in), unless someone resets it on purpose by writing a comment on the issue
with a line

    scorecard-baseline: <sha> [measure,measure,...]

(sha: 7 to 40 hex characters; measures default to all). From then on, those
measures' best is read only from the rows starting at the first row measured
at <sha> (or, when no row has that sha, from the rows written after the
marker comment). The newest marker naming a measure wins.

Comment shape (first line, then one machine-readable line of key=value):
  OK ... | REGRESSION: ... | STILL REGRESSED: ... ; then
  sha= prev= run= suite=p/t twins=p/t federation= rust=p/t tree=p/t source=p/t
  board=c/t cpanic= [<label>_lift_files=m/n <label>_lift_funcs=f/t <label>_refused=
  <label>_lift_ierr= <label>_lift_missing= ...] issues= prs= pending= rerun=
  carried= wall=

``rerun=`` and ``carried=`` keep their shape (``suite:N,twins:N,board:N``),
but nothing is carried any more (#8416): rerun is each measure's total and
carried is 0.

``rust`` is the Rust unit and integration tests (``cargo test``) of the crates
on the Python proof path. Rows written before it existed have no ``rust=``
key: they still parse (``rust`` is not in ROW_KEYS) and count as not measured.

``tree`` is the sugar-source-tree package's own tests
(implementations/python/sugar-source-tree/tests), which ran in no CI job
before; they run on the suite's shards (tools/main_scorecard_suite.sh) but are
their own number, so ``suite=`` stays comparable with earlier rows. Like the
suite, the alarm fires when tree failing rises or its total falls beyond the
tolerance. Rows written before it existed have no ``tree=`` key and count as
not measured.

``source`` is the sugar-lift-python-source package's own tests
(implementations/python/sugar-lift-python-source/tests), which ran only under
``make test-python``, which no workflow calls. Like ``tree`` they run on the
suite's shards and are their own number; the alarm (REGRESSION and STILL
REGRESSED) fires when source failing rises or its total falls beyond the
tolerance. Rows written before it existed have no ``source=`` key and count as
not measured.

Lanes: a corpus through the nine steps (docs/path-forward.md). The board
(``board=``) only builds trees and never reduces, so it cannot say how much
of a corpus goes through; a lane can. tools/nine_step_lift_lane.py puts every
file of a corpus through ``sugar mint`` and ``sugar prove`` (the commands the
solver twins and examples/python-base64-federation/run.sh use) and its join
writes one SUMMARY.json naming its ``label``. A workflow whose
SCORECARD_MEASURES names ``lift`` posts it with

    main_scorecard_post.py --runs DIR --lane SUMMARY.json [--lane ...]

A row carries only the labels this run banked, plus any SCORECARD_LANES
names as expected (``pandas``); so a pandas-only or a numpy-only row never
compares the other label's cells. Each label writes its own cells, one way
for every corpus:

  ``<label>_lift_files=M/N``  files minted to a ``.proof`` that states no
                              refusal, of the enrolled files
  ``<label>_lift_funcs=F/T``  functions of minted files that no refusal names
  ``<label>_refused=R``       refusals by name (``undecided`` members whose
                              reason is ``refused``, plus a file mint packaged
                              no proof for)
  ``<label>_lift_ierr=I``     files the instrument failed on
  ``<label>_lift_missing=X``  enrolled files with no row (a lost seat)

plus a ``<label>_refusals_top`` note line. Instrument errors and missing
files are shown, never counted as lifted (and their functions are outside
T). An owed member or an unbound edge (a call into numpy) is carried, not
refused. The alarm (REGRESSION and STILL REGRESSED, best since the baseline,
per label) reads lift_files and lift_funcs as higher is better and refused as
lower is better. A missing or unreadable SUMMARY.json is that lane
unmeasured (its label: the one SCORECARD_LANES names, else the summary's
directory spelled ``<label>-...``); an expected label that never reported is
pending, then unmeasured under ``--final``. ``scorecard-baseline: <sha>
<label>_lift`` resets one lane's best; ``lift``, or a marker naming no
measure, resets every lane.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MEASURES = ("suite", "twins", "federation", "board", "rust", "tree", "source", "lift")
# `lift` is the nine-step lanes: it owns no row cell of its own; each lane
# label writes its own `<label>_...` cells (see "Lanes" above).
CELL_MEASURES = MEASURES[:-1]
# Required for a comment to count as a row. `rust`, `tree` and `source` are
# read optionally: rows written before they existed have no such key and must
# still parse.
ROW_KEYS = ("sha", "prev", "run", "suite", "twins", "federation", "board", "cpanic")
# A measure's total (passed + failed) may fall by this fraction against the
# newest earlier row that measured it (tests deleted); more is a regression.
TOTAL_DROP_TOLERANCE = float(os.environ.get("SCORECARD_TOTAL_DROP_TOLERANCE") or "0.02")
# Measures whose cell is passed/total and whose alarm is "more failing".
FAILING_MEASURES = ("suite", "twins", "rust", "tree", "source")
# A human or coordinator resets the best on purpose with this line.
BASELINE_RE = re.compile(
    r"^[ \t]*scorecard-baseline:[ \t]*([0-9a-fA-F]{7,40})(?:[ \t]+([a-z][a-z0-9_, \t]*?))?[ \t]*$",
    re.MULTILINE,
)
# A lane's label (SCORECARD_LANES, a SUMMARY.json's `label`), and the cells
# one lane writes in a row.
LABEL_RE = re.compile(r"[a-z][a-z0-9]*")
LANE_CELL_RE = re.compile(r"([a-z][a-z0-9]*)_lift_files")
# The SUMMARY.json keys a lane needs to count as measured.
LANE_KEYS = (
    "files_lifted", "files_total", "funcs_lifted", "funcs_total",
    "refused", "instrument_errors", "files_missing",
)


def lane_token(label: str) -> str:
    """A lane's name in a baseline marker, a pending list and the window."""
    return f"{label}_lift"


def lane_label(token: str) -> str | None:
    """The label a ``<label>_lift`` token names, or None."""
    if token.endswith("_lift") and LABEL_RE.fullmatch(token[: -len("_lift")]):
        return token[: -len("_lift")]
    return None


def gh(*args: str) -> str | None:
    """Run gh; return its stdout, or None when it fails (printed)."""
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True)
    except OSError as exc:
        print(f"::warning::gh unavailable: {exc}")
        return None
    if r.returncode != 0:
        print(f"::warning::gh {' '.join(args[:2])} failed: {r.stderr.strip()[:300]}")
        return None
    return r.stdout.strip()


def num(value: object) -> str:
    text = str(value if value is not None else "").strip()
    return text if text.isdigit() else "?"


def parse_row(body: str) -> dict[str, str] | None:
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("sha="):
            continue
        fields = {}
        for token in line.split(" "):
            key, sep, value = token.partition("=")
            if sep:
                fields[key] = value
        if all(k in fields for k in ROW_KEYS):
            return fields
    return None


def parse_baselines(body: str) -> list[tuple[str, tuple[str, ...]]]:
    """The ``scorecard-baseline: <sha> [measures]`` lines of a comment."""
    markers = []
    for match in BASELINE_RE.finditer(body):
        sha = match.group(1).lower()
        named = [m for m in re.split(r"[,\s]+", match.group(2) or "") if m]
        if not named:
            markers.append((sha, MEASURES))
            continue
        known = tuple(m for m in MEASURES if m in named) + tuple(
            m for m in named if lane_label(m) is not None
        )
        unknown = [m for m in named if m not in MEASURES and lane_label(m) is None]
        if unknown or not known:
            print(f"::warning::ignored scorecard-baseline line naming {unknown}: {match.group(0).strip()}")
            continue
        markers.append((sha, known))
    return markers


def read_history(
    bodies: list[str], run_id: str
) -> tuple[list[dict[str, str]], dict[str, list[dict[str, str]]], dict[str, str]]:
    """Read the issue's comments (oldest first) into the rows to compare with.

    Returns the earlier rows (other runs), newest first; for each measure, the
    rows its best is read from (since its baseline), newest first; and each
    reset measure's baseline sha.
    """
    rows: list[tuple[int, dict[str, str]]] = []
    markers: list[tuple[int, str, tuple[str, ...]]] = []
    for index, body in enumerate(bodies):
        row = parse_row(body)
        if row is not None:
            if row.get("run") != run_id:
                rows.append((index, row))
            continue
        for sha, measures in parse_baselines(body):
            markers.append((index, sha, measures))
    start = {m: 0 for m in MEASURES}
    # Lanes are named by the rows themselves: a marker naming no measure
    # resets every lane (lanes_start), a `<label>_lift` marker one lane.
    lanes_start = 0
    lane_start: dict[str, int] = {}
    baseline: dict[str, str] = {}
    for index, sha, measures in markers:  # oldest first: the newest marker wins
        at = next((j for j, row in rows if j < index and row["sha"].lower().startswith(sha)), index)
        if measures == MEASURES or "lift" in measures:
            lanes_start, lane_start = at, {}
        for measure in measures:
            label = lane_label(measure)
            if label is not None:
                lane_start[label] = at
            else:
                start[measure] = at
            baseline[measure] = sha
    earlier = [row for _, row in reversed(rows)]
    window = {m: [row for j, row in reversed(rows) if j >= start[m]] for m in MEASURES}
    labels = sorted({
        match.group(1)
        for _, row in rows
        for key in row
        if (match := LANE_CELL_RE.fullmatch(key))
    })
    for label in labels:
        begin = lane_start.get(label, lanes_start)
        window[lane_token(label)] = [row for j, row in reversed(rows) if j >= begin]
    return earlier, window, baseline


def split_pair(cell: str) -> tuple[int, int] | None:
    pieces = cell.split("/")
    if len(pieces) == 2 and pieces[0].isdigit() and pieces[1].isdigit():
        return int(pieces[0]), int(pieces[1])
    return None


def judge(
    current: dict[str, str],
    earlier: list[dict[str, str]],
    window: dict[str, list[dict[str, str]]],
    skip: set[str] | frozenset[str] = frozenset(),
    lanes: tuple[str, ...] | list[str] = (),
) -> tuple[list[str], list[str]]:
    """Compare this row's cells with the previous measured rows and with the best.

    ``current`` holds this row's cells by row key (suite, twins, rust, tree,
    source, board, cpanic, federation, and each lane's ``<label>_lift_files``,
    ``<label>_lift_funcs``, ``<label>_refused``); ``skip`` names measures that
    are pending or not this workflow's; ``lanes`` names the lane labels to
    compare (this workflow's, reported). Returns (fresh drops against the
    previous measured row, numbers still worse than their best since the
    baseline).
    """
    drops: dict[tuple[str, str], str] = {}
    still: dict[tuple[str, str], str] = {}

    def newest(rows: list[dict[str, str]], read) -> object | None:
        for row in rows:
            value = read(row)
            if value is not None:
                return value
        return None

    def best(rows: list[dict[str, str]], read, better) -> tuple[int, str] | None:
        """Best value and the sha of the newest row that measured it."""
        found: tuple[int, str] | None = None
        for row in rows:  # newest first: a tie keeps the newest row
            value = read(row)
            if value is not None and (found is None or better(value, found[0])):
                found = (value, row.get("sha", "?"))
        return found

    def failing(row: dict[str, str], key: str) -> int | None:
        pair = split_pair(row.get(key, ""))
        return pair[1] - pair[0] if pair else None

    def total(row: dict[str, str], key: str) -> int | None:
        pair = split_pair(row.get(key, ""))
        return pair[1] if pair else None

    def digit(row: dict[str, str], key: str, part: int | None = None) -> int | None:
        value = row.get(key, "")
        if part is not None:
            pieces = value.split("/")
            value = pieces[part] if len(pieces) > part else ""
        return int(value) if value.isdigit() else None

    lower = lambda a, b: a < b  # noqa: E731
    higher = lambda a, b: a > b  # noqa: E731

    for m in FAILING_MEASURES:
        if m in skip:
            continue
        cur = split_pair(current.get(m, ""))
        before = newest(earlier, lambda r: failing(r, m))
        if before is not None:
            if cur is None:
                drops[(m, "failing")] = f"{m} unmeasured (was {before} failing)"
            elif cur[1] - cur[0] > before:
                drops[(m, "failing")] = f"{m} failing {before} -> {cur[1] - cur[0]}"
        top = best(window[m], lambda r: failing(r, m), lower)
        if cur is not None and top is not None and cur[1] - cur[0] > top[0]:
            still[(m, "failing")] = f"{m} failing {cur[1] - cur[0]} > best {top[0]} @{top[1][:9]}"

    for m in FAILING_MEASURES + ("board",):
        if m in skip:
            continue
        cur = split_pair(current.get(m, ""))
        if cur is None:
            continue
        floor = 1.0 - TOTAL_DROP_TOLERANCE
        before = newest(earlier, lambda r: total(r, m))
        if before is not None and cur[1] < before * floor:
            drops[(m, "total")] = f"{m} total {before} -> {cur[1]} (shard lost?)"
        top = best(window[m], lambda r: total(r, m), higher)
        if top is not None and cur[1] < top[0] * floor:
            still[(m, "total")] = (
                f"{m} total {cur[1]} < best {top[0]} @{top[1][:9]} "
                f"(beyond {TOTAL_DROP_TOLERANCE:.0%})"
            )

    if "board" not in skip:
        cur_done = digit(current, "board", 0)
        before = newest(earlier, lambda r: digit(r, "board", 0))
        if before is not None:
            if cur_done is None:
                drops[("board", "completed")] = f"board completed unmeasured (was {before})"
            elif cur_done < before:
                drops[("board", "completed")] = f"board completed {before} -> {cur_done}"
        top = best(window["board"], lambda r: digit(r, "board", 0), higher)
        if cur_done is not None and top is not None and cur_done < top[0]:
            still[("board", "completed")] = f"board {cur_done} < best {top[0]} @{top[1][:9]}"

        cur_panic = digit(current, "cpanic")
        before = newest(earlier, lambda r: digit(r, "cpanic"))
        if before is not None:
            if cur_panic is None:
                drops[("board", "cpanic")] = f"board cpanic unmeasured (was {before})"
            elif cur_panic > before:
                drops[("board", "cpanic")] = f"board cpanic {before} -> {cur_panic}"
        top = best(window["board"], lambda r: digit(r, "cpanic"), lower)
        if cur_panic is not None and top is not None and cur_panic > top[0]:
            still[("board", "cpanic")] = f"cpanic {cur_panic} > best {top[0]} @{top[1][:9]}"

    for label in lanes:
        # A lane: more files and functions lifted is better, more refusals by
        # name is worse. Each cell is compared with the newest earlier row
        # that measured it and with its best since the baseline.
        for key, part, better, sign in (
            (f"{label}_lift_files", 0, higher, "<"),
            (f"{label}_lift_funcs", 0, higher, "<"),
            (f"{label}_refused", None, lower, ">"),
        ):
            read = lambda r, key=key, part=part: digit(r, key, part)  # noqa: E731
            cur = read(current)
            before = newest(earlier, read)
            if before is not None:
                if cur is None:
                    drops[(label, key)] = f"{key} unmeasured (was {before})"
                elif better(before, cur):
                    drops[(label, key)] = f"{key} {before} -> {cur}"
            top = best(window.get(lane_token(label), []), read, better)
            if cur is not None and top is not None and better(top[0], cur):
                still[(label, key)] = f"{key} {cur} {sign} best {top[0]} @{top[1][:9]}"

    if "federation" not in skip:
        fed = current.get("federation", "?")
        verdict = lambda r: r.get("federation") if r.get("federation") in ("PASS", "FAIL") else None  # noqa: E731
        if newest(earlier, verdict) == "PASS" and fed != "PASS":
            drops[("federation", "verdict")] = (
                f"federation PASS -> {fed if fed in ('PASS', 'FAIL') else 'unmeasured'}"
            )
        passed = next((r for r in window["federation"] if verdict(r) == "PASS"), None)
        if fed == "FAIL" and passed is not None:
            still[("federation", "verdict")] = f"federation FAIL, best PASS @{passed.get('sha', '?')[:9]}"

    return list(drops.values()), [text for key, text in still.items() if key not in drops]


def headline(
    drops: list[str],
    still: list[str],
    *,
    prev_error: bool = False,
    first: bool = False,
    pending: list[str] | None = None,
    range_txt: str = "",
    baseline: dict[str, str] | None = None,
) -> str:
    """The comment's first line: OK, REGRESSION:, STILL REGRESSED: or UNCOMPARED."""
    tail = f" | pending: {', '.join(pending)}" if pending else ""
    if baseline:
        by_sha: dict[str, list[str]] = {}
        for measure, sha in baseline.items():
            by_sha.setdefault(sha[:9], []).append(measure)
        tail += " | baseline " + ", ".join(f"{','.join(ms)}@{sha}" for sha, ms in by_sha.items())
    if range_txt:
        tail += f" | {range_txt}"
    if prev_error:
        return f"UNCOMPARED: the previous rows could not be read{tail}"
    parts = []
    if drops:
        parts.append("REGRESSION: " + "; ".join(drops))
    if still:
        parts.append("STILL REGRESSED: " + "; ".join(still))
    if parts:
        return " | ".join(parts) + tail
    if first:
        return f"OK first machine-readable row, nothing to compare{tail}"
    return f"OK all measured numbers held or improved and none is below its best{tail}"


class Lock:
    def __init__(self, path: Path):
        self.path = path

    def __enter__(self) -> None:
        deadline = time.time() + 240
        while True:
            try:
                self.path.mkdir()
                return
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > 600:
                        shutil.rmtree(self.path, ignore_errors=True)
                        continue
                except OSError:
                    continue
                if time.time() > deadline:
                    print(f"::warning::post lock {self.path} held too long; posting anyway")
                    return
                time.sleep(1)

    def __exit__(self, *exc: object) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


def own_measures() -> tuple[str, ...]:
    """The measures this workflow reports (SCORECARD_MEASURES; default: all)."""
    raw = os.environ.get("SCORECARD_MEASURES", "").strip()
    if not raw:
        return MEASURES
    named = tuple(m.strip() for m in raw.split(",") if m.strip())
    unknown = [m for m in named if m not in MEASURES]
    if unknown or not named:
        sys.exit(f"::error::bad SCORECARD_MEASURES {raw!r}")
    return tuple(m for m in MEASURES if m in named)


def own_lanes() -> tuple[str, ...]:
    """The lane labels this workflow reports (SCORECARD_LANES; default none)."""
    raw = os.environ.get("SCORECARD_LANES", "").strip()
    named = tuple(label.strip() for label in raw.split(",") if label.strip())
    bad = [label for label in named if not LABEL_RE.fullmatch(label)]
    if bad:
        sys.exit(f"::error::bad SCORECARD_LANES {raw!r}")
    return tuple(dict.fromkeys(named))


def row_measured(row: dict[str, str], measure: str) -> bool:
    """Whether a row measured a measure, or a lane (by its `<label>_lift` token)."""
    label = lane_label(measure)
    key = f"{label}_lift_files" if label is not None else measure
    value = row.get(key, "").split("/")[0]
    return value.isdigit() or value in ("PASS", "FAIL")


def lane_result(summary: object) -> dict:
    """A lane's banked result from its SUMMARY.json (measured only when whole)."""
    if not isinstance(summary, dict):
        return {"measured": False, "note": "lane summary is not an object"}
    lacking = [k for k in LANE_KEYS if not isinstance(summary.get(k), int)]
    if lacking:
        return {"measured": False, "note": "lane summary lacks " + ", ".join(lacking)}
    result = {k: summary[k] for k in LANE_KEYS}
    for key in ("files_minted", "unanswered_edges"):
        if isinstance(summary.get(key), int):
            result[key] = summary[key]
    result["refusals_top"] = str(summary.get("refusals_top") or "none")
    result["measured"] = True
    return result


def missing_lane_label(source: str) -> str | None:
    """The label of a lane whose SUMMARY.json is missing: the one label in
    SCORECARD_LANES, else the summary's directory spelled ``<label>[-...]``
    (``numpy-lift/summary.json`` is numpy's)."""
    named = own_lanes()
    if len(named) == 1:
        return named[0]
    head = Path(source).parent.name.split("-", 1)[0]
    if LABEL_RE.fullmatch(head) and (not named or head in named):
        return head
    return None


def load_lanes(runs: Path, final: bool) -> tuple[dict[str, dict], list[str]]:
    """The lanes this row carries: every lane banked for this run, and each
    label SCORECARD_LANES expects (pending, or unmeasured under --final).
    Only a workflow that owns ``lift`` carries lanes; a row carries only its
    own labels, so it never compares another label's cells."""
    if "lift" not in own_measures():
        return {}, []
    results: dict[str, dict] = {}
    for directory in reversed(attempt_dirs(runs)):  # this attempt wins
        for path in sorted(directory.glob("lane-*.json")):
            label = path.stem[len("lane-"):]
            if not LABEL_RE.fullmatch(label):
                continue
            try:
                results[label] = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
    pending: list[str] = []
    for label in own_lanes():
        if label in results:
            continue
        if final:
            results[label] = {"measured": False, "note": "lane did not report"}
        else:
            pending.append(lane_token(label))
            results[label] = {}
    if not results and not final:
        pending.append("lift")
    return dict(sorted(results.items())), pending


def attempt_dirs(runs: Path) -> list[Path]:
    """This attempt's result directory, then the run's earlier attempts', newest first.

    SCORECARD_RUNS is ``<run id>-<attempt>``. "Re-run failed jobs" re-runs only
    the jobs that failed (a lost suite shard, the join, the final row); the
    numbers the other jobs banked in an earlier attempt still belong to this
    run's commit, so they are read from there rather than called unmeasured.
    """
    match = re.fullmatch(r"(.+)-(\d+)", runs.name)
    if not match:
        return [runs]
    base, attempt = match.group(1), int(match.group(2))
    return [runs] + [runs.parent / f"{base}-{k}" for k in range(attempt - 1, 0, -1)]


def load_results(runs: Path, final: bool) -> tuple[dict[str, dict], list[str]]:
    results: dict[str, dict] = {}
    pending: list[str] = []
    own = own_measures()
    for measure in CELL_MEASURES:
        if measure not in own:
            results[measure] = {}
            continue
        for directory in attempt_dirs(runs):
            try:
                results[measure] = json.loads((directory / f"{measure}.json").read_text())
                break
            except (OSError, ValueError):
                continue
        else:
            if final:
                results[measure] = {"measured": False, "note": "job did not report"}
            else:
                pending.append(measure)
                results[measure] = {}
    return results, pending


def run_wall(repo: str, run_id: str) -> str:
    created = gh("api", f"repos/{repo}/actions/runs/{run_id}", "--jq", ".created_at")
    if not created:
        return "?"
    try:
        start = datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return "?"
    return f"{int((datetime.now(timezone.utc) - start).total_seconds())}s"


def read_comments(owner: str, name: str, issue: str) -> list[dict] | None:
    """Every comment on the scorecard issue, oldest first; None when unreadable.

    Paged backwards 100 at a time: the best since the baseline needs the whole
    history, not only the newest 100 comments.
    """
    query = (
        "query($o:String!,$r:String!,$n:Int!,$b:String){repository(owner:$o,name:$r)"
        "{issue(number:$n){comments(last:100,before:$b){"
        "pageInfo{hasPreviousPage startCursor} nodes{databaseId body}}}}}"
    )
    pages: list[list[dict]] = []
    before: str | None = None
    for _ in range(200):
        args = ["api", "graphql", "-f", f"query={query}",
                "-f", f"o={owner}", "-f", f"r={name}", "-F", f"n={issue}"]
        if before:
            args += ["-f", f"b={before}"]
        raw = gh(*args)
        if raw is None:
            return None
        try:
            comments = json.loads(raw)["data"]["repository"]["issue"]["comments"]
        except (ValueError, KeyError, TypeError):
            print("::warning::unreadable scorecard comment page")
            return None
        pages.append(comments.get("nodes") or [])
        info = comments.get("pageInfo") or {}
        before = info.get("startCursor")
        if not info.get("hasPreviousPage") or not before:
            break
    return [node for page in reversed(pages) for node in page]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", required=True, help="this run's shared result directory")
    parser.add_argument("--put", action="append", default=[], metavar="MEASURE=FILE")
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="MEASURE.KEY[.KEY]=VALUE",
        help="build a measure's result from values (measured=true unless set)",
    )
    parser.add_argument(
        "--lane",
        action="append",
        default=[],
        metavar="SUMMARY.json",
        help="bank a nine-step lane's join summary (tools/nine_step_lift_lane.py) under its label",
    )
    parser.add_argument("--final", action="store_true")
    parser.add_argument("--no-post", action="store_true", help="bank only")
    args = parser.parse_args(argv)

    env = os.environ
    repo = env["GITHUB_REPOSITORY"]
    run_id = env["GITHUB_RUN_ID"]
    sha = env.get("GITHUB_SHA") or "?"
    title = env.get("SCORECARD_ISSUE_TITLE") or "Main scorecard"
    run_url = f"{env.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{run_id}"
    runs = Path(args.runs)
    runs.mkdir(parents=True, exist_ok=True)

    for item in args.put:
        measure, _, source = item.partition("=")
        if measure not in CELL_MEASURES:
            sys.exit(f"::error::unknown measure {measure!r}")
        tmp = runs / f".{measure}.{os.getpid()}.tmp"
        shutil.copyfile(source, tmp)
        os.replace(tmp, runs / f"{measure}.json")
    built: dict[str, dict] = {}
    for item in args.set:
        path, _, value = item.partition("=")
        measure, *keys = path.split(".")
        if measure not in CELL_MEASURES or not keys:
            sys.exit(f"::error::bad --set {item!r}")
        target = built.setdefault(measure, {"measured": True})
        for key in keys[:-1]:
            target = target.setdefault(key, {})
        parsed: object = value
        if value.isdigit():
            parsed = int(value)
        elif value in ("true", "false"):
            parsed = value == "true"
        target[keys[-1]] = parsed
    t0 = env.get("JOB_T0", "")
    for measure, result in built.items():
        if t0 and "jobWallSeconds" not in result:
            result["jobWallSeconds"] = int(time.time() - float(t0))
        tmp = runs / f".{measure}.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(result, sort_keys=True) + "\n")
        os.replace(tmp, runs / f"{measure}.json")
    for source in args.lane:
        try:
            summary = json.loads(Path(source).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            # A missing or unreadable summary is the lane unmeasured, under the
            # label its workflow expects.
            label = missing_lane_label(source)
            if label is None:
                print(f"::warning::lane summary {source!r} unreadable and its label unknown")
                continue
            result = {
                "measured": False,
                "note": f"lane summary {source} unreadable ({type(error).__name__})",
            }
        else:
            label = summary.get("label") if isinstance(summary, dict) else None
            if not isinstance(label, str) or not LABEL_RE.fullmatch(label):
                sys.exit(f"::error::lane summary {source!r} has no valid label: {label!r}")
            result = lane_result(summary)
        if t0:
            result["jobWallSeconds"] = int(time.time() - float(t0))
        tmp = runs / f".lane-{label}.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(result, sort_keys=True) + "\n")
        os.replace(tmp, runs / f"lane-{label}.json")
    if args.no_post:
        return 0

    with Lock(runs / ".post.lock"):
        return post(repo, run_id, sha, title, run_url, runs, args.final)


def post(repo: str, run_id: str, sha: str, title: str, run_url: str, runs: Path, final: bool) -> int:
    results, pending = load_results(runs, final)
    lanes, lanes_pending = load_lanes(runs, final)
    pending = pending + lanes_pending
    suite, twins, fed_r, board, rust, tree, source = (
        results[m] for m in ("suite", "twins", "federation", "board", "rust", "tree", "source")
    )
    own = own_measures()
    # Lanes reported by this run (pending ones are written `?` and not compared).
    reported_lanes = [label for label in lanes if lane_token(label) not in lanes_pending]

    def lane_cells(label: str) -> dict[str, str]:
        result = lanes[label]
        if not result.get("measured"):
            files = funcs = "?/?"
            refused = ierr = missing = "?"
        else:
            files = f"{num(result.get('files_lifted'))}/{num(result.get('files_total'))}"
            funcs = f"{num(result.get('funcs_lifted'))}/{num(result.get('funcs_total'))}"
            refused = num(result.get("refused"))
            ierr = num(result.get("instrument_errors"))
            missing = num(result.get("files_missing"))
        return {
            f"{label}_lift_files": files,
            f"{label}_lift_funcs": funcs,
            f"{label}_refused": refused,
            f"{label}_lift_ierr": ierr,
            f"{label}_lift_missing": missing,
        }

    lane_row = {key: value for label in lanes for key, value in lane_cells(label).items()}
    # Not this workflow's number: written "-", never pending, never compared.
    outside = [m for m in MEASURES if m not in own]

    def pair(measure: str, done: str, total: str) -> tuple[str, str]:
        result = results[measure]
        if measure in outside:
            return "-", "-"
        if not result.get("measured"):
            return "?", "?"
        return num(result.get(done)), num(result.get(total))

    suite_pass, suite_total = pair("suite", "passed", "total")
    twins_pass, twins_total = pair("twins", "passed", "total")
    if twins_total == "0":
        twins_pass = twins_total = "?"
    rust_pass, rust_total = pair("rust", "passed", "total")
    if rust_total == "0":
        rust_pass = rust_total = "?"
    tree_pass, tree_total = pair("tree", "passed", "total")
    source_pass, source_total = pair("source", "passed", "total")
    fed =fed_r.get("verdict") if fed_r.get("measured") else "?"
    fed = fed if fed in ("PASS", "FAIL") else "?"
    if "federation" in outside:
        fed = "-"
    board_done, board_total = pair("board", "completed", "total")
    cpanic = num(board.get("cpanic")) if board.get("measured") else "?"
    if "board" in outside:
        cpanic = "-"

    issues = num(gh("issue", "list", "--state", "open", "--limit", "10000",
                    "--json", "number", "--jq", "length"))

    issue = gh("issue", "list", "--state", "open",
               "--search", f'"{title}" in:title', "--json", "number,title",
               "--jq", f'map(select(.title == "{title}")) | .[0].number // empty')
    if issue is None:
        print("::error::could not list issues to find the scorecard issue")
        return 1
    if not issue:
        url = gh("issue", "create", "--title", title, "--body",
                 "One row per run of .github/workflows/main-scorecard.yml (suite, "
                 "twins, federation, rust, tree, source) and of main-scorecard-board.yml (the pandas "
                 "board and its nine-step lane), on every push to main, hourly, on demand. "
                 "Each measuring "
                 "job edits its run's comment as soon as its own number lands; `?` "
                 "is pending until then and `-` is the other workflow's number. "
                 "Each comment starts with OK, REGRESSION: or STILL REGRESSED: "
                 "(a number worse than its best since the baseline; reset the best "
                 "with a comment line `scorecard-baseline: <sha> [measures]`), then one "
                 "machine-readable line: sha= prev= run= suite= twins= federation= "
                 "rust= tree= source= board= cpanic= <label>_lift_files= <label>_lift_funcs= "
                 "<label>_refused= <label>_lift_ierr= <label>_lift_missing= issues= prs= "
                 "pending= rerun= carried= wall=.")
        if url is None:
            print("::error::could not create the scorecard issue")
            return 1
        issue = url.rsplit("/", 1)[-1]
        if gh("issue", "pin", issue) is None:
            print(f"::warning::could not pin issue #{issue}")

    owner, name = repo.split("/", 1)
    nodes = read_comments(owner, name, issue)
    own_comment = None
    earlier: list[dict[str, str]] = []  # newest first
    window: dict[str, list[dict[str, str]]] = {m: [] for m in MEASURES}
    baseline: dict[str, str] = {}
    prev_error = nodes is None
    if nodes is not None:
        for node in reversed(nodes):
            row = parse_row(node.get("body") or "")
            if row is not None and row.get("run") == run_id:
                own_comment = node.get("databaseId")
                break
        earlier, window, baseline = read_history(
            [node.get("body") or "" for node in nodes], run_id
        )
    # The comment this run already wrote: banked next to the results, so a
    # second job never creates a duplicate even if the listing lags.
    banked_id = runs / ".comment-id"
    try:
        own_comment = own_comment or int(banked_id.read_text().strip())
    except (OSError, ValueError):
        pass
    # The previous row is the newest earlier row that measured one of this
    # workflow's numbers, so the PR range is the range those numbers moved in.
    comparable = [
        row for row in earlier
        if any(row_measured(row, m) for m in own)
        or any(row_measured(row, lane_token(label)) for label in lanes)
    ]
    prev_sha = (comparable or earlier)[0]["sha"] if earlier else "none"

    prs: list[str] = []
    prs_known = True
    if earlier and prev_sha != sha and "?" not in (prev_sha, sha):
        out = gh("api", "--paginate", f"repos/{repo}/compare/{prev_sha}...{sha}",
                 "--jq", r'.commits[].commit.message | split("\n")[0]')
        if out is None:
            prs_known = False
        else:
            for subject in out.splitlines():
                for n in re.findall(r"\(#(\d+)\)", subject):
                    if f"#{n}" not in prs:
                        prs.append(f"#{n}")
    elif not earlier:
        prs_known = not prev_error
    prs_cell = ",".join(prs) if prs_known else "?"

    # Fresh drops against the newest earlier row that measured each number, and
    # numbers still worse than their best since the baseline (sticky). Failing
    # counts, not passed counts, are compared: tests are added and deleted. A
    # total may fall by the small tolerance (tests deleted); beyond it the
    # total itself is the regression (run 43832361876 lost a shard: suite total
    # ~5667 -> 4212 with three failing, and the row said OK).
    current = {
        "suite": f"{suite_pass}/{suite_total}",
        "twins": f"{twins_pass}/{twins_total}",
        "rust": f"{rust_pass}/{rust_total}",
        "tree": f"{tree_pass}/{tree_total}",
        "source": f"{source_pass}/{source_total}",
        "board": f"{board_done}/{board_total}",
        "cpanic": cpanic,
        "federation": fed,
        **lane_row,
    }
    drops, still = judge(
        current, earlier, window, set(pending) | set(outside), lanes=reported_lanes
    )

    range_txt = f"PRs {prs_cell or 'none'} ({prev_sha[:9]}..{sha[:9]})"
    status = headline(
        drops,
        still,
        prev_error=prev_error,
        first=not earlier,
        pending=pending,
        range_txt=range_txt if (earlier or prev_error) else "",
        baseline={
            m: s for m, s in baseline.items()
            if m in own or (lane_label(m) or "") in lanes
        },
    )

    def carry_cell(field: str) -> str:
        # Nothing is carried (#8416: the carry recorder is deleted): every
        # measured test or board file ran, so rerun is the measure's total
        # and carried is 0. The cells keep their shape for row readers.
        parts = []
        for measure in ("suite", "twins", "board"):
            if measure in outside:
                value = "-"
            elif not results[measure].get("measured"):
                value = "?"
            elif field == "carried":
                value = "0"
            else:
                value = num(results[measure].get("total"))
            parts.append(f"{measure}:{value}")
        return ",".join(parts)

    wall = run_wall(repo, run_id)
    row = (
        f"sha={sha} prev={prev_sha} run={run_id} suite={suite_pass}/{suite_total} "
        f"twins={twins_pass}/{twins_total} federation={fed} "
        f"rust={rust_pass}/{rust_total} tree={tree_pass}/{tree_total} "
        f"source={source_pass}/{source_total} "
        f"board={board_done}/{board_total} cpanic={cpanic} "
        + "".join(f"{key}={value} " for key, value in lane_row.items())
        + f"issues={issues} "
        f"prs={prs_cell} pending={','.join(pending) or 'none'} "
        f"rerun={carry_cell('rerun')} carried={carry_cell('carried')} wall={wall}"
    )

    def job_wall(result: dict) -> str:
        value = result.get("jobWallSeconds")
        return f"{value}s" if value is not None else "?"

    details = (
        f"`{sha[:9]}` | suite {suite_pass}/{suite_total} failed+error "
        f"{num(suite.get('failed'))} (job {job_wall(suite)}) | twins "
        f"{twins_pass}/{twins_total} failed+error {num(twins.get('failed'))} "
        f"(job {job_wall(twins)}) | federation {fed}"
        f"{' (carried)' if fed_r.get('carried') else ''} (job {job_wall(fed_r)}) | "
        f"rust {rust_pass}/{rust_total} failed {num(rust.get('failed'))} "
        f"(job {job_wall(rust)}) | tree {tree_pass}/{tree_total} failed+error "
        f"{num(tree.get('failed'))} (job {job_wall(tree)}) | "
        f"source {source_pass}/{source_total} failed+error "
        f"{num(source.get('failed'))} (job {job_wall(source)}) | "
        f"board {board_done}/{board_total} cpanic={cpanic} (job {job_wall(board)}) | "
        + "".join(
            f"{label} lift files {lane_row[f'{label}_lift_files']} funcs "
            f"{lane_row[f'{label}_lift_funcs']} refused {lane_row[f'{label}_refused']} "
            f"instrument errors {lane_row[f'{label}_lift_ierr']} missing "
            f"{lane_row[f'{label}_lift_missing']} (job {job_wall(lanes[label])}) | "
            for label in lanes
        )
        + f"run wall {wall} | open issues {issues} | [run]({run_url})"
    )
    notes = []
    if fed_r.get("last_fail"):
        notes.append(f"federation last FAIL line: `{fed_r['last_fail']}`")
    if board.get("line"):
        notes.append(f"board line: `{board['line']}`")
    for measure in CELL_MEASURES:
        if results[measure].get("note"):
            notes.append(f"{measure}: {results[measure]['note']}")
    for label, lane in lanes.items():
        if lane.get("measured"):
            notes.append(f"{label}_refusals_top: {str(lane.get('refusals_top') or 'none')[:600]}")
            unlifted = int(lane.get("instrument_errors") or 0) + int(lane.get("files_missing") or 0)
            if unlifted:
                notes.append(
                    f"{label}: {lane.get('instrument_errors')} instrument errors and "
                    f"{lane.get('files_missing')} missing files are not lifted; their "
                    "functions are outside lift_funcs's total"
                )
        if lane.get("note"):
            notes.append(f"{label}_lift: {lane['note']}")
    body = f"{status}\n\n{row}\n\n{details}\n" + "".join(f"\n{n}" for n in notes) + "\n"

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(f"### Main scorecard\n\n{status}\n\n`{row}`\n\n{details}\n\n")

    if own_comment:
        done = gh("api", "-X", "PATCH", f"repos/{repo}/issues/comments/{own_comment}",
                  "-f", f"body={body}")
    else:
        done = gh("issue", "comment", issue, "--body", body)
        match = re.search(r"issuecomment-(\d+)", done or "")
        if match:
            banked_id.write_text(match.group(1) + "\n")
    if done is None:
        print(f"::error::could not write the row on #{issue}")
        return 1
    print(f"{'updated' if own_comment else 'posted'} on #{issue}:\n{body}")
    if drops or still or prev_error:
        print(f"::error::{status}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
