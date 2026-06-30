"""
CI guard: sugar recognizers/builders must talk only to the SourceSite
fragment, never the raw ast module.

Forbidden patterns:
  - `import ast`
  - `site.node`           (raw node access bypassing SourceSite API)
  - `isinstance(<x>, ast.<Y>)`

If any sugar/*.py file contains one of these patterns, this test FAILS with
the offending file and matched line(s).
"""
import re
from pathlib import Path

SUGAR_DIR = (
    Path(__file__).parent.parent
    / "src" / "sugar_lift_py_tests" / "sugar"
)

FORBIDDEN = [
    re.compile(r"\bimport\s+ast\b"),
    re.compile(r"\bsite\.node\b"),
    re.compile(r"\bisinstance\s*\([^)]*,\s*ast\."),
]


def test_no_raw_ast_in_sugars():
    sugar_files = sorted(SUGAR_DIR.glob("*.py"))
    assert sugar_files, f"No sugar/*.py files found under {SUGAR_DIR}"

    violations: list[str] = []
    for path in sugar_files:
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern in FORBIDDEN:
                if pattern.search(line):
                    violations.append(
                        f"{path.name}:{lineno}: {line.rstrip()}"
                    )

    assert not violations, (
        "Raw-ast usage found in sugar/ files (must use SourceSite API only):\n"
        + "\n".join(violations)
    )
