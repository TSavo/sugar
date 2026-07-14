"""Executable prerequisite audit for the scheduled Python package walls."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WALL_WORKFLOWS = {
    "numpy": ROOT / ".github/workflows/numpy-wall.yml",
    "pandas": ROOT / ".github/workflows/pandas-wall.yml",
}


def test_wall_workflows_install_b3sum_before_minting_frontier() -> None:
    offenders = []

    for wall, workflow_path in WALL_WORKFLOWS.items():
        workflow = workflow_path.read_text(encoding="utf-8")
        install = re.search(r"apt-get install[^\n]*\bb3sum\b", workflow)
        mint = re.search(rf"make {wall}-wall\b", workflow)
        if install is None or mint is None or install.start() > mint.start():
            offenders.append(str(workflow_path.relative_to(ROOT)))

    assert not offenders, (
        "wall workflows must apt-install b3sum before make invokes bin/sugarbin; "
        f"fix prerequisite ordering in: {', '.join(offenders)}"
    )
