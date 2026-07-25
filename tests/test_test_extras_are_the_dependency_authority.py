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
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "implementations/python/sugar-lift-py-tests"
PYPROJECT = PACKAGE / "pyproject.toml"
WORKFLOWS = ROOT / ".github/workflows"

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
    """Every `pip install ...` invocation, one entry per real command."""
    commands = []
    for block in run_blocks(workflow_text):
        block = re.sub(r"\\\s*\n\s*", " ", block)  # shell backslash-newline
        for line in block.split("\n"):
            for match in re.finditer(r"pip install[^\n]*", line):
                command = match.group(0)
                if "--upgrade pip" in command:
                    continue  # bootstrapping pip itself is not a dependency
                commands.append(command)
    return commands


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
            if token in {"--index-url", "--extra-index-url", "-r", "-c"}:
                skip_next = True
            continue
        if "/" in token or token.startswith(".") or token.endswith(".txt"):
            continue  # path install
        if token in {"pip", "install", "python", "-m"}:
            continue
        bare.append(normalize(token))
    return bare


def workflows_installing_authority() -> dict[Path, list[str]]:
    hits: dict[Path, list[str]] = {}
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
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
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
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
        commands = [c for c in pip_install_commands(text) if AUTHORITY in c]
        if not commands:
            offenders.append(f"{name}: never installs {AUTHORITY}")
            continue
        for command in commands:
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
