#!/usr/bin/env python3
"""THE authoritative Python corpus scoreboard.

This script is the sole authority for the Python corpus board. Every other
census in this kit is a developer probe or a single-capability instrument, and
none of their numbers may be quoted as the board. That rule exists because they
were quoted as the board: an AST-shape site census read ``With 4125/811/85``
while the construction ledger for the same period read ``assertion 3 /
resource 104 / other 4``. Both were correct. They were counting different
things, against different denominators, and the difference was read as motion.

So this instrument states its denominator before it states any number:

* **the corpus pin** — distribution, version, per-file content hashes and one
  aggregate hash (:mod:`sugar_lift_py_tests.corpus_pin`). Two boards are
  comparable iff their aggregate hashes are equal. The 1,415-file ledger was a
  different pandas: it is archived, not compared.
* **the enrolled file identities**, and which of them produced a terminal row.
  Missing, duplicate and malformed rows are named individually, and any of them
  makes the run red. A partial denominator is never banked as a board.
* **the corpus root**, which is what the demand table is derived from, stated
  separately from whatever slice this invocation measured. A bounded run
  inherits the full run's root or it does not run.
* **the source stamp** — commit, host, platform, load, wall clock.

**The two quantities, never conflated:**

``astSitePrevalence``
    How many AST sites of a shape exist. A denominator. **Never R.** Lifting a
    capability does not change it — the ``with`` statements are still there.
``R_construction`` / ``R_desugar``
    How many authenticated occurrences failed to construct or desugar. A
    capability succeeded only when one of these falls without another axis
    rising.

One process. Two named axes (never merged into one R):

    SourceTree(corpus).paths()
      → provisional_contract_refs_from_demands(corpus)  (once)
      → open_source_file_for_construction (context + source-derived CM refs)
      → functions()
      → fn.sugar()                    # axis 1: construction families
      → sugar.desugar(None)           # axis 2: desugar refusals + typed red

Construction R answers "is the tree total?". Desugar R answers "is meaning
reducible?". Yield/YieldFrom construct then refuse at desugar — correct; they
must stay on the board under axis 2 (see #6243).

Occurrence identity: one gap = (kind, file, line, col). Construction families
are tallied only from ``reporter.gaps`` (catch+reporter type double-count is
presentation duplication — e.g. mid-band With CM residual ≈213 sites, not
~2×). Demand/resolution ``BackendDefect``s are a separate hygiene axis
(``R_backend_defects``), never merged into construction R.

Behind the desugar door the membrane (sugar_lift_py_tests.desugar_axis) keeps
three quantities apart: ``R_desugar`` (typed refusals + typed red effects, keyed
by authenticated effect occurrence), ``desugarConstructionPanics``
(construction-law None arms — ``ConstructionPanic`` is a ``BaseException``,
caught BY NAME) and ``desugarDefects`` (ordinary exceptions and named audit /
instrument gaps). The last two are red and are never semantic R.

No subprocess. No process pool. Construction context is required: bare
``fn.sugar()`` with ``construction_context is None`` paints every With as
``RuntimeSelectedContextManager`` regardless of resolvability (instrument
defect). The real lift pipeline injects the same door via lift_rpc.

I/O split (never mixed):
  --engine-log   sugar engine JSONL (WARNING heartbeats by default)
  --engine-trace opt-in full per-span DEBUG enter/exit flood
  --progress     tqdm bar only
  --json         final result summary
  --checkpoint-jsonl  per-file durable journal

Engine log default is SUGAR_ENGINE_TRACE_EVENTS=0: WARNING heartbeats,
cycle_suspected, and errors only — enough to name a stall. Per-span DEBUG
enter/exit is write-only for this board (R comes from construction/desugar
axes, not engine.jsonl) and costs json.dumps+FileHandler on every sugar
enter/exit on the reduction hot path. Pass --engine-trace only when
debugging a named stall needs the full stack flood.
"""

from __future__ import annotations

# The sole authoritative Python corpus scoreboard. Enforced by
# tests/test_one_authoritative_scoreboard.py: exactly one module may say True.
SCOREBOARD_AUTHORITY = True

_PANDAS_3_0_3_AGGREGATE_HASH = (
    "bbb70a76f4032eda3362102c8bd872ca769b6f8143a91f60a36374fa1066b76c"
)
_PANDAS_3_0_3_MANIFEST_SHAPE_CID = (
    "sha256:a223a4499d0909f22190748b4aca9144e35a58fec31e84cb924e2c25fd3c03d0"
)

import argparse
import json
import logging
import os
import platform
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, TextIO

# CI-visible narration: default print buffering makes a live process look dead.
# Every RECENSUS line uses flush=True; prefer PYTHONUNBUFFERED=1 in the workflow.
_PROGRESS_EVERY_N = max(1, int(os.environ.get("RECENSUS_PROGRESS_EVERY_N", "1")))
# Doctrine: never more than 30s of job-log silence on a long path.
_JOB_LOG_MAX_SILENCE_S = float(os.environ.get("JOB_LOG_MAX_SILENCE_S", "30"))

_TOOLS = Path(__file__).resolve().parents[4] / "tools"
if _TOOLS.is_dir() and str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))


def _narrate(msg: str) -> None:
    """Unbuffered stdout so CI / SSH can see the scoreboard is alive."""
    print(msg, flush=True)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:  # noqa: BLE001 — never fail the board for a flush
        pass


def _phase_begin(name: str) -> float:
    _narrate(f"RECENSUS PHASE BEGIN: {name}")
    return time.perf_counter()


def _phase_end(name: str, t0: float) -> None:
    _narrate(
        f"RECENSUS PHASE END: {name} elapsed_s={time.perf_counter() - t0:.3f}"
    )


def _phase_call(name: str, fn):
    """Run a long sub-phase with ≤30s job-log silence (alive lines if blocked)."""
    from job_log_heartbeat import JobLogHeartbeat

    t0 = _phase_begin(name)
    beat = JobLogHeartbeat(f"recensus-{name}", max_silence_s=_JOB_LOG_MAX_SILENCE_S)
    beat.watch()
    try:
        result = fn()
        beat.stop(status="ok")
        _phase_end(name, t0)
        return result
    except BaseException:
        beat.stop(status="failed")
        _phase_end(name, t0)
        raise


def _git_commit(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


def _authenticate_declared_pandas_corpus(observed_pin, manifest_shape_cid: str) -> None:
    """Refuse a corpus before source selection on either named pin axis.

    The aggregate covers distribution, version, relative paths, file bytes and
    sizes.  The shape CID covers only relative path names; it is retained as a
    separately named diagnostic, never presented as content authentication.
    """
    failures: list[str] = []
    if observed_pin.aggregate_hash != _PANDAS_3_0_3_AGGREGATE_HASH:
        failures.append(
            "corpus aggregate hash mismatch: "
            f"observed {observed_pin.aggregate_hash}; "
            f"required {_PANDAS_3_0_3_AGGREGATE_HASH}"
        )
    if manifest_shape_cid != _PANDAS_3_0_3_MANIFEST_SHAPE_CID:
        failures.append(
            "corpus manifest shape CID mismatch: "
            f"observed {manifest_shape_cid}; "
            f"required {_PANDAS_3_0_3_MANIFEST_SHAPE_CID}"
        )
    if failures:
        raise ValueError("; ".join(failures))


def _silence_console_logging() -> None:
    """Keep library noise off the progress stream.

    Sugar engine ERROR events otherwise hit logging's lastResort handler on
    stderr and pollute tqdm. Root/other loggers stay quiet too unless the
    caller attached an explicit handler.
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(logging.NullHandler())
    root.setLevel(logging.CRITICAL)
    # lastResort still fires for WARNING+ with no handlers on a logger that
    # propagates to a root with only NullHandler? Actually lastResort is used
    # when lastResort is not None and the record is not handled. With
    # NullHandler, records are "handled". Good.
    logging.lastResort = None  # type: ignore[assignment]


class _EngineStdoutHeartbeat(logging.Handler):
    """Mirror engine log activity to the job log without TTY gating.

    Full JSONL stays on disk (SUGAR_ENGINE_LOG). CI needs a live heartbeat so a
    long lift is not a silent 95% CPU wedge. Rate-limited to avoid flooding.
    """

    def __init__(self, *, min_interval_s: float = 2.0) -> None:
        super().__init__()
        self._min_interval_s = min_interval_s
        self._last_emit = 0.0
        self._suppressed = 0

    def emit(self, record: logging.LogRecord) -> None:
        now = time.monotonic()
        if now - self._last_emit < self._min_interval_s:
            self._suppressed += 1
            return
        self._last_emit = now
        try:
            msg = self.format(record)
            extra = (
                f" suppressed={self._suppressed}" if self._suppressed else ""
            )
            self._suppressed = 0
            print(
                f"RECENSUS ENGINE heartbeat{extra} {msg[:240]}",
                flush=True,
            )
        except Exception:  # noqa: BLE001
            self.handleError(record)


def _configure_engine_log(path: Path, *, engine_trace: bool = False) -> None:
    """Engine JSONL on disk + rate-limited stdout heartbeat for CI job logs.

    Default is WARNING-only (``SUGAR_ENGINE_TRACE_EVENTS=0``): heartbeats,
    cycle_suspected, and errors — enough to name a stall. Per-span DEBUG
    enter/exit is opt-in via ``engine_trace=True`` / ``--engine-trace``; the
    scoreboard path does not read those events for R, and they cost
    ``json.dumps(sort_keys=...)`` plus a FileHandler write on every sugar
    enter/exit on the reduction hot path (~1 MB/file, write-only).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Prefer the kit's own sink; also pin env so late imports see it.
    os.environ["SUGAR_ENGINE_LOG"] = str(path.resolve())
    # Force the scoreboard default: do not inherit ambient TRACE=1 from a
    # parent shell. Full span flood is explicit --engine-trace only.
    os.environ["SUGAR_ENGINE_TRACE_EVENTS"] = "1" if engine_trace else "0"
    from sugar_lift_py_tests import engine_log

    # Drop any prior live handler (e.g. wrong path from env at import time).
    logger = engine_log.LOGGER
    logger.handlers.clear()
    logger.propagate = False
    engine_log._LIVE_HANDLER = None  # type: ignore[attr-defined]
    engine_log.configure_live_log(str(path.resolve()))
    logger.propagate = False
    # configure_live_log already set logger level from TRACE. Do not re-raise
    # to DEBUG here — that re-enables hot-path json.dumps even when the file
    # handler filters at WARNING.
    logger.setLevel(logging.DEBUG if engine_trace else logging.WARNING)
    # SCOREBOARD_AUTHORITY: never leave engine heartbeats file-only in CI.
    # WARNING floor: job log names stalls; never mirror per-span DEBUG flood.
    heartbeat = _EngineStdoutHeartbeat(min_interval_s=2.0)
    heartbeat.setLevel(logging.WARNING)
    heartbeat.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(heartbeat)


def _occurrence_key(
    kind: str,
    relative: str,
    *,
    node: object | None = None,
    line: object = "?",
    col: object = -1,
) -> tuple[str, str, object, object]:
    """One gap/effect occurrence = (kind, file, line, col). Never double-tally."""
    if node is not None:
        try:
            lc = node.line_col_span()  # type: ignore[attr-defined]
            return (kind, relative, lc.start_line, lc.start_col)
        except Exception:  # noqa: BLE001 -- fall back to hints
            pass
    return (kind, relative, line, col)


def _cm_resolution_bucket(resolution) -> str:
    """Partition With residual by its AUTHENTICATED resolution kind — structural.

    This used to bucket by spelling: a hard-coded table of leaf names
    (``raises``, ``ensure_clean``, ``option_context``, …) sorted rows into
    "assertion-membrane" and "protocol-resource-candidate". That is a vendor
    name table. It grants a semantic category from how pandas happened to spell
    a function, so the board moved when pandas renamed something and stayed
    still when a new project used the same shape under a different name.

    The structural fact is already on the row: ``kind`` is the authenticated
    resolution gap kind that prereq-2 produced. Bucket on that. It is a closed
    vocabulary (:class:`WithConstructionGapKind`), it survives renames, and it
    names what is actually blocking construction rather than who wrote it.

    The assertion-vs-resource split this replaced is a real distinction, but it
    needs a structural discriminator (does the manager's contract swallow the
    exception?) rather than a name list. Until such a discriminator exists,
    this instrument reports the resolution kinds and does not invent the split.
    """
    from sugar_source_tree.panic import WithConstructionGapKind

    kind = getattr(resolution, "kind", None)
    if not isinstance(kind, str) or not kind:
        raise ValueError("With resolution gap has no typed kind")
    # Normalize through the closed vocabulary. Unknown wire kinds belong to
    # the vocabulary's explicit sentinel; they never mint an escape bucket.
    parsed = WithConstructionGapKind.parse(kind)
    return f"gap:{parsed.value}"


def _tally_cm_resolutions(
    context,
) -> tuple[Counter[str], Counter[str]]:
    """Count derived-table rows by structural resolution kind."""
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
        SourceDerivedContextManagerRefV1,
    )
    from sugar_source_tree.panic import WithConstructionGapKind

    buckets: Counter[str] = Counter()
    unrecognized_kinds: Counter[str] = Counter()
    refs = getattr(context, "source_derived_contract_refs", None) or {}
    for resolution in refs.values():
        if isinstance(resolution, SourceDerivedContextManagerRefV1):
            buckets["derived-contract"] += 1
            continue
        if isinstance(resolution, ContextManagerResolutionGapV1):
            bucket = _cm_resolution_bucket(resolution)
            buckets[bucket] += 1
            if bucket == (
                f"gap:{WithConstructionGapKind.UNRECOGNIZED_RESOLUTION_KIND.value}"
            ):
                unrecognized_kinds[str(resolution.kind)] += 1
            continue
        raise TypeError(
            "With resolution table contains a value outside the closed "
            f"derived-contract | ContextManagerResolutionGapV1 union: "
            f"{type(resolution).__name__}"
        )
    return buckets, unrecognized_kinds


def _with_census_partition(
    cm_resolutions: Counter[str],
    ast_sites: Counter[str],
    unrecognized_kinds: Counter[str] | None = None,
) -> dict[str, Any]:
    """Conserve every synchronous With item into constructed or one typed gap."""
    from sugar_source_tree.panic import WithConstructionGapKind

    vocabulary = tuple(member.value for member in WithConstructionGapKind)
    # ENTER_MAY_HALT / EXIT_MAY_HALT are source-derived resource lifecycle
    # gaps, added with the generator-backed resource contract. Keep the exact
    # cardinality tooth current; do not replace it with an open-ended bucket.
    if len(vocabulary) != 41:
        raise ValueError(
            "WithConstructionGapKind vocabulary changed: "
            f"expected 41 members, found {len(vocabulary)}"
        )
    allowed = {"derived-contract", *(f"gap:{kind}" for kind in vocabulary)}
    unexpected = sorted(set(cm_resolutions) - allowed)
    if unexpected:
        raise ValueError(
            "With census contains keys outside its closed vocabulary: "
            + ", ".join(unexpected)
        )

    typed_gaps = {
        kind: int(cm_resolutions.get(f"gap:{kind}", 0)) for kind in vocabulary
    }
    unrecognized_kinds = unrecognized_kinds or Counter()
    unrecognized_total = typed_gaps[
        WithConstructionGapKind.UNRECOGNIZED_RESOLUTION_KIND.value
    ]
    if sum(unrecognized_kinds.values()) != unrecognized_total:
        raise ValueError(
            "With census sentinel lacks preserved resolution kinds: "
            f"sentinel={unrecognized_total} "
            f"preserved={sum(unrecognized_kinds.values())}"
        )
    total = int(ast_sites.get("site:with-item", 0))
    constructed = int(cm_resolutions.get("derived-contract", 0))
    accounted = constructed + sum(typed_gaps.values())
    if accounted != total:
        raise ValueError(
            "With census does not conserve: "
            f"with_items_total={total} constructed={constructed} "
            f"typed_gaps={sum(typed_gaps.values())} accounted={accounted}"
        )
    return {
        "with_items_total": total,
        "constructed": constructed,
        "typed_gap_kinds_total": len(vocabulary),
        "typed_gaps": typed_gaps,
        "unrecognized_resolution_kinds": dict(sorted(unrecognized_kinds.items())),
        "accounted": accounted,
        "reconciliation": (
            f"{total} = {constructed} constructed + "
            f"{sum(typed_gaps.values())} typed gaps"
        ),
        "conserves": True,
    }


def _backend_defect_key(exc: object) -> str:
    """Classify demand/resolution table hygiene — never construction mass.

    The mid-band With probe surfaces two distinct BackendDefects that are
    table bijection failures, not residual construction mass:

    1. enrolled context-manager demand missing from resolution table
    2. enrolled call demand missing from resolution table

    Preserve them as separate keys so the board can track each to zero
    without conflating either with ContextManagerResolutionConstructionGap.
    """
    text = str(exc)
    name = type(exc).__name__ if not isinstance(exc, str) else "BackendDefect"
    observed = getattr(exc, "observed", None)
    if isinstance(observed, str) and observed:
        text = f"{text} {observed}"
    lowered = text.lower()
    if "context-manager demand missing" in lowered or (
        "context-manager" in lowered and "missing from resolution" in lowered
    ):
        return "BackendDefect:cm-demand-missing-from-resolution"
    if "call demand missing" in lowered or (
        "call demand" in lowered and "missing from resolution" in lowered
    ):
        return "BackendDefect:call-demand-missing-from-resolution"
    if "BackendDefect" in name or "backend defect" in lowered:
        # Always keyed `BackendDefect:<what>` — a bare "BackendDefect" would
        # collide with the axis label itself and made this key unreadable as a
        # row (its own twin asserted the prefix and was red).
        return (
            f"BackendDefect:{name}"
            if name != "BackendDefect"
            else ("BackendDefect:unclassified")
        )
    return f"BackendDefect:{name}"


# The desugar membrane lives in ONE place — sugar_lift_py_tests.desugar_axis —
# so this script and `python -m sugar_lift_py_tests.census` cannot drift into
# two different definitions of R_desugar. It also owns the three separations:
# ConstructionPanic (BaseException, caught BY NAME) and ordinary defects are
# kept out of semantic R, and rows are keyed by the authenticated effect
# occurrence rather than the enclosing function's line.


def _ast_site_prevalence(path: Path) -> Counter[str]:
    """How many AST sites of each shape exist. **This is not R.**

    Site prevalence and residual are different denominators and were quoted
    interchangeably: an AST-shape census read ``With 4125/811/85`` while the
    construction ledger for the same period read ``assertion 3 / resource 104``.
    Both were true. Neither was the other.

    Prevalence answers "how much of this shape is in the corpus". R answers
    "how many authenticated construction occurrences did not construct". A
    capability that lifts a shape moves R and leaves prevalence untouched — the
    ``with`` statements are still there. Keys here are deliberately prefixed
    ``site:`` so a prevalence number can never be pasted into an R column
    without the reader seeing it.
    """
    import ast

    sites: Counter[str] = Counter()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        # A file the corpus's own Python cannot parse is a corpus fact, not a
        # residual. Named, counted, never silently zero.
        sites["site:unparseable"] += 1
        return sites
    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            sites["site:with-statement"] += 1
            sites["site:with-item"] += len(node.items)
        elif isinstance(node, ast.AsyncWith):
            sites["site:async-with-statement"] += 1
            sites["site:async-with-item"] += len(node.items)
        elif isinstance(node, ast.Try):
            sites["site:try-statement"] += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sites["site:function-def"] += 1
    return sites


def locus_root_for_corpus(corpus_root: Path) -> Path:
    """The root a corpus's source LOCUS is stated against.

    Distinct from the corpus root, which is the demand-table denominator --
    WHICH TREE is measured. They were one variable, and that conflation is what
    made this census mint addresses no other checkout resolves: measuring
    ``.../site-packages/pandas`` rooted at itself states ``core/frame.py``,
    one of several addresses for one file.

    For an installed corpus the answer is the install root its distribution
    recorded seats against, read from the distribution's own manifest by the
    same walk the seat law uses -- so this driver and that law cannot disagree.
    Computing it any other way would be a second addressing convention.

    For a first-party tree no distribution states an address, and the corpus
    root stands unchanged.
    """
    from sugar_lift_python_source.source_oracle import install_root_for

    installed = install_root_for(str(corpus_root))
    return corpus_root if installed is None else Path(installed)


def _measure_file(
    path: Path,
    *,
    relative: str,
    workspace_root: Path,
    locus_root: Path | None = None,
    contract_refs=None,
    on_function: "Callable[[int, int, str, float | None], None] | None" = None,
) -> dict[str, Any]:
    from sugar_lift_py_tests.audit_only import collect_construction_panic
    from sugar_lift_py_tests.desugar_axis import DesugarAxis
    from sugar_lift_py_tests.lift_rpc import (
        open_source_file_for_construction,
        tree_construction_context_for_workspace,
    )
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.reporter import CollectingReporter

    functions_total = 0
    functions_clean = 0
    functions_enumerated = 0
    families: Counter[str] = Counter()
    construction_seen: set[tuple[str, str, object, object]] = set()
    backend_defects: Counter[str] = Counter()
    cm_resolutions: Counter[str] = Counter()
    unrecognized_cm_kinds: Counter[str] = Counter()
    desugar_axis = DesugarAxis()
    if workspace_root is None:
        # No silent ``path.parent``. That default made a one-file run derive its
        # demand table from a DIFFERENT tree than the full run, so the same file
        # measured alone and measured in the corpus produced different With
        # resolutions. A bounded run must inherit the corpus root, or not run.
        raise ValueError(
            "control_effect_recensus._measure_file requires an explicit "
            "workspace_root: the demand table must come from the corpus root, "
            "never from the measured file's parent directory"
        )
    root = workspace_root
    # The demand table comes from the corpus root; the LOCUS is stated against
    # the root its seats were recorded against. Same value for a first-party
    # tree, different for an installed one.
    address_root = locus_root if locus_root is not None else workspace_root

    def tally_construction(
        kind: str, node: object | None = None, line: object = "?"
    ) -> None:
        key = _occurrence_key(kind, relative, node=node, line=line)
        if key in construction_seen:
            return
        construction_seen.add(key)
        families[kind] += 1

    def construct():
        nonlocal functions_total, functions_clean, functions_enumerated
        reporter = CollectingReporter()
        # Fresh context per file so source_derived refs stay file-local; the
        # demand/gap table (contract_refs) may be shared across the census.
        construction_context = tree_construction_context_for_workspace(
            root, contract_refs=contract_refs
        )
        try:
            source_file = open_source_file_for_construction(
                path,
                root=address_root,
                reporter=reporter,
                construction_context=construction_context,
                populate_derived=True,
            )
        except SugarNotWritten as gap:
            # Derivation can hit a real missing sugar before any function walk.
            tally_construction(type(gap).__name__, line=0)
            return reporter
        # Resolution partition from the derived table (manager-expression
        # sites, not functions-blocked), keyed by authenticated gap kind.
        file_cm_resolutions, file_unrecognized_kinds = _tally_cm_resolutions(
            construction_context
        )
        cm_resolutions.update(file_cm_resolutions)
        unrecognized_cm_kinds.update(file_unrecognized_kinds)
        # Materialize the function population BEFORE the per-function walk.
        # ConstructionPanic is BaseException and escapes this loop; if we
        # increment functions_total inside the loop, a mid-file panic freezes a
        # PARTIAL denominator that is later summed into the board, and Clean%
        # is computed over a silently shrunken set. The full declared count is
        # the denominator; enumeration progress is a separate measurement.
        declared_functions = tuple(source_file.functions())
        functions_total = len(declared_functions)
        functions_enumerated = 0
        for function in declared_functions:
            functions_enumerated += 1
            try:
                span = function.line_col_span()
                line: object = span.start_line
                where = f"{relative}:{span.start_line}:{span.start_col}"
            except Exception:  # noqa: BLE001 -- name is best-effort display
                line = "?"
                where = f"{relative}:?"
            fn_name = f"{getattr(function, 'name', '?')}:{line}"
            # Announce the function BEFORE constructing it (elapsed=None), so a
            # hang shows the exact function it is stuck on -- not the one before.
            if on_function is not None:
                on_function(functions_enumerated - 1, functions_clean, fn_name, None)
            t_fn = time.perf_counter()
            try:
                sugar = function.sugar()
                functions_clean += 1
            except SugarNotWritten:
                # Do NOT tally type here — report_gap already recorded the
                # occurrence on the reporter. Catch+reporter double-tally is
                # what turned 196 With gaps into a false 392.
                sugar = None
            if sugar is not None:
                desugar_axis.measure(sugar, where=where)
            fn_s = time.perf_counter() - t_fn
            # Report completion WITH this function's own construction time, so
            # `last=` is per-function and a slow/blowup function is obvious.
            if on_function is not None:
                on_function(functions_enumerated, functions_clean, fn_name, fn_s)
        # Sole construction-gap source: reporter occurrences, site-deduped.
        # BackendDefect is table hygiene — own counter, never construction R.
        for node, panic in reporter.gaps:
            kind = type(panic).__name__
            if kind == "BackendDefect" or "BackendDefect" in kind:
                backend_defects[_backend_defect_key(panic)] += 1
                continue
            tally_construction(kind, node=node)
        return reporter

    _reporter, panic_row = collect_construction_panic(relative, construct)
    # Two quantities, never one column: resolution residual (R-bearing) and AST
    # site prevalence (denominator, never R).
    resolution_row = {
        "cmResolutions": dict(cm_resolutions),
        "unrecognizedCmResolutionKinds": dict(unrecognized_cm_kinds),
        "R_cm_derived_contract": int(cm_resolutions.get("derived-contract", 0)),
        "astSites": dict(_ast_site_prevalence(path)),
    }
    functions_not_enumerated = max(0, functions_total - functions_enumerated)
    function_accounting = {
        "functionsTotal": functions_total,
        "functionsClean": functions_clean,
        "functionsEnumerated": functions_enumerated,
        "functionsNotEnumerated": functions_not_enumerated,
        "functionsEnumerationComplete": functions_not_enumerated == 0
        and (panic_row is None or functions_total == functions_enumerated),
    }
    if panic_row is not None:
        # File-level ConstructionPanic is BaseException: it escapes construct()
        # via collect_construction_panic and never lands in reporter.gaps, so
        # tally_construction never sees it. Enroll it here — the family set is
        # derived from what measure actually observed, not invented at aggregate.
        panic_families = dict(families)
        panic_families["ConstructionPanic"] = (
            int(panic_families.get("ConstructionPanic") or 0) + 1
        )
        return {
            "category": "construction-panic",
            "panic": {
                "file": relative,
                "type": "ConstructionPanic",
                "message": panic_row.message,
                "gap": panic_row.info,
            },
            **function_accounting,
            "families": panic_families,
            "backendDefects": dict(backend_defects),
            "R_backend_defects": sum(backend_defects.values()),
            **resolution_row,
            **desugar_axis.row(),
        }
    return {
        "category": "completed",
        **function_accounting,
        "families": dict(families),
        "backendDefects": dict(backend_defects),
        "R_backend_defects": sum(backend_defects.values()),
        **resolution_row,
        **desugar_axis.row(),
    }


def main() -> int:
    # Line-buffer stdout even when not a TTY (CI pipes / artifact capture).
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    # Also force C-level unbuffering when the parent forgot PYTHONUNBUFFERED.
    os.environ.setdefault("PYTHONUNBUFFERED", "1")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "corpus",
        type=Path,
        help="what to measure: the corpus root, or one file/subtree inside it",
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=None,
        help=(
            "the package root the demand table is derived from. Required when "
            "CORPUS is not itself that root. A bounded run MUST inherit the "
            "full run's root, or its With resolutions differ for reasons that "
            "are purely the instrument's."
        ),
    )
    parser.add_argument(
        "--corpus-distribution",
        default=None,
        help="distribution name for the pin (default: corpus root directory name)",
    )
    parser.add_argument(
        "--corpus-version",
        default=None,
        help="pinned distribution version (default: read from the *.dist-info)",
    )
    parser.add_argument(
        "--require-corpus-pin",
        type=Path,
        default=None,
        help="refuse to measure unless the corpus matches this pin file exactly",
    )
    parser.add_argument(
        "--write-corpus-pin",
        type=Path,
        default=None,
        help="write the observed corpus pin (version + manifest + aggregate hash)",
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--commit")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(".sugar/pandas-control-effect"),
        help="default directory for progress/engine/result/checkpoint files",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="final result JSON (default: <out-dir>/recensus.json)",
    )
    parser.add_argument(
        "--checkpoint-jsonl",
        type=Path,
        default=None,
        help="per-file journal (default: <out-dir>/checkpoint.jsonl)",
    )
    parser.add_argument(
        "--engine-log",
        type=Path,
        default=None,
        help="sugar engine JSONL only (default: <out-dir>/engine.jsonl)",
    )
    parser.add_argument(
        "--engine-trace",
        action="store_true",
        default=False,
        help=(
            "opt-in full per-span DEBUG enter/exit JSONL (SUGAR_ENGINE_TRACE_EVENTS=1). "
            "Default is WARNING-only heartbeats/cycles/errors for stall naming — "
            "the board does not consume per-span events for R, and the flood is "
            "serialisation on the reduction hot path."
        ),
    )
    parser.add_argument(
        "--progress",
        type=Path,
        default=None,
        help="tqdm progress only (default: <out-dir>/progress.log)",
    )
    parser.add_argument(
        "--aggregate-only",
        action="store_true",
        help=(
            "Rebuild the sealed board from an existing COMPLETE checkpoint "
            "without re-walking files. Recovery is not a shortcut past "
            "identity: pin, shape CID, commit/sourceStamp, and denominator "
            "flags are still computed the normal way. Incomplete checkpoint "
            "(pending files) is UNMEASURED — never a Complete board. "
            "running-counts.jsonl alone is orientation, not a board body."
        ),
    )
    parser.add_argument(
        "--progress-stdout",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "mirror progress heartbeats to stdout (default: ON). "
            "SCOREBOARD_AUTHORITY never TTY-gates this — CI is not a TTY. "
            "Use --no-progress-stdout only for interactive local quiet."
        ),
    )
    args = parser.parse_args()

    if not args.corpus.exists():
        parser.error(f"corpus not found: {args.corpus}")

    # The corpus ROOT is the demand-table denominator; CORPUS is only which
    # slice of it to measure now. Conflating them is the drift that made a
    # bounded file run and the full run disagree about the same file.
    corpus = args.corpus.resolve()
    if args.corpus_root is not None:
        corpus_root = args.corpus_root.resolve()
    elif corpus.is_dir():
        corpus_root = corpus
    else:
        parser.error(
            "--corpus-root is required when CORPUS is a single file: without it "
            "the demand table would be derived from the file's parent directory, "
            "a different tree than the full run, and the rows would not be "
            "comparable"
        )
    if not corpus_root.is_dir():
        parser.error(f"--corpus-root is not a directory: {corpus_root}")
    if corpus != corpus_root and corpus_root not in corpus.parents:
        parser.error(f"corpus {corpus} is not inside --corpus-root {corpus_root}")

    from sugar_lift_py_tests.corpus_pin import (
        CorpusPinDefect,
        load_pin,
        pin_corpus,
        require_pin,
        write_pin,
    )
    # Path-shape CID only (relative path names). Content authentication is the
    # pin aggregate. Do NOT call demand_table_identity.corpus_manifest_cid here:
    # that is the content manifest (root, abs paths) -> (blake3, count), a
    # different preimage than the enrolled shape axis a223.... Paths MUST come
    # from the pin's enrolled population — the same door as pin_corpus /
    # SourceTree — never a re-walk or guessed alternate set.
    from pandas_floor_summary import corpus_cid as corpus_manifest_shape_cid
    from sugar_source_tree.tree import SourceTree

    tip = args.commit or _git_commit(args.repo.resolve()) or "unpinned"
    _narrate(
        "RECENSUS START "
        f"corpus={corpus} corpus_root={corpus_root} tip={tip} "
        f"out_dir={args.out_dir.resolve()} "
        f"host={platform.node()} pid={os.getpid()}"
    )

    # Pin FIRST. A run that cannot name its corpus has no denominator, and a
    # number without a denominator is not a scoreboard entry — it is a rumour.
    t_pin = _phase_begin("manifest_cid_and_pin")
    try:
        observed_pin = pin_corpus(
            corpus_root,
            distribution=args.corpus_distribution,
            version=args.corpus_version,
        )
        if args.require_corpus_pin is not None:
            require_pin(load_pin(args.require_corpus_pin), observed_pin)
        # Same door as "recensus population: authenticated … at …": pin.files
        # is the authenticated corpus population already resolved above.
        manifest_shape_cid = corpus_manifest_shape_cid(list(observed_pin.paths))
        _authenticate_declared_pandas_corpus(observed_pin, manifest_shape_cid)
    except CorpusPinDefect as defect:
        print(str(defect), file=sys.stderr, flush=True)
        return 2
    except ValueError as defect:
        print(str(defect), file=sys.stderr, flush=True)
        return 2
    _phase_end("manifest_cid_and_pin", t_pin)
    _narrate(
        "RECENSUS PIN "
        f"distribution={observed_pin.distribution} version={observed_pin.version} "
        f"manifest_shape_cid={manifest_shape_cid} "
        f"aggregate_hash={observed_pin.aggregate_hash} "
        f"pin_file_count={len(observed_pin.paths)}"
    )

    # Authentication precedes every output artifact and every source-selection
    # pass. A refused tree cannot leave a checkpoint that looks resumable.
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    result_path = args.json or (out / "recensus.json")
    checkpoint_path = args.checkpoint_jsonl or (out / "checkpoint.jsonl")
    engine_path = args.engine_log or (out / "engine.jsonl")
    progress_path = args.progress or (out / "progress.log")
    running_counts_path = out / "running-counts.jsonl"

    _silence_console_logging()
    _configure_engine_log(engine_path, engine_trace=bool(args.engine_trace))
    if args.write_corpus_pin is not None:
        write_pin(observed_pin, args.write_corpus_pin)

    t_src = _phase_begin("source_tree_path_selection")
    paths = list(SourceTree(corpus).paths())
    _phase_end("source_tree_path_selection", t_src)
    if not paths:
        parser.error("corpus contains no Python files")
    # DENOMINATOR before demand-table derivation and before any per-file lift.
    _narrate(
        "RECENSUS DENOMINATOR "
        f"files_to_walk={len(paths)} "
        f"manifest_shape_cid={manifest_shape_cid} "
        f"tip={tip} "
        f"out_dir={out.resolve()} "
        f"checkpoint={checkpoint_path.resolve()} "
        f"result={result_path.resolve()}"
    )
    # File identity is ALWAYS relative to the corpus root — never to CORPUS.
    # That is what makes one file measured alone produce the same row identity
    # as that file inside the full run.
    by_file = {
        f"{corpus_root.name}/{path.resolve().relative_to(corpus_root).as_posix()}": path
        for path in paths
    }
    # TWO ROOTS, not one. They were the same variable, and that conflation is
    # what made the census mint addresses no other checkout resolves.
    #
    #   corpus_root  the demand-table denominator -- WHICH TREE is measured.
    #   locus_root   the address the source locus is stated against.
    #
    # For a first-party tree they coincide. For an INSTALLED corpus they must
    # not: seats are recorded relative to the install root, so measuring
    # `.../site-packages/pandas` rooted at itself mints `core/frame.py` -- one
    # of several addresses for one file, resolvable in no other checkout.
    #
    # The install root is read from the distribution's own manifest, by the
    # same walk the seat law uses, so the driver and the law cannot disagree.
    # Computing it any other way would be a second addressing convention.
    locus_root = locus_root_for_corpus(corpus_root)
    workspace_root = corpus_root

    file_names = sorted(by_file)
    if len(file_names) != len(paths):
        parser.error(
            f"enumeration produced {len(paths)} paths but "
            f"{len(file_names)} distinct identities — duplicate enrolled file"
        )
    pending: list[str] = list(file_names)

    # One provisional demand→gap table for the whole corpus ROOT. Shared across
    # files; each file still gets a fresh TreeConstructionContextV1 so
    # source-derived manager refs do not leak between files. Deriving this from
    # anything but the root is the corpus-context drift defect.
    from sugar_lift_py_tests.lift_rpc import provisional_contract_refs_from_demands

    # Demand-table walk can take minutes with only a BEGIN/END pair — that is
    # blind by construction. Alive heartbeats every ≤30s hit the job log.
    _narrate(
        f"RECENSUS DEMAND_TABLE deriving provisional refs from workspace_root={workspace_root}"
    )
    contract_refs = _phase_call(
        "demand_table_derivation",
        lambda: provisional_contract_refs_from_demands(workspace_root),
    )
    _narrate(
        "RECENSUS DEMAND_TABLE ready "
        f"(type={type(contract_refs).__name__})"
    )

    from pandas_census_checkpoint import Checkpoint

    t_ckpt = _phase_begin("checkpoint_load")
    checkpoint = Checkpoint(
        floor="control-effect",
        files=tuple(file_names),
        path=checkpoint_path,
    )
    pending = list(checkpoint.pending_files())
    _phase_end("checkpoint_load", t_ckpt)
    _narrate(
        "RECENSUS CHECKPOINT "
        f"total={len(file_names)} already_done={len(file_names) - len(pending)} "
        f"pending={len(pending)} path={checkpoint_path.resolve()}"
    )
    if args.aggregate_only:
        if pending:
            _narrate(
                "RECENSUS AGGREGATE-ONLY REFUSED: checkpoint incomplete "
                f"pending={len(pending)}/{len(file_names)} — walk did not finish; "
                "running-counts.jsonl is orientation only, not a sealed board. "
                "Do not bank as Measured."
            )
            print(
                "aggregate-only requires a complete checkpoint (zero pending); "
                f"pending={len(pending)} of {len(file_names)}",
                file=sys.stderr,
                flush=True,
            )
            return 2
        _narrate(
            "RECENSUS AGGREGATE-ONLY: complete checkpoint; skipping lift; "
            "board identity still from pin+commit+denominator (not from "
            "running-counts alone)"
        )
    defects: list[dict[str, Any]] = []
    construction_panics: list[dict[str, Any]] = []
    floor_rows: list[dict[str, Any]] = []
    families: Counter[str] = Counter()
    desugar_families: Counter[str] = Counter()
    desugar_categories: Counter[str] = Counter()
    desugar_by_category_owner: Counter[str] = Counter()
    backend_defects: Counter[str] = Counter()
    cm_resolutions: Counter[str] = Counter()
    unrecognized_cm_kinds: Counter[str] = Counter()
    ast_sites: Counter[str] = Counter()
    # Three disjoint desugar-layer quantities; the two below are NEVER folded
    # into R_desugar and both make the run red.
    desugar_construction_panics: list[dict[str, Any]] = []
    desugar_defects: list[dict[str, Any]] = []
    # A FOURTH, disjoint from all three and RED-NEUTRAL: a declared mechanism
    # refusing on purpose, as its correct answer, in something that is not a
    # SugarNotWritten. See sugar_lift_py_tests.desugar_axis._designed_gap_types
    # for why membership is a declared TYPE and never "a ValueError from this
    # call". Published with its MEMBERS, not a bare count: `factoringGaps = 13`
    # as a lone scalar sent an owner hunting for a whole session.
    desugar_designed_gaps: list[dict[str, Any]] = []
    unresolvable_dispatch: list[dict[str, Any]] = []
    files_completed = 0
    functions_total = 0
    functions_clean = 0
    started = time.time()
    measured_now: list[tuple[str, dict[str, Any]]] = []

    if not args.aggregate_only:
        try:
            from tqdm import tqdm
        except ImportError as error:  # pragma: no cover
            raise SystemExit(
                "tqdm is required: python3 -m pip install 'tqdm>=4.66'"
            ) from error

        live_done = 0
        live_panic = 0  # ConstructionPanic only (file-level kit panic)
        live_defect = 0
        live_fns = 0
        live_clean = 0
        live_snw = 0  # SugarNotWritten (missing sugar)
        live_other_gaps = 0  # other typed gaps (e.g. RuntimeSelectedContextManager)
        already_done = len(file_names) - len(pending)
        # Seed running totals from checkpoint so resume doesn't look like "0 gaps".
        if checkpoint is not None and already_done:
            for crow in checkpoint.rows():
                raw = crow.get("result") or {}
                cat = str(raw.get("category") or "")
                live_fns += int(raw.get("functionsTotal") or 0)
                live_clean += int(raw.get("functionsClean") or 0)
                # NOT `families`: that name is main's accumulating Counter, and
                # rebinding it to this plain dict made the later
                # `families["ConstructionPanic"] += 1` a KeyError crash — the whole
                # run lost, at the exact moment a panic row appeared.
                row_families = raw.get("families") or {}
                live_snw += int(row_families.get("SugarNotWritten") or 0)
                live_other_gaps += sum(
                    int(v)
                    for k, v in row_families.items()
                    if k != "SugarNotWritten"
                )
                if cat == "construction-panic":
                    live_panic += 1
                elif cat not in {"completed", ""}:
                    live_defect += 1
                live_done += 1

        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_stream: TextIO = progress_path.open("w", encoding="utf-8")
        # Header so `tail -f progress.log` is self-describing.
        progress_stream.write(
            f"# pandas enum progress\n"
            f"# corpus={args.corpus}\n"
            f"# engine_log={engine_path.resolve()}\n"
            f"# checkpoint={checkpoint_path.resolve()}\n"
            f"# result={result_path.resolve()}\n"
            f"# already_done={already_done} pending={len(pending)} total={len(file_names)}\n"
            f"# postfix: file=current path | snw=SugarNotWritten | gaps=other typed | "
            f"cpanic=ConstructionPanic | fn=clean/total functions\n"
        )
        progress_stream.flush()

        bar_format = (
            "{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} "
            "[{elapsed}<{remaining}, {rate_fmt}] {postfix}"
        )

        _last_progress_stdout = 0.0

        def _set_bars(postfix: dict[str, object], *, refresh: bool = True) -> None:
            nonlocal _last_progress_stdout
            bar.set_postfix(postfix, refresh=refresh)
            if live_bar is not None:
                live_bar.set_postfix(postfix, refresh=refresh)
            progress_stream.flush()
            # File-side tqdm is invisible in CI. ALWAYS mirror to the job log —
            # never TTY-gate, never hide behind --progress-stdout (that flag only
            # controls the optional interactive stderr bar). Cap silence at 30s.
            if not refresh:
                return
            now = time.monotonic()
            status = str(postfix.get("status") or "")
            force = status not in {"lifting…", "ok", "…"}
            if not force and now - _last_progress_stdout < _JOB_LOG_MAX_SILENCE_S:
                return
            if force and now - _last_progress_stdout < 2.0 and status in {
                "done",
                "cpanic",
            }:
                # Allow dense end-of-file lines without flooding.
                pass
            _last_progress_stdout = now
            n = getattr(bar, "n", live_done)
            total = getattr(bar, "total", len(file_names)) or len(file_names)
            bits = " ".join(f"{k}={v}" for k, v in postfix.items())
            _narrate(f"RECENSUS PROGRESS {n}/{total} {bits}")

        try:
            bar = tqdm(
                pending,
                total=len(file_names),
                initial=already_done,
                unit="file",
                desc="pandas enum",
                file=progress_stream,
                dynamic_ncols=False,
                ncols=320,
                mininterval=0.15,
                smoothing=0.05,
                bar_format=bar_format,
            )
            # Interactive TTY only: second tqdm bar on stderr. Never gate *all*
            # progress on isatty — CI is not a TTY and that was the silent wedge.
            live_bar = None
            if args.progress_stdout and sys.stderr.isatty():
                live_bar = tqdm(
                    total=len(file_names),
                    initial=already_done,
                    unit="file",
                    desc="pandas enum",
                    file=sys.stderr,
                    dynamic_ncols=True,
                    mininterval=0.15,
                    smoothing=0.05,
                    bar_format=bar_format,
                )
            _narrate(
                "RECENSUS PROGRESS_ROUTE "
                f"file={progress_path.resolve()} "
                f"stdout_mirror={args.progress_stdout} "
                f"tty_stderr_bar={live_bar is not None} "
                f"(SCOREBOARD never TTY-gates stdout heartbeats)"
            )

            t_lift = _phase_begin("per_file_lift")
            _narrate(
                "RECENSUS LIFT ENTER "
                f"pending={len(pending)} total={len(file_names)} "
                f"progress_every_n={_PROGRESS_EVERY_N}"
            )
            for file in bar:
                path = by_file[file]
                # Same identity in a bounded run and in the full run: relative to
                # the corpus ROOT, never to whatever slice this invocation measured.
                relative = path.resolve().relative_to(corpus_root).as_posix()
                # index is 1-based among pending within this invocation; live_done
                # includes checkpoint resume so overall position is known.
                file_index = live_done + 1
                # Show the file we are about to open — before the work starts.
                _set_bars(
                    {
                        "file": relative,
                        "status": "lifting…",
                        "snw": live_snw,
                        "gaps": live_other_gaps,
                        "cpanic": live_panic,
                        "defect": live_defect,
                        "fn": f"{live_clean}/{live_fns}",
                    },
                    refresh=True,
                )
                if (
                    file_index == 1
                    or file_index % _PROGRESS_EVERY_N == 0
                    or file_index == len(file_names)
                ):
                    _narrate(
                        "RECENSUS FILE BEGIN "
                        f"{file_index}/{len(file_names)} file={relative} "
                        f"elapsed_s={time.time() - started:.1f} "
                        f"counts completed≈{live_done - live_panic - live_defect} "
                        f"snw={live_snw} other_gaps={live_other_gaps} "
                        f"cpanic={live_panic} defect={live_defect} "
                        f"fn_clean/total={live_clean}/{live_fns}"
                    )
                t_file = time.perf_counter()
                fn_stat = {
                    "slow_s": 0.0,
                    "slow_name": "-",
                    "fn_seen": 0,
                    "fn_time": 0.0,
                    "file_start": time.perf_counter(),
                }

                def _on_function(
                    in_total: int, in_clean: int, fn_name: str, elapsed: "float | None"
                ) -> None:
                    # live_clean/live_fns are the completed-file base; add this
                    # file's running counts so `fn=` climbs per function, live.
                    shown_fns = live_fns + in_total
                    shown_clean = live_clean + in_clean
                    clean_pct = (100.0 * shown_clean / shown_fns) if shown_fns else 0.0
                    if elapsed is not None:
                        fn_stat["fn_seen"] += 1
                        fn_stat["fn_time"] += elapsed
                        if elapsed > fn_stat["slow_s"]:
                            fn_stat["slow_s"] = elapsed
                            fn_stat["slow_name"] = fn_name
                    seen = fn_stat["fn_seen"] or 1
                    avg = fn_stat["fn_time"] / seen
                    wall = time.perf_counter() - fn_stat["file_start"]
                    rate = fn_stat["fn_seen"] / wall if wall > 0 else 0.0
                    post = {
                        "file": relative,
                        "func": fn_name,
                        "status": "lifting…" if elapsed is None else "ok",
                        "last": "…" if elapsed is None else f"{elapsed:.3f}s",
                        "avg": f"{avg:.3f}s",
                        "fn/s": f"{rate:.1f}",
                        "slowest": f"{fn_stat['slow_name']} {fn_stat['slow_s']:.2f}s",
                        "snw": live_snw,
                        "gaps": live_other_gaps,
                        "cpanic": live_panic,
                        "defect": live_defect,
                        "fn": f"{shown_clean}/{shown_fns}",
                        "clean%": f"{clean_pct:.0f}",
                    }
                    _set_bars(post, refresh=True)

                try:
                    row = _measure_file(
                        path,
                        relative=relative,
                        workspace_root=workspace_root,
                        locus_root=locus_root,
                        contract_refs=contract_refs,
                        on_function=_on_function,
                    )
                except (ImportError, AttributeError) as error:
                    # An arm that cannot resolve its dispatch target is UNWRITTEN,
                    # wearing a working arm's clothes. It is not a panic, not a
                    # typed refusal, and not in any family below -- so absorbing it
                    # into `backend-defect` would leave the row short with nothing
                    # saying so. Own category, named, loud, red (#6329).
                    row = {
                        "category": "instrument-defect-unresolvable-dispatch",
                        "defect": {
                            "file": relative,
                            "type": type(error).__name__,
                            "message": str(error),
                            "owner": "kit dispatch target",
                            "fix": (
                                "the arm imports a name that does not exist; write "
                                "the target or delete the arm"
                            ),
                        },
                    }
                except Exception as error:  # noqa: BLE001 -- per-file terminal
                    row = {
                        "category": "backend-defect",
                        "defect": {
                            "file": relative,
                            "type": type(error).__name__,
                            "message": str(error),
                        },
                    }
                file_s = time.perf_counter() - t_file
                checkpoint.append(file, row)
                measured_now.append((file, row))

                cat = str(row.get("category") or "?")
                fn = int(row.get("functionsTotal") or 0)
                clean = int(row.get("functionsClean") or 0)
                # NEVER rebind the name `families` — that is main()'s accumulating
                # Counter for board aggregation. Assigning row.get("families") here
                # replaced the Counter with a plain dict; after the last file,
                # aggregation did families["ConstructionPanic"] += 1 and KeyError'd
                # (landmine two: 1421/1421 walk, zero board). Same class as the
                # seed-path defect above — always use a row-local name.
                row_families = row.get("families") or {}
                snw = int(row_families.get("SugarNotWritten") or 0)
                other = sum(
                    int(v) for k, v in row_families.items() if k != "SugarNotWritten"
                )
                live_fns += fn
                live_clean += clean
                live_snw += snw
                live_other_gaps += other
                live_done += 1
                if cat == "construction-panic":
                    live_panic += 1
                    status = "cpanic"
                elif cat == "completed":
                    status = "done"
                else:
                    live_defect += 1
                    status = cat

                clean_pct = (100.0 * live_clean / live_fns) if live_fns else 0.0
                _set_bars(
                    {
                        "file": relative,
                        "status": status,
                        "last": f"{file_s:.2f}s",
                        "snw": live_snw,
                        "gaps": live_other_gaps,
                        "cpanic": live_panic,
                        "defect": live_defect,
                        "fn": f"{live_clean}/{live_fns}",
                        "clean%": f"{clean_pct:.0f}",
                    },
                    refresh=True,
                )
                if live_bar is not None:
                    live_bar.update(1)

                # Durable running counts — crash at file 900 still leaves 899 rows
                # on checkpoint AND a jsonl tail of counts on stdout-equivalent disk.
                running = {
                    "schema": "control-effect-recensus-running-v1",
                    "index": live_done,
                    "total": len(file_names),
                    "file": relative,
                    "category": cat,
                    "file_s": round(file_s, 4),
                    "elapsed_s": round(time.time() - started, 3),
                    "snw": live_snw,
                    "other_gaps": live_other_gaps,
                    "cpanic": live_panic,
                    "defect": live_defect,
                    "fn_clean": live_clean,
                    "fn_total": live_fns,
                    "phase": "per_file_lift",
                }
                with running_counts_path.open("a", encoding="utf-8") as rc_stream:
                    rc_stream.write(
                        json.dumps(running, sort_keys=True, separators=(",", ":"))
                        + "\n"
                    )
                    rc_stream.flush()
                if (
                    live_done == 1
                    or live_done % _PROGRESS_EVERY_N == 0
                    or live_done == len(file_names)
                ):
                    _narrate(
                        "RECENSUS FILE END "
                        f"{live_done}/{len(file_names)} file={relative} "
                        f"category={cat} file_s={file_s:.3f} "
                        f"elapsed_s={time.time() - started:.1f} "
                        f"snw={live_snw} other_gaps={live_other_gaps} "
                        f"cpanic={live_panic} defect={live_defect} "
                        f"fn_clean/total={live_clean}/{live_fns}"
                    )

            _phase_end("per_file_lift", t_lift)
            if live_bar is not None:
                live_bar.close()
            bar.close()
        finally:
            progress_stream.close()


    # Tripwire: the lift loop must never rebind `families` to a row dict.
    if not isinstance(families, Counter):
        raise TypeError(
            "families rebinding defect before aggregation: expected Counter, "
            f"got {type(families).__name__}. Never assign row.get('families') "
            "to the name families — use row_families (landmine two)."
        )
    t_agg = _phase_begin("aggregation")
    measured_rows = [(row["file"], row["result"]) for row in checkpoint.rows()]
    # The denominator, stated before any rate is quoted. Checkpoint already
    # refuses duplicate rows, unknown files, a foreign manifest CID and
    # malformed JSON at load; what it cannot say is which enrolled files never
    # produced a terminal row at all. Name them.
    terminal_files = [file for file, _ in measured_rows]
    missing_files = sorted(set(file_names) - set(terminal_files))
    duplicate_files = sorted(
        {file for file in terminal_files if terminal_files.count(file) > 1}
    )
    malformed_rows = sorted(
        file
        for file, raw in measured_rows
        if not isinstance(raw, dict) or not raw.get("category")
    )

    for file, raw in measured_rows:
        row = dict(raw)
        category = str(row.get("category"))
        floor_rows.append({"file": file, "category": category})
        functions_total += int(row.get("functionsTotal") or 0)
        functions_clean += int(row.get("functionsClean") or 0)
        families.update(row.get("families") or {})
        desugar_families.update(row.get("desugarFamilies") or {})
        desugar_categories.update(row.get("desugarCategories") or {})
        desugar_by_category_owner.update(row.get("desugarByCategoryOwner") or {})
        backend_defects.update(row.get("backendDefects") or {})
        cm_resolutions.update(row.get("cmResolutions") or {})
        unrecognized_cm_kinds.update(row.get("unrecognizedCmResolutionKinds") or {})
        ast_sites.update(row.get("astSites") or {})
        desugar_construction_panics.extend(row.get("desugarConstructionPanics") or [])
        desugar_defects.extend(row.get("desugarDefects") or [])
        desugar_designed_gaps.extend(row.get("desugarDesignedGaps") or [])
        if category == "completed":
            files_completed += 1
        elif category == "construction-panic":
            panic = row.get("panic")
            if isinstance(panic, dict):
                construction_panics.append(panic)
            # Measure now enrolls ConstructionPanic into the row's families
            # (file-level BaseException path). Prefer that; only fill if a
            # legacy checkpoint row still omits it. Use get+assign so a plain
            # dict can never KeyError (Counter already tolerated missing keys).
            if "ConstructionPanic" not in (row.get("families") or {}):
                families["ConstructionPanic"] = (
                    int(families.get("ConstructionPanic") or 0) + 1
                )
        elif category == "instrument-defect-unresolvable-dispatch":
            defect = row.get("defect")
            if isinstance(defect, dict):
                unresolvable_dispatch.append(dict(defect))
            defects.append(
                dict(defect)
                if isinstance(defect, dict)
                else {"file": file, "type": category, "message": category}
            )
        else:
            defect = row.get("defect")
            defects.append(
                dict(defect)
                if isinstance(defect, dict)
                else {"file": file, "type": category, "message": category}
            )
            # Demand/resolution table hygiene — own counter, not mass residual.
            # Keep CM-demand vs call-demand bijection failures separate.
            if isinstance(defect, dict):
                msg = f"{defect.get('type', '')}: {defect.get('message', '')}"
            else:
                msg = str(category)
            if (
                "BackendDefect" in msg
                or "backend defect" in msg.lower()
                or (
                    isinstance(defect, dict)
                    and "BackendDefect" in str(defect.get("type", ""))
                )
            ):
                backend_defects[_backend_defect_key(msg)] += 1
            elif category == "backend-defect":
                backend_defects[_backend_defect_key(msg)] += 1

    from pandas_floor_summary import floor_summary

    r_construction = sum(families.values())
    r_desugar = sum(desugar_families.values())
    r_backend = sum(backend_defects.values())
    with_census = _with_census_partition(
        cm_resolutions, ast_sites, unrecognized_cm_kinds
    )
    result: dict[str, Any] = {
        "kind": "control-effect-construction-recensus",
        "corpusAuthentication": {
            "aggregateHash": observed_pin.aggregate_hash,
            "requiredAggregateHash": _PANDAS_3_0_3_AGGREGATE_HASH,
            "manifestShapeCid": manifest_shape_cid,
            "requiredManifestShapeCid": _PANDAS_3_0_3_MANIFEST_SHAPE_CID,
        },
        "authority": (
            "sole authoritative Python corpus scoreboard; every other census "
            "output is non-authoritative"
        ),
        "commit": args.commit or _git_commit(args.repo),
        "corpus": str(corpus),
        "corpusRoot": str(corpus_root),
        # WHICH corpus — version, manifest length, one aggregate hash. Two runs
        # are comparable iff these aggregate hashes are equal. The 1,415-file
        # ledger is a different pandas and is NOT comparable to this board.
        "corpusPin": observed_pin.summary(),
        "door": "enum:path_source→SourceFile→functions→sugar→desugar",
        "isolation": "in-process",
        "paths": {
            "engineLog": str(engine_path.resolve()),
            "progress": str(progress_path.resolve()),
            "checkpoint": str(checkpoint_path.resolve()),
            "result": str(result_path.resolve()),
        },
        # THE DENOMINATOR — stated, with exact identities, before any rate.
        "denominator": {
            "enrolled": len(file_names),
            "terminalRows": len(measured_rows),
            "completed": files_completed,
            "corpusManifestCid": checkpoint.manifest_cid,
            "enrolledFiles": list(file_names),
            "missingFiles": missing_files,
            "duplicateFiles": duplicate_files,
            "malformedRows": malformed_rows,
            "complete": (
                len(measured_rows) == len(file_names)
                and not missing_files
                and not duplicate_files
                and not malformed_rows
            ),
        },
        "filesTotal": len(file_names),
        "filesCompleted": files_completed,
        "defects": defects,
        "constructionPanics": construction_panics,
        "R_construction_panics": len(construction_panics),
        "functionsTotal": functions_total,
        "functionsConstructClean": functions_clean,
        # Axis 1 — construction totality (tree owned). Occurrence-deduped.
        # Never merge with R_desugar. Never double-count catch+reporter.
        "R": r_construction,
        "R_construction": r_construction,
        "families": dict(
            sorted(families.items(), key=lambda item: (-item[1], item[0]))
        ),
        # Axis 2 — desugar refusals + typed red (#6243). Separate quantity.
        # R_desugar is MIXED. Read the split, never the total: a typed refusal
        # owes work, a constructed effect IS the correct output of a reduction
        # that succeeded. Publishing the sum as work remaining overstated the
        # earlier board 7.6x.
        "R_desugar": r_desugar,
        "desugarCategories": dict(
            sorted(desugar_categories.items(), key=lambda item: (-item[1], item[0]))
        ),
        "R_desugar_owed_work": int(desugar_categories.get("typed-refusal", 0)),
        "R_desugar_accounted_semantics": int(
            desugar_categories.get("constructed-effect", 0)
        ),
        "desugarByCategoryOwner": dict(
            sorted(
                desugar_by_category_owner.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        "desugarFamilies": dict(
            sorted(desugar_families.items(), key=lambda item: (-item[1], item[0]))
        ),
        # Table hygiene — not residual mass (probe: 2 BackendDefect files).
        "R_backend_defects": r_backend,
        "backendDefects": dict(
            sorted(backend_defects.items(), key=lambda item: (-item[1], item[0]))
        ),
        # With residual partition, keyed by AUTHENTICATED resolution kind.
        # Structural, not spelling: no vendor name table decides these buckets.
        "cmResolutions": dict(
            sorted(cm_resolutions.items(), key=lambda item: (-item[1], item[0]))
        ),
        "R_cm_derived_contract": int(cm_resolutions.get("derived-contract", 0)),
        "withCensus": with_census,
        # AST SITE PREVALENCE — a denominator, NEVER R. Different question,
        # different number: prevalence counts shapes present, R counts
        # authenticated occurrences that failed to construct. Quoting one as
        # the other is exactly the confusion this board was repaired to end.
        "astSitePrevalence": dict(
            sorted(ast_sites.items(), key=lambda item: (-item[1], item[0]))
        ),
        # Neither of these is semantic R. A construction-law None arm during
        # desugar is a construction gap; an ordinary exception is an
        # implementation defect. Both are red, separately.
        "desugarConstructionPanics": desugar_construction_panics,
        "R_desugar_construction_panics": len(desugar_construction_panics),
        "desugarDefects": desugar_defects,
        "R_desugar_defects": len(desugar_defects),
        # Correct output from a named mechanism. Disjoint from desugarDefects
        # (not a bug), from R_desugar (not a typed refusal) and from the panic
        # collection. Never added to any of them, and never a red reason.
        "desugarDesignedGaps": desugar_designed_gaps,
        "R_desugar_designed_gaps": len(desugar_designed_gaps),
        "desugarDesignedGapOwners": dict(
            Counter(str(gap.get("owner", "?")) for gap in desugar_designed_gaps)
        ),
        # #6329 -- an arm reaching a dispatch target that does not exist. Its
        # own axis: never semantic R, never quietly a backend defect.
        "unresolvableDispatchTargets": unresolvable_dispatch,
        "R_unresolvable_dispatch_targets": len(unresolvable_dispatch),
        "elapsedSeconds": time.time() - started,
        "python": sys.version,
        # WHERE and WHEN this was measured. A board row without its stamp
        # cannot be re-run, and a number nobody can re-run is not evidence.
        "sourceStamp": {
            "commit": args.commit or _git_commit(args.repo),
            "repo": str(args.repo.resolve()),
            "python": sys.version,
            "platform": platform.platform(),
            "host": platform.node(),
            "loadAverage": list(os.getloadavg()) if hasattr(os, "getloadavg") else [],
            "measuredAtUnix": time.time(),
        },
        "floorSummary": floor_summary(
            floor="control-effect",
            files=file_names,
            rows=floor_rows,
            totals={
                "R_control_effect": r_construction + len(defects),
                "R_desugar": r_desugar,
                "R_backend_defects": r_backend,
                "R_cm_derived_contract": int(cm_resolutions.get("derived-contract", 0)),
                "desugarConstructionPanics": len(desugar_construction_panics),
                "desugarDefects": len(desugar_defects),
                "constructionPanics": len(construction_panics),
                "backendDefectsOrProcessTerminals": len(defects),
            },
            measured=len(floor_rows) == len(file_names),
            unmeasurable_reasons=(),
        ),
    }
    # stableZero -- RULING ON PLACEMENT.
    #
    # This is a ONE-FLOOR term and is deliberately named
    # ``controlEffectStableZero``, not ``stableZero``. The corpus-level verdict
    # is NOT here: it belongs to ``reconcile_pandas_floors.py``, which merges
    # all five floors, enforces that they name one identical manifest CID and
    # one identical file list, and emits ``verdict: green|red``. A second
    # corpus-level verdict computed here would be a parallel authority --
    # exactly the disease this repair exists to cure -- and it would be
    # computed from one floor's view while claiming to speak for all five.
    #
    # It does not go into ``floor_summary`` either: that helper is shared by
    # every floor and already owns conservation (rows account for every corpus
    # file exactly once) plus the measured/unmeasurable distinction. Adding a
    # zero-verdict there would make each floor separately claim a corpus-level
    # property it cannot see.
    #
    # So: this floor states its own terms honestly, the reconciler owns the
    # corpus verdict, and ``desugar_repro.py`` keeps its own reproducer-level
    # ``stableZero`` as a process exit verdict. Three scopes, three names.
    #
    # Every conjunct is reported beside the term, so a false claim is visible
    # in the same object that makes it.
    denominator = result["denominator"]

    def _matching(needle: str) -> int:
        """Count a named shape wherever it can land — never one hopeful key.

        A factoring gap can surface as a construction family, a desugar family,
        a desugar defect or a per-file terminal defect. Reading only one of
        those and reporting zero is how a term goes quiet without being fixed.
        """
        total = sum(n for key, n in families.items() if needle in key)
        total += sum(n for key, n in desugar_families.items() if needle in key)
        total += sum(1 for row in desugar_defects if needle in json.dumps(row))
        total += sum(
            1
            for defect in defects
            if needle in f"{defect.get('type', '')}{defect.get('message', '')}"
        )
        return total

    stable_zero_terms = {
        "completedDenominatorPositive": files_completed > 0,
        "denominatorComplete": bool(denominator["complete"]),
        # This instrument has no timeout mechanism: it runs in-process and a
        # hang is a hang, not a row. Any timeout testimony can only arrive as a
        # named defect, so that is where it is counted from.
        "timeouts": _matching("imeout"),
        "constructionPanics": len(construction_panics),
        "factoringGaps": _matching("FactoringGap"),
        "unresolvableDispatchTargets": len(unresolvable_dispatch),
        "backendDefectFiles": sum(
            1 for defect in defects if "BackendDefect" in str(defect.get("type", ""))
        ),
        "desugarConstructionPanics": len(desugar_construction_panics),
        "desugarDefects": len(desugar_defects),
    }
    result["controlEffectStableZeroTerms"] = stable_zero_terms
    # A True stableZero sitting beside a red exit is the false green this whole
    # repair exists to abolish. The term below is the brief's exact conjunction
    # and is deliberately NOT redefined -- but it is a narrow claim, and axes
    # outside it (desugar construction panics, desugar defects, per-file
    # terminals) can be nonzero while it holds. So the run states its own
    # colour and its reasons in the same breath, and no reader has to know
    # which axes the conjunction happens to cover.
    red_reasons: list[str] = []
    if defects:
        red_reasons.append(f"{len(defects)} per-file terminal defect rows")
    if construction_panics:
        red_reasons.append(f"{len(construction_panics)} construction panics")
    if desugar_construction_panics:
        red_reasons.append(
            f"{len(desugar_construction_panics)} desugar construction panics "
            "(construction-law None arms -- red, and never semantic R)"
        )
    if desugar_defects:
        red_reasons.append(f"{len(desugar_defects)} desugar defects")
    if unresolvable_dispatch:
        red_reasons.append(
            f"{len(unresolvable_dispatch)} unresolvable dispatch targets (#6329)"
        )
    if files_completed != len(file_names):
        # NOT "denominator incomplete" -- that phrasing was itself misleading.
        # Every enrolled file DID produce a terminal row (that is what a
        # complete denominator means); some of those rows are defects rather
        # than completions. Two different facts, two different sentences.
        red_reasons.append(
            f"{len(file_names) - files_completed} of {len(file_names)} enrolled "
            "files produced a terminal row that is not a completion "
            "(denominator is complete; the completion count is not)"
        )
    if not denominator["complete"]:
        red_reasons.append("denominator contaminated (missing/duplicate/malformed)")
    result["red"] = bool(red_reasons)
    result["redReasons"] = red_reasons
    result["controlEffectStableZero"] = (
        stable_zero_terms["completedDenominatorPositive"]
        and stable_zero_terms["denominatorComplete"]
        and stable_zero_terms["timeouts"] == 0
        and stable_zero_terms["constructionPanics"] == 0
        and stable_zero_terms["factoringGaps"] == 0
        and stable_zero_terms["unresolvableDispatchTargets"] == 0
    )
    _phase_end("aggregation", t_agg)

    t_board = _phase_begin("board_write")
    rendered = json.dumps(result, indent=2)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(rendered + "\n")
    _phase_end("board_write", t_board)
    _narrate(
        "RECENSUS DONE "
        f"files={files_completed}/{len(file_names)} "
        f"R_construction={result.get('R_construction')} "
        f"R_desugar={result.get('R_desugar')} "
        f"cpanic={len(construction_panics)} defect={len(defects)} "
        f"elapsed_s={time.time() - started:.1f} "
        f"result={result_path} progress={progress_path} engine={engine_path} "
        f"running_counts={running_counts_path}"
    )
    # An incomplete or contaminated denominator is red on its own. Banking a
    # partial run as a board is the exact failure this repair exists to end.
    return (
        1
        if defects
        or construction_panics
        or desugar_construction_panics
        or desugar_defects
        or files_completed != len(file_names)
        or not denominator["complete"]
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
