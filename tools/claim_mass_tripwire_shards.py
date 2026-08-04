#!/usr/bin/env python3
"""Deterministic claim-mass tripwire shards (#4266).

Each pin in PINS is an independent corpus tripwire. Standing law: N independent
items ⇒ N CI jobs, not one serial pytest. Completeness is enrollment of every
pin's identity-bound result body — missing pin = UNMEASURED.

Usage:
  python3 tools/claim_mass_tripwire_shards.py --list
  python3 tools/claim_mass_tripwire_shards.py --emit-matrix-json
  python3 tools/claim_mass_tripwire_shards.py --print-roster
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
from sugar_repo_root import resolve_repo_root  # noqa: E402

ROOT = resolve_repo_root()
# Single source of truth: pin names live in the tripwire test module's PINS
# tuple. Parse the AST (do not import the test — it needs sugar packages).
_TRIPWIRE = (
    ROOT
    / "implementations/python/sugar-lift-py-tests/tests/test_claim_mass_tripwires.py"
)
_CORPUS = (
    ROOT / "implementations/python/sugar-lift-py-tests/tests/claim_mass_corpus.py"
)


def pin_names() -> list[str]:
    """Extract pin names in declaration order without importing the test."""
    names: list[str] = []
    # DATETIME_PIN is imported into PINS first — resolve its name from corpus.
    corpus = _CORPUS.read_text(encoding="utf-8")
    m = re.search(
        r"DATETIME_PIN\s*=\s*ClaimMassPin\(\s*name\s*=\s*\"([^\"]+)\"",
        corpus,
    )
    if m:
        names.append(m.group(1))
    tree = ast.parse(_TRIPWIRE.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(getattr(t, "id", None) == "PINS" for t in node.targets):
            continue
        if not isinstance(node.value, ast.Tuple):
            continue
        for elt in node.value.elts:
            if isinstance(elt, ast.Name) and elt.id == "DATETIME_PIN":
                continue  # already from corpus
            if isinstance(elt, ast.Call):
                for kw in elt.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        names.append(str(kw.value.value))
    if len(names) < 2:
        raise SystemExit(f"could not parse pin names from {_TRIPWIRE}")
    return names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--emit-matrix-json", action="store_true")
    parser.add_argument("--print-roster", action="store_true")
    args = parser.parse_args(argv)
    names = pin_names()
    if args.list or args.print_roster:
        for name in names:
            print(name)
        return 0
    if args.emit_matrix_json:
        print(json.dumps({"pin": names}, separators=(",", ":")))
        return 0
    parser.error("pass --list / --emit-matrix-json / --print-roster")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
