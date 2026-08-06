"""Do roads already exist for the callees the CM join calls runtime-selected?

Diagnostic only.

ARM 1 -- builtins. `with open(path) as f:` is 10 of the 24 runtime-selected
manager demands inside the slice's panicking With statements. Question: does
ANY call-contract demand row in the whole corpus name a builtin callee? If none
does, then an ordinary `f = open(p)` is no better served than `with open(p)`,
the CM join is not a wrong entrance for builtins, and the gap is a missing
construct rather than a missed door.

ARM 2 -- same-module definitions. `manager_summary_derivation` already has
`_populate_same_module_class_manager_uses`, whose own docstring says "Import
receipts never fire for local constructors. When Call.func Name binds to
exactly one module ClassDef ...". Question: is `ensure_removed` -- 5 of the 24
-- a ClassDef (already served) or a decorated generator FUNCTION (a door built
for one half of the same problem)?
"""

from __future__ import annotations

import ast
import sys
from collections import Counter


BUILTIN_CALLEES = {
    "open",
    "iter",
    "memoryview",
    "enumerate",
    "zip",
    "reversed",
}

SAME_MODULE_TARGETS = [
    ("tests/test_register_accessor.py", "ensure_removed"),
    ("_config/localization.py", "set_locale"),
    ("io/clipboard/__init__.py", "clipboard"),
    ("io/clipboard/__init__.py", "window"),
]


def main() -> int:
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_py_tests.lift_rpc import _call_contract_demand_rows
    from sugar_lift_python_source.source_oracle import path_source

    corpus = authenticated_pandas_corpus()
    root = corpus.root
    print(f"CORPUS {corpus.distribution} {corpus.version} files={corpus.file_count}")

    rows = [
        row
        for row in _call_contract_demand_rows(root)
        if row.get("kind") == "call-contract-demand"
    ]
    print(f"CALL_CONTRACT_DEMAND_ROWS {len(rows)}")

    # ---- ARM 1: is any builtin callee ever enrolled as a call demand? -------
    targets = Counter()
    prefixes = Counter()
    for row in rows:
        symbol = str(row.get("targetSymbol") or "")
        bare = symbol.removeprefix("python:")
        prefixes[bare.split(".", 1)[0]] += 1
        if bare in BUILTIN_CALLEES or bare.startswith("builtins."):
            targets[bare] += 1
    print("\nARM 1 -- builtin callees among enrolled call demands")
    print(f"  rows naming a builtin callee: {sum(targets.values())}")
    for name, count in targets.most_common(20):
        print(f"    {count:>6}  {name}")
    print("  top enrolled top-level namespaces (for contrast):")
    for name, count in prefixes.most_common(12):
        print(f"    {count:>6}  {name}")

    # ---- ARM 2: what KIND of definition are the same-module managers? ------
    print("\nARM 2 -- same-module manager definitions, by node kind")
    for seat, name in SAME_MODULE_TARGETS:
        path = root.joinpath(*seat.split("/"))
        try:
            source, _filename, _cid = path_source(str(path))
        except Exception as exc:  # a probe names its own death
            print(f"  {seat}: unreadable: {exc}")
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            print(f"  {seat}: unparseable: {exc}")
            continue
        found = False
        for node in tree.body:
            if getattr(node, "name", None) != name:
                continue
            found = True
            decorators = [ast.unparse(d) for d in getattr(node, "decorator_list", [])]
            is_generator = any(
                isinstance(inner, (ast.Yield, ast.YieldFrom))
                for inner in ast.walk(node)
            )
            print(
                f"  {seat}::{name} -> {type(node).__name__} "
                f"decorators={decorators} yields={is_generator}"
            )
        if not found:
            print(f"  {seat}::{name} -> NOT a module-level definition")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
