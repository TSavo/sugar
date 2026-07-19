# Issue #5919 — contamination triage, idle-host re-measurement

## What this directory is

Durable per-row evidence for #5919, so the finding does not need to be
re-measured to be re-examined. The prior full-corpus measurement (closed
by #5907) left only aggregate category counts in issue comments — no
per-row artifact survived, which is itself part of what this issue asked
to fix.

## Files

- `baseline_compact_idle.json` — full-corpus `corpus_fatal_triage.py numpy
  pandas --file-timeout 30 --compact` run, NO manifest, on the now-idle
  host (load ~1-3 during the run, one stray `find` process killed
  mid-run — see report). This is NOT comparable to the #5907-reported
  baseline (bare-exception 0, crash 0, timeout 11): this idle run instead
  shows bare-exception 5, process-crash-or-overflow 31, timeout-or-hang 1
  (completed 520, factory-construction-panic 475; 1032 conserved). The
  category profile shifted completely between the contended measurement
  and now — see report for interpretation (code drift + nondeterminism,
  not simply "load caused it").
- `first_pass_probe.json` — targeted child-mode (`--child-file`) lift of
  the 5 baseline-idle bare-exception files, 10 of 31 baseline-idle crash
  files, and the 1 baseline-idle timeout file (`test_datetime.py`), plus
  `sklearn/utils/tests/test_stats.py`, each run once without manifest and
  once with `kit_manifests/numpy_families_5907.json`.
- `repeatability_probe.json` — the decisive run. 8 files that showed a
  SIGSEGV or an outcome flip in the first pass, each re-run 3x per
  manifest state (30 more seconds-scale invocations, not a corpus sweep).
- `probe_script.py` / `repeat_script.py` — the exact scripts that
  produced the two probe JSONs (originally staged at
  `implementations/python/sugar-lift-py-tests/scripts/_issue5919_probe.py`
  and `_issue5919_repeat.py`, removed from `scripts/` after the run since
  they are throwaway harnesses, not permanent test infrastructure).

## Headline finding

None of the crash/bare-exception rows are deterministically tied to the
kit manifest. The repeatability probe shows the *same file, same manifest
state* flipping between `completed`, `factory-panic`, and `SIGSEGV`
across three back-to-back invocations on an idle host — e.g.
`pandas/tests/frame/test_reductions.py` with manifest: crash / complete /
complete across 3 reps; `numpy/_core/tests/test_defchararray.py` without
manifest: crash / complete / complete. This is process-level
nondeterminism (almost certainly ASLR/memory-layout-dependent undefined
behavior surfaced through ctypes/FFI probing of the numpy/pandas C
extensions), not a manifest-caused defect and not simple host-load
contention — it reproduces on an already-idle box.

The one clean, fully reproducible signal: `numpy/_core/tests/test_datetime.py`
without manifest hits the full 30s timeout in 3/3 reps on an idle host —
that timeout is real, not contention. With the manifest loaded it never
timed out in 3/3 reps (22.65s/completed via exception, 7.55s exception,
10.09s SIGSEGV) — manifest loading changes this file's behavior from
"hangs" to "fails fast", but which failure mode it fails into (exception
vs. crash) is itself nondeterministic.

`sklearn/utils/tests/test_stats.py` — repeated 3x per manifest state
(`sklearn_repeatability.json`): 4/6 clean `factory-panic` (~12s), 1/6
SIGSEGV (2.91s, no-manifest), 1/6 `exception` outcome (10.04s,
with-manifest). **Zero of 6 reps hit the 30s timeout** on the idle host,
regardless of manifest state. That directly contradicts the original
report of this file as a real timeout under load — on an idle box it
never times out, though which non-timeout outcome it lands on (clean
panic vs. crash vs. exception) is itself nondeterministic, same pattern
as the other flaky files above.
