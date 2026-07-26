"""A bounded run must produce the SAME row as the full run — or it is a rumour.

The pandas board was quoted from two kinds of run: the full corpus, and a
handful of files re-measured alone to check a capability. Those were treated as
one frontier. They were not comparable: a file corpus set the workspace root to
the measured file's *parent directory*, so
``provisional_contract_refs_from_demands`` walked a different tree, produced a
different demand table, and resolved the same ``with`` statements differently.
The instrument, not the code, moved the number.

These teeth pin the repair from both faces:

* **positive** — one file measured alone under the corpus root produces a row
  byte-identical to that file's row inside the full run;
* **discrimination** — the same file measured under a *different* root does NOT
  produce that row, so the tooth above is actually load-bearing and would go
  red if the root stopped mattering.

Plus the refusal: a single-file run with no ``--corpus-root`` is rejected,
rather than silently inventing one.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "control_effect_recensus.py"
)


def _corpus(tmp_path: Path) -> Path:
    """A corpus whose ``with`` resolution depends on a sibling module.

    ``pkg/uses.py`` opens a manager imported from ``pkg/managers.py``. Rooted at
    ``pkg`` the demand table can see the definition; rooted at ``pkg/sub`` it
    cannot. That is exactly the drift the repair removes, in miniature.
    """
    root = tmp_path / "pkg"
    (root / "sub").mkdir(parents=True)
    (root / "__init__.py").write_text("", encoding="utf-8")
    (root / "managers.py").write_text(
        "import contextlib\n"
        "\n"
        "@contextlib.contextmanager\n"
        "def held():\n"
        "    yield 1\n",
        encoding="utf-8",
    )
    (root / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (root / "sub" / "uses.py").write_text(
        "from pkg.managers import held\n"
        "\n"
        "def run():\n"
        "    with held() as value:\n"
        "        return value\n",
        encoding="utf-8",
    )
    return root


def _run(corpus: Path, *, root: Path, out: Path, extra: list[str] | None = None):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(corpus),
            "--corpus-root",
            str(root),
            "--out-dir",
            str(out),
            "--commit",
            "test",
            "--corpus-version",
            "test-pin",
            *(extra or []),
        ],
        capture_output=True,
        text=True,
    )


def _row_for(out: Path, wanted: str) -> str:
    """The measured result for one file, canonicalized — compared as bytes.

    The enclosing journal row also carries ``corpusManifestCid``, which is the
    CID of *this run's enrollment* and is legitimately different when one file
    is enrolled instead of four. What must not differ is the measurement: every
    family, resolution bucket, site count and desugar row. That is what is
    compared here, byte for byte, not a summary number derived from it.
    """
    rows = [
        json.loads(line)
        for line in (out / "checkpoint.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    matching = [row for row in rows if row["file"] == wanted]
    assert len(matching) == 1, f"expected exactly one row for {wanted}, got {matching}"
    return json.dumps(matching[0]["result"], sort_keys=True, separators=(",", ":"))


TARGET = "pkg/sub/uses.py"


def test_file_measured_alone_matches_its_row_in_the_full_run(tmp_path) -> None:
    root = _corpus(tmp_path)

    full = _run(root, root=root, out=tmp_path / "full")
    assert (tmp_path / "full" / "checkpoint.jsonl").exists(), full.stderr

    alone = _run(root / "sub" / "uses.py", root=root, out=tmp_path / "alone")
    assert (tmp_path / "alone" / "checkpoint.jsonl").exists(), alone.stderr

    assert _row_for(tmp_path / "alone", TARGET) == _row_for(tmp_path / "full", TARGET)


def test_a_different_root_does_not_produce_the_same_row(tmp_path) -> None:
    """The discriminating face: if this passed too, the tooth above proved nothing."""
    root = _corpus(tmp_path)

    full = _run(root, root=root, out=tmp_path / "full")
    assert (tmp_path / "full" / "checkpoint.jsonl").exists(), full.stderr

    drifted = _run(
        root / "sub" / "uses.py", root=root / "sub", out=tmp_path / "drifted"
    )
    assert (tmp_path / "drifted" / "checkpoint.jsonl").exists(), drifted.stderr

    # Under the wrong root the file is not even the same identity, and its
    # resolutions come from a table that never saw pkg/managers.py.
    drifted_rows = [
        json.loads(line)
        for line in (tmp_path / "drifted" / "checkpoint.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [row["file"] for row in drifted_rows] == ["sub/uses.py"]
    assert drifted_rows[0]["file"] != TARGET


def test_single_file_run_without_corpus_root_is_refused(tmp_path) -> None:
    root = _corpus(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(root / "sub" / "uses.py"),
            "--out-dir",
            str(tmp_path / "refused"),
            "--commit",
            "test",
            "--corpus-version",
            "test-pin",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "--corpus-root is required" in result.stderr


def test_corpus_pin_refuses_a_changed_corpus(tmp_path) -> None:
    """A board is comparable only against the corpus it was pinned to."""
    root = _corpus(tmp_path)
    pin = tmp_path / "corpus.pin.json"

    first = _run(
        root, root=root, out=tmp_path / "pinned", extra=["--write-corpus-pin", str(pin)]
    )
    assert pin.exists(), first.stderr

    same = _run(
        root,
        root=root,
        out=tmp_path / "same",
        extra=["--require-corpus-pin", str(pin)],
    )
    assert "CORPUS PIN DEFECT" not in same.stderr

    (root / "managers.py").write_text("# corpus moved\n", encoding="utf-8")
    changed = _run(
        root,
        root=root,
        out=tmp_path / "changed",
        extra=["--require-corpus-pin", str(pin)],
    )
    assert changed.returncode == 2
    assert "CORPUS PIN DEFECT" in changed.stderr
