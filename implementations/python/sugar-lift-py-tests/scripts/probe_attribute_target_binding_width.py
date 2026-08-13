"""WIDTH of the ``module_direct_bindings`` attribute-target over-count (#7394).

``_module_statement_bound_names`` collected every ``Name`` in a module-level
assignment TARGET subtree, so ``get_option.__module__ = "pandas"`` published a
binding of ``get_option``.  This probe counts, over the WHOLE authenticated
corpus, how wide that is -- and separately the number that actually matters:
names the over-count made look AMBIGUOUS to a by-name authority that must
refuse more than one module-scope binding.

The rules are re-derived here from the stdlib ``ast`` over the corpus source,
INDEPENDENTLY of the typed tree, so the two instruments can disagree; the
disagreement is the finding.  ``--verify-table`` additionally re-asks the real
``SourceUnit.module_direct_bindings`` at named seats, which is the arm that
proves the source-level reading describes the table and not just the grammar.

An absent seat is REFUSED by name; it never reads as a clean file.

usage:
  python probe_attribute_target_binding_width.py [--verify-table SEAT ...]
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections import Counter
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_ASSIGNABLE = (ast.Name, ast.Tuple, ast.List, ast.Starred, ast.Attribute, ast.Subscript)


def _old_rule(target: ast.expr) -> set[str]:
    """Every ``Name`` anywhere under the target -- the defect, reproduced."""
    if isinstance(target, ast.Name):
        return {target.id}
    return {node.id for node in ast.walk(target) if isinstance(node, ast.Name)}


def _new_rule(target: ast.expr) -> set[str]:
    """Names the target BINDS.  Closed over the assignment grammar."""
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for element in target.elts:
            names |= _new_rule(element)
        return names
    if isinstance(target, ast.Starred):
        return _new_rule(target.value)
    if isinstance(target, (ast.Attribute, ast.Subscript)):
        return set()
    raise AssertionError(f"target is not an assignable construct: {type(target).__name__}")


def _statement_names(statement: ast.stmt, rule) -> set[str]:
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {statement.name}
    if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = (
            statement.targets
            if isinstance(statement, ast.Assign)
            else (statement.target,)
        )
        names: set[str] = set()
        for target in targets:
            names |= rule(target)
        return names
    if isinstance(statement, (ast.Import, ast.ImportFrom)):
        return {alias.asname or alias.name.split(".", 1)[0] for alias in statement.names}
    return set()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-table", action="append", default=None)
    parser.add_argument("--name", action="append", default=None)
    args = parser.parse_args(argv)

    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus

    authenticated = authenticated_pandas_corpus()
    corpus = authenticated.root
    print(
        f"WIDTH_CORPUS root={corpus} fileCount={authenticated.file_count} "
        f"manifestCid={authenticated.manifest_cid}",
        flush=True,
    )

    roster = sorted(
        path.resolve().relative_to(corpus).as_posix()
        for path in corpus.rglob("*.py")
    )
    print(f"WIDTH_ROSTER files={len(roster)}", flush=True)
    # The walk is not the authority on the population; the authenticated pin
    # is. If they disagree the census is over the wrong universe, and that is
    # a refusal, not a footnote.
    if len(roster) != authenticated.file_count:
        print(
            f"WIDTH_ROSTER_DISAGREES walked={len(roster)} "
            f"authenticated={authenticated.file_count}",
            flush=True,
        )
        return 4

    files_touched = 0
    statements_touched = 0
    spurious_pairs = 0
    disambiguated = 0  # (file, name): count > 1 under the old rule, == 1 under the new
    vanished = 0       # (file, name): had a binding ONLY because of the over-count
    target_kinds: Counter[str] = Counter()
    affected_by_kind: Counter[str] = Counter()
    ambiguous_by_kind: Counter[str] = Counter()
    exemplars: list[str] = []
    read_ok = 0
    refused: list[str] = []

    for seat in roster:
        path = corpus.joinpath(*seat.split("/"))
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=seat)
        except (OSError, SyntaxError, UnicodeDecodeError) as error:
            # Loud, by name -- never a silently skipped file.
            refused.append(f"{seat}: {type(error).__name__}: {error}")
            continue
        read_ok += 1

        old: dict[str, int] = {}
        new: dict[str, int] = {}
        touched_here = False
        # Which TARGET KIND is responsible for each name's over-count. The
        # brief called this defect "attribute assignment"; `X[k] = v` is the
        # same defect through the same walk, so the two are attributed
        # separately rather than merged into one number.
        blame_kinds: dict[str, set[str]] = {}
        for statement in tree.body:
            old_names = _statement_names(statement, _old_rule)
            new_names = _statement_names(statement, _new_rule)
            for name in old_names:
                old[name] = old.get(name, 0) + 1
            for name in new_names:
                new[name] = new.get(name, 0) + 1
            if old_names != new_names:
                statements_touched += 1
                touched_here = True
                targets_here = (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else (statement.target,)
                )
                for target in targets_here:
                    kind = type(target).__name__
                    target_kinds[kind] += 1
                    if kind in ("Attribute", "Subscript"):
                        for name in _old_rule(target) - _new_rule(target):
                            blame_kinds.setdefault(name, set()).add(kind)
                if len(exemplars) < 12:
                    exemplars.append(
                        f"{seat}:{statement.lineno}:{statement.col_offset} "
                        f"spurious={sorted(old_names - new_names)}"
                    )
        if touched_here:
            files_touched += 1
        for name, count in old.items():
            after = new.get(name, 0)
            if after == count:
                continue
            spurious_pairs += 1
            kinds = blame_kinds.get(name) or {"unattributed"}
            key = "+".join(sorted(kinds))
            affected_by_kind[key] += 1
            if after == 0:
                vanished += 1
            elif count > 1 and after == 1:
                disambiguated += 1
                ambiguous_by_kind[key] += 1

    print(f"WIDTH_READ_OK {read_ok} REFUSED {len(refused)}", flush=True)
    for line in refused:
        print(f"WIDTH_REFUSED {line}", flush=True)
    print(
        f"WIDTH_FILES_AFFECTED {files_touched}\n"
        f"WIDTH_STATEMENTS_AFFECTED {statements_touched}\n"
        f"WIDTH_NAME_SEATS_AFFECTED {spurious_pairs}\n"
        f"WIDTH_FALSELY_AMBIGUOUS_NOW_SINGLE {disambiguated}\n"
        f"WIDTH_NAME_SEATS_LOSING_ALL_BINDINGS {vanished}",
        flush=True,
    )
    for kind, count in sorted(target_kinds.items(), key=lambda item: -item[1]):
        print(f"WIDTH_TARGET_KIND {kind} {count}", flush=True)
    for kind, count in sorted(affected_by_kind.items(), key=lambda item: -item[1]):
        print(f"WIDTH_NAME_SEATS_BY_KIND {kind} {count}", flush=True)
    for kind, count in sorted(ambiguous_by_kind.items(), key=lambda item: -item[1]):
        print(f"WIDTH_FALSELY_AMBIGUOUS_BY_KIND {kind} {count}", flush=True)
    for line in exemplars:
        print(f"WIDTH_EXEMPLAR {line}", flush=True)

    if args.verify_table:
        try:
            from sugar_lift_py_tests.lift_rpc import (
                open_source_file_for_construction,
            )
            from sugar_lift_python_source.source_oracle import install_root_for
        except ModuleNotFoundError as error:
            # A verification arm that quietly does not run is worse than one
            # that fails: it reads as a clean confirmation. Say so and refuse.
            print(f"WIDTH_TABLE_ARM_UNAVAILABLE {error}", flush=True)
            return 5
        for seat in args.verify_table:
            if seat not in roster:
                print(f"WIDTH_SEAT_ABSENT {seat}", flush=True)
                return 2
            path = corpus.joinpath(*seat.split("/"))
            # An installed file's address is the seat its DISTRIBUTION
            # recorded, not the spelling the roster happens to use. The
            # roster says `_config/config.py`; the recorded seat is
            # `pandas/_config/config.py`, and opening against the package
            # root mints an address no other checkout resolves.
            installed = install_root_for(str(path))
            locus_root = corpus if installed is None else Path(installed)
            # The SOLE construction door -- never the bare `SourceFile`
            # entrance, which seats no construction context.
            source_file = open_source_file_for_construction(
                path,
                root=corpus,
                source_workspace_root=locus_root,
                distribution="pandas",
            )
            table = source_file.unit.module_direct_bindings or {}
            names = args.name or sorted(table)
            for name in names:
                if name not in table:
                    print(f"WIDTH_TABLE_NAME_ABSENT {seat} name={name}", flush=True)
                    return 3
                rows = table[name]
                spelled = ", ".join(
                    f"{type(row).__name__}@{row.line_col_span().start_line}:"
                    f"{row.line_col_span().start_col}"
                    for row in rows
                )
                print(
                    f"WIDTH_TABLE {seat} name={name} entries={len(rows)} [{spelled}]",
                    flush=True,
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
