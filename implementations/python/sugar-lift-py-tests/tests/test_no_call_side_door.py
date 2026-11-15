"""CI guard: calls go through the catalog, never a side-door constructor.

CALLSUGAR_REFACTOR_GOAL.md DONE #1 + #22: `FunctionCallSugar` and `build_function_call_sugar`
are deleted; the dig dispatches `CallSugar` via `ctx.build_body` (the catalog). This test
keeps them gone -- the absence IS the invariant. If it fails, someone reached around the
factory with a constructor again (the exact failure the whole refactor exists to prevent),
and that reach is a silent-green side door unless this guard makes it loud.
"""

from __future__ import annotations

from pathlib import Path


from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_SRC = sugar_lift_py_tests_package_root() / "src" / "sugar_lift_py_tests"
_FORBIDDEN_NAMES = (
    "build_function_call_sugar",
    "build_fcs_from_call_site",
    "FunctionCallSugar",
)


def test_no_side_door_constructor_anywhere_in_src():
    hits = []
    for py in _SRC.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for name in _FORBIDDEN_NAMES:
            if name in text:
                hits.append(f"{py.relative_to(_SRC)}: {name}")
    assert not hits, (
        "side-door call constructor reference(s) reappeared -- the dig must dispatch "
        f"CallSugar through the catalog (ctx.build_body), never a constructor:\n  "
        + "\n  ".join(hits)
    )
