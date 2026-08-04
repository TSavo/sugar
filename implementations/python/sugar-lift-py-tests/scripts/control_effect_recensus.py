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
      → mint prebuilt demand table ONCE (or LOAD plan-time artifact)
      → install into process memo (shards: zero walk)
      → measure_file_via_enumerate(contract_refs=…)  # D2/D3 sugar.enumerate
      → (legacy path) open_source_file_for_construction + sugar/desugar

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

# Terminals come from sugar.enumerate only (recensus_enumerate_consumer).
# Sole seal door is compose_control_effect_board.py (SCOREBOARD_AUTHORITY=True).
# _measure_file is a RETIRED side door — not on the production path.
# Law: protocol/specs/2026-08-02-recensus-as-enumerate-consumer.md
SCOREBOARD_AUTHORITY = False

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
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping, TextIO

from sugar_lift_py_tests.gap.panic import ConstructionPanic

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
    _narrate(f"RECENSUS PHASE END: {name} elapsed_s={time.perf_counter() - t0:.3f}")


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


def _consume_sealed_files_complete(
    result: dict[str, Any],
    *,
    measured_commit: str,
) -> tuple[bool | None, dict[str, Any] | None]:
    """Read the file-completeness testimony owned by the compose seal.

    A sealed board can only carry ``denominator.files.complete is True``.
    Missing, malformed, or contradictory testimony is instrument failure and
    must replace the purported board with an unmeasured envelope.
    """
    try:
        denominator = result["denominator"]
        if not isinstance(denominator, dict):
            raise TypeError("sealed board denominator testimony is not an object")
        files = denominator["files"]
        if not isinstance(files, dict):
            raise TypeError("sealed board denominator.files testimony is not an object")
        complete = files["complete"]
        if complete is not True:
            raise ValueError(
                "sealed board denominator.files.complete testimony is not true"
            )
    except (KeyError, TypeError, ValueError) as exc:
        from compose_control_effect_board import (
            STAGE_TERMINAL_AGGREGATE_SEAL,
            unmeasured_envelope,
        )

        reason = (
            "sealed board missing denominator.files.complete testimony"
            if isinstance(exc, KeyError)
            else str(exc)
        )
        refusal = unmeasured_envelope(
            plan={
                "planCid": result.get("planCid"),
                "measuredCommit": measured_commit,
            },
            missing_shards=["compose"],
            unmeasured_reasons={"compose": reason},
            measured_commit=measured_commit,
            instrument_failures=[
                {
                    "stageId": STAGE_TERMINAL_AGGREGATE_SEAL,
                    "observedEventType": (
                        f"{type(exc).__module__}.{type(exc).__qualname__}"
                    ),
                    "phase": "post-compose-denominator-consumer",
                    "reason": reason,
                }
            ],
        )
        return None, refusal
    return True, None


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
            extra = f" suppressed={self._suppressed}" if self._suppressed else ""
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


# Conservation: every sync with-item constructs or does not.
# No kind vocabulary. Unconstructed rows are panics waiting to be written.
WITH_CENSUS_CONSERVATION_IDENTITY = (
    "site:with-item == constructed + unconstructed " "(no residual kind taxonomy)"
)


def _tally_cm_resolutions(
    context=None,
    *,
    source_cid: str,
    resolution_events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Emit one canonical coordinate row per With resolution, no name buckets."""
    from sugar_lift_py_tests.context_manager_resolution import (
        context_manager_resolution_outcome,
        effective_context_manager_resolutions_for_source,
    )

    if not source_cid:
        raise ValueError(
            "cm resolution tally requires source_cid so shared contract_refs "
            "are not multiplied across every file in the census"
        )

    rows: list[dict[str, Any]] = []
    if resolution_events is not None:
        for event in resolution_events:
            if not isinstance(event, dict):
                raise TypeError("With resolution event must be an object")
            key = event.get("inputKey")
            outcome = event.get("outcome")
            observed_type = event.get("observedEventType")
            if (
                not isinstance(key, dict)
                or key.get("sourceCid") != source_cid
                or outcome not in {"constructed", "unconstructed"}
                or not isinstance(observed_type, str)
                or "." not in observed_type
            ):
                raise TypeError(f"malformed With resolution event: {event}")
            rows.append(
                {
                    "inputKey": dict(key),
                    "observedEventType": observed_type,
                    "outcome": outcome,
                }
            )
    else:
        if context is None:
            raise TypeError("With resolution tally requires context or raw events")
        for coordinate, resolution in effective_context_manager_resolutions_for_source(
            context, source_cid=source_cid
        ).items():
            rows.append(
                {
                    "inputKey": coordinate.wire(),
                    "observedEventType": (
                        f"{type(resolution).__module__}.{type(resolution).__qualname__}"
                    ),
                    "outcome": context_manager_resolution_outcome(resolution),
                }
            )
    return sorted(rows, key=lambda row: json.dumps(row["inputKey"], sort_keys=True))


def _with_census_partition(
    cm_resolution_rows: list[dict[str, Any]],
    ast_sites: Counter[str],
    unrecognized_kinds: Counter[str] | None = None,
) -> dict[str, Any]:
    """Preserve coordinate keys while splitting constructed/unconstructed."""
    del unrecognized_kinds
    from compose_control_effect_board import (
        STAGE_WITH_TALLY_PARTITION,
        key_edge_witness,
    )

    constructed_rows = [
        dict(row) for row in cm_resolution_rows if row.get("outcome") == "constructed"
    ]
    unconstructed_rows = [
        dict(row) for row in cm_resolution_rows if row.get("outcome") == "unconstructed"
    ]
    if len(constructed_rows) + len(unconstructed_rows) != len(cm_resolution_rows):
        raise TypeError("With partition received a row outside its closed outcomes")
    input_keys = [dict(row["inputKey"]) for row in cm_resolution_rows]
    output_rows = [*constructed_rows, *unconstructed_rows]
    output_keys = [dict(row["inputKey"]) for row in output_rows]
    edge_witness = key_edge_witness(
        stage_id=STAGE_WITH_TALLY_PARTITION,
        input_keys=input_keys,
        output_keys=output_keys,
    )
    if (
        edge_witness["missingKeys"]
        or edge_witness["extraKeys"]
        or edge_witness["duplicateKeys"]
    ):
        raise TypeError(
            "With coordinate-key partition does not conserve: "
            f"missing={edge_witness['missingKeys']} "
            f"extra={edge_witness['extraKeys']} "
            f"duplicate={edge_witness['duplicateKeys']}"
        )
    total = int(ast_sites.get("site:with-item", 0))
    constructed = len(constructed_rows)
    unconstructed = len(unconstructed_rows)
    accounted = constructed + unconstructed
    if accounted != total:
        unaccounted = total - accounted
        raise ValueError(
            "With census does not conserve. "
            f"LAW: {WITH_CENSUS_CONSERVATION_IDENTITY}. "
            f"REFUSED: with_items_total={total} constructed={constructed} "
            f"unconstructed={unconstructed} accounted={accounted} "
            f"unaccounted={unaccounted}. "
            "Construct or panic — fix the partition or write the missing construction."
        )
    return {
        "conservationIdentity": WITH_CENSUS_CONSERVATION_IDENTITY,
        "edgeWitness": edge_witness,
        "constructedRows": constructed_rows,
        "unconstructedRows": unconstructed_rows,
        "with_items_total": total,
        "constructed": constructed,
        "unconstructed": unconstructed,
        "accounted": accounted,
        "unaccounted": 0,
        "reconciliation": (
            f"{total} = {constructed} constructed + {unconstructed} unconstructed"
        ),
        "conserves": True,
    }


def _attested_cm_counts(result: dict[str, Any]) -> tuple[int, int]:
    with_census = result.get("withCensus")
    if not isinstance(with_census, dict):
        raise ValueError("CM zero lacks key attestation")
    edge = with_census.get("edgeWitness")
    if not isinstance(edge, dict) or edge.get("missingKeys") or edge.get("extraKeys"):
        raise ValueError("CM zero lacks conserving key attestation")
    return int(with_census.get("constructed", 0)), int(
        with_census.get("unconstructed", 0)
    )


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
    """RETIRED side door — not on the scoreboard path.

    Production terminals: ``recensus_enumerate_consumer.measure_file_via_enumerate``
    (sugar.enumerate only). Law:
    ``protocol/specs/2026-08-02-recensus-as-enumerate-consumer.md``.
    """
    raise RuntimeError(
        "control_effect_recensus._measure_file is a retired side door "
        "(protocol/specs/2026-08-02-recensus-as-enumerate-consumer.md). "
        "Use sugar.enumerate via recensus_enumerate_consumer; "
        "do not re-open a private SourceFile walk."
    )


def _is_process_control(error: BaseException) -> bool:
    """Never swallow process death as a per-file terminal."""
    return isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit))


def _render_terminal_category(row: Mapping[str, Any]) -> str:
    """Render a terminal without discarding instrument-failure testimony."""
    category = row.get("category")
    if category:
        return str(category)
    failure = row.get("instrumentFailure")
    if isinstance(failure, Mapping):
        return (
            "instrument-failure "
            f"stageId={failure.get('stageId', '?')} "
            f"phase={failure.get('phase', '?')} "
            f"message={failure.get('message', '?')}"
        )
    return "?"


def terminal_after_measure_escape(
    *,
    path: Path,
    relative: str,
    workspace_root: Path,
    error: BaseException,
    category: str = "panic",
) -> dict[str, Any]:
    """Outer-shell law: never bank 0 when roster/AST mass is recoverable.

    measure_file_via_enumerate must not raise after a roster bank — but when
    anything escapes (new BaseException subclass, consumer refactor, outer
    path), this shell must bank the recoverable population and name the
    escape as residual. Banking functionsTotal=0 over known mass is the
    #7073 mass-erase class with a timer on it.
    """
    try:
        from recensus_enumerate_consumer import (
            count_ast_function_defs,
            demand_function_roster,
            terminal_from_enumerate,
        )
    except ImportError:
        # Consumer itself cannot load — true empty instrument path.
        return {
            "category": category,
            "defect": {
                "file": relative,
                "type": type(error).__name__,
                "message": str(error),
                "phase": "outer-shell-escape",
            },
            "functionsTotal": 0,
            "functionsEnumerated": 0,
            "functionsClean": None,
            "cleanRatioRefused": True,
            "cleanRefuseReason": "consumer import failed; clean not measured",
            "families": {f"outer-escape:{type(error).__name__}": 1},
            "enumerateSource": True,
        }

    function_nodes: list[dict[str, Any]] = []
    try:
        function_nodes, _gaps = demand_function_roster(
            workspace_root=workspace_root,
            file_rel=relative,
        )
    except ConstructionPanic:
        raise
    except BaseException as roster_err:
        if _is_process_control(roster_err):
            raise
        function_nodes = []

    ast_fn = count_ast_function_defs(path)
    if function_nodes:
        # Recovered D2 roster — bank full mass, residual is the outer escape.
        return terminal_from_enumerate(
            file_rel=relative,
            function_nodes=function_nodes,
            function_gaps=[],
            audit=None,
            construction_gaps=[],
            residual_phase_failed=True,
            residual_error=error,
            ast_fn=ast_fn,
        )

    # No D2 nodes — AST mass still forbids silent zero when the file has defs.
    bank = int(ast_fn) if ast_fn is not None else 0
    return {
        "category": category,
        "defect": {
            "file": relative,
            "type": type(error).__name__,
            "message": str(error),
            "phase": "outer-shell-escape",
        },
        "functionsTotal": bank,
        "functionsEnumerated": 0,
        "functionsNotEnumerated": bank,
        "functionsEnumerationComplete": False,
        "functionsClean": None if bank > 0 else 0,
        "cleanRatioRefused": bank > 0,
        "cleanRefuseReason": (
            "outer shell escape; clean not measured" if bank > 0 else None
        ),
        "functionsAuthenticated": bank,
        "astSites": {"site:function-def": bank} if bank else {},
        "rosterPreservedAfterResidualFailure": bank > 0,
        "families": {f"outer-escape:{type(error).__name__}": 1},
        "enumerateSource": True,
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
    parser.add_argument(
        "--plan-json",
        type=Path,
        default=None,
        help=(
            "LPT shard plan (planCid). With --shard-index, measure only that bin "
            "and emit a partial (never a sealed board)."
        ),
    )
    parser.add_argument(
        "--shard-index",
        type=int,
        default=None,
        help="shard seat to measure (requires --plan-json); writes partial only",
    )
    parser.add_argument(
        "--partial-out",
        type=Path,
        default=None,
        help="where to write the shard partial JSON (default: <out-dir>/partial-sXX.json)",
    )
    parser.add_argument(
        "--demand-table-path",
        type=Path,
        default=None,
        help=(
            "load a plan-time prebuilt provisional demand table (content-addressed). "
            "Shards MUST use this so cold processes do not re-walk 1421 files. "
            "Corpus pin on the table must match the observed pin or refuse."
        ),
    )
    parser.add_argument(
        "--write-demand-table",
        type=Path,
        default=None,
        help=(
            "after deriving the provisional demand table once, write the "
            "content-addressed artifact for shards to load"
        ),
    )
    args = parser.parse_args()
    if args.shard_index is not None and args.plan_json is None:
        parser.error("--shard-index requires --plan-json")
    if args.plan_json is not None and args.shard_index is None:
        parser.error("--plan-json requires --shard-index for worker mode")

    # Runtime identity is producer identity. Authenticate it before corpus
    # selection, demand derivation, checkpoints, or any construction stage.
    from compose_control_effect_board import (
        resolve_executing_runtime_attestation,
        unmeasured_envelope,
    )

    runtime_attestation, runtime_failure = resolve_executing_runtime_attestation()
    if runtime_attestation is None:
        result_path = args.json or (args.out_dir / "recensus.json")
        result = unmeasured_envelope(
            plan=None,
            missing_shards=["runtime"],
            unmeasured_reasons={
                "runtime": str(
                    runtime_failure.get("runtimeIdentityFailure")
                    or runtime_failure.get("runtimeIdentityMismatch")
                    or "runtimeIdentity/v1 refused"
                )
            },
            measured_commit=args.commit,
            runtime_failure=runtime_failure,
        )
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 2

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
        # Exit 78: corpus pin gate — distinct from generic instrument failure (2).
        # A number against the wrong pandas is not a measurement.
        print(str(defect), file=sys.stderr, flush=True)
        print(
            "control_effect_recensus: crime=corpus-pin-mismatch exit=78 "
            "(use .venv-py312 pandas==3.0.3 fileCount=1421; never system 2.3.3/1415)",
            file=sys.stderr,
            flush=True,
        )
        return 78
    except ValueError as defect:
        # Declared pandas 3.0.3 aggregate / shape CID refusal — same class as pin.
        print(str(defect), file=sys.stderr, flush=True)
        print(
            "control_effect_recensus: crime=corpus-pin-mismatch exit=78",
            file=sys.stderr,
            flush=True,
        )
        return 78
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
    # Shard worker mode: measure only plan.bins[shard_index]; never seal here.
    shard_plan: dict[str, Any] | None = None
    if args.plan_json is not None:
        shard_plan = json.loads(args.plan_json.read_text(encoding="utf-8"))
        assert args.shard_index is not None
        k = int(shard_plan["shardCount"])
        if args.shard_index < 0 or args.shard_index >= k:
            parser.error(
                f"--shard-index {args.shard_index} out of range for plan k={k}"
            )
        assigned = list(shard_plan["bins"][args.shard_index])
        unknown = sorted(set(assigned) - set(file_names))
        if unknown:
            parser.error(f"plan bin contains files not in this walk: {unknown[:5]}")
        file_names = [f for f in file_names if f in set(assigned)]
        by_file = {f: by_file[f] for f in file_names}
        _narrate(
            "RECENSUS SHARD WORKER "
            f"shard={args.shard_index}/{k} assigned={len(assigned)} "
            f"planCid={shard_plan.get('planCid')} "
            f"(partial only — seal is compose_control_effect_board)"
        )
    pending: list[str] = list(file_names)

    # One provisional demand→gap table for the whole corpus ROOT. Shared across
    # files; each file still gets a fresh TreeConstructionContextV1 so
    # source-derived manager refs do not leak between files. Deriving this from
    # anything but the root is the corpus-context drift defect.
    #
    # k=8 law: the walk is O(corpus) per cold process. Plan time derives once
    # and writes a content-addressed artifact; every shard LOADS it so D2 never
    # re-walks. Process memo alone is not enough — each shard is a new process.
    from sugar_lift_py_tests.lift_rpc import install_provisional_contract_refs
    from sugar_lift_py_tests.prebuilt_demand_table import (
        DemandTableArtifactRefusal,
        DemandTablePinMismatch,
        install_prebuilt_demand_table,
        load_prebuilt_demand_table,
        mint_prebuilt_demand_table,
        write_prebuilt_demand_table,
    )

    def publish_demand_table(table, path: Path) -> None:
        """Publish the derived payload through the authenticated CAS door."""
        repo_root = Path(__file__).resolve().parents[4]
        completed = subprocess.run(
            [
                str(repo_root / "bin" / "sugarbin"),
                "artifact", "publish", "--kind", "python-demand-table",
                "--content-key", table.content_cid, "--input", str(path),
                "--runtime", "cpython-3.12.13",
            ],
            cwd=repo_root, capture_output=True, text=True, check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[:800]
            raise DemandTableArtifactRefusal(
                "python-demand-table CAS publication refused: "
                f"contentCid={table.content_cid} exit={completed.returncode} "
                f"detail={detail}"
            )
        _narrate(
            "RECENSUS DEMAND_TABLE published CAS "
            f"contentCid={table.content_cid} runtime=cpython-3.12.13"
        )

    pin_identity = {
        "distribution": observed_pin.distribution,
        "version": observed_pin.version,
        "fileCount": observed_pin.file_count,
        "aggregateHash": observed_pin.aggregate_hash,
    }
    demand_table_cid: str | None = None
    # Plan may carry demandTableCid / demandTablePath for shard workers.
    plan_demand_path = args.demand_table_path
    plan_demand_cid = None
    if shard_plan is not None:
        plan_demand_cid = shard_plan.get("demandTableCid")
        if plan_demand_path is None and shard_plan.get("demandTablePath"):
            plan_demand_path = Path(str(shard_plan["demandTablePath"]))

    if plan_demand_path is not None:
        _narrate(
            f"RECENSUS DEMAND_TABLE loading prebuilt path={plan_demand_path} "
            f"planCid={plan_demand_cid or 'none'}"
        )
        try:
            prebuilt = load_prebuilt_demand_table(
                plan_demand_path,
                expected_corpus_pin=pin_identity,
                expected_content_cid=plan_demand_cid,
            )
        except (DemandTablePinMismatch, DemandTableArtifactRefusal) as refuse:
            print(str(refuse), file=sys.stderr, flush=True)
            return 78
        contract_refs = _phase_call(
            "demand_table_load",
            lambda: install_prebuilt_demand_table(prebuilt, root=workspace_root),
        )
        demand_table_cid = prebuilt.content_cid
        _narrate(
            "RECENSUS DEMAND_TABLE loaded "
            f"contentCid={demand_table_cid} rows={len(prebuilt.rows)} "
            f"(zero corpus walk)"
        )
    else:
        # Demand-table walk can take minutes with only a BEGIN/END pair — that
        # is blind by construction. Alive heartbeats every ≤30s hit the job log.
        _narrate(
            f"RECENSUS DEMAND_TABLE deriving provisional refs from "
            f"workspace_root={workspace_root}"
        )

        def _derive_and_maybe_write():
            from sugar_lift_py_tests.authenticated_pytest import (
                AuthenticatedPandasCorpus,
            )

            authenticated_corpus = AuthenticatedPandasCorpus(
                root=workspace_root,
                distribution=observed_pin.distribution,
                version=observed_pin.version,
                manifest_cid=observed_pin.aggregate_hash,
                file_count=observed_pin.file_count,
            )
            table = mint_prebuilt_demand_table(
                authenticated_corpus,
            )
            write_path = args.write_demand_table
            if write_path is None and args.out_dir is not None:
                # Default artifact next to board outputs so shards can find it.
                write_path = Path(args.out_dir) / "provisional-demand-table.json"
            temporary_path = None
            if write_path is None:
                handle = tempfile.NamedTemporaryFile(
                    prefix="python-demand-table-", suffix=".json", delete=False
                )
                temporary_path = Path(handle.name)
                handle.close()
                write_path = temporary_path
            write_prebuilt_demand_table(table, write_path)
            _narrate(
                f"RECENSUS DEMAND_TABLE wrote path={write_path} "
                f"contentCid={table.content_cid}"
            )
            try:
                publish_demand_table(table, write_path)
            except DemandTableArtifactRefusal as refuse:
                # Derivation is authenticated product input; CAS publication
                # is only a sharing optimisation. Keep the local table, but
                # never claim it was published or install it as a cache hit.
                _narrate(
                    "RECENSUS DEMAND_TABLE CAS publication refused after "
                    f"successful derivation; continuing locally: {refuse}"
                )
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            refs = install_prebuilt_demand_table(table, root=workspace_root)
            return refs, table.content_cid

        contract_refs, demand_table_cid = _phase_call(
            "demand_table_derivation",
            _derive_and_maybe_write,
        )
        # Also keep the process memo path warm for any code that still calls
        # provisional_contract_refs_from_demands directly.
        install_provisional_contract_refs(workspace_root, contract_refs)
        _narrate(
            "RECENSUS DEMAND_TABLE ready "
            f"(type={type(contract_refs).__name__} contentCid={demand_table_cid})"
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
    # designed-gap taxonomy deleted — panics only
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
        except ImportError:  # pragma: no cover
            print(
                "RECENSUS: tqdm unavailable; proceeding without progress display",
                file=sys.stderr,
                flush=True,
            )

            class _NoProgress:
                def __init__(self, iterable, **_kwargs):
                    self._iterable = iterable

                def __iter__(self):
                    return iter(self._iterable)

                def update(self, _count=1):
                    del _count

                def set_postfix(self, _postfix, **_kwargs):
                    del _postfix, _kwargs

                def close(self):
                    pass

            def tqdm(iterable, **kwargs):
                return _NoProgress(iterable, **kwargs)

        live_done = 0
        live_panic = 0  # ConstructionPanic only (file-level kit panic)
        live_defect = 0
        live_fns = 0
        live_clean = 0
        live_clean_refused = False  # any file refused clean → no clean% identity
        live_snw = 0  # SugarNotWritten (missing sugar)
        live_other_gaps = 0  # other typed gaps (e.g. RuntimeSelectedContextManager)
        already_done = len(file_names) - len(pending)
        # Seed running totals from checkpoint so resume doesn't look like "0 gaps".
        if checkpoint is not None and already_done:
            for crow in checkpoint.rows():
                raw = crow.get("result") or {}
                cat = str(raw.get("category") or "")
                live_fns += int(raw.get("functionsTotal") or 0)
                _seed_clean = raw.get("functionsClean")
                if raw.get("cleanRatioRefused") or (
                    _seed_clean is None and int(raw.get("functionsTotal") or 0) > 0
                ):
                    live_clean_refused = True
                elif _seed_clean is not None:
                    live_clean += int(_seed_clean)
                # NOT `families`: that name is main's accumulating Counter, and
                # rebinding it to this plain dict made the later
                # `families["ConstructionPanic"] += 1` a KeyError crash — the whole
                # run lost, at the exact moment a panic row appeared.
                row_families = raw.get("families") or {}
                live_snw += int(row_families.get("SugarNotWritten") or 0)
                live_other_gaps += sum(
                    int(v) for k, v in row_families.items() if k != "SugarNotWritten"
                )
                if cat == "panic":
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
            if (
                force
                and now - _last_progress_stdout < 2.0
                and status
                in {
                    "done",
                    "cpanic",
                }
            ):
                # Allow dense end-of-file lines without flooding.
                pass
            _last_progress_stdout = now
            n = getattr(bar, "n", live_done)
            total = getattr(bar, "total", len(file_names)) or len(file_names)
            bits = " ".join(f"{k}={v}" for k, v in postfix.items())
            _narrate(f"RECENSUS PROGRESS {n}/{total} {bits}")

        lpt_prior_rows: list[tuple[Path, float, str]] = []
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
                        f"fn_clean/total="
                        f"{'?' if live_clean_refused else live_clean}/{live_fns}"
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
                    # Never mint identity clean% when clean is refused.
                    shown_fns = live_fns + in_total
                    if live_clean_refused:
                        fn_disp = f"?/{shown_fns}"
                        clean_disp = "n/a"
                    else:
                        shown_clean = live_clean + in_clean
                        fn_disp = f"{shown_clean}/{shown_fns}"
                        clean_disp = (
                            f"{(100.0 * shown_clean / shown_fns):.0f}"
                            if shown_fns
                            else "0"
                        )
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
                        "fn": fn_disp,
                        "clean%": clean_disp,
                    }
                    _set_bars(post, refresh=True)

                try:
                    # AUTHORITY: sugar.enumerate only. No private SourceFile walk.
                    # workspace_root for enumerate is the corpus root; at.file is
                    # the path relative to that root (not the pin-prefixed key).
                    from recensus_enumerate_consumer import (
                        _instrument_failure_row,
                        measure_file_via_enumerate,
                    )

                    row = measure_file_via_enumerate(
                        workspace_root=corpus_root,
                        file_rel=relative,
                        contract_refs=contract_refs,
                        distribution=observed_pin.distribution,
                        source_workspace_root=locus_root,
                    )
                    if row.get("terminalKind") in {
                        "constructed",
                        "construction-panic",
                    }:
                        source_cid = str((row.get("inputKey") or {}).get("sourceCid"))
                        resolution_rows = _tally_cm_resolutions(
                            source_cid=source_cid,
                            resolution_events=list(
                                row.pop("contextManagerResolutionEvents", [])
                            ),
                        )
                        sites = _ast_site_prevalence(path)
                        with_partition = _with_census_partition(resolution_rows, sites)
                        row["withResolutionRows"] = resolution_rows
                        row["cmResolutions"] = {
                            "constructed": with_partition["constructed"],
                            "unconstructed": with_partition["unconstructed"],
                        }
                        row["astSites"] = dict(sites)
                        from compose_control_effect_board import EDGE_WITH_PARTITION

                        row.setdefault("edgeWitnesses", {})[EDGE_WITH_PARTITION] = (
                            with_partition["edgeWitness"]
                        )
                except ConstructionPanic:
                    raise
                except BaseException as error:  # noqa: BLE001 -- per-file terminal
                    if _is_process_control(error):
                        raise
                    row = _instrument_failure_row(
                        error,
                        file_rel=relative,
                        phase="main-file-producer",
                        source_cid=None,
                        function_nodes=[],
                        functions_total=int(
                            _ast_site_prevalence(path).get("site:function-def", 0)
                        ),
                        functions_enumerated=0,
                    )
                file_s = time.perf_counter() - t_file
                checkpoint.append(file, row)
                measured_now.append((file, row))

                cat = _render_terminal_category(row)
                fn = int(row.get("functionsTotal") or 0)
                # functionsClean may be null when clean ratio is refused.
                # Law: never treat null clean as 0-of-N and mint clean%=100.
                _raw_clean = row.get("functionsClean")
                if row.get("cleanRatioRefused") or (_raw_clean is None and fn > 0):
                    live_clean_refused = True
                    clean = 0
                else:
                    clean = int(_raw_clean) if _raw_clean is not None else 0
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
                if not live_clean_refused:
                    live_clean += clean
                live_snw += snw
                live_other_gaps += other
                live_done += 1
                if cat == "panic":
                    live_panic += 1
                    status = "cpanic"
                elif cat == "completed":
                    status = "done"
                else:
                    live_defect += 1
                    status = cat

                # ANY RATIO WHOSE NUMERATOR DEFAULTS TO ITS DENOMINATOR IS NOT
                # A MEASUREMENT. Refuse clean% when clean is unmeasured.
                if live_clean_refused:
                    fn_display = f"?/{live_fns}"
                    clean_pct_display = "n/a"
                else:
                    fn_display = f"{live_clean}/{live_fns}"
                    clean_pct_display = (
                        f"{(100.0 * live_clean / live_fns):.0f}" if live_fns else "0"
                    )
                _set_bars(
                    {
                        "file": relative,
                        "status": status,
                        "last": f"{file_s:.2f}s",
                        "snw": live_snw,
                        "gaps": live_other_gaps,
                        "cpanic": live_panic,
                        "defect": live_defect,
                        "fn": fn_display,
                        "clean%": clean_pct_display,
                    },
                    refresh=True,
                )
                if live_bar is not None:
                    live_bar.update(1)

                # Durable running counts — crash at file 900 still leaves 899 rows
                # on checkpoint AND a jsonl tail of counts on stdout-equivalent disk.
                # Phase timers + module materialize counts PERSIST here (not only
                # on the progress bar — that was measured, displayed, thrown away).
                row_timing = row.get("timing") if isinstance(row, dict) else None
                if not isinstance(row_timing, dict):
                    row_timing = {}
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
                    "t_open_s": row_timing.get("t_open_s"),
                    "t_materialize_s": row_timing.get("t_materialize_s"),
                    "materialize_calls": row_timing.get("materialize_calls"),
                    "t_populate_s": row_timing.get("t_populate_s"),
                    "t_enumerate_s": row_timing.get("t_enumerate_s"),
                    "t_sugar_loop_s": row_timing.get("t_sugar_loop_s"),
                    "t_context_s": row_timing.get("t_context_s"),
                    "t_cm_tally_s": row_timing.get("t_cm_tally_s"),
                    "t_gap_tally_s": row_timing.get("t_gap_tally_s"),
                    "dominant_phase": row_timing.get("dominant_phase"),
                    "dominant_phase_s": row_timing.get("dominant_phase_s"),
                    "slowest_fn": row_timing.get("slowest_fn"),
                    "slowest_fn_s": row_timing.get("slowest_fn_s"),
                    "module_materialize": row_timing.get("module_materialize"),
                }
                with running_counts_path.open("a", encoding="utf-8") as rc_stream:
                    rc_stream.write(
                        json.dumps(running, sort_keys=True, separators=(",", ":"))
                        + "\n"
                    )
                    rc_stream.flush()
                # Buffer LPT prior rows — flush once at shard end (not per file).
                # put_for_path re-reads full source bytes for the content CID and
                # does an atomic json write; doing that on the lift hot path under
                # k=8 concurrent seats interleaved disk with Materialize. No
                # flock/fsync, but the re-read+write storm is real volume. Law
                # is unchanged: every file_s still lands on the shelf before the
                # process exits the lift phase.
                lpt_prior_rows.append((path, file_s, relative))
                # One-line cause for slow files (always for first/last/every-N,
                # and always when wall exceeds 5s so a long open names its phase).
                slow = file_s >= 5.0
                if (
                    live_done == 1
                    or live_done % _PROGRESS_EVERY_N == 0
                    or live_done == len(file_names)
                    or slow
                ):
                    mm = row_timing.get("module_materialize") or {}
                    _narrate(
                        "RECENSUS FILE END "
                        f"{live_done}/{len(file_names)} file={relative} "
                        f"category={cat} file_s={file_s:.3f} "
                        f"dominant={row_timing.get('dominant_phase')}:"
                        f"{row_timing.get('dominant_phase_s')}s "
                        f"open={row_timing.get('t_open_s')}s "
                        f"materialize={row_timing.get('t_materialize_s')}s "
                        f"materialize_calls={row_timing.get('materialize_calls')} "
                        f"populate={row_timing.get('t_populate_s')}s "
                        f"enumerate={row_timing.get('t_enumerate_s')}s "
                        f"sugar_loop={row_timing.get('t_sugar_loop_s')}s "
                        f"slowest_fn={row_timing.get('slowest_fn')}:"
                        f"{row_timing.get('slowest_fn_s')}s "
                        f"mod_mat_calls={mm.get('materializeCalls')} "
                        f"mod_mat_s={mm.get('materialize_s')} "
                        f"mod_top={mm.get('top')} "
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
            # LPT prior write-through: once per shard/process, not per file.
            # #7040 law — every measured file_s on the shelf; #7082 put the door
            # on the hot path; batch so concurrent seats do not re-read source
            # + write-write mid-lift (blonde 3.26× inflation suspect). Flush in
            # finally so a mid-walk abort still banks what was measured.
            if lpt_prior_rows:
                try:
                    from lpt_file_shards import ContentAddressedCostPrior

                    prior = ContentAddressedCostPrior()
                    written = 0
                    for pth, cost, hint in lpt_prior_rows:
                        if prior.put_for_path(
                            pth,
                            cost,
                            source="control-effect-recensus",
                            path_hint=hint,
                        ):
                            written += 1
                    _narrate(
                        "JOB_LOG phase=lpt-prior-write population=control-effect-recensus "
                        f"status=ok files_written={written} files_buffered={len(lpt_prior_rows)} "
                        f"mode=batch-end-of-lift prior_root={prior.root}"
                    )
                except Exception as exc:  # noqa: BLE001 — prior must not kill scan
                    _narrate(
                        "JOB_LOG phase=lpt-prior-write population=control-effect-recensus "
                        f"status=failed reason={type(exc).__name__}:{exc} "
                        "mode=batch-end-of-lift degraded=shelf-stale-next-plan"
                    )
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
        if not isinstance(raw, dict)
        or (not raw.get("category") and not raw.get("instrumentFailure"))
    )

    for file, raw in measured_rows:
        row = dict(raw)
        category = str(row.get("category"))
        floor_rows.append({"file": file, "category": category})
        functions_total += int(row.get("functionsTotal") or 0)
        # Null clean is refusal, not zero — do not collapse into 0-of-total.
        _agg_clean = row.get("functionsClean")
        if _agg_clean is not None and not row.get("cleanRatioRefused"):
            functions_clean += int(_agg_clean)
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
        if row.get("instrumentFailure"):
            continue
        if category == "completed":
            files_completed += 1
        elif category == "panic":
            panic = row.get("panic")
            if isinstance(panic, dict):
                construction_panics.append(panic)
            defect = row.get("defect") or panic
            if isinstance(defect, dict):
                defects.append(dict(defect))
                if defect.get("owner") == "kit dispatch target":
                    unresolvable_dispatch.append(dict(defect))
            # Measure now enrolls ConstructionPanic into the row's families
            # (file-level BaseException path). Prefer that; only fill if a
            # legacy checkpoint row still omits it. Use get+assign so a plain
            # dict can never KeyError (Counter already tolerated missing keys).
            if "ConstructionPanic" not in (row.get("families") or {}):
                families["ConstructionPanic"] = (
                    int(families.get("ConstructionPanic") or 0) + 1
                )
        else:
            raise TypeError(
                "control-effect recensus terminal category must be completed or "
                f"panic; got {category!r} for {file}"
            )

    from pandas_floor_summary import floor_summary

    # Sole seal door — never mint measurementClass=control-effect-recensus here.
    from compose_control_effect_board import compose_k1_from_rows, mint_partial

    tip_commit = args.commit or _git_commit(args.repo) or "unpinned"

    # Shard worker: emit PARTIAL only (SCOREBOARD False). Compose is a separate step.
    if shard_plan is not None:
        assert args.shard_index is not None
        partial = mint_partial(
            plan=shard_plan,
            shard_index=args.shard_index,
            terminal_rows=measured_rows,
            measured_commit=tip_commit,
            runtime_attestation=runtime_attestation,
        )
        partial_path = args.partial_out or (
            out / f"partial-s{args.shard_index:02d}.json"
        )
        partial_path.parent.mkdir(parents=True, exist_ok=True)
        partial_path.write_text(
            json.dumps(partial, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _narrate(
            "RECENSUS PARTIAL WRITTEN "
            f"shard={args.shard_index} measured={partial.get('measured')} "
            f"status={partial.get('status')} partialCid={partial.get('partialCid')} "
            f"path={partial_path}"
        )
        # Exit 0/1 = scan completed (measured residual may be red later at compose);
        # exit 2 = unmeasured seat.
        return 0 if partial.get("measured") else 2

    # Default k=1: one full-bin partial + compose (serial observation, one seal path).
    seal_status, result = compose_k1_from_rows(
        measured_rows,
        enrolled_files=file_names,
        measured_commit=tip_commit,
        aggregate_hash=observed_pin.aggregate_hash,
        manifest_shape_cid=manifest_shape_cid,
        corpus=str(corpus),
        corpus_root=str(corpus_root),
        corpus_pin_summary=observed_pin.summary(),
        paths={
            "engineLog": str(engine_path.resolve()),
            "progress": str(progress_path.resolve()),
            "checkpoint": str(checkpoint_path.resolve()),
            "result": str(result_path.resolve()),
        },
        elapsed_seconds=time.time() - started,
        source_stamp={
            "commit": tip_commit,
            "repo": str(args.repo.resolve()),
            "python": sys.version,
            "platform": platform.platform(),
            "host": platform.node(),
            "loadAverage": list(os.getloadavg()) if hasattr(os, "getloadavg") else [],
            "measuredAtUnix": time.time(),
        },
        with_census_fn=_with_census_partition,
        manifest_cid=checkpoint.manifest_cid,
        runtime_attestation=runtime_attestation,
    )
    if seal_status != "sealed":
        _narrate(
            "RECENSUS COMPOSE UNMEASURED "
            f"missing={result.get('missingShards')} "
            f"reasons={result.get('unmeasuredReasons')}"
        )
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result, indent=2) + "\n")
        return 2

    denominator_complete, denominator_refusal = _consume_sealed_files_complete(
        result,
        measured_commit=tip_commit,
    )
    if denominator_refusal is not None:
        _narrate(
            "RECENSUS POST-COMPOSE UNMEASURED "
            f"reasons={denominator_refusal.get('unmeasuredReasons')}"
        )
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(denominator_refusal, indent=2) + "\n",
            encoding="utf-8",
        )
        return 2
    assert denominator_complete is True

    r_construction = int(result.get("R_construction") or 0)
    r_desugar = int(result.get("R_desugar") or 0)
    r_backend = int(result.get("R_backend_defects") or 0)
    construction_panics = list(result.get("constructionPanics") or [])
    defects = list(result.get("defects") or [])
    desugar_construction_panics = list(result.get("desugarConstructionPanics") or [])
    desugar_defects = list(result.get("desugarDefects") or [])
    unresolvable_dispatch = list(result.get("unresolvableDispatchTargets") or [])
    families = Counter(result.get("families") or {})
    desugar_families = Counter(result.get("desugarFamilies") or {})
    files_completed = int(result.get("filesCompleted") or 0)
    result["python"] = sys.version
    result["floorSummary"] = floor_summary(
        floor="control-effect",
        files=file_names,
        rows=floor_rows,
        totals={
            "R_control_effect": r_construction + len(defects),
            "R_desugar": r_desugar,
            "R_backend_defects": r_backend,
            "R_cm_derived_contract": _attested_cm_counts(result)[0],
            "desugarConstructionPanics": len(desugar_construction_panics),
            "desugarDefects": len(desugar_defects),
            "constructionPanics": len(construction_panics),
            "backendDefectsOrProcessTerminals": len(defects),
        },
        measured=len(floor_rows) == len(file_names),
        unmeasurable_reasons=(),
    )
    result["desugarDesignedGapOwners"] = dict(
        Counter(
            str(gap.get("owner", "?"))
            for gap in (result.get("desugarDesignedGaps") or [])
        )
    )

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
        "denominatorComplete": denominator_complete,
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
    if not denominator_complete:
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
        or not denominator_complete
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
