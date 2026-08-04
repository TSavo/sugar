"""Teeth: showcase shared setup + per-shard enrollment (no merge hub)."""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import showcase_wheelhouse  # noqa: E402

CI = ROOT / ".github/workflows/ci.yml"
ATTEND = ROOT / "tools/showcase_shard_attendance.py"


def _green_showcase_body(shard_index: int, shard_count: int = 4) -> dict:
    path = f"examples/python-green-{shard_index}/run.sh"
    return {
        "measurementClass": "test-showcases",
        "shardIndex": shard_index,
        "shardCount": shard_count,
        "measuredCommit": "abc",
        "exitCode": 0,
        "showcaseCounts": {
            "enrolled": 1,
            "executed": 1,
            "retired": 0,
            "passed": 1,
            "failed": 0,
            "unmeasured": 0,
        },
        "showcaseOutcomes": [
            {
                "path": path,
                "outcome": "passed",
                "exitCode": 0,
                "subjectWitness": {"schemaVersion": 1, "subjectId": path},
            }
        ],
    }


def _write_build_project(root: Path, name: str, requires: list[str]) -> Path:
    project = root / name
    project.mkdir(parents=True)
    quoted = ", ".join(json.dumps(requirement) for requirement in requires)
    (project / "pyproject.toml").write_text(
        "[build-system]\n"
        f"requires = [{quoted}]\n"
        'build-backend = "setuptools.build_meta"\n',
        encoding="utf-8",
    )
    return project


def _write_editable_manifest(path: Path, projects: list[Path], root: Path) -> None:
    path.write_text(
        "".join(f"-e {project.relative_to(root)}\n" for project in projects),
        encoding="utf-8",
    )


def _write_wheel(
    wheelhouse: Path,
    distribution: str,
    version: str,
    *,
    requires: tuple[str, ...] = (),
) -> None:
    filename_name = distribution.replace("-", "_")
    dist_info = f"{filename_name}-{version}.dist-info"
    wheel = wheelhouse / f"{filename_name}-{version}-py3-none-any.whl"
    requires_dist = "".join(f"Requires-Dist: {item}\n" for item in requires)
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            f"{dist_info}/METADATA",
            "Metadata-Version: 2.1\n"
            f"Name: {distribution}\n"
            f"Version: {version}\n"
            f"{requires_dist}",
        )
        archive.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\n"
            "Generator: showcase-wheelhouse-test\n"
            "Root-Is-Purelib: true\n"
            "Tag: py3-none-any\n",
        )
        archive.writestr(f"{dist_info}/RECORD", "")
        archive.writestr(
            f"{filename_name}/_vendor/nested-1.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: nested\nVersion: 1\n",
        )


def test_showcase_prepare_builds_one_wheelhouse_for_all_shards() -> None:
    text = CI.read_text(encoding="utf-8")
    prepare = text.split("  showcase-prepare:", 1)[1].split("\n  showcases:", 1)[0]
    assert "showcase-prepare" in text
    assert "showcase-wheelhouse" in text
    assert "pip wheel" in text
    assert "tools/showcase_wheelhouse.py derive" in prepare
    assert "tools/showcase_wheelhouse.py verify" in prepare
    assert ".github/showcase-editable-requirements.txt" in prepare
    assert "setuptools>=68" not in prepare
    # Shards consume the artifact — not four independent network resolves of
    # the same package set as the only install path.
    assert "Download shared wheelhouse" in text
    assert "--no-index --find-links" in text or "--find-links" in text


def test_build_requirements_are_derived_from_every_editable_project(
    tmp_path: Path,
) -> None:
    first = _write_build_project(
        tmp_path,
        "first",
        ["setuptools>=68", "wheel"],
    )
    second = _write_build_project(
        tmp_path,
        "second",
        ["hatchling>=1", "setuptools>=68"],
    )
    manifest = tmp_path / "editables.txt"
    output = tmp_path / "build-requirements.txt"
    _write_editable_manifest(manifest, [first, second], tmp_path)

    returncode = showcase_wheelhouse.main(
        [
            "derive",
            "--repo-root",
            str(tmp_path),
            "--editable-requirements",
            str(manifest),
            "--output",
            str(output),
        ]
    )

    assert returncode == 0
    assert output.read_text(encoding="utf-8") == (
        "hatchling>=1\nsetuptools>=68\nwheel\n"
    )


def test_incomplete_wheelhouse_refuses_by_missing_distribution_name(
    tmp_path: Path,
    capsys,
) -> None:
    project = _write_build_project(
        tmp_path,
        "first",
        ["missing-build-backend>=68"],
    )
    manifest = tmp_path / "editables.txt"
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    _write_editable_manifest(manifest, [project], tmp_path)

    returncode = showcase_wheelhouse.main(
        [
            "verify",
            "--repo-root",
            str(tmp_path),
            "--editable-requirements",
            str(manifest),
            "--wheelhouse",
            str(wheelhouse),
        ]
    )
    captured = capsys.readouterr()

    assert returncode != 0
    assert "missing distribution 'missing-build-backend'" in captured.err
    assert "required for offline editable install" in captured.err


def test_transitive_build_requirement_is_part_of_the_verified_closure(
    tmp_path: Path, capsys
) -> None:
    project = _write_build_project(tmp_path, "first", ["fixture-backend>=1"])
    manifest = tmp_path / "editables.txt"
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    _write_editable_manifest(manifest, [project], tmp_path)
    _write_wheel(
        wheelhouse,
        "fixture-backend",
        "1",
        requires=("fixture-build-hook>=2",),
    )

    args = [
        "verify",
        "--repo-root",
        str(tmp_path),
        "--editable-requirements",
        str(manifest),
        "--wheelhouse",
        str(wheelhouse),
    ]
    assert showcase_wheelhouse.main(args) != 0
    captured = capsys.readouterr()
    assert "missing distribution 'fixture-build-hook'" in captured.err
    assert "required for offline editable install" in captured.err

    _write_wheel(wheelhouse, "fixture-build-hook", "2")
    assert showcase_wheelhouse.main(args) == 0
    captured = capsys.readouterr()
    assert "showcase-wheelhouse-verified" in captured.out


def test_four_shards_remain_for_genuine_per_shard_work() -> None:
    text = CI.read_text(encoding="utf-8")
    assert "shard: [0, 1, 2, 3]" in text
    assert "SHOWCASE_SHARD_INDEX" in text
    assert "make test-showcases" in text


def test_missing_showcase_shard_is_unmeasured(tmp_path: Path) -> None:
    for i in range(3):
        d = tmp_path / f"showcase-shard-{i}"
        d.mkdir()
        (d / "showcase-shard-body.json").write_text(
            json.dumps(_green_showcase_body(i)),
            encoding="utf-8",
        )
    proc = subprocess.run(
        [
            sys.executable,
            str(ATTEND),
            "--reports-dir",
            str(tmp_path),
            "--shard-count",
            "4",
            "--require-commit",
            "abc",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert proc.returncode != 0
    assert "shard-03" in proc.stdout or "UNMEASURED" in proc.stdout


def test_full_showcase_roster_is_green(tmp_path: Path) -> None:
    for i in range(4):
        d = tmp_path / f"showcase-shard-{i}"
        d.mkdir()
        (d / "body.json").write_text(
            json.dumps(_green_showcase_body(i)),
            encoding="utf-8",
        )
    proc = subprocess.run(
        [
            sys.executable,
            str(ATTEND),
            "--reports-dir",
            str(tmp_path),
            "--shard-count",
            "4",
            "--require-commit",
            "abc",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_acid_test_gates_on_enrollment_not_raw_matrix() -> None:
    text = CI.read_text(encoding="utf-8")
    # Post-#7021: no prepare job. Acid gates on enrollment, not the raw matrix.
    acid = text.split("acid-test:")[1]
    needs_block = acid.split("runs-on:")[0]
    assert "showcase-attendance" in needs_block
    assert "needs.showcase-attendance.result" in acid
    assert "needs.showcases.result" not in acid
    # Job-level needs must not reintroduce the deleted prepare job.
    assert "- prepare" not in needs_block
    assert "needs: prepare" not in needs_block
    assert "needs: [prepare" not in needs_block
