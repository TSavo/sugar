from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

from sugar_lift_py_tests.factory import default_catalog

PY_TESTS = Path(__file__).resolve().parents[1]
SRC = PY_TESTS / "src"


def _planted_sugar_class(name: str, *, comes_before: tuple[str, ...] = ()) -> str:
    return f"""
from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing


class {name}(Sugar, role=SugarRole.TERM, comes_before={comes_before!r}):
    @classmethod
    def owns(cls, fragment) -> bool:
        return False

    @classmethod
    def build(cls, fragment, ctx):
        raise AssertionError("registry validation planted sugar must not build")

    @classmethod
    def witnesses(cls):
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="RegistryValidationSyntheticFloor",
            reason="registry import validation planted control",
        )

    def desugar(self, ctx):
        raise AssertionError("registry validation planted sugar must not desugar")
"""


def _run_default_catalog_with_planted_modules(
    tmp_path: Path,
    modules: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    sugar_dir = tmp_path / "sugar"
    sugar_dir.mkdir()
    for module_name, source in modules.items():
        (sugar_dir / f"{module_name}.py").write_text(
            textwrap.dedent(source),
            encoding="utf-8",
        )
    script = """
import sys
import sugar_lift_py_tests.sugar as sugar_pkg
from sugar_lift_py_tests.factory import default_catalog

sugar_pkg.__path__.insert(0, sys.argv[1])
catalog = default_catalog()
planted = sorted(
    claim.name for claim in catalog.claims if claim.name.endswith("PlantedSugar")
)
print("catalog-ok:" + ",".join(planted))
"""
    env = {
        **os.environ,
        "PYTHONPATH": str(SRC),
    }
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script), str(sugar_dir)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _assert_import_refuses(
    completed: subprocess.CompletedProcess[str],
    expected_message: str,
) -> None:
    assert completed.returncode != 0, completed.stdout
    assert expected_message in completed.stderr


def test_live_claim_registry_imports_cleanly() -> None:
    claims = list(default_catalog().claims)

    assert len({claim.name for claim in claims}) == len(claims)
    assert {"CallSugar", "AddSugar", "ReturnSugar", "TrySugar"} <= {
        claim.name for claim in claims
    }


def test_legal_forward_comes_before_registration_imports_cleanly(tmp_path: Path) -> None:
    completed = _run_default_catalog_with_planted_modules(
        tmp_path,
        {
            "planted_legal_a": _planted_sugar_class(
                "LegalAlphaPlantedSugar",
                comes_before=("LegalBetaPlantedSugar",),
            ),
            "planted_legal_b": _planted_sugar_class("LegalBetaPlantedSugar"),
        },
    )

    assert completed.returncode == 0, completed.stderr
    assert "catalog-ok:LegalAlphaPlantedSugar,LegalBetaPlantedSugar" in completed.stdout


def test_duplicate_claim_name_refuses_at_import(tmp_path: Path) -> None:
    completed = _run_default_catalog_with_planted_modules(
        tmp_path,
        {
            "planted_dup_a": _planted_sugar_class("DuplicatePlantedSugar"),
            "planted_dup_b": _planted_sugar_class("DuplicatePlantedSugar"),
        },
    )

    _assert_import_refuses(
        completed,
        "duplicate Sugar claim name `DuplicatePlantedSugar`: "
        "first claimant `sugar_lift_py_tests.sugar.planted_dup_a.DuplicatePlantedSugar`, "
        "second claimant `sugar_lift_py_tests.sugar.planted_dup_b.DuplicatePlantedSugar`. "
        "Fix: rename one Sugar class or merge the implementations behind one "
        "registered claim name.",
    )


def test_dangling_comes_before_refuses_at_import(tmp_path: Path) -> None:
    completed = _run_default_catalog_with_planted_modules(
        tmp_path,
        {
            "planted_dangling": _planted_sugar_class(
                "DanglingPlantedSugar",
                comes_before=("MissingPlantedSugar",),
            ),
        },
    )

    _assert_import_refuses(
        completed,
        "dangling Sugar comes_before reference: `DanglingPlantedSugar` declares "
        "target `MissingPlantedSugar`, but no registered claim has that name. "
        "Fix: rename the comes_before target to an existing Sugar claim or "
        "import/register `MissingPlantedSugar` before the catalog is built.",
    )


def test_two_cycle_comes_before_refuses_at_import(tmp_path: Path) -> None:
    completed = _run_default_catalog_with_planted_modules(
        tmp_path,
        {
            "planted_cycle_a": _planted_sugar_class(
                "CycleAPlantedSugar",
                comes_before=("CycleBPlantedSugar",),
            ),
            "planted_cycle_b": _planted_sugar_class(
                "CycleBPlantedSugar",
                comes_before=("CycleAPlantedSugar",),
            ),
        },
    )

    _assert_import_refuses(
        completed,
        "Sugar comes_before cycle: CycleAPlantedSugar -> CycleBPlantedSugar -> "
        "CycleAPlantedSugar. Fix: remove one comes_before edge or split the "
        "sugar role so registry precedence is acyclic.",
    )


def test_three_cycle_comes_before_refuses_at_import(tmp_path: Path) -> None:
    completed = _run_default_catalog_with_planted_modules(
        tmp_path,
        {
            "planted_cycle_a": _planted_sugar_class(
                "CycleAPlantedSugar",
                comes_before=("CycleBPlantedSugar",),
            ),
            "planted_cycle_b": _planted_sugar_class(
                "CycleBPlantedSugar",
                comes_before=("CycleCPlantedSugar",),
            ),
            "planted_cycle_c": _planted_sugar_class(
                "CycleCPlantedSugar",
                comes_before=("CycleAPlantedSugar",),
            ),
        },
    )

    _assert_import_refuses(
        completed,
        "Sugar comes_before cycle: CycleAPlantedSugar -> CycleBPlantedSugar -> "
        "CycleCPlantedSugar -> CycleAPlantedSugar. Fix: remove one comes_before "
        "edge or split the sugar role so registry precedence is acyclic.",
    )
