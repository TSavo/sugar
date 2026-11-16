"""Teeth for tools/main_scorecard_post.py: the regression alarm is sticky.

The pandas board fell 1420/1421 cpanic=0 -> 1235 cpanic=181; the row said
REGRESSION once, then every later row at 1237 cpanic=179 said OK for eight
hours because each row was compared only with the previous one. Each number
is now also compared with its best since the baseline.
"""

from __future__ import annotations

import json
from pathlib import Path

import repo_root_test_support  # noqa: F401 -- puts tools/ on sys.path

import main_scorecard_post as post

FAST = ("suite", "twins", "federation", "rust", "tree", "source")


def board_row(sha: str, run: str, done: int, cpanic: int, total: int = 1421) -> str:
    return (
        f"OK\n\nsha={sha} prev=x run={run} suite=-/- twins=-/- federation=- "
        f"rust=-/- tree=-/- source=-/- board={done}/{total} cpanic={cpanic} issues=1 prs= pending=none\n"
    )


def fast_row(sha: str, run: str, suite: str, twins: str = "10/10", fed: str = "PASS",
             rust: str = "5/5", tree: str = "3/3", source: str | None = "4/4") -> str:
    # source=None writes a row from before the `source` population existed.
    source_cell = "" if source is None else f"source={source} "
    return (
        f"OK\n\nsha={sha} prev=x run={run} suite={suite} twins={twins} federation={fed} "
        f"rust={rust} tree={tree} {source_cell}board=-/- cpanic=- issues=1 prs= pending=none\n"
    )


def board_now(done: int, cpanic: int, total: int = 1421) -> dict[str, str]:
    return {"suite": "-/-", "twins": "-/-", "rust": "-/-", "tree": "-/-", "source": "-/-",
            "board": f"{done}/{total}", "cpanic": str(cpanic), "federation": "-"}


def fast_now(suite: str, twins: str = "10/10", fed: str = "PASS",
             rust: str = "5/5", tree: str = "3/3", source: str = "4/4") -> dict[str, str]:
    return {"suite": suite, "twins": twins, "rust": rust, "tree": tree, "source": source,
            "board": "-/-", "cpanic": "-", "federation": fed}


def status(bodies: list[str], current: dict[str, str], skip: set[str]) -> str:
    earlier, window, baseline = post.read_history(bodies, "now")
    drops, still = post.judge(current, earlier, window, skip)
    return post.headline(drops, still, first=not earlier, baseline=baseline)


BOARD_DROP = [
    board_row("d4e3cb6d1aaaa", "1", 1420, 0),
    board_row("4c041edf1bbbb", "2", 1420, 0),
    board_row("9bd3d4dddcccc", "3", 1235, 181),
]


def test_fresh_drop_says_regression_once_not_still():
    line = status(BOARD_DROP[:2], board_now(1235, 181), set(FAST))
    assert line.startswith("REGRESSION: ")
    assert "board completed 1420 -> 1235" in line
    assert "board cpanic 0 -> 181" in line
    assert "STILL REGRESSED" not in line


def test_drop_then_flat_is_still_regressed():
    line = status(BOARD_DROP, board_now(1237, 179), set(FAST))
    assert line.startswith("STILL REGRESSED: ")
    assert "board 1237 < best 1420 @4c041edf1" in line
    assert "cpanic 179 > best 0 @4c041edf1" in line
    assert "OK" not in line


def test_recovery_to_best_is_ok():
    line = status(BOARD_DROP, board_now(1420, 0), set(FAST))
    assert line.startswith("OK ")
    assert "STILL" not in line and "REGRESSION" not in line


def test_partial_recovery_is_still_regressed():
    line = status(BOARD_DROP, board_now(1419, 0), set(FAST))
    assert line.startswith("STILL REGRESSED: board 1419 < best 1420 @4c041edf1")
    assert "cpanic" not in line


def test_baseline_marker_resets_best():
    bodies = BOARD_DROP + [
        board_row("7d757bcb9dddd", "4", 1237, 179),
        "Deliberate: the board corpus changed.\nscorecard-baseline: 9bd3d4ddd\n",
    ]
    earlier, window, baseline = post.read_history(bodies, "now")
    assert baseline["board"] == "9bd3d4ddd"
    # The window starts at the first row measured at the marker sha.
    assert [r["sha"] for r in window["board"]] == ["7d757bcb9dddd", "9bd3d4dddcccc"]
    line = status(bodies, board_now(1237, 179), set(FAST))
    assert line.startswith("OK ")
    assert "baseline suite,twins,federation,board,rust,tree,source,lift@9bd3d4ddd" in line
    # Without the marker the same row is still regressed.
    assert status(bodies[:-1], board_now(1237, 179), set(FAST)).startswith("STILL REGRESSED: ")


def test_baseline_with_unknown_sha_counts_rows_after_the_marker():
    bodies = BOARD_DROP + ["scorecard-baseline: abcdef0", board_row("eeeeeeeee", "5", 1300, 50)]
    line = status(bodies, board_now(1300, 50), set(FAST))
    assert line.startswith("OK ")
    line = status(bodies, board_now(1299, 50), set(FAST))
    assert line.startswith("REGRESSION: board completed 1300 -> 1299")


def test_scoped_baseline_resets_only_named_measures():
    bodies = [fast_row("aaaaaaaa1", "1", "100/100")] + BOARD_DROP + [
        fast_row("aaaaaaaa2", "4", "90/100"),
        "scorecard-baseline: 9bd3d4ddd board",
    ]
    earlier, window, baseline = post.read_history(bodies, "now")
    assert set(baseline) == {"board"}
    assert status(bodies, board_now(1237, 179), set(FAST)).startswith("OK ")
    fast = status(bodies, fast_now("90/100"), {"board"})
    assert fast.startswith("STILL REGRESSED: suite failing 10 > best 0 @aaaaaaaa1")


def test_unknown_measure_in_marker_is_ignored():
    assert post.parse_baselines("scorecard-baseline: 9bd3d4ddd boards") == []
    assert post.parse_baselines("scorecard-baseline: 9bd3d4ddd\nboard") == [
        ("9bd3d4ddd", post.MEASURES)
    ]


def test_lanes_read_their_own_history():
    # Fast-lane rows sit between board rows; the board's best and previous
    # come only from board rows, the suite's only from fast-lane rows.
    bodies = [
        board_row("b1aaaaaaa", "1", 1420, 0),
        fast_row("f1aaaaaaa", "2", "100/100"),
        board_row("b2aaaaaaa", "3", 1235, 181),
        fast_row("f2aaaaaaa", "4", "100/100"),
    ]
    board = status(bodies, board_now(1237, 179), set(FAST))
    assert board.startswith("STILL REGRESSED: board 1237 < best 1420 @b1aaaaaaa")
    assert "suite" not in board
    fast = status(bodies, fast_now("100/100"), {"board"})
    assert fast.startswith("OK ")


def test_fast_lane_failing_drop_then_flat():
    bodies = [fast_row("f1aaaaaaa", "1", "100/103"), fast_row("f2aaaaaaa", "2", "95/103")]
    line = status(bodies, fast_now("95/103"), {"board"})
    assert line.startswith("STILL REGRESSED: suite failing 8 > best 3 @f1aaaaaaa")


def test_fresh_drop_and_still_regressed_together():
    bodies = [
        fast_row("f1aaaaaaa", "1", "100/100", twins="10/10"),
        fast_row("f2aaaaaaa", "2", "100/100", twins="8/10"),
    ]
    line = status(bodies, fast_now("98/100", twins="8/10"), {"board"})
    assert line.startswith("REGRESSION: suite failing 0 -> 2 | STILL REGRESSED: twins failing 2 > best 0")


def test_total_small_drop_allowed_against_best():
    bodies = [fast_row("f1aaaaaaa", "1", "5667/5667"), fast_row("f2aaaaaaa", "2", "5600/5600")]
    assert status(bodies, fast_now("5580/5580"), {"board"}).startswith("OK ")
    # Each step under the tolerance, but beyond it against the best total.
    bodies.append(fast_row("f3aaaaaaa", "3", "5500/5500"))
    line = status(bodies, fast_now("5450/5450"), {"board"})
    assert line.startswith("STILL REGRESSED: suite total 5450 < best 5667 @f1aaaaaaa")


def test_federation_fail_stays_regressed():
    bodies = [fast_row("f1aaaaaaa", "1", "1/1", fed="PASS"), fast_row("f2aaaaaaa", "2", "1/1", fed="FAIL")]
    line = status(bodies, fast_now("1/1", fed="FAIL"), {"board"})
    assert line.startswith("STILL REGRESSED: federation FAIL, best PASS @f1aaaaaaa")


def test_own_run_rows_are_not_history():
    bodies = [board_row("b1aaaaaaa", "1", 1420, 0), board_row("b2aaaaaaa", "now", 1000, 400)]
    earlier, window, _ = post.read_history(bodies, "now")
    assert [r["sha"] for r in earlier] == ["b1aaaaaaa"]
    assert [r["sha"] for r in window["board"]] == ["b1aaaaaaa"]


# `source` is the sugar-lift-python-source package's own tests, a new
# population: rows written before it existed have no `source=` key.


def test_rows_before_source_parse_and_leave_it_unmeasured():
    old = fast_row("f1aaaaaaa", "1", "100/100", source=None)
    row = post.parse_row(old)
    assert row is not None and "source" not in row
    assert not post.row_measured(row, "source")
    # The first measured source number has nothing to compare with.
    line = status([old], fast_now("100/100", source="80/114"), {"board"})
    assert line.startswith("OK ")
    assert "source" not in line


def test_source_failing_rise_is_regression_then_still_regressed():
    bodies = [fast_row("f1aaaaaaa", "1", "100/100", source="110/114")]
    line = status(bodies, fast_now("100/100", source="108/114"), {"board"})
    assert line.startswith("REGRESSION: source failing 4 -> 6")
    assert "STILL REGRESSED" not in line
    bodies.append(fast_row("f2aaaaaaa", "2", "100/100", source="108/114"))
    line = status(bodies, fast_now("100/100", source="108/114"), {"board"})
    assert line.startswith("STILL REGRESSED: source failing 6 > best 4 @f1aaaaaaa")
    assert status(bodies, fast_now("100/100", source="110/114"), {"board"}).startswith("OK ")


def test_source_unmeasured_or_total_lost_is_regression():
    bodies = [fast_row("f1aaaaaaa", "1", "100/100", source="110/114")]
    line = status(bodies, fast_now("100/100", source="?/?"), {"board"})
    assert line.startswith("REGRESSION: source unmeasured (was 4 failing)")
    line = status(bodies, fast_now("100/100", source="60/60"), {"board"})
    assert line.startswith("REGRESSION: source total 114 -> 60 (shard lost?)")


def test_board_lane_writes_source_as_not_its_number():
    bodies = [fast_row("f1aaaaaaa", "1", "100/100", source="110/114")]
    assert status(bodies, board_now(1420, 0), set(FAST)).startswith("OK ")


def test_baseline_marker_can_name_source():
    assert post.parse_baselines("scorecard-baseline: 9bd3d4ddd source") == [
        ("9bd3d4ddd", ("source",))
    ]


# Lanes: a corpus through the nine steps (tools/nine_step_lift_lane.py). One
# way for every corpus: each label writes `<label>_lift_files=M/N
# <label>_lift_funcs=F/T <label>_refused=R` (plus ierr/missing), and is
# compared only with rows that carried the same label.

ALL_CELLS = set(post.CELL_MEASURES)


def lane_cells(label: str, files: int | str, funcs: int | str, refused: int | str,
               files_total: int | str = 1421, funcs_total: int | str = 28264) -> dict[str, str]:
    return {
        f"{label}_lift_files": f"{files}/{files_total}",
        f"{label}_lift_funcs": f"{funcs}/{funcs_total}",
        f"{label}_refused": str(refused),
        f"{label}_lift_ierr": "0",
        f"{label}_lift_missing": "0",
    }


def lane_row(sha: str, run: str, *cells: dict[str, str]) -> str:
    text = " ".join(f"{k}={v}" for c in cells for k, v in c.items())
    return (
        f"OK\n\nsha={sha} prev=x run={run} suite=-/- twins=-/- federation=- "
        f"rust=-/- tree=-/- source=-/- board=-/- cpanic=- {text} issues=1 prs= pending=none\n"
    )


def lane_status(bodies: list[str], cells: dict[str, str], lanes: list[str]) -> str:
    earlier, window, baseline = post.read_history(bodies, "now")
    current = {**board_now(1421, 0), **cells}
    drops, still = post.judge(current, earlier, window, ALL_CELLS, lanes=lanes)
    return post.headline(drops, still, first=not earlier)


def test_lane_cells_parse_and_old_rows_have_none():
    row = post.parse_row(lane_row("c1aaaaaaa", "1", lane_cells("pandas", 900, 20000, 40)))
    assert row is not None and row["pandas_lift_files"] == "900/1421"
    assert post.row_measured(row, "pandas_lift")
    assert not post.row_measured(row, "numpy_lift")
    old = post.parse_row(board_row("b1aaaaaaa", "1", 1421, 0))
    assert old is not None and not post.row_measured(old, "pandas_lift")
    # The first lane row has nothing to compare with.
    line = lane_status([board_row("b1aaaaaaa", "1", 1421, 0)],
                       lane_cells("pandas", 900, 20000, 40), ["pandas"])
    assert line.startswith("OK ")


def test_lane_drop_is_regression_then_still_regressed():
    bodies = [lane_row("c1aaaaaaa", "1", lane_cells("pandas", 900, 20000, 40))]
    line = lane_status(bodies, lane_cells("pandas", 880, 19500, 55), ["pandas"])
    assert line.startswith("REGRESSION: ")
    assert "pandas_lift_files 900 -> 880" in line
    assert "pandas_lift_funcs 20000 -> 19500" in line
    assert "pandas_refused 40 -> 55" in line
    assert "STILL REGRESSED" not in line
    bodies.append(lane_row("c2aaaaaaa", "2", lane_cells("pandas", 880, 19500, 55)))
    line = lane_status(bodies, lane_cells("pandas", 880, 19500, 55), ["pandas"])
    assert line.startswith("STILL REGRESSED: ")
    assert "pandas_lift_files 880 < best 900 @c1aaaaaaa" in line
    assert "pandas_lift_funcs 19500 < best 20000 @c1aaaaaaa" in line
    assert "pandas_refused 55 > best 40 @c1aaaaaaa" in line
    assert "OK" not in line
    assert lane_status(bodies, lane_cells("pandas", 950, 21000, 30), ["pandas"]).startswith("OK ")


def test_lane_unmeasured_is_regression():
    bodies = [lane_row("c1aaaaaaa", "1", lane_cells("pandas", 900, 20000, 40))]
    line = lane_status(bodies, lane_cells("pandas", "?", "?", "?", "?", "?"), ["pandas"])
    assert line.startswith("REGRESSION: ")
    assert "pandas_lift_files unmeasured (was 900)" in line
    assert "pandas_lift_funcs unmeasured (was 20000)" in line
    assert "pandas_refused unmeasured (was 40)" in line


def test_two_labels_compare_only_their_own_rows():
    # pandas rows and numpy rows interleave on the issue; each label's
    # previous and best come only from rows that carried that label.
    bodies = [
        lane_row("c1aaaaaaa", "1", lane_cells("pandas", 900, 20000, 40)),
        lane_row("d1aaaaaaa", "2", lane_cells("numpy", 300, 5000, 10, 600, 9000)),
        lane_row("c2aaaaaaa", "3", lane_cells("pandas", 910, 20100, 38)),
        lane_row("d2aaaaaaa", "4", lane_cells("numpy", 280, 4800, 12, 600, 9000)),
    ]
    # A pandas-only row never reads numpy's best, and holds its own.
    pandas = lane_status(bodies, lane_cells("pandas", 910, 20100, 38), ["pandas"])
    assert pandas.startswith("OK "), pandas
    # A numpy-only row is still regressed against numpy's best, not pandas'.
    numpy = lane_status(bodies, lane_cells("numpy", 280, 4800, 12, 600, 9000), ["numpy"])
    assert numpy.startswith("STILL REGRESSED: numpy_lift_files 280 < best 300 @d1aaaaaaa")
    assert "pandas" not in numpy
    # One row carrying both labels judges both.
    both = lane_status(
        bodies,
        {**lane_cells("pandas", 905, 20100, 38), **lane_cells("numpy", 300, 5000, 10, 600, 9000)},
        ["pandas", "numpy"],
    )
    assert both.startswith("REGRESSION: pandas_lift_files 910 -> 905")
    assert "numpy" not in both


def test_lane_baseline_markers():
    assert post.parse_baselines("scorecard-baseline: 9bd3d4ddd pandas_lift") == [
        ("9bd3d4ddd", ("pandas_lift",))
    ]
    assert post.parse_baselines("scorecard-baseline: 9bd3d4ddd lift") == [
        ("9bd3d4ddd", ("lift",))
    ]
    assert post.parse_baselines("scorecard-baseline: 9bd3d4ddd pandas_lifts") == []
    bodies = [
        lane_row("c1aaaaaaa", "1", lane_cells("pandas", 900, 20000, 40),
                 lane_cells("numpy", 300, 5000, 10, 600, 9000)),
        lane_row("c2aaaaaaa", "2", lane_cells("pandas", 800, 18000, 90),
                 lane_cells("numpy", 250, 4000, 20, 600, 9000)),
    ]
    regressed = lane_cells("pandas", 800, 18000, 90)
    numpy_low = lane_cells("numpy", 250, 4000, 20, 600, 9000)
    # A pandas_lift marker resets pandas only.
    marked = bodies + ["scorecard-baseline: c2aaaaaaa pandas_lift"]
    assert lane_status(marked, regressed, ["pandas"]).startswith("OK ")
    assert lane_status(marked, numpy_low, ["numpy"]).startswith("STILL REGRESSED: ")
    # `lift` resets every lane.
    marked = bodies + ["scorecard-baseline: c2aaaaaaa lift"]
    assert lane_status(marked, regressed, ["pandas"]).startswith("OK ")
    assert lane_status(marked, numpy_low, ["numpy"]).startswith("OK ")


def _bank(monkeypatch, tmp_path, measures: str, lanes: str, *sources: str) -> Path:
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_RUN_ID", "1")
    monkeypatch.setenv("SCORECARD_MEASURES", measures)
    monkeypatch.setenv("SCORECARD_LANES", lanes)
    monkeypatch.delenv("JOB_T0", raising=False)
    runs = tmp_path / "runs" / "1-1"
    args = ["--runs", str(runs), "--no-post"]
    for source in sources:
        args += ["--lane", source]
    assert post.main(args) == 0
    return runs


SUMMARY = {
    "label": "pandas", "files_lifted": 900, "files_total": 1421, "files_minted": 1000,
    "files_missing": 2, "instrument_errors": 3, "funcs_lifted": 20000,
    "funcs_total": 28000, "refused": 40, "refusals_top": "TemporalContext x30",
}


def test_lane_summary_is_banked_under_its_label(monkeypatch, tmp_path):
    summary = tmp_path / "pandas-lift" / "summary.json"
    summary.parent.mkdir()
    summary.write_text(json.dumps(SUMMARY))
    runs = _bank(monkeypatch, tmp_path, "board,lift", "pandas", str(summary))
    lanes, pending = post.load_lanes(runs, final=True)
    assert pending == []
    assert lanes["pandas"]["measured"] is True
    assert lanes["pandas"]["files_lifted"] == 900
    assert lanes["pandas"]["instrument_errors"] == 3
    assert lanes["pandas"]["files_missing"] == 2


def test_missing_or_partial_summary_is_unmeasured(monkeypatch, tmp_path):
    missing = tmp_path / "numpy-lift" / "summary.json"
    runs = _bank(monkeypatch, tmp_path, "lift", "", str(missing))
    lanes, _ = post.load_lanes(runs, final=True)
    assert lanes["numpy"]["measured"] is False
    partial = tmp_path / "p" / "summary.json"
    partial.parent.mkdir()
    partial.write_text(json.dumps({k: v for k, v in SUMMARY.items() if k != "instrument_errors"}))
    runs = _bank(monkeypatch, tmp_path, "lift", "", str(partial))
    lanes, _ = post.load_lanes(runs, final=True)
    assert lanes["pandas"]["measured"] is False
    assert "instrument_errors" in lanes["pandas"]["note"]


def test_expected_lane_is_pending_then_unmeasured(monkeypatch, tmp_path):
    runs = _bank(monkeypatch, tmp_path, "board,lift", "pandas")
    assert post.load_lanes(runs, final=False) == ({"pandas": {}}, ["pandas_lift"])
    lanes, pending = post.load_lanes(runs, final=True)
    assert pending == [] and lanes["pandas"]["measured"] is False


def test_a_workflow_without_lift_carries_no_lane(monkeypatch, tmp_path):
    summary = tmp_path / "pandas-lift" / "summary.json"
    summary.parent.mkdir()
    summary.write_text(json.dumps(SUMMARY))
    runs = _bank(monkeypatch, tmp_path, "board,lift", "", str(summary))
    monkeypatch.setenv("SCORECARD_MEASURES", "suite,twins,federation,rust,tree,source")
    assert post.load_lanes(runs, final=True) == ({}, [])
