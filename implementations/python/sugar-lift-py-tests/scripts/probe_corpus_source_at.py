"""Read the PINNED corpus source at a corpus-relative path and line range.

This is a READING instrument, not a resolver probe.  It exists because a
diagnosis on issue #7394 inferred the content of ``pandas/_config/config.py``
line 950 from a DIFFERENT pandas version on the host, and an inference about
what a name is bound to at module scope must not be repaired against.

It prints, for the authenticated 3.0.3 corpus only:

  * the environment banner (python/pandas/numpy/lift identity + manifest CID),
    so the reading is provably against the pin and not a host copy;
  * the requested source lines verbatim;
  * the ``ast`` node kind whose span COVERS each requested line, and the kind
    of the module-level statement that covers it;
  * optionally (``--name``), every module-scope binding statement for a name,
    derived independently with ``ast`` -- a second authority on the
    ``module_direct_bindings`` claim, not a re-reading of it.

REFUSAL IS BY NAME.  A probe that prints nothing for an absent path or an
out-of-range line reads exactly like a clean result; that trap has been hit
twice on this campaign.  Absent path -> ``SOURCE_PATH_ABSENT``, exit 2.
Line past EOF -> ``SOURCE_LINE_ABSENT``, exit 3.  Requested name with no
module-scope binding -> ``SOURCE_NAME_ABSENT``, exit 4.

usage:
  python probe_corpus_source_at.py --path _config/config.py --lines 940-960 \
      --name get_option
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _parse_range(text: str) -> tuple[int, int]:
    if "-" in text:
        first, _, last = text.partition("-")
        start, end = int(first), int(last)
    else:
        start = end = int(text)
    if start < 1 or end < start:
        raise ValueError(f"unusable line range: {text!r}")
    return start, end


def _covering(tree: ast.Module, line: int) -> list[ast.AST]:
    """Every node whose span covers ``line``, outermost first."""
    covering: list[ast.AST] = []
    for node in ast.walk(tree):
        start = getattr(node, "lineno", None)
        if start is None:
            continue
        end = getattr(node, "end_lineno", None) or start
        if start <= line <= end:
            covering.append(node)
    covering.sort(key=lambda node: (node.lineno, -(node.end_lineno or node.lineno)))
    return covering


def _binds(statement: ast.stmt, name: str) -> bool:
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return statement.name == name
    if isinstance(statement, ast.Assign):
        return any(
            isinstance(target, ast.Name) and target.id == name
            for target in statement.targets
        )
    if isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
        return isinstance(statement.target, ast.Name) and statement.target.id == name
    if isinstance(statement, (ast.Import, ast.ImportFrom)):
        return any((alias.asname or alias.name.split(".")[0]) == name
                   for alias in statement.names)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True,
                        help="corpus-relative path, e.g. _config/config.py")
    parser.add_argument("--lines", required=True, help="N or N-M")
    parser.add_argument("--name", action="append", default=None,
                        help="report module-scope bindings for this name")
    args = parser.parse_args(argv)

    from sugar_lift_py_tests.authenticated_pytest import (
        authenticate_environment,
        authenticated_pandas_corpus,
    )

    pandas_identity, numpy_identity, lift_identity, manifest_cid = (
        authenticate_environment()
    )
    print(
        "SOURCE_ENV python=%s pandas=%s numpy=%s lift=%s corpusManifestCid=%s"
        % (
            sys.version.split()[0],
            pandas_identity.version,
            numpy_identity.version,
            lift_identity.version,
            manifest_cid,
        ),
        flush=True,
    )

    authenticated = authenticated_pandas_corpus()
    corpus = authenticated.root
    print(
        f"SOURCE_CORPUS root={corpus} fileCount={authenticated.file_count}",
        flush=True,
    )

    target = corpus.joinpath(*args.path.split("/"))
    if not target.is_file():
        # An absent path is a REFUSAL, never an empty printout.
        print(f"SOURCE_PATH_ABSENT {args.path} resolved={target}", flush=True)
        return 2

    text = target.read_text(encoding="utf-8")
    lines = text.splitlines()
    start, end = _parse_range(args.lines)
    if start > len(lines):
        print(
            f"SOURCE_LINE_ABSENT {args.path}:{start} fileLines={len(lines)}",
            flush=True,
        )
        return 3
    if end > len(lines):
        print(
            f"SOURCE_LINE_ABSENT {args.path}:{end} fileLines={len(lines)}",
            flush=True,
        )
        return 3

    print(f"SOURCE_FILE {args.path} lines={len(lines)}", flush=True)
    for number in range(start, end + 1):
        print(f"SOURCE_LINE {number:>6}| {lines[number - 1]}", flush=True)

    tree = ast.parse(text, filename=str(target))
    module_body = list(tree.body)

    for number in range(start, end + 1):
        covering = _covering(tree, number)
        statements = [
            node for node in module_body
            if node.lineno <= number <= (node.end_lineno or node.lineno)
        ]
        top = statements[0] if statements else None
        innermost = covering[-1] if covering else None
        print(
            "SOURCE_NODE %s:%d moduleStmt=%s@%s:%s innermost=%s@%s:%s"
            % (
                args.path,
                number,
                type(top).__name__ if top is not None else "<none>",
                getattr(top, "lineno", "-"),
                getattr(top, "col_offset", "-"),
                type(innermost).__name__ if innermost is not None else "<none>",
                getattr(innermost, "lineno", "-"),
                getattr(innermost, "col_offset", "-"),
            ),
            flush=True,
        )

    for name in args.name or ():
        found = [node for node in module_body if _binds(node, name)]
        if not found:
            print(f"SOURCE_NAME_ABSENT {args.path} name={name}", flush=True)
            return 4
        print(
            f"SOURCE_NAME {args.path} name={name} moduleScopeBindings={len(found)}",
            flush=True,
        )
        for node in found:
            print(
                "SOURCE_BINDING %s name=%s kind=%s at=%d:%d src=%s"
                % (
                    args.path,
                    name,
                    type(node).__name__,
                    node.lineno,
                    node.col_offset,
                    ast.unparse(node).splitlines()[0][:200],
                ),
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
