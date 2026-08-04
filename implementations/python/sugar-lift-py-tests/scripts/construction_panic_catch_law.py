#!/usr/bin/env python3
"""R_construction_panic_catches_outside_audit — permanent floor.

``ConstructionPanic`` is a sanctioned typed construction gap. Reviewed membranes
may catch it without pure re-raise:

1. **Audit enumeration** — ``audit_only/collect_construction_gaps.py``,
   ``scripts/desugar_repro.py``, ``scripts/exit_set_arm_census.py``, and
   ``scripts/stablezero_classify.py`` hold the panic only to emit their named
   loud-red gap/residual rows.
2. **Production typed-gap classification** — ``scripts/_production_lift_child.py``
   marks the file ``typed-gap`` for the zero-tolerance floors so kit-domain
   construction panics are not misclassified as bare Python exceptions.
   That path does NOT convert the panic into Incomplete, opacity, soft None,
   or a missing report row.
3. **Recensus per-file terminals** — ``scripts/recensus_enumerate_consumer.py``
   authenticates the panic identity, then emits the exact roster,
   context-manager, or residual ``category=panic`` terminal. These witnesses
   are enrolled by exact path, function, and AST shape.

Every other ``except ConstructionPanic`` (or catch via BaseException / bare
except) under production sources is debt unless the handler body is pure
re-raise on every path (no soft assignment / continue / return None after
catch). Production construction, dig, floors, and reports must never convert
ConstructionPanic into Incomplete or silence.

Exit 1 while R > 0. Missing roots and source read/parse failures are separate
``auditor_errors`` and also exit red. No baseline. A named membrane is
authorized only at its exact path, enclosing function, caught type, and handler
body; a filename alone never suppresses inspection.
"""

from __future__ import annotations

# Not the board. This module measures its own named denominator; the sole
# authoritative Python corpus scoreboard is scripts/control_effect_recensus.py.
# See tests/test_one_authoritative_scoreboard.py.

from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

SCOREBOARD_AUTHORITY = False

import argparse
import ast
from pathlib import Path
import sys
from typing import NamedTuple


class PanicCatchOffender(NamedTuple):
    path: str
    line: int
    kind: str
    note: str


_SOFT_AFTER_CATCH = frozenset(
    {
        "None",
        "continue",
        "pass",
        "return",
        "append",
        "Incomplete",
        "resolved_value",
        "recovered",
    }
)


def _canonical_handler(source: str) -> str:
    """Return the location-free AST testimony for one readable handler."""
    tree = ast.parse("try:\n    pass\n" + source)
    try_node = tree.body[0]
    assert isinstance(try_node, ast.Try)
    assert len(try_node.handlers) == 1
    return ast.dump(try_node.handlers[0], include_attributes=False)


def _canonical_statement(source: str) -> str:
    tree = ast.parse(source)
    assert len(tree.body) == 1
    return ast.dump(tree.body[0], include_attributes=False)


# These are source-shape witnesses, not filename exemptions. Any new statement,
# caught type, binding name, or fabricated return changes the handler AST and
# makes the law red until the membrane itself is explicitly reviewed.
_SANCTIONED_HANDLER_SHAPES = {
    (
        "audit_only/collect_construction_gaps.py",
        "collect_construction_gaps",
    ): frozenset(
        {_canonical_handler("""
except ConstructionPanic as panic:
    gaps.append(gap_from_construction_panic(label, panic))
""")}
    ),
    (
        "audit_only/collect_construction_gaps.py",
        "collect_construction_panic",
    ): frozenset(
        {_canonical_handler("""
except ConstructionPanic as panic:
    return None, gap_from_construction_panic(label, panic)
""")}
    ),
    ("desugar_repro.py", "_desugar_one"): frozenset({_canonical_handler("""
except BaseException as exc:
    status = type(exc).__name__
    detail = str(exc)
    origin = [
        f"{frame.filename}:{frame.lineno} {frame.name}"
        for frame in traceback.extract_tb(exc.__traceback__)[-6:]
    ]
""")}),
    ("exit_set_arm_census.py", "patched_and_exit"): frozenset({_canonical_handler("""
except BaseException as exc:
    row.verdict_probe_error = f"{type(exc).__name__}: {exc}"
    row.check()
    return result
""")}),
    ("stablezero_classify.py", "classify"): frozenset(
        {
            _canonical_handler("""
except ConstructionPanic as panic:
    row["status"] = "ConstructionPanic"
    row["testimony"] = _testimony(panic)
"""),
            _canonical_handler("""
except BaseException as error:
    row["status"] = f"raised:{type(error).__name__}"
    row["testimony"] = _testimony(error)
"""),
        }
    ),
    ("_production_lift_child.py", "production_lift_testimony"): frozenset(
        {
            _canonical_handler("""
except BaseException as error:
    row = _typed_construction_row(error)
    if row is None:
        raise
    gaps.append(row)
    return {
        "kind": _TERMINAL_KIND,
        "outcome": OUTCOME_TYPED_GAP,
        "file": rel,
        "typed_gap_count": len(gaps),
        "typed_gaps": gaps,
    }
"""),
            _canonical_handler("""
except BaseException as error:
    row = _typed_construction_row(error)
    if row is None:
        raise
    gaps.append(row)
"""),
        }
    ),
    (
        "recensus_enumerate_consumer.py",
        "measure_file_via_enumerate",
    ): frozenset(
        {
            _canonical_handler("""
except BaseException as error:
    if _is_process_control(error):
        raise
    auth = int(ast_fn) if ast_fn is not None else 0
    panic = _panic_from_exception(error, file_rel=file_rel, phase="roster")
    if panic is None:
        return _instrument_failure_row(
            error,
            file_rel=file_rel,
            phase="roster",
            source_cid=source_cid,
            function_nodes=[],
            functions_total=auth,
            functions_enumerated=0,
        )
    row = _empty_shell(
        file_rel=file_rel,
        category="panic",
        functions_total=auth,
        functions_enumerated=0,
        defect=panic,
        panic=panic,
        functions_clean=None if auth > 0 else 0,
        clean_ratio_refused=auth > 0,
        clean_refuse_reason=(
            "roster demand panicked; clean not measured" if auth > 0 else None
        ),
        ast_fn=ast_fn,
    )
    return _attest_terminal_row(
        row,
        file_rel=file_rel,
        source_cid=source_cid,
        function_nodes=[],
    )
"""),
            _canonical_handler("""
except BaseException as error:
    if _is_process_control(error):
        raise
    panic = _panic_from_exception(
        error, file_rel=file_rel, phase="context-manager-resolutions"
    )
    if panic is None:
        return _instrument_failure_row(
            error,
            file_rel=file_rel,
            phase="context-manager-resolutions",
            source_cid=source_cid,
            function_nodes=function_nodes,
            functions_total=len(function_nodes),
            functions_enumerated=len(function_nodes),
        )
    row = _empty_shell(
        file_rel=file_rel,
        category="panic",
        functions_total=len(function_nodes),
        functions_enumerated=len(function_nodes),
        defect=panic,
        panic=panic,
        functions_clean=None,
        clean_ratio_refused=True,
        clean_refuse_reason="CM resolution panic after roster; clean not measured",
        ast_fn=ast_fn,
    )
    row["constructionPanics"] = [panic]
    row["enumerateConstructionPanics"] = [panic]
    row["contextManagerResolutionEvents"] = _provisional_resolution_events(
        contract_refs=contract_refs,
        source_cid=source_cid,
    )
    return _attest_terminal_row(
        row,
        file_rel=file_rel,
        source_cid=source_cid,
        function_nodes=function_nodes,
    )
"""),
            _canonical_handler("""
except BaseException as error:
    if _is_process_control(error):
        raise
    row = terminal_from_enumerate(
        file_rel=file_rel,
        function_nodes=function_nodes,
        function_gaps=[],
        audit=None,
        construction_gaps=[],
        residual_phase_failed=True,
        residual_error=error,
        ast_fn=ast_fn,
        source_cid=source_cid,
        context_manager_resolution_events=cm_events,
    )
    row["d3Residency"] = _complete_d3_residency_observation(
        source_cid=source_cid,
        present_before_demand=d3_present_before_demand,
    )
    return row
"""),
        }
    ),
}

_SANCTIONED_ISINSTANCE_SHAPES = {
    ("_production_lift_child.py", "_typed_construction_row"): frozenset(
        {_canonical_statement("""
if isinstance(error, ConstructionPanic):
    return _construction_panic_row(error)
""")}
    ),
    ("recensus_enumerate_consumer.py", "_panic_from_exception"): frozenset(
        {_canonical_statement("""
if isinstance(error, ConstructionPanic):
    info = error.info.to_json()
    owner = str(info["owner"])
    coordinate = str(info["blame"])
    observed = str(info["observed"])
    requested = str(info["requested"])
    fix = str(info["fix"])
elif isinstance(error, SugarNotWritten):
    owner = str(error.owner)
    coordinate = str(error.blame)
    observed = str(error.observed)
    requested = str(error.requested)
    fix = str(error.fix)
else:
    return None
""")}
    ),
}


def _enclosing_function_name(
    node: ast.AST, parents: dict[ast.AST, ast.AST]
) -> str | None:
    parent = parents.get(node)
    while parent is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return parent.name
        parent = parents.get(parent)
    return None


def _is_sanctioned_handler(
    rel: str,
    handler: ast.ExceptHandler,
    parents: dict[ast.AST, ast.AST],
) -> bool:
    function_name = _enclosing_function_name(handler, parents)
    if function_name is None:
        return False
    shapes = _SANCTIONED_HANDLER_SHAPES.get((rel, function_name), frozenset())
    return ast.dump(handler, include_attributes=False) in shapes


def _is_sanctioned_isinstance(
    rel: str,
    node: ast.If,
    parents: dict[ast.AST, ast.AST],
) -> bool:
    function_name = _enclosing_function_name(node, parents)
    if function_name is None:
        return False
    shapes = _SANCTIONED_ISINSTANCE_SHAPES.get((rel, function_name), frozenset())
    return ast.dump(node, include_attributes=False) in shapes


def _handler_names(handler: ast.ExceptHandler) -> set[str]:
    """Exception type names this handler catches."""
    names: set[str] = set()
    t = handler.type
    if t is None:
        names.add("<bare>")
        return names

    def walk(node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Tuple):
            for elt in node.elts:
                walk(elt)

    walk(t)
    return names


def _catches_construction_panic(handler: ast.ExceptHandler) -> bool:
    names = _handler_names(handler)
    return bool(names & {"ConstructionPanic", "BaseException"}) or names == {"<bare>"}


def _prior_pure_reraise_intercepts_construction_panic(
    handler: ast.ExceptHandler,
    parents: dict[ast.AST, ast.AST],
) -> bool:
    """Whether an earlier sibling catches ConstructionPanic and pure re-raises.

    Except handlers are ordered. An exact earlier ``except ConstructionPanic``
    that terminates every path with ``raise`` makes a later BaseException/bare
    handler unreachable for ConstructionPanic. This is semantic catch
    precedence, not a path allowlist; removing or softening the earlier handler
    makes the later broad catch red again.
    """
    parent = parents.get(handler)
    if not isinstance(parent, (ast.Try, ast.TryStar)):
        return False
    try:
        index = parent.handlers.index(handler)
    except ValueError:
        return False
    return any(
        "ConstructionPanic" in _handler_names(prior) and _pure_reraise(prior)
        for prior in parent.handlers[:index]
    )


def _is_terminal_raise(stmt: ast.AST) -> bool:
    if isinstance(stmt, ast.Raise):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        # raise SystemExit(...)  is Raise; bare SystemExit() is not allowed
        return False
    return False


def _ends_in_raise(stmts: list[ast.stmt]) -> bool:
    if not stmts:
        return False
    last = stmts[-1]
    if isinstance(last, ast.Raise):
        return True
    if isinstance(last, ast.If):
        return (
            bool(last.orelse)
            and _ends_in_raise(last.body)
            and _ends_in_raise(last.orelse)
        )
    return False


def _pure_reraise(handler: ast.ExceptHandler) -> bool:
    """True if handler always re-raises (process-terminal), never soft-continues.

    Logging / _send before raise SystemExit is allowed if every path ends in raise.
    Conditional soft continue (recovered_panics append + None) is not.
    """
    body = [
        n
        for n in handler.body
        if not (
            isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)
        )
    ]
    if not body:
        return False
    # Soft continue markers anywhere in the handler → debt
    text = ast.unparse(handler)
    if any(
        tok in text
        for tok in (
            " = None",
            "return None",
            "\n    continue\n",
            "\n        continue\n",
            "resolved_value = None",
            "recovered_panics.append",
            "gaps.append",
        )
    ):
        # gaps.append is audit-adjacent; still soft for production
        if "recovered_panics" in text or " = None" in text or "return None" in text:
            return False
        if "gaps.append" in text and "raise" not in text.split("gaps.append")[-1]:
            return False
    return _ends_in_raise(body)


def _soft_continue(handler: ast.ExceptHandler) -> bool:
    """Heuristic: handler assigns None / continues / returns soft after catch."""
    text = ast.unparse(handler)
    if "raise" in text and "if " not in text and "append" not in text:
        # pure re-raise path
        if _pure_reraise(handler):
            return False
    soft_tokens = (
        " = None",
        "return None",
        "\ncontinue",
        "\n        pass",
        "Incomplete",
        "append(",
        "resolved_value = None",
    )
    return any(tok in text for tok in soft_tokens) or not _pure_reraise(handler)


def scan_package(package_root: Path) -> list[PanicCatchOffender]:
    offenders: list[PanicCatchOffender] = []
    try:
        resolved_root = package_root.resolve()
    except OSError as error:
        return [
            PanicCatchOffender(
                package_root.as_posix(),
                0,
                "auditor-root-error",
                f"could not resolve scan root: {error}",
            )
        ]
    if not resolved_root.is_dir():
        return [
            PanicCatchOffender(
                package_root.as_posix(),
                0,
                "auditor-root-error",
                "scan root is not a directory",
            )
        ]
    try:
        paths = sorted(resolved_root.rglob("*.py"))
    except OSError as error:
        return [
            PanicCatchOffender(
                package_root.as_posix(),
                0,
                "auditor-root-error",
                f"could not enumerate scan root: {error}",
            )
        ]
    for path in paths:
        rel = path.relative_to(resolved_root).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            offenders.append(
                PanicCatchOffender(
                    rel,
                    0,
                    "auditor-read-error",
                    f"could not read source: {error}",
                )
            )
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as error:
            offenders.append(
                PanicCatchOffender(
                    rel,
                    int(error.lineno or 0),
                    "auditor-parse-error",
                    f"ast.parse failed: {error.msg}",
                )
            )
            continue
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if not _catches_construction_panic(node):
                continue
            if _prior_pure_reraise_intercepts_construction_panic(node, parents):
                continue
            if _is_sanctioned_handler(rel, node, parents):
                continue
            if _pure_reraise(node):
                # pure re-raise is process-terminal — not a soft membrane
                continue
            # Any non-pure-reraise catch outside sanctioned membranes is debt.
            offenders.append(
                PanicCatchOffender(
                    path=rel,
                    line=node.lineno,
                    kind="construction-panic-catch-outside-membrane",
                    note=(
                        "except ConstructionPanic outside sanctioned membranes "
                        "must not continue; only the named per-file audit "
                        "enumerators or production typed-gap classification "
                        "(_production_lift_child) may hold it"
                    ),
                )
            )
        # isinstance(exc, ConstructionPanic) soft return
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            calls = [
                child
                for child in ast.walk(node.test)
                if isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "isinstance"
                and len(child.args) >= 2
            ]
            if not any(
                (
                    call.args[1].id
                    if isinstance(call.args[1], ast.Name)
                    else (
                        call.args[1].attr
                        if isinstance(call.args[1], ast.Attribute)
                        else ""
                    )
                )
                == "ConstructionPanic"
                for call in calls
            ):
                continue
            if _is_sanctioned_isinstance(rel, node, parents):
                continue
            body_text = ast.unparse(node)
            if (
                "return None" in body_text
                or "return" in body_text
                and "raise" not in body_text
            ):
                offenders.append(
                    PanicCatchOffender(
                        path=rel,
                        line=node.lineno,
                        kind="factory-panic-isinstance-soft-return",
                        note=(
                            "isinstance(exc, ConstructionPanic) then soft return/None — "
                            "dig/report must not convert panic into opacity"
                        ),
                    )
                )
    return sorted(offenders)


def scan_repository(kit_root: Path) -> list[PanicCatchOffender]:
    roots = (
        ("src/sugar_lift_py_tests", kit_root / "src" / "sugar_lift_py_tests"),
        ("scripts", kit_root / "scripts"),
    )
    offenders: list[PanicCatchOffender] = []
    for prefix, root in roots:
        root_offenders = scan_package(root)
        offenders.extend(
            offender._replace(
                path=(
                    prefix
                    if offender.kind == "auditor-root-error"
                    else f"{prefix}/{offender.path}"
                )
            )
            for offender in root_offenders
        )
    return sorted(offenders)


def format_report(offenders: list[PanicCatchOffender]) -> str:
    panic_offenders = [row for row in offenders if not row.kind.startswith("auditor-")]
    auditor_errors = [row for row in offenders if row.kind.startswith("auditor-")]
    lines = [
        f"R_construction_panic_catches_outside_audit = {len(panic_offenders)}",
        f"auditor_errors = {len(auditor_errors)}",
        "Lawful: only per-file corpus / gap-enumeration audit holds ConstructionPanic "
        "and emits a loud red row. Production may only pure re-raise.",
        "",
        "Loci:",
    ]
    for row in offenders:
        lines.append(f"{row.path}:{row.line}:{row.kind} — {row.note}")
    return "\n".join(lines)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kit-root",
        type=Path,
        default=sugar_lift_py_tests_package_root(),
    )
    args = parser.parse_args()
    offenders = scan_repository(args.kit_root)
    if offenders:
        print(
            "FACTORY-PANIC-CATCH LAW RED: "
            f"{sum(not row.kind.startswith('auditor-') for row in offenders)} "
            "illegal ConstructionPanic catches; "
            f"auditor_errors={sum(row.kind.startswith('auditor-') for row in offenders)}"
        )
        print(format_report(offenders))
        return 1
    print(
        "FACTORY-PANIC-CATCH LAW GREEN: R_construction_panic_catches_outside_audit = 0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
