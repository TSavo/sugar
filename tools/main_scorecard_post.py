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

Two workflows post rows: main-scorecard.yml (suite, twins, federation) on every
merge, and main-scorecard-board.yml (the pandas board) in its own lane, so a
slow board never holds the per-merge numbers back. Each names what it measures
in SCORECARD_MEASURES. A measure outside that set is written ``-`` in the row:
it is not this workflow's number, so it is never pending, never unmeasured and
never compared. Each number is still compared with the newest earlier row that
measured it, whichever workflow wrote that row.

Regression alarm: each number is compared with the newest earlier row (another
run) where that number was measured. Any number that got worse, or that was
measured before and is unmeasured now, makes the comment start with
REGRESSION: and makes this invocation exit 1.

Comment shape (first line, then one machine-readable line of key=value):
  OK ... | REGRESSION: ... ; then
  sha= prev= run= suite=p/t twins=p/t federation= board=c/t cpanic= issues=
  prs= pending= rerun= carried= wall=
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

MEASURES = ("suite", "twins", "federation", "board")
ROW_KEYS = ("sha", "prev", "run", "suite", "twins", "federation", "board", "cpanic")


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


def row_measured(row: dict[str, str], measure: str) -> bool:
    value = row.get(measure, "").split("/")[0]
    return value.isdigit() or value in ("PASS", "FAIL")


def load_results(runs: Path, final: bool) -> tuple[dict[str, dict], list[str]]:
    results: dict[str, dict] = {}
    pending: list[str] = []
    own = own_measures()
    for measure in MEASURES:
        if measure not in own:
            results[measure] = {}
            continue
        try:
            results[measure] = json.loads((runs / f"{measure}.json").read_text())
        except (OSError, ValueError):
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
        if measure not in MEASURES:
            sys.exit(f"::error::unknown measure {measure!r}")
        tmp = runs / f".{measure}.{os.getpid()}.tmp"
        shutil.copyfile(source, tmp)
        os.replace(tmp, runs / f"{measure}.json")
    built: dict[str, dict] = {}
    for item in args.set:
        path, _, value = item.partition("=")
        measure, *keys = path.split(".")
        if measure not in MEASURES or not keys:
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
    if args.no_post:
        return 0

    with Lock(runs / ".post.lock"):
        return post(repo, run_id, sha, title, run_url, runs, args.final)


def post(repo: str, run_id: str, sha: str, title: str, run_url: str, runs: Path, final: bool) -> int:
    results, pending = load_results(runs, final)
    suite, twins, fed_r, board = (results[m] for m in MEASURES)
    own = own_measures()
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
    fed = fed_r.get("verdict") if fed_r.get("measured") else "?"
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
                 "twins, federation) and of main-scorecard-board.yml (the pandas "
                 "board), on every push to main, hourly, on demand. Each measuring "
                 "job edits its run's comment as soon as its own number lands; `?` "
                 "is pending until then and `-` is the other workflow's number. "
                 "Each comment starts with OK or REGRESSION:, then one "
                 "machine-readable line: sha= prev= run= suite= twins= federation= "
                 "board= cpanic= issues= prs= pending= rerun= carried= wall=.")
        if url is None:
            print("::error::could not create the scorecard issue")
            return 1
        issue = url.rsplit("/", 1)[-1]
        if gh("issue", "pin", issue) is None:
            print(f"::warning::could not pin issue #{issue}")

    owner, name = repo.split("/", 1)
    query = (
        "query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r)"
        "{issue(number:$n){comments(last:100){nodes{databaseId body}}}}}"
    )
    raw = gh("api", "graphql", "-f", f"query={query}",
             "-f", f"o={owner}", "-f", f"r={name}", "-F", f"n={issue}")
    own_comment = None
    earlier: list[dict[str, str]] = []  # newest first
    prev_error = raw is None
    if raw is not None:
        nodes = json.loads(raw)["data"]["repository"]["issue"]["comments"]["nodes"]
        for node in reversed(nodes):
            row = parse_row(node.get("body") or "")
            if row is None:
                continue
            if row.get("run") == run_id:
                own_comment = own_comment or node.get("databaseId")
            else:
                earlier.append(row)
    # The comment this run already wrote: banked next to the results, so a
    # second job never creates a duplicate even if the listing lags.
    banked_id = runs / ".comment-id"
    try:
        own_comment = own_comment or int(banked_id.read_text().strip())
    except (OSError, ValueError):
        pass
    # The previous row is the newest earlier row that measured one of this
    # workflow's numbers, so the PR range is the range those numbers moved in.
    comparable = [row for row in earlier if any(row_measured(row, m) for m in own)]
    prev_sha = (comparable or earlier)[0]["sha"] if earlier else "none"

    def last_measured(key: str, part: int | None = None) -> str | None:
        for row in earlier:
            value = row.get(key, "")
            if part is not None:
                pieces = value.split("/")
                value = pieces[part] if len(pieces) > part else ""
            if value.isdigit() or value in ("PASS", "FAIL"):
                return value
        return None

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

    drops: list[str] = []

    def higher_is_better(label: str, measure: str, cur: str, key: str, part: int | None) -> None:
        if measure in pending or measure in outside:
            return
        before = last_measured(key, part)
        if before is None or not before.isdigit():
            return
        if not cur.isdigit():
            drops.append(f"{label} unmeasured (was {before})")
        elif int(cur) < int(before):
            drops.append(f"{label} {before} -> {cur}")

    higher_is_better("suite passed", "suite", suite_pass, "suite", 0)
    higher_is_better("twins passed", "twins", twins_pass, "twins", 0)
    higher_is_better("board completed", "board", board_done, "board", 0)
    if "board" not in pending and "board" not in outside:
        before = last_measured("cpanic")
        if before is not None:
            if not cpanic.isdigit():
                drops.append(f"board cpanic unmeasured (was {before})")
            elif int(cpanic) > int(before):
                drops.append(f"board cpanic {before} -> {cpanic}")
    if (
        "federation" not in pending
        and "federation" not in outside
        and last_measured("federation") == "PASS"
        and fed != "PASS"
    ):
        drops.append(f"federation PASS -> {fed if fed != '?' else 'unmeasured'}")

    range_txt = f"PRs {prs_cell or 'none'} ({prev_sha[:9]}..{sha[:9]})"
    pending_txt = f" | pending: {', '.join(pending)}" if pending else ""
    if prev_error:
        status = f"UNCOMPARED: the previous rows could not be read{pending_txt} | {range_txt}"
    elif drops:
        status = "REGRESSION: " + "; ".join(drops) + f"{pending_txt} | {range_txt}"
    elif not earlier:
        status = f"OK first machine-readable row, nothing to compare{pending_txt}"
    else:
        status = f"OK all measured numbers held or improved{pending_txt} | {range_txt}"

    def carry_cell(field: str) -> str:
        parts = []
        for measure in ("suite", "twins", "board"):
            value = (results[measure].get("carry") or {}).get(field)
            parts.append(f"{measure}:{'-' if measure in outside else num(value)}")
        return ",".join(parts)

    wall = run_wall(repo, run_id)
    row = (
        f"sha={sha} prev={prev_sha} run={run_id} suite={suite_pass}/{suite_total} "
        f"twins={twins_pass}/{twins_total} federation={fed} "
        f"board={board_done}/{board_total} cpanic={cpanic} issues={issues} "
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
        f"board {board_done}/{board_total} cpanic={cpanic} (job {job_wall(board)}) | "
        f"run wall {wall} | open issues {issues} | [run]({run_url})"
    )
    notes = []
    if fed_r.get("last_fail"):
        notes.append(f"federation last FAIL line: `{fed_r['last_fail']}`")
    if board.get("line"):
        notes.append(f"board line: `{board['line']}`")
    for measure in MEASURES:
        if results[measure].get("note"):
            notes.append(f"{measure}: {results[measure]['note']}")
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
    if drops or prev_error:
        print(f"::error::{status}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
