"""Class instrument: pyproject.toml is the sole test-dependency authority.

Workflows and Makefile install loops must not free-float packages that
``sugar-lift-py-tests`` already owns via ``dependencies`` or
``[project.optional-dependencies]``. One red forever if a seventh workflow
re-invents the instance.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

# Packages sugar-lift-py-tests owns. Free-floating these names in workflow pip
# install lines (or Makefile install loops) is the closed crime class.
AUTHORITY_PACKAGES = frozenset(
    {
        "blake3",
        "pynacl",
        "cbor2",
        "tqdm",
        "pytest",
        "black",
        "pyright",
        "itsdangerous",
        "numpy",
        "pandas",
        "scikit-learn",
        "scikit_learn",
    }
)

# The six class members named in docs/plans/pyproject-test-sole-dep-authority.md
# plus same-class siblings we close in the same PR.
WORKFLOWS = (
    "bare-exception-zero-tolerance.yml",
    "native-crash-zero-tolerance.yml",
    "timeout-zero-tolerance.yml",
    "factory-zero-tolerance.yml",
    "datetime-claim-twins.yml",
    "restored-suite-scoreboard.yml",
    "ci.yml",
    "examples-gate.yml",
    "numpy-wall.yml",
    "pandas-wall.yml",
)

_PIP_INSTALL = re.compile(r"pip\s+install\b", re.IGNORECASE)
# Token that is only package name / version pin, not a path or flag.
_BARE_TOKEN = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?P<spec>(?:==|>=|<=|~=|!=|>|<)[^;]+)?$"
)


def _authority_name_set() -> set[str]:
    names: set[str] = set()
    for p in AUTHORITY_PACKAGES:
        names.add(p.lower())
        names.add(p.lower().replace("_", "-"))
        names.add(p.lower().replace("-", "_"))
    return names


def free_floating_authority_pins(text: str) -> list[str]:
    """Scan pip-install regions for bare authority package tokens."""
    authority = _authority_name_set()
    findings: list[str] = []
    lines = text.splitlines()
    regions: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] | None = None
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if _PIP_INSTALL.search(stripped):
            current = [(idx, stripped)]
            regions.append(current)
            continue
        if current is None:
            continue
        if line.startswith(" ") or line.startswith("\t") or stripped.endswith("\\"):
            if stripped.startswith("- name:"):
                current = None
                continue
            current.append((idx, stripped))
            continue
        current = None

    for region in regions:
        for line_no, stripped in region:
            cleaned = stripped.rstrip("\\").strip()
            if cleaned.startswith("#"):
                continue
            for raw in cleaned.split():
                token = raw.strip("'\"")
                if not token:
                    continue
                if token in (
                    "python",
                    "python3",
                    "-m",
                    "pip",
                    "install",
                    "-e",
                    "--editable",
                    ">",
                    ">-",
                    "|",
                ):
                    continue
                if token.startswith("--"):
                    continue
                if (
                    token.startswith("./")
                    or token.startswith("../")
                    or token.startswith("implementations/")
                    or token.startswith("$")
                    or "implementations/" in token
                    or token.startswith("-e")
                ):
                    continue
                if "[" in token:
                    continue
                match = _BARE_TOKEN.match(token)
                if match is None:
                    continue
                name = match.group("name").lower()
                if name in authority or name.replace("_", "-") in authority:
                    findings.append(
                        f"line {line_no}: free-floating authority pin {token!r}"
                    )
    return findings


def test_workflows_have_no_free_floating_authority_pins() -> None:
    """Every workflow install of authority packages must go through pyproject."""
    breaches: list[str] = []
    for name in WORKFLOWS:
        path = ROOT / ".github" / "workflows" / name
        assert path.is_file(), f"missing workflow {name}"
        text = path.read_text(encoding="utf-8")
        for finding in free_floating_authority_pins(text):
            breaches.append(f"{name}: {finding}")
    assert breaches == [], (
        "workflow free-floating authority pins (use sugar-lift-py-tests extras):\n"
        + "\n".join(breaches)
    )


def test_six_class_members_install_via_sugar_lift_py_tests_extra() -> None:
    """The named six must install sugar-lift-py-tests[test] (or a composite)."""
    six = (
        "bare-exception-zero-tolerance.yml",
        "native-crash-zero-tolerance.yml",
        "timeout-zero-tolerance.yml",
        "factory-zero-tolerance.yml",
        "datetime-claim-twins.yml",
        "restored-suite-scoreboard.yml",
    )
    for name in six:
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert (
            "sugar-lift-py-tests[test" in text or "sugar-lift-py-tests[test]" in text
        ), f"{name} must install sugar-lift-py-tests[test…] as sole test authority"


def test_pyproject_declares_authority_extras() -> None:
    """Authority packages must live in pyproject, not only in workflow comments."""
    pyproject = (
        ROOT / "implementations/python/sugar-lift-py-tests/pyproject.toml"
    ).read_text(encoding="utf-8")
    assert 'test = ["pytest' in pyproject or "test = [" in pyproject
    assert "pytest" in pyproject
    assert "blake3" in pyproject
    assert "numpy" in pyproject
    assert "pandas" in pyproject
    # Named extras for corpus inputs.
    assert re.search(r"^numpy\s*=", pyproject, re.MULTILINE)
    assert re.search(r"^pandas\s*=", pyproject, re.MULTILINE)


def test_wall_workflows_use_named_corpus_extras() -> None:
    numpy_wall = (ROOT / ".github/workflows/numpy-wall.yml").read_text(encoding="utf-8")
    pandas_wall = (ROOT / ".github/workflows/pandas-wall.yml").read_text(
        encoding="utf-8"
    )
    assert "sugar-lift-py-tests[test,numpy]" in numpy_wall
    assert "sugar-lift-py-tests[test,pandas]" in pandas_wall
    # No free-floating corpus pin lines.
    assert not re.search(r"pip install[^\n]*\bnumpy\b", numpy_wall)
    assert not re.search(r"pip install[^\n]*\bpandas\b", pandas_wall)


def test_makefile_sugar_lift_py_tests_uses_extras_not_free_float() -> None:
    """Primary test-python loop installs via .[test,…] extras."""
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert ".[test,numpy,pandas,scikit-learn]" in makefile or (
        "sugar-lift-py-tests[test" in makefile
    )
    # The sugar-lift-py-tests venv install must not free-float numpy/pandas.
    # (Other package loops may still install their own package -e .)
    block = re.search(
        r"cd implementations/python/sugar-lift-py-tests &&.*?pytest\) \|\|",
        makefile,
        re.DOTALL,
    )
    assert block is not None
    body = block.group(0)
    assert "numpy pandas" not in body
    assert "scikit-learn" not in body or "scikit-learn]" in body
