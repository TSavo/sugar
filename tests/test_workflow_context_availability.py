"""Static teeth for GitHub context availability before runner dispatch."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
ACTIONLINT = os.environ.get("ACTIONLINT", "actionlint")
ACTIONLINT_VERSION = "v1.7.12"


def _run_actionlint(*paths: Path) -> subprocess.CompletedProcess[str]:
    """Run the version-pinned GitHub workflow schema/expression validator."""

    return subprocess.run(
        [
            ACTIONLINT,
            "-oneline",
            *(str(path) for path in paths),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


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


def _top_level_event_types(text: str, event: str) -> tuple[str, ...] | None:
    """Return an event's inline activity types from the top-level ``on`` map."""

    lines = text.splitlines()
    on_index: int | None = None
    for index, line in enumerate(lines):
        if re.fullmatch(r"on:\s*", line):
            on_index = index
            break
    if on_index is None:
        return None

    event_indent = 2
    event_pattern = re.compile(rf"{re.escape(event)}:\s*(.*)")
    for index in range(on_index + 1, len(lines)):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            break
        if indent != event_indent:
            continue
        match = event_pattern.fullmatch(line.strip())
        if match is None:
            continue
        if match.group(1):
            return ()
        for child in lines[index + 1 :]:
            if not child.strip() or child.lstrip().startswith("#"):
                continue
            child_indent = len(child) - len(child.lstrip(" "))
            if child_indent <= event_indent:
                return ()
            if child_indent != event_indent + 2:
                continue
            types_match = re.fullmatch(r"types:\s*\[([^]]*)\]\s*", child.strip())
            if types_match is None:
                continue
            return tuple(
                activity.strip()
                for activity in types_match.group(1).split(",")
                if activity.strip()
            )
        return ()
    return None


def _has_exact_merge_group_trigger(text: str) -> bool:
    """Return whether GitHub can dispatch the intended merge-group activity."""

    return _top_level_event_types(text, "merge_group") == ("checks_requested",)


class WorkflowContextAvailabilityTest(unittest.TestCase):
    def test_actionlint_version_is_pinned(self) -> None:
        result = subprocess.run(
            [ACTIONLINT, "-version"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines()[0], ACTIONLINT_VERSION)

    def test_actionlint_dispatchability_discriminator(self) -> None:
        illegal = """\
name: planted illegal context
on: workflow_dispatch
jobs:
  planted:
    name: illegal ${{ env.NOT_AVAILABLE_BEFORE_DISPATCH }}
    runs-on: ubuntu-latest
    steps:
      - run: echo unreachable
"""
        lawful = """\
name: lawful workflow
on: workflow_dispatch
jobs:
  planted:
    name: lawful static name
    runs-on: ubuntu-latest
    steps:
      - run: echo reachable
"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.yml"
            path.write_text(illegal)
            rejected = _run_actionlint(path)
            rejected_output = rejected.stdout + rejected.stderr
            self.assertNotEqual(rejected.returncode, 0, rejected_output)
            self.assertIn('context "env" is not allowed here', rejected_output)
            self.assertIn(f"{path}:5:23", rejected_output)

            path.write_text(lawful)
            accepted = _run_actionlint(path)
            self.assertEqual(
                accepted.returncode,
                0,
                accepted.stdout + accepted.stderr,
            )

    def test_every_workflow_is_schema_and_expression_valid(self) -> None:
        workflows = tuple(
            sorted((*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")))
        )
        self.assertTrue(workflows, "workflow audit denominator must be non-empty")
        result = _run_actionlint(*workflows)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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

    def test_merge_group_dispatchability_discriminator(self) -> None:
        lawful = """\
on:
  push:
    branches: [main]
  merge_group:
    types: [checks_requested]
jobs: {}
"""
        nested_under_push = """\
on:
  push:
    merge_group:
      types: [checks_requested]
jobs: {}
"""
        wrong_activity = """\
on:
  merge_group:
    types: [closed]
jobs: {}
"""
        missing = """\
on:
  push:
jobs: {}
"""

        self.assertTrue(_has_exact_merge_group_trigger(lawful))
        self.assertFalse(_has_exact_merge_group_trigger(nested_under_push))
        self.assertFalse(_has_exact_merge_group_trigger(wrong_activity))
        self.assertFalse(_has_exact_merge_group_trigger(missing))

    def test_ci_dispatches_exact_merge_group_checks_requested_event(self) -> None:
        self.assertTrue(
            _has_exact_merge_group_trigger((WORKFLOWS / "ci.yml").read_text()),
            "ci.yml must expose the exact top-level merge_group checks_requested "
            "event; YAML parsing alone does not prove GitHub can dispatch it",
        )


if __name__ == "__main__":
    unittest.main()
