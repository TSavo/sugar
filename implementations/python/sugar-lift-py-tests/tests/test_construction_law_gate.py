"""Construction-law gate -- the bad cop.

A STRUCTURAL lint over ``sugar/`` and ``floor/`` source. It does not care which
runtime path built a sugar, so a sugar hand-assembled by a side-door lifter is
caught here exactly the same as one the factory built.

The architecture it enforces: the FACTORY recognizes a shape, builds the
children bottom-up, and HANDS the finished ``SugarBody`` to the sugar at
construction. A sugar is a dumb value that holds its body -- no ``ctx``, no
``build_body``, no path back to the factory. ``desugar`` is the only
transformation: it rewrites/lowers the body it was handed and passes the result
downstream, lowering to FOL so the solver does the math.

Four crimes, named after the base64 disaster that motivated the gate:

  A. self-construction from raw AST   -- ``from_function(fn: ast.FunctionDef)``
  B. raw AST held as a semantic child -- ``stmt: ast.Return``
  C. execution instead of lowering    -- ``left << right`` inside desugar
  D. pulling its own body             -- ``ctx.build_body(...)`` in a sugar

Green is the only way to ship. A vendor fingerprint with a private interpreter
cannot pass it, and neither can a sugar that assembles itself instead of being
handed its body.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_KIT_SRC = Path(__file__).resolve().parents[1] / "src" / "sugar_lift_py_tests"
_LINTED_DIRS = ("sugar", "floor")
# `|` is excluded on purpose: `int | str` unions parse as BinOp(BitOr) and are
# not execution. `<< >> & ^` never appear in type position -- they are math.
_BITWISE_EXEC = (ast.LShift, ast.RShift, ast.BitAnd, ast.BitXor)
_AST_REF = re.compile(r"\bast\.[A-Za-z_]")

# Monotonic-down ratchet. This count only ever decreases, and lowering it is a
# recorded commit. A PR that raises it is a relapse -- someone reached for an
# interpreter -- and the build goes red. 0 is the target: the whole sugar layer
# build()-born and lowering to FOL. The coordinator tightens it as the fleet lands.
_CRIME_CEILING = 30


def _linted_files() -> list[Path]:
    files: list[Path] = []
    for sub in _LINTED_DIRS:
        files.extend(sorted((_KIT_SRC / sub).rglob("*.py")))
    return files


def _is_ast_annotation(annotation: ast.expr | None) -> bool:
    return annotation is not None and bool(_AST_REF.search(ast.unparse(annotation)))


def _first_value_param(fn: ast.FunctionDef) -> ast.arg | None:
    params = fn.args.args
    if not params:
        return None
    if params[0].arg in {"cls", "self"}:
        return params[1] if len(params) > 1 else None
    return params[0]


def crimes_in(path: Path, root: Path) -> list[str]:
    rel = path.relative_to(root)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    crimes: list[str] = []
    for node in ast.walk(tree):
        # CRIME A: a sugar that recognizes-and-builds itself from a raw ast node.
        if isinstance(node, ast.FunctionDef) and node.name.startswith("from_"):
            param = _first_value_param(node)
            if param is not None and _is_ast_annotation(param.annotation):
                crimes.append(
                    f"{rel}:{node.lineno}: CRIME A (self-construction from raw AST) "
                    f"`{node.name}({param.arg}: {ast.unparse(param.annotation)})` -- a sugar "
                    "is build()-born with SugarBody children; recognition is a separate "
                    "Recognizer, not a from_ast classmethod on the sugar."
                )
        # CRIME B: a dataclass field typed `ast.*` is a raw child body, not a sugar.
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)
                    and _is_ast_annotation(stmt.annotation)
                ):
                    crimes.append(
                        f"{rel}:{stmt.lineno}: CRIME B (raw AST as a child) "
                        f"`{node.name}.{stmt.target.id}: {ast.unparse(stmt.annotation)}` -- "
                        "sugars hold SugarBody children, never raw ast.* as a semantic field."
                    )
        # CRIME C: bitwise math executed in kit source -- the next xz.
        if isinstance(node, ast.BinOp) and isinstance(node.op, _BITWISE_EXEC):
            crimes.append(
                f"{rel}:{node.lineno}: CRIME C (execution instead of lowering) "
                f"`{ast.unparse(node)}` -- the kit must LOWER bitwise ops to bitvector FOL "
                "for the solver, never compute them in Python."
            )
        # CRIME D: a sugar reaches into the factory to assemble its own body.
        # The factory builds the children bottom-up and HANDS the finished
        # SugarBody to the sugar at construction. A sugar that calls build_body is
        # pulling its body instead of receiving it -- the inversion.
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "build_body":
                crimes.append(
                    f"{rel}:{node.lineno}: CRIME D (sugar pulls its own body from the factory) "
                    f"`{ast.unparse(node.func)}(...)` -- the factory builds the children and "
                    "hands the SugarBody to the sugar at __init__; a sugar never calls build_body."
                )
    return crimes


def all_crimes() -> list[str]:
    root = _KIT_SRC.parent.parent
    crimes: list[str] = []
    for path in _linted_files():
        crimes.extend(crimes_in(path, root))
    return crimes


def test_construction_law_ratchet() -> None:
    crimes = all_crimes()
    n = len(crimes)
    assert n <= _CRIME_CEILING, (
        f"construction-law RELAPSE: {n} crimes, ceiling is {_CRIME_CEILING}. Someone "
        "built more of the wrong abstraction -- a raw-AST child, a from_ast "
        "self-constructor, or a Python interpreter where a lowering belongs:\n\n"
        + "\n".join(crimes)
    )
    # Hold the line, but keep the debt loud even when green.
    print(f"construction-law gate: {n}/{_CRIME_CEILING} crimes remaining (target 0)")


if __name__ == "__main__":
    import sys

    found = all_crimes()
    for crime in found:
        print(crime)
    print(f"\nconstruction-law gate: {len(found)} crimes")
    sys.exit(1 if found else 0)
