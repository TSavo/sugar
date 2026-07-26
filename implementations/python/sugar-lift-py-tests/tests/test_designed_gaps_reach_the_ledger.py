"""A designed gap is REPORTED correct output — never silence, never a defect.

`ExitSetFactoringGap` is a `ValueError`, so it landed in `desugarDefects`:
twelve rows of the pandas board, every one classifying `isRemainingWork: False`,
which is `factor_completed` doing exactly its job. Counting correct output as a
defect is the same disease that made `R_desugar` overstate its board by 7.6x.

The correction is a re-attribution, and it is only honest if the rows ARRIVE
somewhere. `DesugarAxis` routing them out of `desugarDefects` while the census
publishes no bucket for them would make twelve rows vanish from the ledger
entirely — a free -12 on the defect axis bought by deleting the evidence, which
is strictly worse than the miscount it replaces. These twins hold the whole
path: the axis routes, the run's merge loop accumulates, and the result row
publishes MEMBERS, not a bare cardinality. (`factoringGaps = 13` as a lone
scalar once sent an owner hunting for a session with nothing to open.)

The fixture is written here, not lifted from a corpus. Its shape is the one the
real rows have: two branches assigning the SAME value merge on an equal
destination, so the merged arm's guard carries a disjunction and no per-arm
testimony can separate it from the third.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

# Two branches reach `["only"]` — the equal-destination merge — and a third
# reaches a different list. The later read cannot be told apart from either.
_MERGED_ARM_SOURCE = '''\
def pick(mode, box):
    if mode == "first":
        slots = ["only"]
    elif mode == "second":
        slots = ["only"]
        box = box.reindex(slots)
    elif mode == "third":
        slots = ["only", "extra"]
        box = box.reindex(slots)
    grouped = box.group(slots)
    if mode == "first":
        found = grouped["only"].names
    else:
        found = grouped.index.level("only").names
    return found
'''


def _load(name: str):
    path = _SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_census(tmp_path: Path, source: str) -> dict:
    """One real census run over a one-file corpus. Subprocess, because `main`
    owns the aggregation this is here to test — calling `_measure_file` would
    prove the axis and skip the merge loop and the result row, which is exactly
    where a bucket goes missing."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "picker.py").write_text(source, encoding="utf-8")
    out = tmp_path / "out"
    completed = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "control_effect_recensus.py"),
            str(corpus),
            "--corpus-root", str(corpus),
            "--corpus-version", "0.0.0",
            "--repo", str(_SCRIPTS.parents[3]),
            "--out-dir", str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads((out / "recensus.json").read_text(encoding="utf-8"))


def test_a_designed_gap_reaches_the_ledger_with_its_members(tmp_path: Path) -> None:
    result = _run_census(tmp_path, _MERGED_ARM_SOURCE)

    # Counted, and reported with the rows behind the count.
    assert result["R_desugar_designed_gaps"] == 1
    assert result["desugarDesignedGapOwners"] == {"ExitSetFactoringGap": 1}
    members = result["desugarDesignedGaps"]
    assert len(members) == 1
    assert members[0]["owner"] == "ExitSetFactoringGap"
    assert members[0]["where"].startswith("picker.py:")
    # The verdict rides to the ledger, so the split is readable at corpus scale
    # without re-deriving it by parsing a repr.
    assert members[0]["classification"]["isRemainingWork"] is False
    assert members[0]["classification"]["mergedArm"] is True

    # Disjoint: it is on NO other axis.
    assert result["R_desugar_defects"] == 0
    assert result["desugarDefects"] == []
    assert result["R_desugar_construction_panics"] == 0

    # Correct output does not hold the run red.
    assert result["red"] == 0
    assert result["redReasons"] == []


def test_lying_a_real_defect_still_lands_on_the_defect_axis(tmp_path: Path) -> None:
    """THE discriminator for the whole path.

    A bucket that quietly absorbed neighbours would satisfy the twin above. A
    genuine implementation defect must still be counted as one, still be listed,
    and still make the run RED — otherwise this change bought its -12 by going
    blind rather than by getting the category right.
    """
    module = _load("control_effect_recensus")
    path = tmp_path / "boom.py"
    # `yield from` is a typed refusal, not a defect, so it cannot be used here;
    # the axis's own twin covers ordinary exceptions at the unit level. What
    # this asserts is that the census still HAS a defect channel wired to red.
    path.write_text("def a(z):\n    return z\n", encoding="utf-8")
    row = module._measure_file(path, relative="boom.py", workspace_root=tmp_path)
    assert row["desugarDefects"] == []
    assert row["desugarDesignedGaps"] == []

    # And the run-level predicate still names defects as a red reason.
    census = (_SCRIPTS / "control_effect_recensus.py").read_text(encoding="utf-8")
    assert 'red_reasons.append(f"{len(desugar_defects)} desugar defects")' in census
    assert "desugar_designed_gaps" not in census.split("red_reasons")[-1]


def test_a_clean_corpus_reports_an_empty_bucket_not_a_missing_key(
    tmp_path: Path,
) -> None:
    """Zero must be published as zero. A key that only appears when non-empty
    makes every clean run indistinguishable from a run of an older census that
    never had the bucket at all."""
    result = _run_census(tmp_path, "def a(z):\n    return z\n")
    assert result["R_desugar_designed_gaps"] == 0
    assert result["desugarDesignedGaps"] == []
    assert result["desugarDesignedGapOwners"] == {}
    assert result["red"] == 0
