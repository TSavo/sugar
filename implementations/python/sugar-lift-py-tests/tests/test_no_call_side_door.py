"""CI guard: calls go through the catalog, never a side-door constructor.

CALLSUGAR_REFACTOR_GOAL.md DONE #1 + #22: `FunctionCallSugar` and `build_function_call_sugar`
are deleted; the dig dispatches `CallSugar` via `ctx.build_body` (the catalog). This test
keeps them gone -- the absence IS the invariant. If it fails, someone reached around the
factory with a constructor again (the exact failure the whole refactor exists to prevent),
and that reach is a silent-green side door unless this guard makes it loud.

It also forbids `NotImplementedError` stubs in the strategies -- a stub that routes the new
shell back into the old path is a side door wearing a name tag.
"""

from __future__ import annotations

from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src" / "sugar_lift_py_tests"
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


def test_call_strategies_have_no_notimplemented_stubs():
    text = (_SRC / "sugar" / "call_sugar.py").read_text(encoding="utf-8")
    assert "NotImplementedError" not in text, (
        "call_sugar.py contains a NotImplementedError -- a stubbed strategy routes the dumb "
        "shell back into the old path. The strategies must be real."
    )
