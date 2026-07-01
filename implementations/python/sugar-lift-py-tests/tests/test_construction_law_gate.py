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

Seven crimes, named after the base64 disaster that motivated the gate:

  A. self-construction from raw AST   -- ``from_function(fn: ast.FunctionDef)``
  B. raw AST held as a semantic child -- ``stmt: ast.Return``
  C. execution instead of lowering    -- ``left << right`` inside desugar
  D. pulling its own body             -- ``ctx.build_body(...)`` in a sugar
  E. package-root side-door lifter    -- root lifter claims source before factory
  F. router claims before factory     -- ``lib.py`` calls a bespoke lifter first
  G. child sugar self-assembly        -- a sugar calls another sugar's from_site
  H. Python-side solver dependency    -- ``import z3`` in the kit

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
_SIDE_DOOR_LIFTERS = ("array_map_lifter.py", "literal_call_lifter.py")
_SIDE_DOOR_CALLS = {"lift_array_map_assertions", "lift_literal_call_assertions"}
# `|` is excluded on purpose: `int | str` unions parse as BinOp(BitOr) and are
# not execution. `<< >> & ^` never appear in type position -- they are math.
_BITWISE_EXEC = (ast.LShift, ast.RShift, ast.BitAnd, ast.BitXor)
_AST_REF = re.compile(r"\bast\.[A-Za-z_]")

# Monotonic-down ratchet. This count only ever decreases, and lowering it is a
# recorded commit. A PR that raises it is a relapse -- someone reached for an
# interpreter -- and the build goes red. 0 is the target: the whole sugar layer
# build()-born and lowering to FOL. The coordinator tightens it as the fleet lands.
_CRIME_CEILING = 0


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
    local_sugar = _local_sugar_class(path)

    # Track the enclosing function name so Crime D can distinguish build() from desugar().
    _enclosing_fn: list[str] = []

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            _enclosing_fn.append(node.name)
            visit_node(node)
            self.generic_visit(node)
            _enclosing_fn.pop()

        visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

        def generic_visit(self, node: ast.AST) -> None:
            visit_node(node)
            super().generic_visit(node)

    def visit_node(node: ast.AST) -> None:
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
        # CRIME D: a sugar pulls its own body from the factory inside desugar().
        # build() classmethods ARE allowed to call ctx.build_body -- that is exactly
        # how the factory hands composed children to the sugar at construction.
        # desugar() must NEVER call build_body; it receives pre-built children from
        # __init__ and lowers them to FOL.
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (
                node.func.attr == "build_body"
                and _enclosing_fn
                and _enclosing_fn[-1] == "desugar"
            ):
                crimes.append(
                    f"{rel}:{node.lineno}: CRIME D (sugar pulls its own body inside desugar) "
                    f"`{ast.unparse(node.func)}(...)` -- desugar() receives pre-built SugarBody "
                    "children from __init__; only build() may call build_body to compose them."
                )
        # CRIME G: a sugar reaches sideways to construct another sugar as its
        # child. The factory constructor layer owns that assembly.
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (
                node.func.attr == "from_site"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id.endswith("Sugar")
                and node.func.value.id != local_sugar
            ):
                crimes.append(
                    f"{rel}:{node.lineno}: CRIME G (child sugar self-assembly) "
                    f"`{ast.unparse(node.func)}(...)` -- parent sugars are born with "
                    "factory-built child bodies; move this child construction into "
                    "factory/sugar_constructors.py and pass the child into __init__."
                )

    Visitor().visit(tree)
    return crimes


def _local_sugar_class(path: Path) -> str | None:
    stem = path.stem
    if not stem.endswith("_sugar"):
        return None
    return "".join(part.capitalize() for part in stem.split("_"))


def all_crimes() -> list[str]:
    root = _KIT_SRC.parent.parent
    crimes: list[str] = []
    for path in _linted_files():
        crimes.extend(crimes_in(path, root))
    crimes.extend(side_door_crimes(root))
    crimes.extend(python_solver_crimes(root))
    return crimes


def side_door_crimes(root: Path) -> list[str]:
    crimes: list[str] = []
    for filename in _SIDE_DOOR_LIFTERS:
        path = _KIT_SRC / filename
        if path.exists():
            rel = path.relative_to(root)
            crimes.append(
                f"{rel}:1: CRIME E (package-root side-door lifter) "
                f"`{filename}` -- source behavior must enter through the factory/catalog; "
                "delete this root lifter or move its behavior behind factory-built sugars."
            )

    lib_path = _KIT_SRC / "lib.py"
    tree = ast.parse(lib_path.read_text(encoding="utf-8"))
    rel = lib_path.relative_to(root)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _SIDE_DOOR_CALLS:
                crimes.append(
                    f"{rel}:{node.lineno}: CRIME F (router claims before factory) "
                    f"`{node.func.id}(...)` -- `lift_source` must delegate to the "
                    "factory, not a bespoke pre-factory lifter."
                )
    return crimes


def python_solver_crimes(root: Path) -> list[str]:
    crimes: list[str] = []
    for path in sorted(_KIT_SRC.rglob("*.py")):
        rel = path.relative_to(root)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "z3" or alias.name.startswith("z3."):
                        crimes.append(
                            f"{rel}:{node.lineno}: CRIME H (Python-side solver dependency) "
                            "`import z3` -- the Python kit lowers ProofIR; SMT solving belongs "
                            "to the registered compiler/verifier path."
                        )
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "z3" or module.startswith("z3."):
                    crimes.append(
                        f"{rel}:{node.lineno}: CRIME H (Python-side solver dependency) "
                        f"`from {module} import ...` -- the Python kit lowers ProofIR; "
                        "SMT solving belongs to the registered compiler/verifier path."
                    )
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
