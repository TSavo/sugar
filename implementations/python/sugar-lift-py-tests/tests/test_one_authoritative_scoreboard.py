"""Exactly one module may be the board. Everything else must say it is not.

The Python corpus was being read from several instruments at once, each with a
different denominator, and their numbers were quoted interchangeably. An
AST-shape site census said ``With 4125/811/85``; the construction ledger for
the same period said ``assertion 3 / resource 104 / other 4``. Nobody was
lying. There was simply no fact of the matter about which one was "the board".

So this is a recognizer, not a checklist. It finds every module in the kit that
*emits an R quantity* — structurally, by looking for ``R``/``R_*`` keys in the
payloads it builds and the lines it prints — and requires each one to declare,
in its own source, whether it is the authority. Exactly one may say yes.

A new census cannot quietly join the board: the moment it emits an ``R_*``
quantity this test names it and stays red until it declares itself. That is the
retirement path too — when a capability makes an axis unrepresentable, its
instrument is deleted and disappears from this recognizer on its own.
"""

from __future__ import annotations

import ast
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
SEARCHED = (KIT / "scripts", KIT / "src" / "sugar_lift_py_tests")

DECLARATION = "SCOREBOARD_AUTHORITY"


def _is_r_quantity(name: str) -> bool:
    """``R`` or ``R_<axis>`` — the shape every residual quantity is spelled in."""
    return name == "R" or (name.startswith("R_") and len(name) > 2)


def _emits_r_quantity(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        # A payload key: {"R_construction": ...} — the JSON board shape.
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and _is_r_quantity(key.value)
                ):
                    return True
        # A printed line: "R_construction = {n}" — the console board shape.
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            head = node.value.strip().split(" ", 1)[0].rstrip("=:")
            if _is_r_quantity(head) and ("=" in node.value or ":" in node.value):
                return True
    return False


def _declared_authority(tree: ast.AST) -> bool | None:
    """The module's own statement about itself, or None if it never made one."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == DECLARATION:
                    if isinstance(node.value, ast.Constant) and isinstance(
                        node.value.value, bool
                    ):
                        return node.value.value
    return None


def _board_producers() -> dict[Path, bool | None]:
    found: dict[Path, bool | None] = {}
    for directory in SEARCHED:
        for path in sorted(directory.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if _emits_r_quantity(tree):
                found[path] = _declared_authority(tree)
    return found


def test_every_module_that_emits_an_r_quantity_declares_its_authority() -> None:
    producers = _board_producers()
    assert producers, "recognizer found no R-emitting module — it walked the wrong tree"
    undeclared = sorted(
        str(path.relative_to(KIT))
        for path, declared in producers.items()
        if declared is None
    )
    assert not undeclared, (
        "these modules emit an R quantity but never say whether they are the "
        f"board: {undeclared}. Add `{DECLARATION} = False` (and say in the "
        "docstring what denominator they DO measure), or True if this is "
        "genuinely the authority."
    )


def test_exactly_one_module_claims_to_be_the_authority() -> None:
    claimants = sorted(
        str(path.relative_to(KIT))
        for path, declared in _board_producers().items()
        if declared is True
    )
    assert claimants == ["scripts/compose_control_effect_board.py"], (
        "the Python corpus board has exactly one authority (the compose seal "
        f"door); claimants were {claimants}"
    )


def test_the_recognizer_actually_recognizes(tmp_path) -> None:
    """The discriminating face: a planted board must be caught, a probe must not."""
    board = ast.parse('result = {"R_construction": 7}\n')
    assert _emits_r_quantity(board)
    printer = ast.parse('print(f"R_desugar = {n}")\n')
    assert _emits_r_quantity(printer)
    # Not a board: no R quantity emitted, however much it talks about them.
    probe = ast.parse('"""Counts With sites."""\nsites = {"withStatements": 4125}\n')
    assert not _emits_r_quantity(probe)
    assert _declared_authority(ast.parse("SCOREBOARD_AUTHORITY = False\n")) is False
    assert _declared_authority(ast.parse("x = 1\n")) is None
