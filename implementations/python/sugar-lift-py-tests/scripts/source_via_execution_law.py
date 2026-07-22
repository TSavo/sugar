#!/usr/bin/env python3
"""R_source_via_execution — permanent baseline-free floor (#5930, split from #5928).

Recognition answers the STATIC question "what does this name refer to?" by
IMPORTING the module and reading a live object. That runs arbitrary
third-party C extension code inside the lifting process, makes the answer
depend on environment and corpus ORDER (not on the source under test), and is
the mechanism behind the intermittent SIGSEGV in #5928.

This floor censuses every ``importlib.import_module`` / ``importlib.util.find_spec``
/ ``__import__`` call reachable from recognition, factory, and sugar dispatch,
outside the one mechanically-legitimate self-import.

Legitimate non-executing form: ``importlib.machinery.PathFinder.find_spec(name,
search_path)`` locates a spec WITHOUT importing parent packages or the target.
That is not scanned — only the executing forms are.

Exit 1 whenever R_source_via_execution > 0. There is no baseline, threshold, or
allowlist. The single mechanically-legitimate site (``factory/build.py``
self-registering our own sugar package) is excluded by MECHANISM: its import
target's statically-known prefix names the very top-level package the scanned
source lives under -- never by matching a hardcoded path or string.

Planted-twin discrimination lives in
``tests/test_source_via_execution_law.py`` and must survive relocation into a
helper function, a mapping/registry literal, a getattr indirection, an
aliased import, or a late import inside a function body.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import traceback
from pathlib import Path
from typing import NamedTuple, Sequence

_EXECUTING_KINDS = frozenset(
    {
        "import-module-call",
        "find-spec-call",
        "dunder-import-call",
    }
)


class SourceViaExecution(NamedTuple):
    path: str
    line: int
    kind: str
    target: str
    expression: str
    note: str


def _qualified_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _static_prefix(node: ast.AST) -> str | None:
    """The longest statically-known leading literal of a string expression.

    A plain ``Constant`` string is fully known. An f-string (``JoinedStr``) is
    known up to its first dynamic (``FormattedValue``) chunk -- everything
    before that is a real, unavoidable literal prefix of whatever the whole
    string resolves to at runtime.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                break
        return "".join(parts) if parts else None
    return None


class _AliasTable:
    """Maps a bound local name to the canonical dotted importlib coordinate it
    was imported/assigned from -- so aliasing, ``from`` imports, and simple
    rebinding cannot hide an executing call from the census.
    """

    def __init__(self) -> None:
        self.table: dict[str, str] = {}

    def add(self, name: str, canonical: str) -> None:
        self.table[name] = canonical

    def canonicalize(self, qualified: str) -> str:
        if not qualified:
            return qualified
        parts = qualified.split(".")
        head = parts[0]
        canon_head = self.table.get(head, head)
        return ".".join([canon_head, *parts[1:]]) if parts[1:] else canon_head


def _build_alias_table(tree: ast.AST) -> _AliasTable:
    aliases = _AliasTable()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    # `import importlib.util as u` binds `u` -> `importlib.util`.
                    aliases.add(alias.asname, alias.name)
                # `import importlib.util` (no asname) binds the head name
                # `importlib` to itself -- already the identity default, so
                # no table entry is needed (and adding one would be wrong:
                # it must NOT become `importlib` -> `importlib.util`).
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                bound = alias.asname or alias.name
                aliases.add(bound, f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                value = node.value
                qualified = _qualified_name(value)
                canonical = aliases.canonicalize(qualified) if qualified else ""
                if canonical in (
                    "importlib.import_module",
                    "importlib.util.find_spec",
                    "__import__",
                    "builtins.__import__",
                ):
                    aliases.add(target.id, canonical)
                elif (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id == "getattr"
                    and len(value.args) >= 2
                ):
                    # `loader = getattr(importlib, "import_module")` --
                    # rebinding a name to the RESULT of a getattr lookup is
                    # the same indirection as calling getattr(...) directly;
                    # the alias table must resolve `loader(...)` too.
                    base_qualified = _qualified_name(value.args[0])
                    base_canonical = (
                        aliases.canonicalize(base_qualified) if base_qualified else ""
                    )
                    attr_node = value.args[1]
                    if isinstance(attr_node, ast.Constant) and isinstance(
                        attr_node.value, str
                    ):
                        attr = attr_node.value
                        if base_canonical == "importlib" and attr == "import_module":
                            aliases.add(target.id, "importlib.import_module")
                        elif (
                            base_canonical == "importlib.util"
                            and attr == "find_spec"
                        ):
                            aliases.add(target.id, "importlib.util.find_spec")
    return aliases


def _classify_call(
    node: ast.Call, aliases: _AliasTable
) -> tuple[str, str] | None:
    """Return (kind, resolved-target) for an executing importlib call, else None."""
    func = node.func

    # Direct / aliased / from-imported callable: foo(...) where foo resolves
    # to importlib.import_module / importlib.util.find_spec / __import__.
    qualified = _qualified_name(func)
    if qualified:
        canonical = aliases.canonicalize(qualified)
        if canonical == "importlib.import_module":
            return "import-module-call", canonical
        if canonical == "importlib.util.find_spec":
            return "find-spec-call", canonical
        if canonical in ("__import__", "builtins.__import__"):
            return "dunder-import-call", canonical

    # getattr(importlib, "import_module")(...) / getattr(importlib.util,
    # "find_spec")(...) -- indirection that a plain qualified-name walk misses.
    if isinstance(func, ast.Call):
        inner = func.func
        if isinstance(inner, ast.Name) and inner.id == "getattr" and len(func.args) >= 2:
            base_qualified = _qualified_name(func.args[0])
            base_canonical = aliases.canonicalize(base_qualified) if base_qualified else ""
            attr_node = func.args[1]
            if isinstance(attr_node, ast.Constant) and isinstance(attr_node.value, str):
                attr = attr_node.value
                if base_canonical == "importlib" and attr == "import_module":
                    return "import-module-call", f"getattr({base_canonical!r}, {attr!r})"
                if base_canonical == "importlib.util" and attr == "find_spec":
                    return "find-spec-call", f"getattr({base_canonical!r}, {attr!r})"
    return None


def _own_package_name(root: Path) -> str:
    """The top-level package that owns this scan root, derived from layout.

    Scan roots are direct children of the package directory
    (``src/<package>/sugar``, ``src/<package>/factory``, ...) -- the package
    name is read off the filesystem, never hardcoded.
    """
    return root.parent.name


def _is_legitimate_self_import(node: ast.Call, own_package: str) -> bool:
    """Mechanical exemption: the import target's statically-known prefix
    names our OWN top-level package, not a third-party module under test.

    Never matches a hardcoded path or literal package name -- ``own_package``
    is read off the filesystem layout of the scan root being audited.
    """
    if not node.args:
        return False
    prefix = _static_prefix(node.args[0])
    if prefix is None:
        return False
    if prefix == own_package or prefix.startswith(f"{own_package}."):
        return True
    # Relative coordinate (``.submodule``) resolved against ``__name__`` is,
    # by construction, always a submodule of the CALLING module's own
    # package -- there is no third-party spelling that can satisfy this
    # shape, so it is a mechanical (not name-based) self-import proof.
    if prefix.startswith("."):
        package_arg = node.args[1] if len(node.args) >= 2 else None
        if isinstance(package_arg, ast.Name) and package_arg.id == "__name__":
            return True
    return False


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception as exc:  # noqa: BLE001 -- auditor must not crash
        return f"<unparse-failed:{type(exc).__name__}>"


def _rel_path(root: Path, path: Path) -> str:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        rel = Path(path.name)
    return f"{root.name}/{rel.as_posix()}"


def _read_source(path: Path) -> tuple[str | None, SourceViaExecution | None]:
    try:
        return path.read_text(encoding="utf-8"), None
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8-sig"), None
        except UnicodeDecodeError:
            try:
                return path.read_text(encoding="utf-8", errors="replace"), None
            except OSError as exc:
                return None, SourceViaExecution(
                    path=path.as_posix(),
                    line=0,
                    kind="auditor-read-error",
                    target="-",
                    expression=type(exc).__name__,
                    note=f"could not read source after utf-8 fallback: {exc}",
                )
    except OSError as exc:
        return None, SourceViaExecution(
            path=path.as_posix(),
            line=0,
            kind="auditor-read-error",
            target="-",
            expression=type(exc).__name__,
            note=f"could not read source: {exc}",
        )


def scan_file(path: Path, *, rel: str, own_package: str) -> list[SourceViaExecution]:
    offenders: list[SourceViaExecution] = []
    source, read_error = _read_source(path)
    if read_error is not None:
        return [read_error._replace(path=rel)]
    assert source is not None
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [
            SourceViaExecution(
                path=rel,
                line=int(exc.lineno or 0),
                kind="auditor-parse-error",
                target="-",
                expression=type(exc).__name__,
                note=f"ast.parse failed: {exc.msg}",
            )
        ]
    except Exception as exc:  # noqa: BLE001
        return [
            SourceViaExecution(
                path=rel,
                line=0,
                kind="auditor-parse-error",
                target="-",
                expression=type(exc).__name__,
                note=f"ast.parse failed: {exc}",
            )
        ]

    try:
        aliases = _build_alias_table(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            classified = _classify_call(node, aliases)
            if classified is None:
                continue
            kind, target = classified
            if _is_legitimate_self_import(node, own_package):
                continue
            offenders.append(
                SourceViaExecution(
                    path=rel,
                    line=getattr(node, "lineno", 0) or 0,
                    kind=kind,
                    target=target,
                    expression=_safe_unparse(node),
                    note=(
                        "recognition must answer 'what does this name refer "
                        "to' by reading source (SourceOracle / "
                        "PathFinder.find_spec), never by importing and "
                        "executing the target"
                    ),
                )
            )
    except Exception as exc:  # noqa: BLE001 -- per-file containment
        offenders.append(
            SourceViaExecution(
                path=rel,
                line=0,
                kind="auditor-scan-error",
                target="-",
                expression=type(exc).__name__,
                note=f"scan aborted for file: {exc}",
            )
        )

    deduped: list[SourceViaExecution] = []
    seen: set[tuple[str, int, str, str, str]] = set()
    for row in offenders:
        key = (row.path, row.line, row.kind, row.target, row.expression)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def scan_roots(roots: Sequence[Path]) -> list[SourceViaExecution]:
    offenders: list[SourceViaExecution] = []
    for root in roots:
        try:
            root_resolved = root.resolve()
        except OSError as exc:
            offenders.append(
                SourceViaExecution(
                    path=str(root),
                    line=0,
                    kind="auditor-root-error",
                    target="-",
                    expression=type(exc).__name__,
                    note=f"could not resolve scan root: {exc}",
                )
            )
            continue
        if not root_resolved.is_dir():
            offenders.append(
                SourceViaExecution(
                    path=str(root),
                    line=0,
                    kind="auditor-root-error",
                    target="-",
                    expression="NotADirectory",
                    note=f"scan root is not a directory: {root_resolved}",
                )
            )
            continue
        own_package = _own_package_name(root_resolved)
        try:
            paths = sorted(root_resolved.rglob("*.py"))
        except OSError as exc:
            offenders.append(
                SourceViaExecution(
                    path=str(root),
                    line=0,
                    kind="auditor-root-error",
                    target="-",
                    expression=type(exc).__name__,
                    note=f"rglob failed: {exc}",
                )
            )
            continue
        for path in paths:
            if not path.is_file():
                continue
            rel = _rel_path(root_resolved, path)
            offenders.extend(scan_file(path, rel=rel, own_package=own_package))
    return sorted(offenders)


def r_source_via_execution(offenders: Sequence[SourceViaExecution]) -> int:
    return sum(1 for row in offenders if row.kind in _EXECUTING_KINDS)


def r_auditor_errors(offenders: Sequence[SourceViaExecution]) -> int:
    return sum(1 for row in offenders if row.kind.startswith("auditor-"))


def format_report(offenders: Sequence[SourceViaExecution]) -> str:
    lines = [
        f"R_source_via_execution = {r_source_via_execution(offenders)}",
        f"auditor_errors = {r_auditor_errors(offenders)}",
        (
            "Replacement: SourceOracle (installed_module_source) for text, "
            "importlib.machinery.PathFinder.find_spec(name, search_path) for "
            "existence/origin -- never importlib.import_module / "
            "importlib.util.find_spec / __import__ on third-party source."
        ),
        "",
        "Loci:",
    ]
    for row in offenders:
        lines.append(
            f"{row.path}:{row.line}:{row.kind}:target={row.target} — "
            f"{row.expression} — {row.note}"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    package = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "sugar_lift_py_tests"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "roots",
        nargs="*",
        type=Path,
        # Construction/recognition surface (post-factory architecture).
        # factory/ and recognition/ were folded across these dirs: construction
        # decisions now flow through floor values, effects, outcomes, claims,
        # ProofIR, temporal/context machinery, and lift/RPC orchestration.
        # Excluded on purpose: audit_only + idd (measurement/reporting),
        # manifests (declared contract data).
        default=[
            package / "claim",
            package / "context",
            package / "effect",
            package / "floor",
            package / "gap",
            package / "kit_rpc",
            package / "lift",
            package / "outcome",
            package / "proofir",
            package / "sugar",
            package / "sugar_body",
            package / "temporal",
        ],
    )
    try:
        args = parser.parse_args(argv)
        offenders = scan_roots(args.roots)
    except Exception as exc:  # noqa: BLE001
        print(
            "SOURCE-VIA-EXECUTION LAW ERROR: unhandled auditor failure "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print(traceback.format_exc(), file=sys.stderr)
        print(
            json.dumps(
                {
                    "instrument": "R_source_via_execution",
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "R_source_via_execution": None,
                    "auditor_errors": 1,
                }
            )
        )
        return 2

    r = r_source_via_execution(offenders)
    err = r_auditor_errors(offenders)
    summary = {
        "instrument": "R_source_via_execution",
        "ok": r == 0 and err == 0,
        "R_source_via_execution": r,
        "auditor_errors": err,
    }
    if r > 0 or err > 0:
        print(
            "SOURCE-VIA-EXECUTION LAW RED: "
            f"{r} executing loci"
            + (f"; {err} auditor errors" if err else "")
        )
        print(format_report(offenders))
        print(json.dumps(summary))
        return 1
    print("SOURCE-VIA-EXECUTION LAW GREEN: R_source_via_execution = 0")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
