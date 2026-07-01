"""
CI guard: ALL of src/sugar_lift_py_tests must not import ast or use
isinstance(.., ast.X) directly. Every AST access goes through SourceFragment,
whose sole permitted home for raw ast is factory/source_fragment.py.

Forbidden patterns (anywhere under src/**/*.py):
  - `import ast`
  - `isinstance(<x>, ast.<Y>)`

The ONLY exclusion is the gateway itself. There is no deprecation allowlist:
the three legacy modules still carrying raw ast (lsp.py, layer2.py,
translate_universe.py) are marked DEPRECATED-RAW-AST in-source and this guard
will flag them until they are removed. The red is honest telemetry, not a hole.
"""

import re
from pathlib import Path

SRC_DIR = Path(__file__).parent.parent / "src" / "sugar_lift_py_tests"

FORBIDDEN = [
    re.compile(r"\bimport\s+ast\b"),
    re.compile(r"\bisinstance\s*\([^)]*,\s*ast\."),
]

# The sole permitted ast gateway (relative to SRC_DIR), by design.
GATEWAY = "factory/source_fragment.py"


def _rel(path: Path) -> str:
    return path.relative_to(SRC_DIR).as_posix()


def test_no_raw_ast_outside_gateway():
    src_files = sorted(SRC_DIR.rglob("*.py"))
    assert src_files, f"No src/**/*.py files found under {SRC_DIR}"

    violations: list[str] = []
    for path in src_files:
        if _rel(path) == GATEWAY:
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern in FORBIDDEN:
                if pattern.search(line):
                    violations.append(f"{_rel(path)}:{lineno}: {line.rstrip()}")

    assert not violations, (
        "Raw-ast usage found outside the SourceFragment gateway "
        "(must use the SourceFragment API only):\n" + "\n".join(violations)
    )
