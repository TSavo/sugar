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

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pandas_census_checkpoint import (
    Checkpoint,
    CheckpointError,
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
