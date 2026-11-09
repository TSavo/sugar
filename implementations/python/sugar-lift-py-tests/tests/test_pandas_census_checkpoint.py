from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import textwrap
import time

import pytest


from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

SCRIPTS = sugar_lift_py_tests_package_root() / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pandas_census_checkpoint import (
    Checkpoint,
    CheckpointError,
    parse_slice,
    run_pending,
)  # noqa: E402


def test_killed_run_resumes_without_redoing_completed_file(tmp_path: Path) -> None:
    checkpoint = tmp_path / "rows.jsonl"
    invocations = tmp_path / "invocations.jsonl"
    blocked = tmp_path / "blocked"
    driver = tmp_path / "driver.py"
    driver.write_text(
        textwrap.dedent(f"""
            import json
            from pathlib import Path
            import sys
            import time

            sys.path.insert(0, {str(SCRIPTS)!r})
            from pandas_census_checkpoint import Checkpoint, run_pending

            checkpoint = Checkpoint(
                floor="planted",
                files=("a.py", "b.py", "c.py"),
                path=Path({str(checkpoint)!r}),
            )
            invocations = Path({str(invocations)!r})
            blocked = Path({str(blocked)!r})

            def worker(file):
                with invocations.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({{"file": file}}) + "\\n")
                    stream.flush()
                if file == "b.py" and not blocked.exists():
                    blocked.write_text("started", encoding="utf-8")
                    time.sleep(60)
                return {{"category": "completed"}}

            run_pending(checkpoint, worker, workers=1)
            """),
        encoding="utf-8",
    )

    process = subprocess.Popen([sys.executable, str(driver)])
    deadline = time.monotonic() + 10
    while not blocked.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert blocked.exists(), "planted run never reached the in-flight file"
    os.kill(process.pid, signal.SIGKILL)
    process.wait(timeout=5)

    subprocess.run([sys.executable, str(driver)], check=True, timeout=10)

    calls = [json.loads(line)["file"] for line in invocations.read_text().splitlines()]
    assert calls.count("a.py") == 1
    assert calls.count("b.py") == 2
    assert calls.count("c.py") == 1
    resumed = Checkpoint(
        floor="planted", files=("a.py", "b.py", "c.py"), path=checkpoint
    )
    assert [row["file"] for row in resumed.rows()] == ["a.py", "b.py", "c.py"]


def test_crash_between_good_files_is_a_durable_typed_row(tmp_path: Path) -> None:
    checkpoint = Checkpoint(
        floor="planted",
        files=("a.py", "crash.py", "z.py"),
        path=tmp_path / "rows.jsonl",
    )

    def worker(file: str) -> dict[str, object]:
        program = (
            "import os, signal; os.kill(os.getpid(), signal.SIGABRT)"
            if file == "crash.py"
            else "pass"
        )
        result = subprocess.run(
            [sys.executable, "-c", program], capture_output=True, check=False
        )
        if result.returncode < 0:
            return {
                "category": "native-crash",
                "signal": signal.Signals(-result.returncode).name,
            }
        return {"category": "completed"}

    run_pending(checkpoint, worker, workers=1)

    assert [(row["file"], row["result"]["category"]) for row in checkpoint.rows()] == [
        ("a.py", "completed"),
        ("crash.py", "native-crash"),
        ("z.py", "completed"),
    ]


def test_checkpoint_rejects_foreign_manifest_duplicate_and_malformed_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "rows.jsonl"
    checkpoint = Checkpoint(floor="planted", files=("a.py",), path=path)
    checkpoint.append("a.py", {"category": "completed"})

    with pytest.raises(CheckpointError, match="manifest CID"):
        Checkpoint(floor="planted", files=("different.py",), path=path)

    with pytest.raises(CheckpointError, match="duplicate"):
        checkpoint.append("a.py", {"category": "completed"})

    path.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(CheckpointError, match="malformed"):
        Checkpoint(floor="planted", files=("a.py",), path=path)


_MANIFEST = tuple(f"pkg/m{n:02d}.py" for n in range(11))
_SEATS = 4


def _seat_journal(tmp_path: Path, index: int) -> Path:
    """One seat's process: its own journal over the WHOLE manifest."""
    path = tmp_path / f"seat-{index}.jsonl"
    seat = Checkpoint(floor="planted", files=_MANIFEST, path=path)
    for file in seat.slice_files(index, _SEATS):
        seat.append(file, {"category": "completed"})
    return path


def test_seats_partition_the_manifest_and_join_into_one_complete_journal(
    tmp_path: Path,
) -> None:
    whole = Checkpoint(floor="planted", files=_MANIFEST, path=tmp_path / "none.jsonl")
    seats = [whole.slice_files(index, _SEATS) for index in range(_SEATS)]
    assert sorted(file for seat in seats for file in seat) == sorted(_MANIFEST)
    assert sum(len(seat) for seat in seats) == len(_MANIFEST)

    joined = tmp_path / "joined.jsonl"
    joined.write_text(
        "".join(
            _seat_journal(tmp_path, index).read_text(encoding="utf-8")
            for index in range(_SEATS)
        ),
        encoding="utf-8",
    )
    complete = Checkpoint(floor="planted", files=_MANIFEST, path=joined)
    assert complete.pending_files() == ()
    assert sorted(row["file"] for row in complete.rows()) == sorted(_MANIFEST)


def test_one_seat_alone_is_not_the_manifest_and_a_foreign_seat_does_not_join(
    tmp_path: Path,
) -> None:
    # One seat's journal leaves every other seat's files pending: it cannot
    # be read as a finished walk.
    alone = Checkpoint(
        floor="planted", files=_MANIFEST, path=_seat_journal(tmp_path, 0)
    )
    assert set(alone.pending_files()) == set(_MANIFEST) - set(
        alone.slice_files(0, _SEATS)
    )

    # A row measured against one file's manifest names the same file, but it
    # is not a row of this manifest and does not join it.
    foreign = tmp_path / "foreign.jsonl"
    Checkpoint(floor="planted", files=(_MANIFEST[1],), path=foreign).append(
        _MANIFEST[1], {"category": "completed"}
    )
    with pytest.raises(CheckpointError, match="manifest CID"):
        Checkpoint(floor="planted", files=_MANIFEST, path=foreign)

    # The same seat joined twice answers one file twice.
    twice = tmp_path / "twice.jsonl"
    twice.write_text(
        _seat_journal(tmp_path, 1).read_text(encoding="utf-8") * 2, encoding="utf-8"
    )
    with pytest.raises(CheckpointError, match="duplicate"):
        Checkpoint(floor="planted", files=_MANIFEST, path=twice)


def test_slice_spec_names_a_seat_or_is_refused(tmp_path: Path) -> None:
    assert parse_slice("0/24") == (0, 24)
    assert parse_slice("23/24") == (23, 24)
    for lie in ("24/24", "-1/3", "x", "1/", "/3", "1/0", "1/2/3", "1.0/3", " 1/3"):
        with pytest.raises(CheckpointError, match="slice must be I/K"):
            parse_slice(lie)
    whole = Checkpoint(floor="planted", files=_MANIFEST, path=tmp_path / "none.jsonl")
    with pytest.raises(CheckpointError, match="slice must be I/K"):
        whole.slice_files(4, 4)
