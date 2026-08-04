"""`sugar-lift-py-tests[test]` is the SOLE dependency authority across CI.

#6260 found `itsdangerous` and `numpy` declared in `[test]` but never installed
by CI, because CI maintained its own hand-list. The four zero-tolerance floors
were the worst offenders: they installed the package WITHOUT `[test]` and
hand-listed `pytest`. A hand-list is one module-scope import away from the
collection abort those very floors exist to catch.

This is a static audit over `pyproject.toml` + the workflow YAMLs. It asserts a
property of the CONFIG, not of a run, so it is red the moment the config drifts
— no CI round trip required.

Four teeth, and the fourth is the one that keeps the authority honest:

1. Every workflow that installs the package installs `-e ...[test]`.
2. No workflow duplicates a dependency owned by the authority.
3. Removing a required package from the authority makes its consumer fail:
   every third-party MODULE-SCOPE import in the package's collected tests must
   be declared in the authority.
4. Adding a dependency only to a workflow CANNOT satisfy tooth 3 — the
   resolver reads pyproject and never the workflows, proven on a synthetic
   pair where the workflow supplies what pyproject omits.

THE AUDIT FOLLOWS THE INSTALL, WHEREVER IT LIVES. The environment is now built
once by the composite action `.github/actions/python-test-environment`, which
the authoritative suite job and the zero-tolerance floors all consume. Moving
an install out of a workflow and into an action must NOT move it out of this
audit's sight, so the action file is audited with the identical teeth and a
consumer counts as bound either by installing `[test]` itself or by using that
action. A floor that does neither is still an offender, by name.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

from sugar_lift_py_tests.repo_root import resolve_repo_root

ROOT = resolve_repo_root()
PACKAGE = ROOT / "implementations/python/sugar-lift-py-tests"
PYPROJECT = PACKAGE / "pyproject.toml"
WORKFLOWS = ROOT / ".github/workflows"

# The ONE place the Python test environment is defined. Audited exactly like a
# workflow: an install that hides in a composite action is still an install.
ENVIRONMENT_ACTION = ROOT / ".github/actions/python-test-environment/action.yml"
ENVIRONMENT_ACTION_USE = "./.github/actions/python-test-environment"

AUTHORITY = "sugar-lift-py-tests"

# Import name -> distribution name, where they differ.
IMPORT_TO_DIST = {"nacl": "pynacl"}

# Sibling modules importable because conftest puts the package's own scripts/
# and tests/ on sys.path. These are first-party, not dependencies.
FIRST_PARTY_PREFIXES = ("sugar_", "libsugar_", "conftest", "test_")


def normalize(name: str) -> str:
    """PEP 503 canonical form, minus any version specifier or extra."""
    name = re.split(r"[<>=!~\[;]", name, maxsplit=1)[0].strip()
    return re.sub(r"[-_.]+", "-", name).lower()


def authority_packages(pyproject_text: str) -> set[str]:
    """Every distribution the authority declares: runtime deps + [test] extras.

    Reads ONLY pyproject. Never reads a workflow — that is tooth 4.
    """
    data = tomllib.loads(pyproject_text)
    project = data["project"]
    declared = list(project.get("dependencies", []))
    declared += list(project.get("optional-dependencies", {}).get("test", []))
    return {normalize(dep) for dep in declared}


def module_scope_third_party_imports(package: Path) -> dict[str, list[str]]:
    """Third-party distributions imported at MODULE scope by collected tests.

    tests/vendor/** and tests/fixtures/** are LIFT CORPUS — files Sugar reads as
    input, never collected or executed by pytest — so their imports are not
    dependencies of this package.
    """
    stdlib = set(sys.stdlib_module_names)
    found: dict[str, list[str]] = {}

    for path in sorted(package.glob("tests/**/*.py")):
        rel = path.relative_to(package).as_posix()
        if rel.startswith(("tests/vendor/", "tests/fixtures/")):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:  # module scope only — the collection-abort class
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = [node.module.split(".")[0]]
            else:
                continue
            for root in roots:
                if root in stdlib or root.startswith(FIRST_PARTY_PREFIXES):
                    continue
                if (package / "scripts" / f"{root}.py").exists():
                    continue  # sibling script module, first-party
                if (package / "tests" / f"{root}.py").exists():
                    continue
                if (ROOT / "tests" / f"{root}.py").exists():
                    continue  # repo-level test support (checkout_resolution),
                    # reached by path from a conftest, not a distribution
                dist = IMPORT_TO_DIST.get(root, normalize(root))
                found.setdefault(dist, []).append(rel)

    return found


def run_blocks(workflow_text: str) -> list[str]:
    """Every `run:` script in a workflow, with its YAML scalar style honoured.

    `run: >-` folds every line into ONE command; `run: |` keeps lines separate.
    Getting this wrong merges neighbouring commands and silently swallows
    offenders, so the two styles are handled apart rather than regex-folded.
    """
    lines = workflow_text.split("\n")
    blocks: list[str] = []

    index = 0
    while index < len(lines):
        header = re.match(r"^(\s*)-?\s*run:\s*(\S*)\s*$", lines[index])
        if header is None:
            # `run: some-inline-command`
            inline = re.match(r"^\s*-?\s*run:\s+(\S.*)$", lines[index])
            if inline and inline.group(1) not in {"|", ">-", ">", "|-"}:
                blocks.append(inline.group(1))
            index += 1
            continue

        indent, style = len(header.group(1)), header.group(2)
        body: list[str] = []
        index += 1
        while index < len(lines):
            line = lines[index]
            if line.strip() and (len(line) - len(line.lstrip())) <= indent:
                break
            body.append(line.strip())
            index += 1

        blocks.append(" ".join(body) if style in {">-", ">"} else "\n".join(body))

    return blocks


def pip_install_commands(workflow_text: str) -> list[str]:
    """Every dependency-acquiring pip invocation, one entry per real command.

    `pip wheel` is included: building a wheelhouse from a requirement is how
    the immutable environment acquires its dependencies, so a hand-list smuggled
    into a `pip wheel` line is the same #6260 offence as one in `pip install`.
    """
    commands = []
    for block in run_blocks(workflow_text):
        block = re.sub(r"\\\s*\n\s*", " ", block)  # shell backslash-newline
        for line in block.split("\n"):
            for match in re.finditer(r"pip (?:install|wheel)[^\n]*", line):
                command = match.group(0)
                if "--upgrade pip" in command:
                    continue  # bootstrapping pip itself is not a dependency
                commands.append(command)
    return commands


def is_wheel_build(command: str) -> bool:
    """`pip wheel` BUILDS the immutable environment's inputs.

    Editability is meaningless for a wheel build — and an editable install is
    precisely what the immutable environment exists to avoid — so tooth 1's
    `-e` requirement does not apply here. The `[test]` requirement still does:
    a wheelhouse built without the extras is an environment missing every
    package the suite declares, which is #6260 with extra steps.
    """
    return command.startswith("pip wheel")


def audit_sites() -> list[Path]:
    """Every file that may acquire this package's dependencies.

    Workflows plus the composite action. Adding a new install site without
    adding it here is the drift this list exists to make impossible.
    """
    sites = sorted(WORKFLOWS.glob("*.yml"))
    if ENVIRONMENT_ACTION.exists():
        sites.append(ENVIRONMENT_ACTION)
    return sites


def binds_to_authority(text: str) -> bool:
    """Does this file draw its Python environment from the authority?

    Two legal ways, and only two: install `[test]` directly, or delegate to the
    one composite action that does. Anything else is a floor running against an
    environment nobody defined.
    """
    if ENVIRONMENT_ACTION_USE in text:
        return True
    return any(AUTHORITY in command for command in pip_install_commands(text))


def bare_requirements(command: str) -> list[str]:
    """Requirement tokens that are NOT path installs — i.e. hand-listed."""
    tokens = command.replace("'", " ").replace('"', " ").split()
    bare = []
    skip_next = False
    for token in tokens[2:]:  # drop "pip install"
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            if token in {
                "--index-url",
                "--extra-index-url",
                "--find-links",
                "-r",
                "-c",
                "-f",
            }:
                skip_next = True
            continue
        if "/" in token or token.startswith(".") or token.endswith(".txt"):
            continue  # path install
        if token.endswith(".whl"):
            continue  # wheel file by name (third-party wheelhouse install)
        if "$" in token or token.startswith("{"):
            continue  # shell expansion / array (e.g. "${third_party[@]}")
        if token in {"pip", "install", "python", "-m"}:
            continue
        bare.append(normalize(token))
    return bare


def workflows_installing_authority() -> dict[Path, list[str]]:
    hits: dict[Path, list[str]] = {}
    for workflow in audit_sites():
        commands = [
            command
            for command in pip_install_commands(workflow.read_text(encoding="utf-8"))
            if AUTHORITY in command
        ]
        if commands:
            hits[workflow] = commands
    return hits


# --------------------------------------------------------------------------
# Tooth 1: every relevant install uses `-e ...[test]`
# --------------------------------------------------------------------------
def test_every_authority_install_uses_editable_test_extras() -> None:
    installs = workflows_installing_authority()
    assert installs, "no workflow installs the authority package — audit is blind"

    offenders = []
    for workflow, commands in installs.items():
        for command in commands:
            for token in command.replace("'", " ").replace('"', " ").split():
                if not token.endswith(AUTHORITY) and AUTHORITY not in token:
                    continue
                if "/" not in token:
                    continue
                if not token.endswith(f"{AUTHORITY}[test]"):
                    offenders.append(
                        f"{workflow.name}: installs `{token}` without [test] extras"
                    )
                elif is_wheel_build(command):
                    continue  # wheel builds are immutable by construction
                elif f"-e {token}" not in command and f"-e '{token}'" not in command:
                    offenders.append(
                        f"{workflow.name}: installs `{token}` non-editable"
                    )

    assert not offenders, (
        "every install of the dependency authority must be `-e "
        f"'...{AUTHORITY}[test]'`; installing it without the extras silently "
        "drops every package the suite declares.\nfix=append [test] and -e:\n  "
        + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------
# Tooth 2: no workflow duplicates a dependency owned by [test]
# --------------------------------------------------------------------------
def test_no_workflow_hand_lists_a_package_the_authority_owns() -> None:
    owned = authority_packages(PYPROJECT.read_text(encoding="utf-8"))

    offenders = []
    for workflow in audit_sites():
        text = workflow.read_text(encoding="utf-8")
        commands = pip_install_commands(text)
        # Scope is the WORKFLOW, not the single command: `pip install numpy` in
        # a later step of the same job supplements the authority just as much as
        # naming numpy on the authority's own install line.
        if not any(AUTHORITY in command for command in commands):
            continue
        for command in commands:
            for requirement in bare_requirements(command):
                if requirement in owned:
                    offenders.append(f"{workflow.name}: hand-lists `{requirement}`")

    assert not offenders, (
        f"`{AUTHORITY}[test]` is the SOLE dependency authority: a workflow that "
        "installs [test] AND hand-lists a package it owns is supplementing, not "
        "delegating, and the hand-list drifts out of date exactly the way #6260 "
        "did.\nfix=DELETE the hand-listed token; [test] already provides it:\n  "
        + "\n  ".join(sorted(set(offenders)))
    )


# --------------------------------------------------------------------------
# Tooth 3: removing a required package from [test] makes its consumer fail
# --------------------------------------------------------------------------
def test_every_module_scope_import_is_declared_by_the_authority() -> None:
    declared = authority_packages(PYPROJECT.read_text(encoding="utf-8"))
    imported = module_scope_third_party_imports(PACKAGE)
    assert imported, "import census found nothing — the audit walked the wrong tree"

    offenders = [
        f"`{dist}` imported at module scope by {consumers[0]}"
        f" ({len(consumers)} file(s)) but not declared"
        for dist, consumers in sorted(imported.items())
        if dist not in declared
    ]

    assert not offenders, (
        "an undeclared module-scope import aborts collection for the WHOLE "
        f"package (#6260). Declare it in {AUTHORITY}'s [project] dependencies "
        "or [project.optional-dependencies].test — never in a workflow:\n  "
        + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------
# Tooth 4: a workflow-only addition CANNOT satisfy the authority law
# --------------------------------------------------------------------------
def test_adding_a_dependency_only_to_a_workflow_cannot_satisfy_the_law() -> None:
    """Both faces of the discriminator, on a synthetic pyproject/workflow pair.

    Positive face: declared in pyproject   -> resolver sees it.
    Negative face: declared ONLY in a workflow -> resolver still does not see it.
    """
    without = """
[project]
name = "synthetic"
version = "0"
dependencies = ["blake3"]
[project.optional-dependencies]
test = ["pytest"]
"""
    with_declaration = without.replace('test = ["pytest"]', 'test = ["pytest", "numpy"]')

    # Positive face: pyproject is the only thing that can grant authority.
    assert "numpy" in authority_packages(with_declaration)

    # Negative face: a workflow that installs numpy explicitly, and installs the
    # authority WITH [test], still cannot make the resolver believe numpy is
    # declared — because the resolver never reads the workflow at all.
    workflow_supplying_numpy = (
        "      - name: Install\n"
        "        run: |\n"
        "          python -m pip install --quiet numpy\n"
        f"          python -m pip install -e 'implementations/python/{AUTHORITY}[test]'\n"
    )
    supplied = {
        requirement
        for command in pip_install_commands(workflow_supplying_numpy)
        for requirement in bare_requirements(command)
    }
    assert "numpy" in supplied, (
        "fixture is inert: the synthetic workflow does not actually install numpy"
    )

    assert "numpy" not in authority_packages(without), (
        "a workflow-only `pip install numpy` must NEVER satisfy the authority "
        "law — otherwise the hand-list papers over a missing declaration and "
        "#6260 recurs the moment that workflow is copied without the hand-list"
    )


def test_the_four_zero_tolerance_floors_are_bound_to_the_authority() -> None:
    """The floors are the instruments that catch the collection abort. They are
    the LAST place a hand-list may live, so they are named explicitly here: a
    new floor that forgets [test] is caught by name, not by luck."""
    floors = [
        "bare-exception-zero-tolerance.yml",
        "factory-zero-tolerance.yml",
        "native-crash-zero-tolerance.yml",
        "timeout-zero-tolerance.yml",
    ]

    offenders = []
    for name in floors:
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        if not binds_to_authority(text):
            offenders.append(
                f"{name}: neither installs {AUTHORITY}[test] nor uses "
                f"{ENVIRONMENT_ACTION_USE}"
            )
            continue
        for command in [c for c in pip_install_commands(text) if AUTHORITY in c]:
            if f"{AUTHORITY}[test]" not in command:
                offenders.append(f"{name}: installs {AUTHORITY} without [test]")
            if bare_requirements(command):
                offenders.append(
                    f"{name}: hand-lists {sorted(set(bare_requirements(command)))}"
                )

    assert not offenders, (
        "the zero-tolerance floors must draw their entire environment from "
        f"`{AUTHORITY}[test]`:\n  " + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------
# Tooth 6: the delegation target is real, and is itself bound
# --------------------------------------------------------------------------
def test_the_environment_action_is_the_one_bound_definition() -> None:
    """`uses:` the action is only a legal binding because the action obeys.

    Tooth 5 accepts delegation to `.github/actions/python-test-environment`.
    That acceptance is worth exactly as much as this test: if the action stops
    existing, stops acquiring `[test]` into the wheelhouse, or starts
    hand-listing, then every floor that delegates to it is unbound and tooth
    5's green is a lie.

    First-party packages are resolved from the synced checkout (PYTHONPATH),
    not wheel-installed into the venv. The authority still drives the
    *wheelhouse* via ``pip wheel ... sugar-lift-py-tests[test]``; the install
    step must not put first-party packages into site-packages.
    """
    assert ENVIRONMENT_ACTION.exists(), (
        f"{ENVIRONMENT_ACTION_USE} is the single definition of the Python test "
        "environment and every zero-tolerance floor delegates to it. It is "
        "missing — restore it, or re-bind each floor to the authority directly."
    )

    text = ENVIRONMENT_ACTION.read_text(encoding="utf-8")
    commands = [c for c in pip_install_commands(text) if AUTHORITY in c]
    assert commands, (
        f"{ENVIRONMENT_ACTION.name} never acquires {AUTHORITY}[test]; every "
        "consumer that delegates to it is running against an environment "
        "nobody declared"
    )

    offenders = []
    for command in commands:
        if f"{AUTHORITY}[test]" not in command:
            offenders.append(f"acquires {AUTHORITY} without [test]: {command}")
        # First-party must not be installed into the venv. `pip wheel` may
        # still name the path so the third-party wheelhouse resolves from the
        # authority table; `pip install` of the first-party package is the
        # false-provenance defect authenticate_lift exists to refuse.
        if command.startswith("pip install") and AUTHORITY in command:
            offenders.append(
                f"wheel-installs first-party {AUTHORITY} into the venv "
                f"(must resolve from checkout via PYTHONPATH): {command}"
            )
    for command in pip_install_commands(text):
        hand_listed = [
            requirement
            for requirement in bare_requirements(command)
            if requirement
            not in {
                # wheel bootstrap only; third-party deps arrive as wheel paths.
                "wheel",
            }
        ]
        if hand_listed:
            offenders.append(f"hand-lists {sorted(set(hand_listed))}: {command}")

    if "managed_checkout_pythonpath" not in text and "SUGAR_CHECKOUT_PYTHONPATH" not in text:
        offenders.append(
            "does not bind managed checkout PYTHONPATH before consumers import "
            "first-party packages"
        )

    assert not offenders, (
        f"{ENVIRONMENT_ACTION.name} is the ONE definition of the Python test "
        f"environment; third-party from `{AUTHORITY}[test]` wheelhouse, "
        f"first-party from the synced checkout:\n  "
        + "\n  ".join(offenders)
    )
