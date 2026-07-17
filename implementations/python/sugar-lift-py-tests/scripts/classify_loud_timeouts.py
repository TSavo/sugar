#!/usr/bin/env python3
"""Classify loud-bounded-timeout corpus files (#4894).

The #4775/#4872 recensus left 293 assertion-bearing NumPy+pandas files as a
single provisional timeout blob at a 10-second discovery bound. A loud timeout
is honest only when it is a host/bound artifact — not a product non-termination
masquerading as "didn't finish." This instrument re-measures each candidate
with escalating bounds (60s → 120s → 300s) and records an explicit verdict:

  - completes-at-bound: finished with IR payload at bound B (not wall panic mass)
  - completes-with-panic: typed FactoryPanic once given time (dispatchable fatal)
  - bare-exception: untyped exception once given time
  - hang-at-300s: still non-terminating at 300s (real budget-exceeded frontier)
  - other terminal: crash/signal/transport (must stay loud)

Hard law:
  - Timeout is NEVER silently reclassified as complete or dropped.
  - No panic/refusal weakened; no bound raised to invent green without recording slow.
  - Single-lane sequential replay only (no host parallelism).
  - Ledger is append-only JSONL so partial progress ships and residual R is measured.

Progress (macro hotspots — no guessing):
  - Children set SUGAR_ENGINE_LOG + SUGAR_ENGINE_PROGRESS so factory/sugar
    reduction_span heartbeats write JSONL while lifting.
  - On kill, each attempt carries last_progress: sugar_hotspots, last stack/site.
  - That answers "lift, and which sugar?" — not solve (this path never solves).
"""

from __future__ import annotations

import argparse
import ast
import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

# Reuse the production triage child + classifier so discovery and escalation
# share one terminal taxonomy with corpus_fatal_triage (#4775).
from corpus_fatal_triage import (  # type: ignore[import-not-found]
    PACKAGES,
    _classify_child,
    package_root,
    python_files,
)
from sugar_lift_py_tests.idd.factory_panic_fronts import (
    fingerprint_from_gap,
    rank_factory_panic_fronts,
)

DEFAULT_DISCOVERY_BOUND = 10
DEFAULT_ESCALATION_BOUNDS = (60, 120, 300)
PERF_CANDIDATE_THRESHOLD_SECONDS = 120
# #4775/#4872 recensus provisional timeout mass. Live rediscovery may differ;
# used as a residual floor until a pure timeout seed replaces it.
RECENSUS_TIMEOUT_BLOB_COUNT = 293

# Cause classes (#4894): every final timeout-blob verdict gets one explicit tag.
# Residual R = unclassified_timeout_blob + hang@300 (class D). Stable zero only
# when both are zero — hang is classified but remains product work until a
# budget-exceeded terminal exists.
CAUSE_CLASS_A_BOUND_TIGHT = "A"  # completes after bound > discovery (≤120s)
CAUSE_CLASS_B_HIDDEN_PANIC = "B"  # completes-with-panic → typed FactoryPanic
CAUSE_CLASS_C_PERF_COMPLETE = "C"  # completes-at-bound with elapsed/bound >120s
CAUSE_CLASS_D_HANG = "D"  # hang-at-max-bound at 300s
CAUSE_CLASS_E_BARE = "E"  # bare-exception after long work

CAUSE_CLASS_LABELS = {
    CAUSE_CLASS_A_BOUND_TIGHT: "bound-tight",
    CAUSE_CLASS_B_HIDDEN_PANIC: "hidden-panic",
    CAUSE_CLASS_C_PERF_COMPLETE: "perf-complete",
    CAUSE_CLASS_D_HANG: "hang",
    CAUSE_CLASS_E_BARE: "bare",
}


def _resolve_path(package: str, rel: str) -> Path:
    """Map ``package/relative/path.py`` to an on-disk file under the installed package."""
    if not rel.startswith(f"{package}/"):
        raise ValueError(f"rel {rel!r} does not start with package {package!r}")
    root = package_root(package)
    return root / rel[len(package) + 1 :]


def _assert_count(path: Path) -> int:
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source, filename=str(path))
    return sum(isinstance(node, ast.Assert) for node in ast.walk(tree))


def enumerate_assertion_files(
    packages: tuple[str, ...] = PACKAGES,
) -> list[tuple[str, Path, str]]:
    """Return (package, absolute_path, rel) for every assertion-bearing file."""
    rows: list[tuple[str, Path, str]] = []
    for package in packages:
        root = package_root(package)
        for path in python_files(root):
            rel = f"{package}/{path.relative_to(root).as_posix()}"
            if _assert_count(path) == 0:
                continue
            rows.append((package, path, rel))
    return rows


def load_file_list(path: Path) -> list[str]:
    """Load relative paths (one per line, or JSON array / {files:[...]})."""
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if stripped.startswith("[") or stripped.startswith("{"):
        payload = json.loads(stripped)
        if isinstance(payload, list):
            return [str(item) for item in payload]
        if isinstance(payload, dict):
            files = payload.get("files") or payload.get("timeout_files") or []
            return [str(item) for item in files]
        raise ValueError(f"unsupported JSON shape in {path}")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def already_classified(ledger_path: Path) -> set[str]:
    """Resume set: files that already have a final ledger verdict."""
    if not ledger_path.is_file():
        return set()
    done: set[str] = set()
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("verdict") and row.get("file"):
            done.add(str(row["file"]))
    return done


def append_ledger(ledger_path: Path, row: dict[str, Any]) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
        handle.flush()


def _phase_from_role(role: str | None) -> str:
    """Bisection bucket from span role.

    First cut: factory vs reduce vs file.
    Second cut (inside factory wall): dig.* vs factory.select vs factory.new.*.
    """
    text = str(role or "")
    if text.startswith("dig."):
        return "dig"
    if text.startswith("factory.select"):
        return "factory_select"
    if text.startswith("factory.new") or text.startswith("factory."):
        return "factory_new"
    if text == "file":
        return "file"
    if text:
        return "reduce"
    return "other"


def extract_progress_from_engine_log(
    path: Path, *, last_n: int = 12
) -> dict[str, Any] | None:
    """Macro hotspot summary from ``sugar.engine.log.v1`` JSONL (no guessing).

    First-cut bisection answers (not a profiler guess):
      - phase_ms / phase_share: factory construct vs SugarBody.reduce wall
        from completed span exits (elapsed_ms)
      - sugar_hotspots: heartbeat primary sugar (deepest live frame)
      - exit_sugar_ms: completed-span wall by sugar name (where time *finished*)
      - last_heartbeat / active_stack: where the kill still was

    Bisect method: open the dominant phase, then the dominant sugar, then add
    tighter spans inside that path until the quadratic shows.
    """
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("schema") == "sugar.engine.log.v1":
            events.append(payload)
    if not events:
        return {
            "event_count": 0,
            "heartbeat_count": 0,
            "sugar_hotspots": [],
            "exit_sugar_ms": [],
            "phase_ms": {},
            "phase_share": {},
            "last_heartbeat": None,
            "recent": [],
        }
    heartbeats = [event for event in events if event.get("event") == "heartbeat"]
    exits = [event for event in events if event.get("event") == "exit"]
    sugar_counts: Counter[str] = Counter(
        str(event.get("sugar") or "?") for event in heartbeats
    )
    # Completed-span wall: sum exit elapsed_ms by sugar and by phase.
    # Nested spans double-count wall; use phase_share only for ranking buckets.
    exit_ms_by_sugar: Counter[str] = Counter()
    phase_ms: Counter[str] = Counter()
    role_ms: Counter[str] = Counter()
    dig_target_ms: Counter[str] = Counter()
    for event in exits:
        try:
            ms = float(event.get("elapsed_ms") or 0.0)
        except (TypeError, ValueError):
            ms = 0.0
        if ms <= 0:
            continue
        sugar = str(event.get("sugar") or "?")
        role = (
            event.get("role")
            if isinstance(event.get("role"), str)
            else str(event.get("role") or "")
        )
        exit_ms_by_sugar[sugar] += ms
        phase = _phase_from_role(role)
        phase_ms[phase] += ms
        role_ms[role or "?"] += ms
        if phase == "dig":
            dig_target_ms[sugar] += ms
    # Heartbeat phase votes (live stack tips during hang).
    heartbeat_phase: Counter[str] = Counter(
        _phase_from_role(
            event.get("role")
            if isinstance(event.get("role"), str)
            else str(event.get("role") or "")
        )
        for event in heartbeats
    )
    heartbeat_role: Counter[str] = Counter(
        str(event.get("role") or "?") for event in heartbeats
    )
    total_phase = sum(phase_ms.values()) or 0.0
    phase_share = {
        name: round(ms / total_phase, 4) if total_phase else 0.0
        for name, ms in phase_ms.items()
    }
    recent = (heartbeats or events)[-last_n:]
    last_hb = heartbeats[-1] if heartbeats else None
    return {
        "event_count": len(events),
        "heartbeat_count": len(heartbeats),
        "sugar_hotspots": [
            {"sugar": name, "heartbeat_count": count}
            for name, count in sugar_counts.most_common(12)
        ],
        "exit_sugar_ms": [
            {"sugar": name, "elapsed_ms": round(ms, 1)}
            for name, ms in exit_ms_by_sugar.most_common(12)
        ],
        "phase_ms": {name: round(ms, 1) for name, ms in phase_ms.most_common()},
        "phase_share": phase_share,
        "role_ms": {name: round(ms, 1) for name, ms in role_ms.most_common(16)},
        "dig_target_ms": [
            {"target": name, "elapsed_ms": round(ms, 1)}
            for name, ms in dig_target_ms.most_common(12)
        ],
        "heartbeat_phase_counts": dict(heartbeat_phase),
        "heartbeat_role_counts": dict(heartbeat_role),
        "last_heartbeat": last_hb,
        "recent": recent,
    }


def run_child_at_bound(
    *,
    script: Path,
    path: Path,
    rel: str,
    timeout_seconds: int,
    engine_log_dir: Path | None = None,
) -> dict[str, Any]:
    """Run one file in a child process with a hard wall clock bound.

    When ``engine_log_dir`` is set (default: temp under system tmp for each
    call when env SUGAR_ENGINE_PROGRESS is not ``0``), the child writes engine
    heartbeats to a per-run JSONL. On timeout the parent attaches
    ``last_progress`` (macro sugar hotspots + last stack) so the kill is not
    a blind stopwatch.
    """
    command = [
        sys.executable,
        str(script),
        "--child-file",
        str(path),
        "--child-rel",
        rel,
    ]
    env = dict(os.environ)
    env["PYTHONFAULTHANDLER"] = "1"
    progress_off = (env.get("SUGAR_ENGINE_PROGRESS") or "").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }
    log_path: Path | None = None
    if not progress_off:
        import tempfile

        if engine_log_dir is not None:
            engine_log_dir.mkdir(parents=True, exist_ok=True)
            safe = rel.replace("/", "__").replace("\\", "__")
            log_path = engine_log_dir / f"{safe}.{timeout_seconds}s.engine.jsonl"
        else:
            fd, name = tempfile.mkstemp(prefix="sugar-engine-", suffix=".jsonl")
            os.close(fd)
            log_path = Path(name)
        env["SUGAR_ENGINE_LOG"] = str(log_path)
        env["SUGAR_ENGINE_PROGRESS"] = "1"
        # Fast heartbeats under short discovery bounds so 10s kills still have stacks.
        env.setdefault("SUGAR_ENGINE_HEARTBEAT_SECONDS", "2")
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            env=env,
            check=False,
        )
        elapsed = time.monotonic() - started
        row = _classify_child(
            rel=rel,
            result=result,
            timed_out=False,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - started
        row = _classify_child(
            rel=rel,
            result=None,
            timed_out=True,
            timeout_seconds=timeout_seconds,
        )
    row["bound_seconds"] = timeout_seconds
    row["elapsed_seconds"] = round(elapsed, 3)
    if log_path is not None:
        progress = extract_progress_from_engine_log(log_path)
        if progress is not None:
            row["last_progress"] = progress
            if row.get("category") == "timeout-or-hang" or row.get("verdict") in {
                "timeout-at-bound",
                "hang-at-max-bound",
            }:
                # Surface the hotspot name for humans scanning JSONL.
                hotspots = progress.get("sugar_hotspots") or []
                if hotspots:
                    row["timeout_hotspot"] = hotspots[0].get("sugar")
                last_hb = progress.get("last_heartbeat")
                if isinstance(last_hb, dict):
                    row["timeout_last_sugar"] = last_hb.get("sugar")
                    row["timeout_last_site"] = last_hb.get("site")
                    row["timeout_last_stack"] = last_hb.get("active_stack")
        # Keep hang logs; drop completed noise unless caller set a durable dir.
        if engine_log_dir is None and log_path.is_file():
            if row.get("category") != "timeout-or-hang":
                try:
                    log_path.unlink()
                except OSError:
                    pass
    return row


def cause_class_for_verdict(
    *,
    verdict: str,
    bound_seconds: int | None = None,
    elapsed_seconds: float | None = None,
    perf_candidate: bool | None = None,
) -> str | None:
    """Map a final classification verdict to cause class A–E.

    Intermediate ``timeout-at-bound`` rows and ``other:*`` crash/signal terminals
    are not A–E product-cause classes (they stay loud under their own labels).
    """
    if verdict == "completes-with-panic":
        return CAUSE_CLASS_B_HIDDEN_PANIC
    if verdict == "hang-at-max-bound":
        return CAUSE_CLASS_D_HANG
    if verdict == "bare-exception":
        return CAUSE_CLASS_E_BARE
    if verdict == "completes-at-bound":
        elapsed = float(elapsed_seconds or 0)
        bound = int(bound_seconds or 0)
        is_perf = bool(perf_candidate) or (
            elapsed > PERF_CANDIDATE_THRESHOLD_SECONDS
            or bound > PERF_CANDIDATE_THRESHOLD_SECONDS
        )
        if is_perf:
            return CAUSE_CLASS_C_PERF_COMPLETE
        return CAUSE_CLASS_A_BOUND_TIGHT
    return None


def attach_cause_class(row: dict[str, Any]) -> dict[str, Any]:
    """Stamp ``cause_class`` + human label on a final ledger row (idempotent)."""
    verdict = str(row.get("verdict") or "")
    cause = cause_class_for_verdict(
        verdict=verdict,
        bound_seconds=row.get("bound_seconds"),
        elapsed_seconds=row.get("elapsed_seconds"),
        perf_candidate=row.get("perf_candidate"),
    )
    if cause is not None:
        row["cause_class"] = cause
        row["cause_class_label"] = CAUSE_CLASS_LABELS[cause]
    return row


def _copy_progress_fields(src: dict[str, Any], dest: dict[str, Any]) -> None:
    """Preserve macro hotspot progress from the child kill/finish path."""
    for key in (
        "last_progress",
        "timeout_hotspot",
        "timeout_last_sugar",
        "timeout_last_site",
        "timeout_last_stack",
    ):
        if key in src and src[key] is not None:
            dest[key] = src[key]


def verdict_from_terminal(terminal: dict[str, Any], *, bound: int) -> dict[str, Any]:
    """Map a triage category at a given bound into a #4894 classification verdict."""
    category = str(terminal.get("category") or "")
    base: dict[str, Any] = {
        "file": terminal.get("file"),
        "bound_seconds": bound,
        "elapsed_seconds": terminal.get("elapsed_seconds"),
        "category": category,
        "reason": terminal.get("reason"),
    }
    _copy_progress_fields(terminal, base)
    if category == "completed":
        base["verdict"] = "completes-at-bound"
        # PERF lane: only when the lift truly needed >120s, not merely when the
        # successful bound label is large after a tight discovery miss.
        elapsed = float(terminal.get("elapsed_seconds") or 0)
        base["perf_candidate"] = bool(
            elapsed > PERF_CANDIDATE_THRESHOLD_SECONDS
            or bound > PERF_CANDIDATE_THRESHOLD_SECONDS
        )
        testimony = terminal.get("testimony") or {}
        base["facts"] = testimony.get("facts")
        base["factory_walk_rows"] = testimony.get("factory_walk_rows")
        effects = testimony.get("effects") or []
        base["effect_classes"] = sorted(
            {
                str(effect.get("effect") or "")
                for effect in effects
                if effect.get("effect")
            }
        )
        return attach_cause_class(base)
    if category == "factory-construction-panic":
        testimony = terminal.get("testimony") or {}
        gap = testimony.get("gap") if isinstance(testimony, dict) else {}
        fingerprint = fingerprint_from_gap(gap if isinstance(gap, dict) else {})
        base["verdict"] = "completes-with-panic"
        base["owner"] = fingerprint[0] or "unknown"
        base["fingerprint"] = list(fingerprint)
        base["gap"] = gap if isinstance(gap, dict) else {}
        return attach_cause_class(base)
    if category == "bare-exception":
        base["verdict"] = "bare-exception"
        testimony = terminal.get("testimony") or {}
        base["exception_type"] = (
            testimony.get("exception_type") if isinstance(testimony, dict) else None
        )
        return attach_cause_class(base)
    if category == "timeout-or-hang":
        base["verdict"] = "timeout-at-bound"
        return base
    base["verdict"] = f"other:{category}"
    base["returncode"] = terminal.get("returncode")
    base["signal"] = terminal.get("signal")
    return base


def classify_file(
    *,
    script: Path,
    path: Path,
    rel: str,
    discovery_bound: int,
    escalation_bounds: tuple[int, ...],
    skip_discovery: bool,
) -> dict[str, Any] | None:
    """Discover-or-escalate one file; return a final ledger row or None.

    When discovery is enabled, files that finish inside the discovery bound are
    not part of the loud-timeout blob and return None (not ledgered as
    timeout-reclassified). Seeded lists with ``skip_discovery`` always escalate.
    """
    attempts: list[dict[str, Any]] = []

    if not skip_discovery:
        terminal = run_child_at_bound(
            script=script, path=path, rel=rel, timeout_seconds=discovery_bound
        )
        attempt = verdict_from_terminal(terminal, bound=discovery_bound)
        attempts.append(attempt)
        if attempt["verdict"] != "timeout-at-bound":
            # Finished inside discovery bound → not the timeout blob.
            return None

    # Deduplicate escalation bounds while preserving order. When discovery
    # already ran, only strictly larger bounds are useful.
    seen: set[int] = set()
    ordered_bounds: list[int] = []
    for bound in escalation_bounds:
        if bound in seen:
            continue
        if not skip_discovery and bound <= discovery_bound:
            continue
        seen.add(bound)
        ordered_bounds.append(bound)

    for bound in ordered_bounds:
        terminal = run_child_at_bound(
            script=script, path=path, rel=rel, timeout_seconds=bound
        )
        attempt = verdict_from_terminal(terminal, bound=bound)
        attempts.append(attempt)
        if attempt["verdict"] != "timeout-at-bound":
            final = dict(attempt)
            final["attempts"] = attempts
            final["discovery_bound_seconds"] = discovery_bound
            final["escalation_bounds_seconds"] = list(escalation_bounds)
            final["was_discovery_timeout"] = True
            return attach_cause_class(final)

    # Exhausted all bounds including max — genuine hang / pathological lift.
    last = attempts[-1]
    hang: dict[str, Any] = {
        "file": rel,
        "verdict": "hang-at-max-bound",
        "bound_seconds": last.get("bound_seconds"),
        "elapsed_seconds": last.get("elapsed_seconds"),
        "category": "timeout-or-hang",
        "reason": last.get("reason"),
        "attempts": attempts,
        "discovery_bound_seconds": discovery_bound,
        "escalation_bounds_seconds": list(escalation_bounds),
        "was_discovery_timeout": True,
        "next_owner": (
            "lift-work-budget: emit loud budget-exceeded terminal; hang is not OK"
        ),
    }
    # Prefer last attempt's progress (max-bound kill); fall back to any earlier.
    _copy_progress_fields(last, hang)
    if "last_progress" not in hang:
        for attempt in reversed(attempts):
            if attempt.get("last_progress"):
                _copy_progress_fields(attempt, hang)
                break
    return attach_cause_class(hang)


def summarize_ledger(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate classification counts, cause classes, panic owners, perf candidates."""
    verdict_counts: Counter[str] = Counter()
    cause_counts: Counter[str] = Counter()
    bound_hist: Counter[int] = Counter()
    perf_candidates: list[str] = []
    hang_files: list[str] = []
    panic_rows: list[dict[str, Any]] = []
    bare_exceptions: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    by_cause: dict[str, list[str]] = defaultdict(list)
    timeout_hotspot_counts: Counter[str] = Counter()

    for row in rows:
        # Recompute cause tags so pre-upgrade ledger lines still classify.
        tagged = attach_cause_class(dict(row))
        verdict = str(tagged.get("verdict") or "missing")
        verdict_counts[verdict] += 1
        cause = tagged.get("cause_class")
        if cause:
            cause_counts[str(cause)] += 1
            by_cause[str(cause)].append(str(tagged.get("file") or ""))
        hotspot = tagged.get("timeout_hotspot")
        if hotspot:
            timeout_hotspot_counts[str(hotspot)] += 1
        elif isinstance(tagged.get("last_progress"), dict):
            sugars = tagged["last_progress"].get("sugar_hotspots") or []
            if sugars and isinstance(sugars[0], dict) and sugars[0].get("sugar"):
                timeout_hotspot_counts[str(sugars[0]["sugar"])] += 1
        if verdict == "completes-at-bound":
            bound = int(tagged.get("bound_seconds") or 0)
            bound_hist[bound] += 1
            if tagged.get("perf_candidate") or cause == CAUSE_CLASS_C_PERF_COMPLETE:
                perf_candidates.append(str(tagged["file"]))
        elif verdict == "completes-with-panic":
            panic_rows.append(
                {
                    "file": tagged.get("file"),
                    "owner": tagged.get("owner") or "unknown",
                    "gap": tagged.get("gap") or {},
                    "fingerprint": tagged.get("fingerprint") or [],
                    "cause_class": CAUSE_CLASS_B_HIDDEN_PANIC,
                }
            )
            bound_hist[int(tagged.get("bound_seconds") or 0)] += 1
        elif verdict == "hang-at-max-bound":
            hang_files.append(str(tagged["file"]))
        elif verdict == "bare-exception":
            bare_exceptions.append(
                {
                    "file": tagged.get("file"),
                    "exception_type": tagged.get("exception_type"),
                    "reason": tagged.get("reason"),
                    "bound_seconds": tagged.get("bound_seconds"),
                    "cause_class": CAUSE_CLASS_E_BARE,
                }
            )
        elif verdict.startswith("other:"):
            other.append(
                {
                    "file": tagged.get("file"),
                    "verdict": verdict,
                    "reason": tagged.get("reason"),
                }
            )

    ranking = rank_factory_panic_fronts(panic_rows)
    # Ranked B owners: same ranking as factory panic fronts, tagged for dispatch.
    ranked_b_owners = [
        {
            "rank": index,
            "owner": owner,
            "file_count": count,
            "cause_class": CAUSE_CLASS_B_HIDDEN_PANIC,
            "cause_class_label": CAUSE_CLASS_LABELS[CAUSE_CLASS_B_HIDDEN_PANIC],
            "dispatch": "typed FactoryPanic owner — fold into factory-panic lane",
        }
        for index, (owner, count) in enumerate(
            sorted(
                (ranking.get("owners") or {}).items(),
                key=lambda item: (-int(item[1]), str(item[0])),
            ),
            start=1,
        )
    ]
    cause_class_counts = {
        key: int(cause_counts.get(key, 0))
        for key in (
            CAUSE_CLASS_A_BOUND_TIGHT,
            CAUSE_CLASS_B_HIDDEN_PANIC,
            CAUSE_CLASS_C_PERF_COMPLETE,
            CAUSE_CLASS_D_HANG,
            CAUSE_CLASS_E_BARE,
        )
    }
    return {
        "R_classified": len(rows),
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "cause_class_counts": cause_class_counts,
        "cause_class_labels": dict(CAUSE_CLASS_LABELS),
        "cause_class_files": {
            key: sorted(files) for key, files in sorted(by_cause.items())
        },
        "ranked_B_owners": ranked_b_owners,
        "completes_by_bound": dict(sorted(bound_hist.items())),
        "perf_candidate_count": len(perf_candidates),
        "perf_candidates": sorted(perf_candidates),
        "hang_at_max_bound_count": len(hang_files),
        "hang_files": sorted(hang_files),
        "bare_exception_count": len(bare_exceptions),
        "bare_exceptions": bare_exceptions,
        "other_count": len(other),
        "other": other,
        "R_live_factory_panic_files": ranking["R_live_factory_panic_files"],
        "owner_family_count": ranking["owner_family_count"],
        "owner_families": ranking["owner_families"],
        "owners": ranking["owners"],
        "factory_panic_fronts": ranking["exact_fronts"],
        "timeout_sugar_hotspots": [
            {"sugar": name, "file_count": count}
            for name, count in timeout_hotspot_counts.most_common(20)
        ],
    }


def load_ledger_rows(ledger_path: Path) -> list[dict[str, Any]]:
    if not ledger_path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("verdict"):
            rows.append(row)
    return rows


def resolve_candidates(
    args: argparse.Namespace,
) -> list[tuple[str, Path, str]]:
    """Build the candidate worklist from discovery seed or full package scan."""
    packages = tuple(args.packages) or PACKAGES
    if args.files_from:
        rels = load_file_list(Path(args.files_from))
        rows: list[tuple[str, Path, str]] = []
        for rel in rels:
            package = rel.split("/", 1)[0]
            if package not in packages and packages != PACKAGES:
                # Caller restricted packages; still allow explicit seed rows.
                pass
            if package not in PACKAGES:
                raise SystemExit(f"unknown package prefix in {rel!r}")
            path = _resolve_path(package, rel)
            if not path.is_file():
                raise SystemExit(f"missing seed file: {rel} -> {path}")
            rows.append((package, path, rel))
        return rows

    all_rows = enumerate_assertion_files(packages)
    if args.limit is not None:
        return all_rows[: args.limit]
    if args.shard_count > 1:
        return [
            row
            for index, row in enumerate(all_rows)
            if index % args.shard_count == args.shard_index
        ]
    return all_rows


def _parse_bounds(raw: str) -> tuple[int, ...]:
    parts = [int(part.strip()) for part in raw.split(",") if part.strip()]
    if not parts:
        raise argparse.ArgumentTypeError("escalation bounds must be non-empty")
    if any(part <= 0 for part in parts):
        raise argparse.ArgumentTypeError("escalation bounds must be positive")
    return tuple(parts)


def run_discover_timeouts(args: argparse.Namespace) -> int:
    """Phase 1: rediscover live timeout-or-hang rows at the discovery bound only.

    Writes a seed file suitable for ``--files-from`` + ``--skip-discovery`` so
    the expensive 60/120/300 escalation pass never re-pays the 10s discovery tax.
    """
    triage_script = Path(__file__).resolve().with_name("corpus_fatal_triage.py")
    discovery_bound = int(args.discovery_bound)
    out_path = Path(args.discover_timeouts)
    candidates = resolve_candidates(args)
    timeouts: list[str] = []
    terminal_counts: Counter[str] = Counter()

    print(
        json.dumps(
            {
                "event": "discover-start",
                "candidates": len(candidates),
                "discovery_bound": discovery_bound,
                "output": str(out_path),
                "single_lane": True,
            },
            sort_keys=True,
        ),
        flush=True,
    )

    for index, (_package, path, rel) in enumerate(candidates, start=1):
        terminal = run_child_at_bound(
            script=triage_script,
            path=path,
            rel=rel,
            timeout_seconds=discovery_bound,
        )
        category = str(terminal.get("category") or "unknown")
        terminal_counts[category] += 1
        if category == "timeout-or-hang":
            timeouts.append(rel)
            print(
                json.dumps(
                    {
                        "event": "discovery-timeout",
                        "index": index,
                        "total": len(candidates),
                        "file": rel,
                        "timeout_count": len(timeouts),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        elif index % 25 == 0:
            print(
                json.dumps(
                    {
                        "event": "discover-progress",
                        "index": index,
                        "total": len(candidates),
                        "timeout_count": len(timeouts),
                        "terminal_counts": dict(sorted(terminal_counts.items())),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        if args.max_scan is not None and index >= args.max_scan:
            break

    payload = {
        "discovery_bound_seconds": discovery_bound,
        "scanned": min(len(candidates), args.max_scan or len(candidates)),
        "timeout_count": len(timeouts),
        "timeout_files": timeouts,
        "terminal_counts": dict(sorted(terminal_counts.items())),
        "note": (
            "Seed for classify_loud_timeouts.py --files-from ... --skip-discovery. "
            "Every timeout remains loud until escalation records a final verdict."
        ),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True), flush=True)
    # Red until the live timeout blob is empty at the discovery bound (stable zero
    # only after escalation retires them — discovery alone never greens hangs).
    return 1 if timeouts else 0


def run_classify(args: argparse.Namespace) -> int:
    script = Path(__file__).resolve()
    # Child mode reuses this script via corpus_fatal_triage's --child-* flags,
    # but those live on corpus_fatal_triage.py. Point children at the triage
    # script so payload construction stays identical to the recensus instrument.
    triage_script = script.with_name("corpus_fatal_triage.py")
    ledger_path = Path(args.ledger)
    summary_path = Path(args.summary) if args.summary else None
    discovery_bound = int(args.discovery_bound)
    escalation_bounds = _parse_bounds(args.escalation_bounds)

    candidates = resolve_candidates(args)
    done = already_classified(ledger_path) if args.resume else set()
    pending = [(pkg, path, rel) for pkg, path, rel in candidates if rel not in done]

    print(
        json.dumps(
            {
                "event": "start",
                "candidates": len(candidates),
                "already_classified": len(done),
                "pending": len(pending),
                "discovery_bound": discovery_bound,
                "escalation_bounds": list(escalation_bounds),
                "skip_discovery": bool(args.skip_discovery),
                "ledger": str(ledger_path),
                "single_lane": True,
            },
            sort_keys=True,
        ),
        flush=True,
    )

    versions = {
        package: importlib.metadata.version(package)
        for package in (tuple(args.packages) or PACKAGES)
        if importlib.util.find_spec(package) is not None
    }

    scanned = 0
    classified = 0
    skipped_not_timeout = 0
    for _package, path, rel in pending:
        scanned += 1
        row = classify_file(
            script=triage_script,
            path=path,
            rel=rel,
            discovery_bound=discovery_bound,
            escalation_bounds=escalation_bounds,
            skip_discovery=bool(args.skip_discovery),
        )
        if row is None:
            skipped_not_timeout += 1
            print(
                json.dumps(
                    {
                        "event": "not-timeout-at-discovery",
                        "scanned": scanned,
                        "pending_total": len(pending),
                        "file": rel,
                        "discovery_bound": discovery_bound,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        else:
            row["package_versions"] = versions
            row["classified_at_unix"] = int(time.time())
            attach_cause_class(row)
            append_ledger(ledger_path, row)
            classified += 1
            print(
                json.dumps(
                    {
                        "event": "classified",
                        "scanned": scanned,
                        "classified": classified,
                        "pending_total": len(pending),
                        "file": rel,
                        "verdict": row.get("verdict"),
                        "cause_class": row.get("cause_class"),
                        "cause_class_label": row.get("cause_class_label"),
                        "bound_seconds": row.get("bound_seconds"),
                        "elapsed_seconds": row.get("elapsed_seconds"),
                        "owner": row.get("owner"),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        if args.max_files is not None and classified >= args.max_files:
            break
        if args.max_scan is not None and scanned >= args.max_scan:
            break

    rows = load_ledger_rows(ledger_path)
    summary = summarize_ledger(rows)
    summary["package_versions"] = versions
    summary["ledger"] = str(ledger_path)
    summary["R_seeded_or_scanned_pool"] = len(candidates)
    summary["scanned_this_run"] = scanned
    summary["classified_this_run"] = classified
    summary["skipped_not_timeout_this_run"] = skipped_not_timeout
    # Residual work left in THIS invocation's worklist (unscanned remaining).
    # Ledger-classified rows are already removed from ``pending`` under --resume.
    summary["R_pending"] = max(0, len(pending) - scanned)
    summary["R_timeout_blob_classified"] = len(rows)
    # Unclassified timeout-blob residual:
    # - pure timeout seed (--skip-discovery): seed − classified
    # - otherwise: max(unscanned pending, recensus baseline − classified)
    #   so the instrument cannot green while ~293 remain unmeasured.
    recensus_unclassified = max(0, RECENSUS_TIMEOUT_BLOB_COUNT - len(rows))
    if args.files_from and args.skip_discovery:
        unclassified = max(0, len(candidates) - len(rows))
    else:
        unclassified = max(int(summary["R_pending"]), recensus_unclassified)
    summary["R_unclassified_timeout_blob"] = unclassified
    summary["R_recensus_timeout_blob"] = RECENSUS_TIMEOUT_BLOB_COUNT
    summary["R_recensus_unclassified"] = recensus_unclassified
    # Residual R: unclassified blob + hang@300 (class D). Instrument stays red
    # until both are zero (hang needs product budget-exceeded terminal).
    hang_count = int(summary["hang_at_max_bound_count"])
    summary["R_residual"] = unclassified + hang_count
    summary["R_residual_axes"] = {
        "unclassified_timeout_blob": unclassified,
        "hang_at_max_bound_D": hang_count,
        "recensus_unclassified": recensus_unclassified,
    }
    rendered = json.dumps(summary, indent=2, sort_keys=True)
    if summary_path is not None:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered, flush=True)
    print(
        json.dumps(
            {
                "event": "residual-R",
                "R_residual": summary["R_residual"],
                "R_unclassified_timeout_blob": summary["R_unclassified_timeout_blob"],
                "hang_at_max_bound_count": hang_count,
                "cause_class_counts": summary.get("cause_class_counts"),
                "ranked_B_owners": summary.get("ranked_B_owners"),
            },
            sort_keys=True,
        ),
        flush=True,
    )

    # Red while residual pool remains OR hang mass remains. Hang rows are
    # recorded explicitly (never silent); exit red so R>0 cannot look green.
    residual = int(summary["R_residual"])
    return 1 if residual > 0 else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Classify loud-bounded-timeout corpus files (#4894)."
    )
    parser.add_argument("packages", nargs="*", choices=PACKAGES)
    parser.add_argument(
        "--files-from",
        help="Seed list of package/rel paths (txt lines or JSON). Skips full scan.",
    )
    parser.add_argument(
        "--ledger",
        default="docs/ledgers/loud-timeout-classification-4894.jsonl",
        help="Append-only JSONL ledger path (repo-relative or absolute).",
    )
    parser.add_argument(
        "--summary",
        default="docs/ledgers/loud-timeout-classification-4894-summary.json",
        help="Summary JSON path written after each run.",
    )
    parser.add_argument(
        "--discovery-bound",
        type=int,
        default=DEFAULT_DISCOVERY_BOUND,
        help="First bound (seconds). Matches the #4775 10s discovery ceiling.",
    )
    parser.add_argument(
        "--escalation-bounds",
        default=",".join(str(b) for b in DEFAULT_ESCALATION_BOUNDS),
        help="Comma-separated escalating bounds after discovery timeout.",
    )
    parser.add_argument(
        "--skip-discovery",
        action="store_true",
        help="Treat --files-from rows as already-timeout; start at escalation bounds.",
    )
    parser.add_argument(
        "--resume", action="store_true", help="Skip ledger-classified files."
    )
    parser.add_argument(
        "--limit", type=int, help="Only first N assertion-bearing files."
    )
    parser.add_argument(
        "--max-files",
        type=int,
        help="Stop after N timeout-blob classifications this invocation (first shard).",
    )
    parser.add_argument(
        "--max-scan",
        type=int,
        help="Stop after scanning N candidates (discovery+skip counts).",
    )
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument(
        "--summarize-only",
        action="store_true",
        help="Rebuild summary from existing ledger without lifting.",
    )
    parser.add_argument(
        "--discover-timeouts",
        help=(
            "Discovery-only mode: write live timeout-or-hang file list JSON to this "
            "path at --discovery-bound (no escalation)."
        ),
    )
    # Child-mode passthrough is owned by corpus_fatal_triage.py; this script
    # never runs as the lift child.
    args = parser.parse_args()
    if not 0 <= args.shard_index < args.shard_count:
        parser.error("shard index must be in [0, shard count)")
    if args.discover_timeouts:
        return run_discover_timeouts(args)
    if args.summarize_only:
        rows = load_ledger_rows(Path(args.ledger))
        summary = summarize_ledger(rows)
        summary["ledger"] = args.ledger
        summary["R_classified"] = len(rows)
        summary["R_timeout_blob_classified"] = len(rows)
        hang_count = int(summary.get("hang_at_max_bound_count") or 0)
        recensus_unclassified = max(0, RECENSUS_TIMEOUT_BLOB_COUNT - len(rows))
        # summarize-only: pure timeout seed residual, else recensus baseline − classified.
        if args.files_from and args.skip_discovery:
            seed = load_file_list(Path(args.files_from))
            unclassified = max(0, len(seed) - len(rows))
        else:
            unclassified = recensus_unclassified
        summary["R_pending"] = unclassified
        summary["R_unclassified_timeout_blob"] = unclassified
        summary["R_recensus_timeout_blob"] = RECENSUS_TIMEOUT_BLOB_COUNT
        summary["R_recensus_unclassified"] = recensus_unclassified
        summary["R_residual"] = unclassified + hang_count
        summary["R_residual_axes"] = {
            "unclassified_timeout_blob": unclassified,
            "hang_at_max_bound_D": hang_count,
            "recensus_unclassified": recensus_unclassified,
        }
        rendered = json.dumps(summary, indent=2, sort_keys=True)
        if args.summary:
            Path(args.summary).parent.mkdir(parents=True, exist_ok=True)
            Path(args.summary).write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        print(
            json.dumps(
                {
                    "event": "residual-R",
                    "R_residual": summary["R_residual"],
                    "R_unclassified_timeout_blob": unclassified,
                    "hang_at_max_bound_count": hang_count,
                    "cause_class_counts": summary.get("cause_class_counts"),
                    "ranked_B_owners": summary.get("ranked_B_owners"),
                },
                sort_keys=True,
            )
        )
        # Hang mass and/or seed residual keep red; never green while D>0.
        return 1 if summary["R_residual"] > 0 else 0
    return run_classify(args)


if __name__ == "__main__":
    raise SystemExit(main())
