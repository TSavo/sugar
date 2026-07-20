# Issue #5338 — exact-nine remeasure WITH repetition (5x/file, idle host)

## Why this exists

#5928 established that the exact-nine board's single-observation rows are
not evidence: the same file at the same pinned state flips between
`completed` / `factory-panic` / `SIGSEGV` / bare exception across
back-to-back reps on an idle host. The prior #5338 table (`71394ec2`) was
one run per file. This directory is the 5-rep-per-file remeasure that
replaces it, run on a fresh idle-host pin.

## Pin

`cc443f3c1aee0fb811594f68131a9a96f5a813f6` — the tip of the shared
`~/provekit` checkout used to drive `bin/sugarbin run --host bx` (that
command syncs the workspace it's invoked from to battleaxe; this worktree's
own HEAD, `4e7465ec83150f42dfad60f29ea5ddc426774e3`, is one commit behind
that pin — the delta is a single unrelated #5919 evidence commit, not part
of lift construction). No `SUGAR_KIT_MANIFEST` was set (unmanifested,
matching the #5338 table's own condition). 30s per-file bound, never raised.
Executed via
`bin/sugarbin run --host bx --env docker:python-test,python-scientific,solver-z3 --needs sugar`.

## Host state

- Start: `uptime` on battleaxe read `load average: 1.26, 1.11, 1.94` (checked
  immediately before the run) after confirming no stray `sugar-env`
  containers were running (`docker ps` / `docker stats --no-stream` showed
  only steady-state platform services, no orphans at elevated CPU%).
- End: `load average: 3.71, 2.40, 2.22` (post-run) — `docker ps -a | grep sugar`
  showed zero leftover containers; the run's `docker run --rm` invocations
  reaped themselves.
- No other heavy job was started on the box during this run's window by this
  agent. #5928 is tracked as investigating the same nondeterminism
  separately; this run did not coordinate a lock, but no contention was
  observed (elapsed-per-rep stayed in the 0.3s-12s band, consistent with an
  idle host, not the multi-minute drift load contention would cause).

## Files and script

- `probe_script.py` — the exact driver, synced into the container and run as
  `python3 .../scripts/_exact9_5338_probe.py` (staged from repo root as a
  throwaway harness inside `scripts/`, same pattern as #5919's probe
  scripts, removed from `scripts/` after the run — this copy under
  `measurements/` is the permanent record).
- `rep_rows.json` — all 45 raw rows (9 files x 5 reps), one JSON object per
  invocation: `file`, `elapsed_s`, `returncode`, `signal`, `outcome`,
  `detail` (panic/exception message), `timed_out`, `repeat_index`.

## Per-file, per-rep table (5 reps each, in order rep0..rep4)

| file | rep0 | rep1 | rep2 | rep3 | rep4 | verdict |
| --- | --- | --- | --- | --- | --- | --- |
| `numpy/random/tests/test_random.py` | typed FactoryPanic | typed FactoryPanic | typed FactoryPanic | typed FactoryPanic | typed FactoryPanic | **STABLE** — typed FactoryPanic 5/5 |
| `numpy/random/tests/test_randomstate.py` | typed FactoryPanic | typed FactoryPanic | typed FactoryPanic | native crash (SIGSEGV) | typed FactoryPanic | **NONDETERMINISTIC** — typed FactoryPanic 4/5, native crash 1/5 |
| `numpy/tests/test_public_api.py` | completed | native crash (SIGSEGV) | completed | completed | completed | **NONDETERMINISTIC** — completed 4/5, native crash 1/5 |
| `pandas/io/stata.py` | typed FactoryPanic | native crash (SIGSEGV) | bare exception (`'NodeKind' object has no attribute 'type'`) | typed FactoryPanic | typed FactoryPanic | **NONDETERMINISTIC** — typed FactoryPanic 3/5, native crash 1/5, bare exception 1/5 |
| `scipy/optimize/tests/test__dual_annealing.py` | typed FactoryPanic | bare exception (`'SourceFragment' object is not iterable`) | typed FactoryPanic | typed FactoryPanic | typed FactoryPanic | **NONDETERMINISTIC** — typed FactoryPanic 4/5, bare exception 1/5 |
| `scipy/sparse/csgraph/tests/test_shortest_path.py` | completed | completed | completed | completed | native crash (SIGSEGV) | **NONDETERMINISTIC** — completed 4/5, native crash 1/5 |
| `sklearn/manifold/tests/test_t_sne.py` | typed FactoryPanic | typed FactoryPanic | typed FactoryPanic | typed FactoryPanic | typed FactoryPanic | **STABLE** — typed FactoryPanic 5/5 |
| `sklearn/utils/tests/test_sorting.py` | completed | completed | completed | completed | completed | **STABLE** — completed 5/5 |
| `sklearn/utils/tests/test_stats.py` | bare exception (`ord()` on multi-char string) | bare exception (`ord()` on multi-char string) | typed FactoryPanic | typed FactoryPanic | typed FactoryPanic | **NONDETERMINISTIC** — bare exception 2/5, typed FactoryPanic 3/5 |

3/9 files are STABLE across 5 reps. 6/9 files are NONDETERMINISTIC.

## The timeout question — resolved, consistent with #5928

`sklearn/utils/tests/test_stats.py` hit **zero timeouts in 5/5 reps** on this
idle host. This matches #5928's own idle-host finding (0/6 timeouts across
its earlier 6-rep probe) and confirms the `timeout=1` row in the prior
`71394ec2` #5338 table was a host-load artifact, not a construction defect.
No other file among the nine hit the 30s bound in any of the 45 total
invocations. `numpy/_core/tests/test_datetime.py` (the file #5928 found
reproduces its timeout 3/3 on idle) is **not** one of the exact-nine files
and is out of scope for this remeasure.

## Conservation does not sum cleanly at Σ=9 anymore

The prior table reported one disposition per file and summed to
`completed=3 | typed_FactoryPanic=5 | timeout=1` = Σ9. That framing assumed
each file has one true terminal state. It does not. Six of nine files
produced more than one distinct terminal category across 5 reps at the same
pin. A single-column category count for those six would misrepresent the
measurement regardless of which value is chosen (mode, first-rep, last-rep):

- Stable (1 category, 5/5): `test_random.py` (typed FactoryPanic),
  `test_t_sne.py` (typed FactoryPanic), `test_sorting.py` (completed) — 3
  files.
- Nondeterministic (2+ categories observed): `test_randomstate.py`,
  `test_public_api.py`, `stata.py`, `test__dual_annealing.py`,
  `test_shortest_path.py`, `test_stats.py` — 6 files, each showing a
  SIGSEGV or bare-exception rep interleaved with either `completed` or
  typed FactoryPanic reps.

No single number is more true than the per-rep record. Reporting a
conservation sum as if it held would launder the nondeterminism this issue
exists to surface.

## What this does NOT establish

- Root cause of the SIGSEGV/bare-exception flips is #5928's scope, not
  remeasured here.
- This run did not vary `SUGAR_KIT_MANIFEST` state (matched the original
  #5338 condition: no manifest). #5928's own probes found manifest state
  does not explain the flips either.
