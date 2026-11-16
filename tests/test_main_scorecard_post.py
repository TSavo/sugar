"""Teeth for tools/main_scorecard_post.py: the regression alarm is sticky.

The pandas board fell 1420/1421 cpanic=0 -> 1235 cpanic=181; the row said
REGRESSION once, then every later row at 1237 cpanic=179 said OK for eight
hours because each row was compared only with the previous one. Each number
is now also compared with its best since the baseline.
"""

from __future__ import annotations

import repo_root_test_support  # noqa: F401 -- puts tools/ on sys.path

import main_scorecard_post as post

FAST = ("suite", "twins", "federation", "rust", "tree")


def board_row(sha: str, run: str, done: int, cpanic: int, total: int = 1421) -> str:
    return (
        f"OK\n\nsha={sha} prev=x run={run} suite=-/- twins=-/- federation=- "
        f"rust=-/- tree=-/- board={done}/{total} cpanic={cpanic} issues=1 prs= pending=none\n"
    )


def fast_row(sha: str, run: str, suite: str, twins: str = "10/10", fed: str = "PASS",
             rust: str = "5/5", tree: str = "3/3") -> str:
    return (
        f"OK\n\nsha={sha} prev=x run={run} suite={suite} twins={twins} federation={fed} "
        f"rust={rust} tree={tree} board=-/- cpanic=- issues=1 prs= pending=none\n"
    )


def board_now(done: int, cpanic: int, total: int = 1421) -> dict[str, str]:
    return {"suite": "-/-", "twins": "-/-", "rust": "-/-", "tree": "-/-",
            "board": f"{done}/{total}", "cpanic": str(cpanic), "federation": "-"}


def fast_now(suite: str, twins: str = "10/10", fed: str = "PASS",
             rust: str = "5/5", tree: str = "3/3") -> dict[str, str]:
    return {"suite": suite, "twins": twins, "rust": rust, "tree": tree,
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
    assert "baseline suite,twins,federation,board,rust,tree@9bd3d4ddd" in line
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
