#!/usr/bin/env python3
"""R_construction_panic_catches_outside_audit — permanent floor.

There is ONE refusal: ``sugar_source_tree.panic.LifterRefusal`` (a
``BaseException``). Both refusal families derive from it:
``ConstructionPanic`` (``sugar_lift_py_tests.gap.panic``) and
``SourceTreePanic`` (``SugarNotWritten``, ``BackendDefect``,
``VocabularyMissing``, ...). This law counts every catch of ANY refusal class
-- the root, either family, any subclass (found by walking the runtime
hierarchy and every ``class X(<refusal>)`` in the scanned sources), a tuple
containing one, an alias of one, or ``BaseException`` / bare ``except`` -- under
the same membrane rules. Reviewed membranes may hold a refusal without pure
re-raise:

1. **Audit enumeration** — per-file corpus / gap-enumeration audits
   (``audit_only/collect_construction_gaps.py``, ``census.py``,
   ``desugar_axis.py``, ``no_call_body_attribution.py``,
   ``scripts/desugar_repro.py``, ``scripts/exit_set_arm_census.py``,
   ``scripts/stablezero_classify.py`` and the frontier measurement scripts)
   hold the refusal only to emit their named loud-red gap/residual rows.
2. **Production typed-gap classification** — ``scripts/_production_lift_child.py``
   marks the file ``typed-gap`` for the zero-tolerance floors, and the
   resident RPC (``lift_rpc._serve`` / ``_handle_enumerate``) carries a refusal
   to the host by name (a typed-loud JSON-RPC error, a refused-function row).
   That path does NOT convert the refusal into a halt, opacity, soft None,
   or a missing report row.
3. **Recensus per-file terminals** — ``scripts/recensus_enumerate_consumer.py``
   authenticates the refusal identity, then emits the exact roster,
   context-manager, or residual ``category=panic`` terminal. These witnesses
   are enrolled by exact path, function, and AST shape.

Every other catch of a refusal under production sources is debt unless the
handler body is pure re-raise on every path (no soft assignment / continue /
return None after catch). Production construction, dig, floors, and reports
must never convert a refusal into a halt or silence. An ``except Exception``
never holds a refusal: the root is a ``BaseException``.

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
from typing import Iterable, NamedTuple


class PanicCatchOffender(NamedTuple):
    path: str
    line: int
    kind: str
    note: str


# The one refusal, and the two families that together cover it. A prior
# ``except`` that names the root (or both families) makes every later broad
# handler in the same ``try`` unreachable for a refusal.
REFUSAL_ROOT = "LifterRefusal"
REFUSAL_FAMILIES = frozenset({"ConstructionPanic", "SourceTreePanic"})
_REFUSAL_MODULE_PACKAGES = frozenset({"sugar_source_tree", "sugar_lift_py_tests"})


_SOFT_AFTER_CATCH = frozenset(
    {
        "None",
        "continue",
        "pass",
        "return",
        "append",
        "halted",
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
    # REVIEWED (#7757). The developer-loop corpus census (category 1). It holds
    # a ``SugarNotWritten`` only to count it on the R_construction family row
    # (the reporter carries the per-site row); a refusal that escapes the walk
    # is a red REFUSAL row in the crash ledger and the census exits 1.
    ("census.py", "_measure_file"): frozenset(
        {
            _canonical_handler("""
except SugarNotWritten as gap:
    families[type(gap).__name__] += 1
    return 1
"""),
            _canonical_handler("""
except SugarNotWritten:
    sugar = None
"""),
        }
    ),
    ("census.py", "census"): frozenset({_canonical_handler("""
except LifterRefusal as refusal:
    crashes[f"REFUSAL:{type(refusal).__name__}"] += 1
    print(
        f"[{i + 1}/{len(files)}]  REFUSAL {type(refusal).__name__} {rel}",
        flush=True,
    )
    continue
""")}),
    # REVIEWED (#7757). The desugar axis (category 1) counts a desugar refusal
    # on its own R_desugar owner row; it is never folded into a success.
    ("desugar_axis.py", "_desugar"): frozenset({_canonical_handler("""
except SugarNotWritten as gap:
    return ("refusal", gap)
""")}),
    # REVIEWED (#7757, flagged on #8081). The no-call body attribution ledger is
    # a gap-enumeration audit over the authenticated corpus manifest (category
    # 1): every enrolled body lands in exactly one conserved outcome arm, and a
    # refusal is held only to emit its ``namedRefusal body=... coordinate=<owner>``
    # row. ``UnattributableRefusal`` is re-raised first, by name.
    ("no_call_body_attribution.py", "attribute_body_probe"): frozenset(
        {_canonical_handler("""
except SugarNotWritten as refusal:
    return BodyAttribution(
        probe.body_id,
        probe.family,
        AttributionOutcome.NAMED_REFUSAL,
        refusal.owner,
    )
""")}
    ),
    # REVIEWED (#7757). The resident RPC (category 2), the one answer to the
    # one refusal: a refusal of one request (either family, any subclass) is
    # that request's typed-loud JSON-RPC error naming its class, message and
    # locus; the resident keeps serving the next request.
    ("lift_rpc.py", "_serve"): frozenset({_canonical_handler("""
except LifterRefusal as refusal:
    _send(
        {
            "jsonrpc": "2.0",
            "id": msg.get("id"),
            "error": {
                "code": -32001,
                "message": str(refusal),
                "data": {
                    "kind": "typed-loud",
                    "exception_type": type(refusal).__name__,
                    "stage": "dispatch",
                    "diagnostic": refusal.diagnostic(),
                },
            },
        }
    )
    _log_resident_profile(request_count, msg.get("method"))
    continue
""")}),
    # REVIEWED (#7785; the owner's one undecided member kind, 2026-11-12, in
    # docs/path-forward.md). A function whose row names a variable outside its
    # declared scope is refused by name: the full scan writes the
    # refused-function `undecided` row (step 8) and serves the rest of the file.
    # A seek packages nothing, so the refusal re-raises by name (#8081).
    ("lift_rpc.py", "_handle_enumerate"): frozenset({_canonical_handler("""
except FreeVariableRefusal as refusal:
    if seek:
        raise
    scan_rows.append(
        (
            _tree.function_def_memento(fn, file_rel).to_rpc(),
            _tree.refused_function_row(fn, file_rel, refusal),
        )
    )
    continue
""")}),
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
except SugarNotWritten:
    row["status"] = "SugarNotWritten"
"""),
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
    # REVIEWED (#7757). Frontier measurement scripts (category 1): each holds a
    # tree refusal only to count it on a named row (by owner / type) of the
    # per-file frontier it reports; the reporter carries the per-site gap.
    ("comprehension_iteration_recensus.py", "construct_file"): frozenset(
        {_canonical_handler("""
except SugarNotWritten:
    pass
""")}
    ),
    ("measure_binding_assignment_frontier.py", "measure"): frozenset(
        {
            _canonical_handler("""
except SugarNotWritten as panic:
    own = getattr(panic, "owner", "") in {
        "Assign.sugar",
        "AnnAssign.sugar",
        "AugAssign.sugar",
    }
    direct[shape]["direct_gap" if own else "blocked_descendant"] += 1
    roots[_panic_key(panic)] += 1
"""),
            _canonical_handler("""
except SourceTreePanic as panic:
    direct[shape]["other_typed_loud"] += 1
    roots[_panic_key(panic)] += 1
"""),
            _canonical_handler("""
except SourceTreePanic as panic:
    enclosing_functions["typed_loud"] += 1
    if object_field_candidate:
        object_field_enclosing["typed_loud"] += 1
        object_field_rows.append(
            {**row, "status": "typed_loud", "error": str(panic)}
        )
    roots[_panic_key(panic)] += 1
    for shape in shapes:
        enclosing[shape]["loud"] += 1
        enclosing[shape][
            f"root:{getattr(panic, 'owner', type(panic).__name__)}"
        ] += 1
"""),
            _canonical_handler("""
except (OSError, UnicodeError, SourceTreePanic) as panic:
    counts["files_other_failure"] += 1
    roots[_panic_key(panic)] += 1
"""),
        }
    ),
    ("measure_formatted_value_frontier.py", "measure"): frozenset(
        {
            _canonical_handler("""
except SugarNotWritten as panic:
    if panic.owner == "FormattedValue.sugar":
        counts["direct_gap"] += 1
        direct_by_shape[shape] += 1
    else:
        counts["blocked_descendant_gap"] += 1
        blocked_by_child[panic.observed.split(" at ", 1)[0]] += 1
"""),
            _canonical_handler("""
except SourceTreePanic as panic:
    counts["other_source_tree_panic"] += 1
    other_panics[type(panic).__name__] += 1
"""),
            _canonical_handler("""
except SugarNotWritten as panic:
    if panic.owner == "FormattedValue.sugar":
        roll_call["direct_gap"] += 1
    else:
        roll_call["blocked_descendant_gap"] += 1
        roll_call_blocked_by_child[
            panic.observed.split(" at ", 1)[0]
        ] += 1
"""),
            _canonical_handler("""
except SourceTreePanic as panic:
    roll_call["other_source_tree_panic"] += 1
    other_panics[type(panic).__name__] += 1
"""),
            _canonical_handler("""
except (OSError, UnicodeError, SourceTreePanic) as panic:
    counts["files_other_failure"] += 1
    other_panics[type(panic).__name__] += 1
"""),
        }
    ),
    ("measure_raise_from_direct_gaps.py", "measure"): frozenset(
        {
            _canonical_handler("""
except SugarNotWritten:
    descendant_gap = True
"""),
            _canonical_handler("""
except SugarNotWritten:
    pass
"""),
        }
    ),
    ("pandas_recensus_latency_probe.py", "main"): frozenset(
        {
            _canonical_handler("""
except SugarNotWritten:
    not_written += 1
    status = "SugarNotWritten"
"""),
            _canonical_handler("""
except SourceTreePanic:
    panics += 1
    status = "SourceTreePanic"
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
        # REVIEWED (#7374). This membrane runs AFTER the file's terminal row is
        # already minted, and it asks a second, separate question: who did the
        # walk see. A panic raised answering THAT question is not the file's
        # product terminal -- the loud counted terminal for this file already
        # exists in ``row``. Re-raising here would destroy it and report the
        # file as no terminal at all, which is a strictly worse lie than the
        # one this attestation exists to prevent.
        #
        # So the panic becomes a NAMED attendance gap on a row that stays red.
        # The gap field is never populated beside a membership manifest, so the
        # shard still cannot look like a shard that saw nobody: it refuses by
        # name at compose. Absence and lookup-failure keep separate spellings.
        #
        # REKEYED (#7415). The bounded-seat cut moved this membrane under
        # ``_measure_seat_under_ceiling`` and widened its guard from process
        # control to ``is_unswallowable``, which also re-raises
        # MeasurementCeilingExceeded. The handler re-raises strictly more than
        # the reviewed shape and banks the same named gap row.
        "recensus_enumerate_consumer.py",
        "_measure_seat_under_ceiling",
    ): frozenset(
        {
            _canonical_handler("""
except BaseException as error:
    if is_unswallowable(error):
        raise
    row[RELATION_MEMBERSHIP_GAP_ROW_FIELD] = [
        {
            "memento": {"file": file_rel},
            "reason": (
                "relation-membership demand raised: "
                f"{type(error).__name__}: {error}"
            ),
        }
    ]
    return row
""")
        }
    ),
    (
        # These three reviewed membranes did not change. #7374 split the old
        # ``measure_file_via_enumerate`` body out under this name and left a
        # thin wrapper behind, which silently orphaned their sanction: the
        # shapes still matched, the FUNCTION KEY no longer did. Keyed by name,
        # a rename reads exactly like an unreviewed membrane -- which is the
        # law behaving correctly, and why it is rekeyed rather than exempted.
        # #7415 then swapped ``_is_process_control`` for ``is_unswallowable``
        # (process control plus MeasurementCeilingExceeded): the same three
        # membranes, re-raising strictly more.
        "recensus_enumerate_consumer.py",
        "_terminal_via_enumerate",
    ): frozenset(
        {
            _canonical_handler("""
except BaseException as error:
    if is_unswallowable(error):
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
    if is_unswallowable(error):
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
    if is_unswallowable(error):
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
        {
            _canonical_statement("""
if isinstance(error, ConstructionPanic):
    return _construction_panic_row(error)
"""),
            _canonical_statement("""
if isinstance(error, SourceTreePanic):
    return _source_tree_gap_row(error)
"""),
        }
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


def runtime_refusal_names() -> frozenset[str]:
    """Every refusal class the lifter's own packages define, read off the
    runtime hierarchy under the one root.

    Restricted to classes whose module lives in ``sugar_source_tree`` or
    ``sugar_lift_py_tests`` so a test-local subclass never changes the law.
    """
    import sugar_lift_py_tests.gap.panic  # noqa: F401 -- loads the kit family
    from sugar_source_tree.panic import LifterRefusal

    seen: set[type] = set()
    stack: list[type] = [LifterRefusal]
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.add(cls)
        stack.extend(cls.__subclasses__())
    return frozenset(
        cls.__name__
        for cls in seen
        if cls.__module__.split(".", 1)[0] in _REFUSAL_MODULE_PACKAGES
    )


def _base_names(node: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for base in node.bases:
        if isinstance(base, ast.Name):
            names.add(base.id)
        elif isinstance(base, ast.Attribute):
            names.add(base.attr)
    return names


def refusal_family(
    trees: Iterable[ast.AST],
    seeds: Iterable[str] | None = None,
) -> frozenset[str]:
    """The root, both families, and every subclass defined in ``trees``.

    A fixed point over ``class X(<refusal>)``: a subclass a scanned source
    defines (``FreeVariableRefusal(ConstructionPanic)``) is a refusal class
    exactly like the ones the runtime hierarchy names.
    """
    family = set(runtime_refusal_names() if seeds is None else seeds)
    family.add(REFUSAL_ROOT)
    family |= REFUSAL_FAMILIES
    classes = [
        (node.name, _base_names(node))
        for tree in trees
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    ]
    changed = True
    while changed:
        changed = False
        for name, bases in classes:
            if name not in family and bases & family:
                family.add(name)
                changed = True
    return frozenset(family)


def _refusal_aliases(tree: ast.AST, family: frozenset[str]) -> dict[str, str]:
    """``from x import SugarNotWritten as SNW`` -> ``{"SNW": "SugarNotWritten"}``."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in family and alias.asname:
                    aliases[alias.asname] = alias.name
    return aliases


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
    """A sanctioned ``if``, or an ``elif`` arm of one."""
    current: ast.AST = node
    while True:
        function_name = _enclosing_function_name(current, parents)
        if function_name is not None:
            shapes = _SANCTIONED_ISINSTANCE_SHAPES.get(
                (rel, function_name), frozenset()
            )
            if ast.dump(current, include_attributes=False) in shapes:
                return True
        parent = parents.get(current)
        if isinstance(parent, ast.If) and parent.orelse == [current]:
            current = parent
            continue
        return False


def _type_names(node: ast.AST | None, aliases: dict[str, str]) -> set[str]:
    """Exception type names an ``except`` / ``isinstance`` type expression names."""
    names: set[str] = set()

    def walk(child: ast.AST) -> None:
        if isinstance(child, ast.Name):
            names.add(aliases.get(child.id, child.id))
        elif isinstance(child, ast.Attribute):
            names.add(aliases.get(child.attr, child.attr))
        elif isinstance(child, ast.Tuple):
            for elt in child.elts:
                walk(elt)

    if node is not None:
        walk(node)
    return names


def _handler_names(
    handler: ast.ExceptHandler, aliases: dict[str, str] | None = None
) -> set[str]:
    """Exception type names this handler catches."""
    if handler.type is None:
        return {"<bare>"}
    return _type_names(handler.type, aliases or {})


def _catches_refusal(names: set[str], family: frozenset[str]) -> bool:
    return bool(names & (family | {"BaseException"})) or names == {"<bare>"}


def _covers_every_refusal(names: set[str]) -> bool:
    return bool(
        names & {REFUSAL_ROOT, "BaseException", "<bare>"}
        or REFUSAL_FAMILIES <= names
    )


def _prior_handlers_intercept_refusal(
    handler: ast.ExceptHandler,
    parents: dict[ast.AST, ast.AST],
    aliases: dict[str, str],
) -> bool:
    """Whether earlier siblings already catch every refusal.

    Except handlers are ordered. Earlier handlers that between them name the
    root (or both families) make a later broad handler unreachable for any
    refusal. Each earlier handler is itself inspected under this law, so an
    earlier soft catch stays red on its own line. This is semantic catch
    precedence, not a path allowlist; removing or narrowing the earlier
    handler makes the later broad catch red again.
    """
    parent = parents.get(handler)
    if not isinstance(parent, (ast.Try, ast.TryStar)):
        return False
    try:
        index = parent.handlers.index(handler)
    except ValueError:
        return False
    covered: set[str] = set()
    for prior in parent.handlers[:index]:
        covered |= _handler_names(prior, aliases)
    return _covers_every_refusal(covered)


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
        "ExitSet.halted(",
        "append(",
        "resolved_value = None",
    )
    return any(tok in text for tok in soft_tokens) or not _pure_reraise(handler)


def _read_trees(
    package_root: Path,
) -> tuple[list[PanicCatchOffender], list[tuple[str, ast.AST]]]:
    """Parse every source under one scan root; read failures are auditor rows."""
    offenders: list[PanicCatchOffender] = []
    trees: list[tuple[str, ast.AST]] = []
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
        ], trees
    if not resolved_root.is_dir():
        return [
            PanicCatchOffender(
                package_root.as_posix(),
                0,
                "auditor-root-error",
                "scan root is not a directory",
            )
        ], trees
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
        ], trees
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
        trees.append((rel, tree))
    return offenders, trees


def _scan_tree(
    rel: str, tree: ast.AST, family: frozenset[str]
) -> list[PanicCatchOffender]:
    offenders: list[PanicCatchOffender] = []
    aliases = _refusal_aliases(tree, family)
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if not _catches_refusal(_handler_names(node, aliases), family):
            continue
        if _prior_handlers_intercept_refusal(node, parents, aliases):
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
                    "a catch of a refusal (LifterRefusal: ConstructionPanic, "
                    "SourceTreePanic / SugarNotWritten, or any subclass) outside "
                    "sanctioned membranes must not continue; only the named "
                    "per-file audit enumerators or production typed-gap "
                    "classification may hold it"
                ),
            )
        )
    # isinstance(exc, <refusal>) soft return
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
        if not any(_type_names(call.args[1], aliases) & family for call in calls):
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
                        "isinstance(exc, <refusal>) then soft return/None — "
                        "dig/report must not convert a refusal into opacity"
                    ),
                )
            )
    return offenders


def scan_package(
    package_root: Path, family: frozenset[str] | None = None
) -> list[PanicCatchOffender]:
    offenders, trees = _read_trees(package_root)
    if family is None:
        family = refusal_family(tree for _rel, tree in trees)
    for rel, tree in trees:
        offenders.extend(_scan_tree(rel, tree, family))
    return sorted(offenders)


def scan_repository(kit_root: Path) -> list[PanicCatchOffender]:
    roots = (
        ("src/sugar_lift_py_tests", kit_root / "src" / "sugar_lift_py_tests"),
        ("scripts", kit_root / "scripts"),
    )
    read = [(prefix, _read_trees(root)) for prefix, root in roots]
    # One family over both roots: a script that catches a subclass the package
    # defines is counted exactly like a catch of the subclass in the package.
    family = refusal_family(
        tree for _prefix, (_errors, trees) in read for _rel, tree in trees
    )
    offenders: list[PanicCatchOffender] = []
    for prefix, (root_errors, trees) in read:
        root_offenders = list(root_errors)
        for rel, tree in trees:
            root_offenders.extend(_scan_tree(rel, tree, family))
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
        "Lawful: only per-file corpus / gap-enumeration audit holds a refusal "
        "(LifterRefusal and every subclass) and emits a loud red row. "
        "Production may only pure re-raise.",
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
            "illegal refusal catches; "
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
