"""Lift-ownership gate -- the lift translates, it never solves.

A STRUCTURAL lint over the lift kit's ``src/``. The lift's only job is
source -> IR: it emits FOL terms (bvshl, bvand, ...) and stops. SOLVING belongs
to verify -- the rust realizer and the SMT-IR compilers hand those terms to a
solver THERE, once, downstream, independently.

A solver imported into the lift kit means the lifter is doing verify's job: it
computes the answer itself, so there is nothing left for the independent verifier
to recompute. That collapses recomputation into trust -- the lifter grading its
own homework -- which is the Swagger door, and the wrong ownership line.

The venv confessed it: a pure translator needs no solver. The day the lift kit
needs z3 installed is the day it stopped translating and started verifying.

Crime: any SMT solver imported anywhere under ``src/``. Loud until the bit-vector
ops desugar to IR terms and the solver leaves the kit entirely (target 0).
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

_KIT_SRC = Path(__file__).resolve().parents[1] / "src" / "sugar_lift_py_tests"
# Solving belongs to verify. A lift module that imports any of these has crossed
# the ownership line and is doing the verifier's job.
_SOLVER_MODULES = frozenset({"z3", "z3solver", "cvc5", "pysmt", "pysat"})

# Ratchet: solver imports in the lift only ever decrease, and lowering this is a
# recorded commit. 0 is the target -- the lift emits bit-vector IR terms and the
# rust verify stage owns the solver. A PR that raises it reached back across the
# ownership line.
_SOLVER_CEILING = 1


def _root(name: str | None) -> str:
    return (name or "").split(".", 1)[0]


def solver_imports() -> list[str]:
    crimes: list[str] = []
    root = _KIT_SRC.parent.parent
    for path in sorted(_KIT_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(root)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _root(alias.name) in _SOLVER_MODULES:
                        crimes.append(
                            f"{rel}:{node.lineno}: lift imports solver `import {alias.name}` -- "
                            "the lift translates, it never solves; desugar bit-vector ops to IR "
                            "terms and let the rust verify stage own the solver."
                        )
            elif isinstance(node, ast.ImportFrom) and _root(node.module) in _SOLVER_MODULES:
                crimes.append(
                    f"{rel}:{node.lineno}: lift imports solver `from {node.module} import ...` -- "
                    "the lift translates, it never solves; desugar bit-vector ops to IR terms and "
                    "let the rust verify stage own the solver."
                )
    return crimes


def test_lift_owns_no_solver() -> None:
    crimes = solver_imports()
    n = len(crimes)
    assert n <= _SOLVER_CEILING, (
        f"lift-ownership RELAPSE: {n} solver imports in the lift, ceiling {_SOLVER_CEILING}. "
        "A solver in the lift means the lifter solved it itself -- nothing is left for the "
        "independent verifier to recompute:\n\n" + "\n".join(crimes)
    )
    # Never let a green pass hide the debt: name every solver still in the lift.
    if crimes:
        warnings.warn(
            f"lift-ownership: {n} solver import(s) still in the lift "
            f"(ceiling {_SOLVER_CEILING}, target 0). the lift must translate, not solve:\n"
            + "\n".join(crimes),
            stacklevel=2,
        )


if __name__ == "__main__":
    import sys

    found = solver_imports()
    for crime in found:
        print(crime)
    print(f"\nlift-ownership gate: {len(found)} solver import(s) in the lift")
    sys.exit(1 if found else 0)
