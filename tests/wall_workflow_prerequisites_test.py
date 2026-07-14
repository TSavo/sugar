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


def test_wall_workflows_preserve_structured_wall_evidence() -> None:
    offenders = []

    for wall, workflow_path in WALL_WORKFLOWS.items():
        workflow = workflow_path.read_text(encoding="utf-8")
        wall_dir = f".sugar/{wall}-wall"
        log_dir = f".sugar/{wall}-wall-logs"
        mint = re.search(rf"make {wall}-wall\b", workflow)
        upload = re.search(r"(?m)^\s*- name: Upload .+ wall artifacts\s*$", workflow)
        required_before_mint = (
            f"SUGAR_ENGINE_LOG: ${{{{ github.workspace }}}}/{log_dir}/engine.jsonl",
            'SUGAR_ENGINE_HEARTBEAT_SECONDS: "5"',
            'SUGAR_ENGINE_CYCLE_THRESHOLD: "8"',
            f"SUGAR_KIT_LOG: ${{{{ github.workspace }}}}/{log_dir}/transport.jsonl",
            "SUGAR_KIT_LOG_LEVEL: INFO",
            f"mkdir -p {log_dir}",
            ': > "$SUGAR_ENGINE_LOG"',
            ': > "$SUGAR_KIT_LOG"',
        )
        required_in_upload = (
            "if: always()",
            f"{log_dir}/engine.jsonl",
            f"{log_dir}/transport.jsonl",
            f"{wall_dir}/",
        )

        reasons = []
        if mint is None:
            reasons.append("missing wall command")
        else:
            for requirement in required_before_mint:
                position = workflow.find(requirement)
                if position == -1 or position > mint.start():
                    reasons.append(f"missing before wall command: {requirement}")

        if upload is None:
            reasons.append("missing artifact upload step")
        else:
            if mint is not None and upload.start() < mint.start():
                reasons.append("artifact upload precedes wall command")
            upload_step = workflow[upload.start() :]
            for requirement in required_in_upload:
                if requirement not in upload_step:
                    reasons.append(
                        f"missing from always artifact upload: {requirement}"
                    )

        if reasons:
            offenders.append(
                f"{workflow_path.relative_to(ROOT)}: " + "; ".join(reasons)
            )

    assert not offenders, (
        "wall workflows must initialize per-wall engine/transport JSONL before the "
        "long wall command and always upload logs plus wall/frontier evidence; "
        "fix=configure the canonical SUGAR_ENGINE_*/SUGAR_KIT_* channels, pre-create "
        "both JSONL files, and keep the explicit artifact upload under always():\n"
        + "\n".join(offenders)
    )
