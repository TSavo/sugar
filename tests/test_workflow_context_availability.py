"""Static teeth for GitHub context availability before runner dispatch."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _pre_dispatch_runner_context_violations(text: str) -> list[int]:
    """Return runner-context uses in workflow/job env, before a runner exists."""

    violations: list[int] = []
    env_indent: int | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if env_indent is not None and indent <= env_indent:
            env_indent = None
        if re.fullmatch(r"env:\s*", line.strip()) and indent in (0, 4):
            env_indent = indent
            continue
        if env_indent is not None and "${{ runner." in line:
            violations.append(line_number)
    return violations


class WorkflowContextAvailabilityTest(unittest.TestCase):
    def test_runner_context_availability_discriminator(self) -> None:
        workflow = """\
env:
  GLOBAL_ROOT: ${{ runner.temp }}/global
jobs:
  example:
    env:
      JOB_ROOT: ${{ runner.temp }}/job
    steps:
      - name: allowed after dispatch
        env:
          STEP_ROOT: ${{ runner.temp }}/step
        run: echo ok
"""
        self.assertEqual(_pre_dispatch_runner_context_violations(workflow), [2, 6])

    def test_workflows_do_not_use_runner_context_before_dispatch(self) -> None:
        violations = {
            path.relative_to(ROOT).as_posix(): lines
            for path in sorted((*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")))
            if (lines := _pre_dispatch_runner_context_violations(path.read_text()))
        }
        self.assertEqual(
            violations,
            {},
            "runner context is unavailable in workflow/job env before dispatch; "
            "move each use to step env",
        )


if __name__ == "__main__":
    unittest.main()
