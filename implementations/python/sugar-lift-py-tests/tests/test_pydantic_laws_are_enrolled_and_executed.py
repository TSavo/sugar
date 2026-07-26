"""The pydantic lift laws are ENROLLED, EXECUTED, and RECONCILED -- five teeth.

Collection succeeding is the weaker claim, and it is the one that fooled us
repeatedly: a suite can collect cleanly and still execute nothing that matters.
So each tooth opposes a different way the claim could be hollow:

    1. removing pydantic  -> an explicit dependency/collection FAILURE, never
                             a skip. Absence must be loud.
    2. a deliberate law failure -> observed as FAILED. Not skipped, not absent.
                             A denominator that cannot go red is not a
                             denominator.
    3. collected node IDs -> contain the pydantic laws BY NAME. Counting tests
                             does not prove which tests.
    4. the workflow       -> installs ONLY the declared [test] authority. If it
                             installs anything more, the authority is not the
                             authority and every claim resting on it is weaker
                             than it reads.
    5. the receipt        -> reconciles collected / passed / failed / skipped /
                             errored. Conservation, so a vanished test is
                             arithmetic rather than an absence nobody sees.

RULING ON THE HISTORY (#6369): these laws were **unintentionally unexecuted**.
`pydantic` was declared nowhere -- not in [project] dependencies, not in the
[test] extra, not in any workflow -- for the ENTIRE repo history
(``git log -S pydantic -- .github/`` returns nothing). Nobody decided they were
optional. They simply never ran.

So prior green runs of this package **ranged over a smaller universe than they
claimed** and are not retroactively authoritative for pydantic lifting.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
ROOT = PACKAGE.parents[2]
LAW_FILE = HERE / "test_lift_pydantic.py"

# The laws that must be enrolled by name. Counting is not naming.
REQUIRED_NODE_IDS = (
    "TestPydanticLift::test_pydantic_v2_field_constraints",
    "TestPydanticLift::test_pydantic_v2_numeric_range",
    "TestPydanticLift::test_pydantic_v2_annotated_types",
)

SUMMARY = re.compile(
    r"(?:(?P<n>\d+) (?P<outcome>passed|failed|skipped|error|errors|xfailed|xpassed))"
)


def _run_pytest(args, cwd=None, extra_env=None):
    """Run pytest out-of-process so a real verdict is observed, not simulated."""
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(PACKAGE / "src"), str(HERE)])
    env.pop("SUGAR_BIN", None)
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args, "--noconftest", "-p", "no:cacheprovider"],
        cwd=str(cwd or PACKAGE),
        capture_output=True,
        text=True,
        env=env,
        timeout=600,
    )


def _outcomes(output):
    """Parse the terminal summary into {outcome: count}."""
    tail = output.strip().splitlines()[-1] if output.strip() else ""
    found = {}
    for match in SUMMARY.finditer(tail):
        outcome = match.group("outcome")
        outcome = "error" if outcome == "errors" else outcome
        found[outcome] = found.get(outcome, 0) + int(match.group("n"))
    return found


# -- tooth 4: the authority is actually the authority ------------------------


def test_the_workflow_installs_only_the_declared_authority():
    """If a workflow hand-installs anything, the authority is not the authority.

    This closes the loop the pydantic finding opened: the MECHANISM was sound
    (every job installs only from the [test] table) while the TABLE was
    incomplete. Had the mechanism been leaky instead, declaring pydantic would
    have fixed nothing, because some job could satisfy the import another way
    and the table would describe nothing real.
    """
    pyproject = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))
    declared = set(pyproject["project"]["optional-dependencies"]["test"])
    assert any(dep.startswith("pydantic") for dep in declared), (
        "pydantic must be declared by the sole authority; it is imported by "
        "tests/test_lift_pydantic.py and lifted by a first-party production "
        "module. Undeclared, CI never installs it and the laws never run."
    )

    workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows, "no workflows found; this tooth would be vacuous"

    offenders = []
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        if "sugar-lift-py-tests" not in text:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if "pip install" not in stripped and not stripped.startswith("-e "):
                continue
            # A bare `pip install pydantic` anywhere would mean the import can
            # be satisfied without the authority declaring it.
            if re.search(r"\bpip install\b(?![^\n]*-e )[^\n]*\bpydantic\b", stripped):
                offenders.append(f"{workflow.name}: {stripped}")

    assert not offenders, (
        "a workflow installs pydantic directly, so the [test] extra is not the "
        "sole authority and every claim resting on it is weaker than it "
        f"reads:\n  " + "\n  ".join(offenders)
    )


# -- tooth 3: the laws are enrolled BY NAME ----------------------------------


def test_the_pydantic_laws_are_collected_by_name():
    """Counting collected tests does not prove WHICH tests were collected."""
    result = _run_pytest([str(LAW_FILE), "--collect-only", "-q"])
    assert result.returncode == 0, (
        f"collection of the pydantic laws failed:\n{result.stdout}\n{result.stderr}"
    )

    # EXACT node identities, not substrings. A substring test cannot tell a
    # law from a law that was renamed around it: `..._numeric_range_RENAMED`
    # contains `..._numeric_range`, so `in` reports the vanished law as
    # present. Mutation caught exactly that, which is the whole point of a
    # tooth that claims to check names.
    collected = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if ".py::" in line:
            collected.add(line.split(".py::", 1)[1])

    assert collected, f"no node IDs parsed; tooth would be vacuous:\n{result.stdout}"
    missing = [node for node in REQUIRED_NODE_IDS if node not in collected]
    assert not missing, (
        f"R={len(missing)} pydantic laws are not enrolled by exact name:\n  "
        + "\n  ".join(missing)
        + "\ncollected node IDs were:\n  "
        + "\n  ".join(sorted(collected))
    )


# -- teeth 1 + 2 + 5: absence is loud, failure is FAILED, counts reconcile ----


def test_the_pydantic_laws_actually_execute_and_reconcile():
    """Executed, not merely collected -- and the receipt conserves.

    Collection succeeding is the weaker claim. This asserts the stronger one:
    the laws ran, produced passes, and the terminal counts account for every
    collected node.
    """
    collect = _run_pytest([str(LAW_FILE), "--collect-only", "-q"])
    match = re.search(r"(\d+) tests? collected", collect.stdout)
    assert match, f"could not read collected count:\n{collect.stdout}"
    collected = int(match.group(1))
    assert collected >= len(REQUIRED_NODE_IDS)

    run = _run_pytest([str(LAW_FILE), "-q", "--tb=short"])
    outcomes = _outcomes(run.stdout)

    assert outcomes.get("skipped", 0) == 0, (
        "a pydantic law skipped. pydantic is DECLARED by the authority, so its "
        f"absence is a broken environment, never a skip: {outcomes}\n{run.stdout}"
    )
    assert outcomes.get("passed", 0) >= len(REQUIRED_NODE_IDS), (
        f"the pydantic laws did not execute to a pass: {outcomes}\n{run.stdout}"
    )

    # Conservation: every collected node reached a terminal verdict.
    accounted = sum(outcomes.values())
    assert accounted == collected, (
        f"receipt does not reconcile: collected={collected} accounted="
        f"{accounted} outcomes={outcomes}. A node that is collected and reaches "
        "no verdict has vanished, and a vanished node is exactly the defect "
        "this file exists to make impossible."
    )


def test_a_deliberate_law_failure_is_observed_as_FAILED(tmp_path):
    """The denominator must be able to go red, on these specific laws.

    A suite that cannot fail is not evidence. This mutates one pydantic law and
    requires the verdict to be FAILED -- not skipped (the law quietly not
    running) and not absent (the law quietly not collected).
    """
    mutated = tmp_path / "test_lift_pydantic.py"
    source = LAW_FILE.read_text(encoding="utf-8")
    broken = source.replace(
        'assert "User.name" in names',
        'assert "User.name" not in names  # deliberate mutation',
        1,
    )
    assert broken != source, "mutation anchor not found; this tooth would be vacuous"
    mutated.write_text(broken, encoding="utf-8")

    result = _run_pytest([str(mutated), "-q", "--tb=no"], cwd=tmp_path)
    outcomes = _outcomes(result.stdout)

    assert outcomes.get("failed", 0) >= 1, (
        "a deliberately broken pydantic law did not FAIL. It was "
        f"{outcomes or 'not observed at all'} -- so these laws cannot report a "
        f"defect and their green is not evidence.\n{result.stdout}\n{result.stderr}"
    )
    assert outcomes.get("skipped", 0) == 0, (
        f"the mutated law SKIPPED instead of failing: {outcomes}"
    )


def test_removing_pydantic_is_a_loud_failure_never_a_skip(tmp_path):
    """Tooth 1: absence of a declared dependency must be loud.

    Simulated by making the import unsatisfiable in a child process. The point
    is the SHAPE of the outcome: an environment missing a declared dependency
    must produce a failure or a collection error, never a skip that reports
    green on every machine that lacks it.
    """
    blocker = tmp_path / "sitecustomize.py"
    blocker.write_text(
        "import sys\n"
        "class _Block:\n"
        "    def find_module(self, name, path=None):\n"
        "        return self if name == 'pydantic' or name.startswith('pydantic.') else None\n"
        "    def load_module(self, name):\n"
        "        raise ImportError('pydantic blocked for this law')\n"
        "sys.meta_path.insert(0, _Block())\n",
        encoding="utf-8",
    )

    result = _run_pytest(
        [str(LAW_FILE), "-q", "--tb=no"],
        extra_env={"PYTHONPATH": f"{tmp_path}:{PACKAGE / 'src'}:{HERE}"},
    )
    outcomes = _outcomes(result.stdout)

    assert outcomes.get("skipped", 0) == 0, (
        "removing a DECLARED dependency produced a SKIP. That is the defect: "
        "the laws would report green on every machine lacking pydantic, which "
        f"is exactly how they went unrun for the repo's whole history.\n{result.stdout}"
    )
    assert result.returncode != 0, (
        "removing a declared dependency left the suite GREEN; absence must be "
        f"loud.\n{result.stdout}\n{result.stderr}"
    )
