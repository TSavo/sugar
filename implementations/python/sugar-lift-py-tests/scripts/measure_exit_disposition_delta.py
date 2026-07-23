#!/usr/bin/env python3
"""Measure ΔR for errstate / option_context under ExitDispositionProof.

Counts ``with`` items whose manager spelling matches the families, and how many
prove NeverSuppresses via source-visible __exit__ (vs remain unproven).
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from collections import Counter
from pathlib import Path

from sugar_lift_py_tests.exit_disposition_proof import prove_never_suppresses_for_class


def package_root(name: str) -> Path:
    spec = importlib.util.find_spec(name)
    assert spec and spec.origin
    return Path(spec.origin).resolve().parent


def dotted(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        if base is None:
            return None
        return f"{base}.{node.attr}"
    return None


FAMILIES = {
    "errstate": ("np.errstate", "errstate", "numpy.errstate"),
    "option_context": (
        "option_context",
        "pd.option_context",
        "pandas.option_context",
        "cf.option_context",
    ),
}


def main() -> int:
    import numpy as np
    from pandas import option_context

    proofs = {
        "errstate": prove_never_suppresses_for_class(np.errstate),
        "option_context": prove_never_suppresses_for_class(option_context),
    }
    print("class proofs:")
    for k, p in proofs.items():
        print(f"  {k}: {p.kind if p else None} cid={getattr(p, 'source_cid', None)}")

    counts: dict[str, Counter] = {
        "errstate": Counter(),
        "option_context": Counter(),
    }
    for pkg in ("numpy", "pandas"):
        root = package_root(pkg)
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.With, ast.AsyncWith)):
                    continue
                for item in node.items:
                    if not isinstance(item.context_expr, ast.Call):
                        continue
                    id_ = dotted(item.context_expr.func)
                    if id_ is None:
                        continue
                    for family, spellings in FAMILIES.items():
                        if (
                            id_ in spellings
                            or id_.endswith("." + family)
                            or id_ == family
                        ):
                            # proven iff class proof exists (same definition)
                            if proofs[family] is not None:
                                counts[family]["proven_never_suppresses"] += 1
                            else:
                                counts[family]["unproven"] += 1

    print("\nΔR proxy (with-items matching family spellings):")
    for family, c in counts.items():
        proven = c["proven_never_suppresses"]
        unproven = c["unproven"]
        print(
            f"  {family}: proven_NeverSuppresses={proven} unproven={unproven} "
            f"total={proven + unproven}"
        )
        print(
            f"    → sites that leave RuntimeSelected residual when proof absent: "
            f"{unproven}; sites eligible for WithResourceSugar when proof holds: {proven}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
