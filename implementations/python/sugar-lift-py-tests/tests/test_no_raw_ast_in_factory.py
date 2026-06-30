"""
CI guard: factory files (except source_fragment.py) must not import ast or use
isinstance(.., ast.X) directly. All AST access must go through SourceFragment.

Forbidden patterns:
  - `import ast`
  - `isinstance(<x>, ast.<Y>)`

source_fragment.py is the sole permitted ast gateway and is excluded.
"""
import re
from pathlib import Path

FACTORY_DIR = (
    Path(__file__).parent.parent
    / "src" / "sugar_lift_py_tests" / "factory"
)

FORBIDDEN = [
    re.compile(r"\bimport\s+ast\b"),
    re.compile(r"\bisinstance\s*\([^)]*,\s*ast\."),
]

EXCLUDED = {"source_fragment.py"}


def test_no_raw_ast_in_factory():
    factory_files = sorted(FACTORY_DIR.glob("*.py"))
    assert factory_files, f"No factory/*.py files found under {FACTORY_DIR}"

    violations: list[str] = []
    for path in factory_files:
        if path.name in EXCLUDED:
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern in FORBIDDEN:
                if pattern.search(line):
                    violations.append(
                        f"{path.name}:{lineno}: {line.rstrip()}"
                    )

    assert not violations, (
        "Raw-ast usage found in factory/ files (must use SourceFragment API only):\n"
        + "\n".join(violations)
    )
