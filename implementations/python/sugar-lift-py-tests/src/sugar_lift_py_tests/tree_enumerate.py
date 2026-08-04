"""Enumeration served by the AST tree, not the factory.

The wire protocol's levels below `functions` — call_sites, assertions, facts —
were serviced by lifting the whole file through the factory and reading its IR
rows. Here they are serviced by walking the tree the parser produces and
asking each Assert node for its sugar and its desugared fact. The RPC drives
AST walking directly; the factory is not consulted.

For `assert <test>`: the assertion IS the Assert node; its fact is the InvValue
its sugar desugars to (formula on the wire via formula_to_value). A bare
assertion carries no call site — call_sites and assertions are the same locus,
1:1, exactly as the factory's protocol Section 4 already had them.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Optional

from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile
from sugar_source_tree.nodes import Assert, AsyncFunctionDef, FunctionDef


def source_file(
    full_path: Path,
    *,
    root: Path,
    construction_context=None,
) -> SourceFile:
    """The file's tree over workspace-relative oracle-pinned source.

    Enumeration levels that only walk syntax must not implicitly add a
    construction context: doing so changes which call occurrences are
    authenticated and can turn a completed function into a deeper native
    operation demand.  The functions entrance, which does construct, owns the
    separate ``open_source_file_for_construction`` call.
    """
    return SourceFile(
        workspace_path_source(str(full_path), root=str(root)),
        construction_context=construction_context,
    )


def functions_of(sf: SourceFile):
    return list(sf.functions())


def asserts_of(node) -> list:
    """Every Assert in a function body, in source order."""
    return [n for n in node.walk() if isinstance(n, Assert)]


def find_function(sf: SourceFile, name: Optional[str], span: Optional[dict]):
    for fn in sf.functions():
        if name is not None and fn.name != name:
            continue
        if span and not _span_matches(fn, span):
            continue
        return fn
    return None


class FunctionBindingMiss(Exception):
    """Named refusal: no unique authenticated function binding.

    Absence is a decision. Returning bare ``None`` made a miss
    indistinguishable from a soft skip; callers that need soft handling must
    catch this named throw explicitly.
    """

    def __init__(self, *, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason
        super().__init__(f"FunctionBindingMiss name={name!r} reason={reason}")


def find_function_by_name(sf: SourceFile, name: str):
    """Resolve the unique module-direct function binding for ``name``.

    Authority is ``module_direct_bindings`` (bind-time roster), never
    first-match-by-spelling over transitive ``functions()`` (class methods and
    nested defs share spellings). Miss or competing bindings THROW named —
    they are not soft ``None``.
    """
    bindings = (sf.unit.module_direct_bindings or {}).get(name, ())
    functions = [
        binding
        for binding in bindings
        if isinstance(binding, (FunctionDef, AsyncFunctionDef))
    ]
    if len(functions) == 1:
        return functions[0]
    if not functions:
        raise FunctionBindingMiss(name=name, reason="no module-direct function binding")
    raise FunctionBindingMiss(
        name=name,
        reason=f"{len(functions)} competing module-direct function bindings",
    )


def resolve_function_for_call(call):
    """Resolve the callee through binding/coordinate at an exact call site.

    Uses ``SourceUnit.source_function_definition_for_call`` — lexical rows and
    module-direct bindings, not spelling walks. THROW named on a miss.
    """
    from sugar_source_tree.nodes import Name

    unit = call.unit
    definition = unit.source_function_definition_for_call(call)
    if definition is not None:
        return definition
    name = call.func.id if isinstance(call.func, Name) else type(call.func).__name__
    raise FunctionBindingMiss(
        name=name,
        reason="no unique authenticated function binding at call site",
    )


def call_target_names(sf: SourceFile, span: Optional[dict]) -> list:
    """The callee names cued by the assertion at `span`: the func-name of every
    plain Call inside it. This is how a call-site cue resolves to the callee(s)
    whose universe it digs -- by NAME, directly, no bridge-matching heuristics
    (the tree kept the names the factory had to reconstruct)."""
    from sugar_source_tree.nodes import Call, Name

    _source, node = temporally_rewritten_assert(sf, span)
    if node is None:
        return []
    names = []
    for call in node.walk():
        if isinstance(call, Call) and isinstance(call.func, Name):
            if call.func.id not in names:
                names.append(call.func.id)
    return names


def find_assert(sf: SourceFile, span: Optional[dict]):
    for node in sf:
        if isinstance(node, Assert) and (span is None or _span_matches(node, span)):
            return node
    return None


def temporally_rewritten_assert(sf: SourceFile, span: Optional[dict]):
    """Return ``(source_assert, rewritten_assert)`` for an exact locus.

    An assertion is not a construction root.  Its meaning depends on every
    binding before it in the enclosing function (or module), so constructing
    its Sugar directly from the parser-backed tree is a temporal side door.
    Find the narrowest enclosing function, rewrite that scope as a block, and
    only then return the assertion on which callers may invoke ``sugar()``.

    The source node is returned separately because its fragment/memento is the
    durable address.  Shadow rewrites deliberately borrow that address, but
    keeping the two roles explicit prevents a future caller from mistaking
    source lookup for construction readiness.
    """
    source_assert = find_assert(sf, span)
    if source_assert is None:
        return None, None

    target = source_assert.line_col_span()

    def contains(node) -> bool:
        locus = node.line_col_span()
        return (
            locus.start_line <= target.start_line and locus.end_line >= target.end_line
        )

    owners = [fn for fn in sf.functions() if contains(fn)]
    if owners:
        # Nested functions are also yielded by SourceFile.functions(); temporal
        # ownership belongs to the narrowest one, never its enclosing function.
        owner = min(
            owners,
            key=lambda fn: (
                fn.line_col_span().end_line - fn.line_col_span().start_line,
                fn.line_col_span().end_col - fn.line_col_span().start_col,
            ),
        )
        rewritten_owner = owner.substitute({})
    else:
        # Module assertions are temporally owned by the module block.
        rewritten_owner = sf.root.substitute({})

    for node in rewritten_owner.walk():
        if isinstance(node, Assert) and _span_matches(node, span or {}):
            return source_assert, node
    return source_assert, None


def _span_matches(node, span: dict) -> bool:
    lc = node.line_col_span()
    return lc.start_line == span.get("start_line") and lc.start_col == span.get(
        "start_col"
    )


def assert_memento(node, file_rel: str) -> dict:
    """The Assert's own self-locating memento: file + its span + CID."""
    lc = node.line_col_span()
    sealed = node.fragment.seal()
    return {
        "kind": "source-memento",
        "file": file_rel,
        "function_name": "",
        "source_function_name": "",
        "span": {
            "start_line": lc.start_line,
            "start_col": lc.start_col,
            "end_line": lc.end_line,
            "end_col": lc.end_col,
        },
        "source_cid": sealed.cid,
    }


def fact_of(node) -> Optional[Any]:
    """Desugar the assertion; its InvValue's formula is the fact, on the wire.

    ``node`` must be the result of ``temporally_rewritten_assert``, never the
    parser-backed lookup node.  None when the assertion emits no fact (e.g.
    inert support). No factory and no ambient context: the enclosing tree has
    already expressed the temporal state.
    """
    import json

    from sugar_lift_py_tests.canonicalizer import encode_jcs
    from sugar_lift_py_tests.ir import formula_to_value

    outcome = node.sugar().desugar(None)
    inv = getattr(outcome, "value", None)
    formula = getattr(inv, "formula", None)
    if formula is None:
        return None
    # Same shape the factory's facts payload carried (ir.py `item["inv"]`):
    # the formula's JCS Value tree, flattened to a plain JSON dict.
    return json.loads(encode_jcs(formula_to_value(formula)))


# --- The recovered-construction frontier, re-homed onto the tree ------------
#
# The factory's corpus-wide R census is gone. Its replacement is here: walk the
# file with a CollectingReporter and ask every node for its sugar. A node whose
# OWN sugar() reaches the abstract base throw (SugarNotWritten) reports itself
# through the reporter before the throw fires; that report IS a frontier row.
# Coverage is the class hierarchy, so R = the count of nodes that self-reported.
#
# The frontier is served at MODULE granularity: one demanded body per file
# (function_name "<module>", whole-file span), whose audit leaf walks the entire
# file. One body per file means the census consistency (bodies == files) holds
# trivially and no gap is counted twice across a function/module split.


def audit_file_gaps(full_path: Path, *, root: Path):
    """The file's frontier: ONE construction per top-level statement; the
    reporter witnesses every gap underneath it as it is built.

    Construction is correctness -- there is no other path, so there is nothing
    to re-ask. Each top-level statement's sugar() is called once; a gap anywhere
    in its subtree self-reports through the reporter DURING that construction.
    Linear in the file, never quadratic: asking every node separately would
    re-construct every subtree once per ancestor -- a second computation, the
    side door this replaces. Only ``SugarNotWritten`` is caught: a
    VocabularyMissing/BackendDefect is a different, louder failure and is left
    to propagate, never swallowed into the census.

    Returns ``(sf, [(node, panic), ...])`` deduped by SOURCE identity (kind +
    span): the tree materializes nodes fresh per access, so the same source gap
    reached twice is still one gap.
    """
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.reporter import CollectingReporter

    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    reporter = CollectingReporter()
    # Construction needs its context: the bare door builds a tree with none,
    # and a context-less tree paints every With RuntimeSelectedContextManager
    # regardless of resolvability. See scripts/construction_context_door_law.py.
    sf = open_source_file_for_construction(full_path, root=root, reporter=reporter)
    for stmt in sf.root.body:
        try:
            stmt.sugar()
        except SugarNotWritten:
            pass  # reported through the channel already; keep counting
    seen: dict[tuple, Any] = {}
    for node, panic in reporter.gaps:
        lc = node.line_col_span()
        key = (node.kind, lc.start_line, lc.start_col, lc.end_line, lc.end_col)
        seen[key] = (node, panic)
    return sf, list(seen.values())


def function_def_memento(fn, file_rel: str):
    """The function's own SourceMemento (the def warrant payload_rows needs)."""
    from sugar_lift_py_tests.kit_rpc.source_memento_dto import SourceMementoDto
    from sugar_lift_py_tests.kit_rpc.source_span_dto import SourceSpanDto

    lc = fn.line_col_span()
    return SourceMementoDto(
        file=file_rel,
        span=SourceSpanDto(lc.start_line, lc.start_col, lc.end_line, lc.end_col),
        source_cid=fn.fragment.seal().cid,
        source_function_name=fn.name,
        param_names=[p.name for p in fn.params],
    )


def function_universe_outcome(fn):
    """Construct one function universe through its authenticated entrance.

    Ordinary functions reduce with symbolic formals.  The active ``__init__``
    of a source class is different: its first parameter is the receiver that
    the class constructor itself creates.  The backend's exact lexical-owner
    relation selects that existing class door, and this seam seats the same
    receiver coordinate before reducing the universe.  No spelling or inferred
    parent walk is used.
    """
    sugar = fn.sugar()
    owner = fn._active_initializer_owner()
    if owner is None:
        return sugar.desugar(None)

    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.floor import ClassDefinitionValue
    from sugar_lift_py_tests.outcome import Complete
    from sugar_source_tree.panic import SugarNotWritten

    if not fn.params:
        raise SugarNotWritten(
            owner="function_universe_outcome",
            blame=fn.fragment,
            observed="class initializer has no receiver parameter",
            requested="the active initializer receiver coordinate",
            fix="preserve the parsed receiver parameter on __init__",
        )
    receiver_coordinate = fn._constructed_receiver_coordinate(owner, fn.params[0])
    definition_outcome = owner.sugar().desugar(None)
    if not isinstance(definition_outcome, Complete) or not isinstance(
        definition_outcome.value, ClassDefinitionValue
    ):
        raise SugarNotWritten(
            owner="function_universe_outcome",
            blame=owner.fragment,
            observed=type(definition_outcome).__name__,
            requested="the authenticated source class definition",
            fix="construct the initializer through its lexical class owner",
        )
    receiver = definition_outcome.value.construct_receiver_state_from_block(
        None, receiver_coordinate.cid
    )
    root = ReduceContext.root(owner="function_universe_outcome")
    context = root.with_temporal(
        root.temporal.bind_value(
            receiver_coordinate.cid,
            receiver,
            blame=fn.fragment,
        )
    )
    return sugar.desugar(context)


@functools.lru_cache(maxsize=128)
def _source_sidecars_by_line(source_cid: str, source: str, file_rel: str) -> tuple[
    tuple[dict[str, Any], ...],
    tuple[tuple[int, tuple[dict[str, Any], ...]], ...],
]:
    """Construct source testimony once through its authoritative door."""
    del source_cid  # cache identity; source remains the construction input
    from sugar_lift_python_source import lift_source

    rows = lift_source(source, file_rel).ir
    class_shapes = tuple(
        shape
        for row in rows
        for shape in row.get("classShapes", [])
        if isinstance(shape, dict)
    )
    by_line = []
    for row in rows:
        locus = row.get("locus")
        line = locus.get("line") if isinstance(locus, dict) else None
        if not isinstance(line, int):
            continue
        panic_loci = tuple(
            item for item in row.get("panicLoci", []) if isinstance(item, dict)
        )
        if panic_loci:
            by_line.append((line, panic_loci))
    return class_shapes, tuple(by_line)


def _source_sidecars_for_function(fn, file_rel: str):
    class_shapes, by_line = _source_sidecars_by_line(
        fn.unit.source_cid, fn.unit.source, file_rel
    )
    line = fn.line_col_span().start_line
    panic_loci = tuple(
        locus
        for row_line, row_loci in by_line
        if row_line == line
        for locus in row_loci
    )
    receiver_classes = {
        safety.get("receiverClass")
        for locus in panic_loci
        if isinstance((safety := locus.get("attributeSafety")), dict)
        and isinstance(safety.get("receiverClass"), str)
    }
    relevant_shapes = tuple(
        shape for shape in class_shapes if shape.get("className") in receiver_classes
    )
    return panic_loci, relevant_shapes


def _source_sidecar_carrier(fn, def_memento, panic_loci, class_shapes):
    """Carry source testimony without claiming an incomplete body reduced."""
    from sugar_lift_py_tests.floor.universe_mint_projection import claim_formula
    from sugar_lift_py_tests.ir import atomic
    from sugar_lift_py_tests.kit_rpc import BodyUniverseDto
    from sugar_lift_py_tests.proofir.nodes import ConstructionSite, Derived, Provenance

    span = def_memento.span
    provenance = Provenance(
        node_class="SourceSidecarCarrier",
        construction_site=ConstructionSite(
            path=def_memento.file,
            line=span.start_line,
            column=span.start_col,
        ),
        warrant=Derived(floor_chain=("sugar_lift_python_source.lift_source",)),
    )
    return BodyUniverseDto(
        name=fn.name,
        pre=claim_formula(
            atomic("true", []),
            formals=(),
            provenance=provenance,
            role="pre",
        ),
        source_warrants=[def_memento],
        proofir_provenance=provenance.to_rpc(),
        kind="contract",
        panic_loci=list(panic_loci),
        class_shapes=list(class_shapes),
    )


def function_contract_rows(fn, file_rel: str):
    """A function's contract DTO rows, produced from its TREE universe.

    `fn.sugar()` constructs the FunctionUniverseSugar; desugar reduces the body.
    Complete -> the UniverseValue projects its own DTO rows (one function-
    contract carrying the post, one contract per stated inv) via payload_rows --
    the exact rows the factory used to emit. Incomplete -> the def is an effect
    (a halt), returned as (def_memento, None) so the caller emits an effect, not
    a contract. A SugarNotWritten from an unported body statement propagates
    (the whole function is a frontier gap).
    """
    import dataclasses

    from sugar_lift_py_tests.outcome import Complete

    def_memento = function_def_memento(fn, file_rel)
    panic_loci, class_shapes = _source_sidecars_for_function(fn, file_rel)
    outcome = function_universe_outcome(fn)
    if not isinstance(outcome, Complete):
        if not panic_loci and not class_shapes:
            return def_memento, None  # an effect with no source testimony
        return def_memento, [
            _source_sidecar_carrier(fn, def_memento, panic_loci, class_shapes)
        ]
    rows = outcome.value.payload_rows(def_memento)
    rows[0] = dataclasses.replace(
        rows[0],
        panic_loci=list(panic_loci),
        class_shapes=list(class_shapes),
    )
    return def_memento, rows


def call_nodes_in_assert(sf: SourceFile, span: Optional[dict]) -> list:
    """The plain named Call nodes inside the assertion at `span`, in walk order.
    The cue's own AST: each carries the callee name AND the actual argument
    nodes -- the pre this call fills."""
    from sugar_source_tree.nodes import Call, Name

    _source, node = temporally_rewritten_assert(sf, span)
    if node is None:
        return []
    return [
        call
        for call in node.walk()
        if isinstance(call, Call) and isinstance(call.func, Name)
    ]


def _args_are_ground(call) -> bool:
    """True when every argument fills its pre with no remaining hole: no free
    Name inside any arg. A hole-bearing arg leaves the callee's contract
    curried (the abstract contract IS the callable floor); a ground arg set is
    a fill, and the dig applies it."""
    for arg in call.args:
        for n in arg.walk():
            if n.kind == "Name":
                return False
    return True


def applied_contract_rows(fn, arg_nodes: tuple, file_rel: str, keywords: tuple = ()):
    """The callee's contract AS APPLIED at a call: a call IS substitution.

    Binding goes through ``SourceCallFrame.bind_node_actuals`` — the same door
    that packs positional, keyword, default, positional-only, keyword-only, and
    variadic formals. An ad-hoc flat param/actual zip binder is forbidden:
    ``def f(a, *rest)`` called ``f(1, 2)`` must bind ``rest=(2,)``, not
    ``rest=2``.

    Construction uses the bound frame's already-sugared body and the frame's
    formal coordinates — not a second bare ``FunctionUniverseSugar`` mint that
    drifts from ``FunctionDef.sugar()``. Incomplete -> (memento, None), an
    effect, as the abstract path. Binding gaps propagate as
    ``SourceCallBindingGap``.
    """
    from sugar_lift_py_tests.floor.universe_value import UniverseValue
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_body

    def_memento = function_def_memento(fn, file_rel)
    frame = fn.source_visible_call_frame()
    # SourceCallBindingGap propagates loud — no soft gap swallow.
    bound = frame.bind_node_actuals(tuple(arg_nodes), tuple(keywords))
    # Statement sugars and formal coordinates come from the construction door
    # (frame bind + FunctionDef body sugars). Project the universe floor
    # without a second incomplete FunctionUniverseSugar producer.
    outcome = reduce_body(bound.body.statements).and_then(
        lambda record: Complete(
            UniverseValue(
                name=fn.name,
                formals=bound.parameters,
                record=record,
                formal_coordinates=bound.formal_coordinates,
            )
        )
    )
    if not isinstance(outcome, Complete):
        return def_memento, None
    return def_memento, outcome.value.payload_rows(def_memento)


def module_definition_memento(sf: SourceFile, file_rel: str, file_cid: str) -> dict:
    """The whole-file body the audit frontier demands one leaf for."""
    lc = sf.root.line_col_span()
    sealed = sf.fragment.seal()
    return {
        "kind": "source-memento",
        "file": file_rel,
        "function_name": "<module>",
        "source_function_name": "<module>",
        "span": {
            "start_line": lc.start_line,
            "start_col": lc.start_col,
            "end_line": lc.end_line,
            "end_col": lc.end_col,
        },
        "source_cid": sealed.cid,
        "file_cid": file_cid,
        "template_cid": None,
        "param_names": [],
    }


def _gap_locus(node, file_rel: str) -> tuple[str, str]:
    """(position locus, terminal gap locus) for a gap node.

    The terminal locus carries the full span AND the node kind so two distinct
    nodes never collide — the fold rejects duplicate owner identities loudly,
    and (demandedBody, demandedSource, terminalGapLocus) must be unique.
    """
    lc = node.line_col_span()
    pos = f"{file_rel}:{lc.start_line}:{lc.start_col}"
    terminal = (
        f"{file_rel}:{lc.start_line}:{lc.start_col}-"
        f"{lc.end_line}:{lc.end_col}[{node.kind}]"
    )
    return pos, terminal


def _roll_call_identity(entry) -> tuple:
    """The SAME identity ``MinorityReport`` uses for present/minority.

    Equal source text seals to one CID at distinct loci; those seats are
    distinct obligations. Never key presence by CID alone.
    """
    return (entry.file, entry.start_line, entry.start_col, entry.kind, entry.cid)


def assert_source_audit_ledger(
    *,
    warranted: int,
    unresolved: int,
    source_loci: int,
    report_R: int,
) -> None:
    """Panic tooth for source-audit ledger conservation.

    The historical dual-producer drift (SIN CLUSTER 7 / lift_rpc path) was:
    status keyed by CID alone (inflating warranted) while ``source_unresolved``
    was taken from ``report.R`` (still counting the absent shared-CID seat).
    Then ``warranted + report.R > source_loci`` and Yellow silently became Blue.

    The tooth that sings is therefore:

        warranted + report_R == source_loci
        AND unresolved == report_R

    A status-only sum ``warranted + unresolved == source_loci`` is NOT a tooth:
    when every locus is assigned exactly one of {warranted, unresolved}, that
    equality is tautological and stays green under the illegal CID-alone map.
    That decorative shell was deleted; this function is the live replacement.

    Retirement path: if presence status becomes unconstructable except via
    full-tuple identity (typed present set / closed seat key), this assert
    remains as contact panic for ledger arithmetic only, or retires if the
    wire totals become derived fields of a single typed partition value.
    """
    if warranted + report_R != source_loci:
        raise AssertionError(
            f"source-audit conservation broken: warranted({warranted}) + "
            f"report.R({report_R}) != source_loci({source_loci}); "
            "CID-alone presence inflates warranted while R still counts the "
            "absent seat — key presence by (file, line, col, kind, cid)"
        )
    if unresolved != report_R:
        raise AssertionError(
            f"source-audit unresolved({unresolved}) != report.R({report_R}); "
            "presence must use the full roll-call identity, not CID alone"
        )


def source_audit_from_report(report, file_rel: str) -> dict:
    """ONE door: project a ``MinorityReport`` onto the source-audit wire.

    Presence is keyed by the full roll-call identity
    ``(file, line, col, kind, cid)`` — the same tuple ``MinorityReport`` uses.
    Status and the three ledger totals are derived once from that partition.
    There is no second producer of ``source_unresolved`` (no independent
    ``report.R`` path, no CID-only set kept "in sync").

    Conservation is a tooth, not a print: ``warranted + report.R == source_loci``
    (and ``unresolved == report.R``). See ``assert_source_audit_ledger``.
    """
    present_keys = {_roll_call_identity(entry) for entry in report.present}
    loci = []
    for entry in report.roster:
        status = (
            "warranted" if _roll_call_identity(entry) in present_keys else "unresolved"
        )
        loci.append(
            {
                "status": status,
                "kind": entry.kind,
                "name": entry.name,
                "source_cid": entry.cid,
                "locus": {
                    "file": file_rel,
                    "line": entry.start_line,
                    "col": entry.start_col,
                },
            }
        )
    warranted = sum(1 for locus in loci if locus["status"] == "warranted")
    unresolved = sum(1 for locus in loci if locus["status"] == "unresolved")
    source_loci = len(loci)
    assert_source_audit_ledger(
        warranted=warranted,
        unresolved=unresolved,
        source_loci=source_loci,
        report_R=report.R,
    )
    return {
        "role": file_rel,
        "loci": loci,
        "totals": {
            "source_loci": source_loci,
            "source_warranted": warranted,
            "source_unresolved": unresolved,
        },
    }


def source_audit_from_roll_call(full_path: Path, file_rel: str) -> dict:
    """The report feed the Rust CLI renders, straight from the reporter's roll
    call. Construction registers every node; the discharge answers present
    (desugared -> Blue) or absent (the minority -> Yellow). Each roster entry
    becomes one source-audit locus keyed by its status; the CLI reads the source
    text for each locus from its span.

    ``warranted`` = present (accounted, Blue); ``unresolved`` = the minority
    (absent, Yellow). ``source_loci`` / ``source_warranted`` / ``source_unresolved``
    are the ledger counts the report summary measures.
    """
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.roll_call import discharge

    reporter = CollectingReporter()
    sf = SourceFile.from_path(str(full_path), reporter=reporter)
    report = discharge(sf)
    return source_audit_from_report(report, file_rel)


def source_audit_membership_from_registration(full_path: Path, file_rel: str) -> dict:
    """Roll-call **membership** only: materialize + register, no sugar discharge.

    Used by R_silent, which keys on whether a disk locus is in
    ``warranted ∪ unresolved``. Both statuses are roster members; discharge
    only splits Blue/Yellow and does not change membership of
    ``(file, line, col, kind)`` for nodes already registered at materialize.

    Full discharge remains :func:`source_audit_from_roll_call` for report feeds
    that need present-vs-minority. Silent twin tests assert identical
    ``silent_offenders`` under both doors.
    """
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.roll_call import minority_report

    reporter = CollectingReporter()
    sf = SourceFile.from_path(str(full_path), reporter=reporter)
    report = minority_report(sf)
    return source_audit_from_report(report, file_rel)


def _root_of(full_path: Path, file_rel: str) -> Path:
    """The root ``file_rel`` is stated against -- the locus's own denominator."""
    resolved = Path(full_path).resolve()
    relative = Path(file_rel)
    root = resolved
    for _ in relative.parts:
        root = root.parent
    return root


def frontier_leaf_rpc(full_path: Path, file_rel: str) -> dict:
    """The recovered-construction audit leaf for one file, tree-walked.

    Emits the closed ``RecoveredAuditDto`` wire shape (status ``failed`` when
    the file has any unwritten-sugar gap, ``clean`` when it is fully sugared).
    ``demandedSource`` is the file's own content CID: stable per file, so gap
    uniqueness rides on each gap's terminal locus. It ALSO carries the
    ``sourceAudit`` -- the reporter's roll-call partition the Rust CLI renders
    (present Blue / absent Yellow), everything the report needs on the CLI side.
    """
    from sugar_lift_py_tests.kit_rpc.recovered_audit_dto import (
        AuditLeafEnvelopeDto,
        RecoveredAuditDto,
        RecoveredConstructionPanicDto,
    )

    # The workspace root is what `file_rel` is stated against, by definition.
    root = _root_of(full_path, file_rel)
    sf, gaps = audit_file_gaps(full_path, root=root)
    demanded_source = f"module:{sf.unit.source_cid}"
    panics = []
    for node, panic in gaps:
        pos, terminal = _gap_locus(node, file_rel)
        reason = panic.observed or str(panic)
        panics.append(
            RecoveredConstructionPanicDto(
                locus=pos,
                demanded_source=demanded_source,
                terminal_gap_locus=terminal,
                reason=reason,
                gap={"blame": terminal, "kind": node.kind, "reason": reason},
            )
        )
    return AuditLeafEnvelopeDto.from_rpc(
        {
            "semanticCore": RecoveredAuditDto(panics=panics).to_rpc(),
            "auxiliaryRows": {
                "sourceAudit": source_audit_from_roll_call(full_path, file_rel)
            },
        }
    ).to_rpc()
