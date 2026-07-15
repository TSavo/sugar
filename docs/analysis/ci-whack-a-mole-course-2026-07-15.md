# Stop CI whack-a-mole — steady course (2026-07-15)

## Diagnosis

Today's ~30 merges were not one campaign. Three interleaved loops:

1. **CI surface ejects** — hang / false-red instruments removed from `make ci`
   (#4525–#4533, #4526–#4529, …). Correct as triage, wrong as strategy: each
   eject was a reaction, not a declared surface contract.
2. **Hosted-memory cascade on the pandas wall** — one process-lifetime owner
   bounded per PR (#4531 → #4535 → #4538 → #4539 → #4540 → #4541 → #4542 →
   #4543). The wall then died on the *next residual*. Orientation lived only
   in the next death message.
3. **Product / seam work** mixed into the same push stream (#4517–#4537, …).

Whack-a-mole is what you get when:

- generation is cheap (agents can ship another bound in minutes),
- orientation is not stored in an instrument that names the *class* of
  residue,
- default CI and the wall frontier are treated as the same red light.

### Tip residue (post-#4543)

| Lane | Run | Failure mode |
|------|-----|--------------|
| **A — acid test** | CI `29447485517` | `test-showcases` cascade: `ModuleNotFoundError: sugar_lift_python_source`, missing property rows, expected discharge → `refused` |
| **B — wall** | Pandas Wall `29447486525` | `read_line.disconnected` mid-`sugar.enumerate` on `core/indexes/multi.py` after ~3.8k responses / ~60 generation peaks at budget 64 |

These are **independent**. Bounding another cache will not install the showcase
kit. Fixing showcase packaging will not finish the wall. Merging either as a
"CI is red" PR restarts the mole loop.

Known residual ownership still in tree (examples, not complete):

- `source_tables.py`: four `@lru_cache(maxsize=None)` keyed by full source
  string — retains every distinct source body forever inside a resident
  process.
- Generation budget and QuestionCache spill exist, but **no census** asserts
  the full set of process-lifetime holders is finite.

Stale orientation compounds the problem:

- `docs/_surface/gates_ci.md` still claims `test-all` + `check-cargo-entrypoint`
  are default CI. `Makefile` `ci` is now
  `check-lift-refusal-vocabulary test-python-format test-showcases self-attest
  coretests-source-audit coretests-invariants`.
- `.github/workflows/ci.yml` header still claims `test-rust` + `test-python`.

---

## Law (operating)

1. **Two lanes, hard split.** Default CI (Lane A) and wall / hosted-memory
   frontier (Lane B) never share a PR title, never share a "CI red" decision
   tree, and never block each other.
2. **No fix without an instrument that names the residue class.** A PR that
   bounds one map is illegal unless a red instrument already lists that map
   (and the rest of its class) and stays red while any class member remains.
3. **Merge-and-hope is suspended.** Do not fire wall workflow_dispatch after
   every memory micro-PR. Measure with the scoreboard; land when `ΔR` is
   predicted and observed on the instrument, not on "did the wall finish."
4. **Orientation is durable.** `make ci` composition, lane ownership, and R
   axes live in code + this (or successor) analysis — not in chat.

---

## Lanes

### Lane A — Mainline acid test (`make ci`)

**Goal / law:** A clean self-hosted runner produces a diagnostic green (or a
red that names one contract). Showcases are end-to-end receipts, not ambient
venv archaeology.

**R axes (initial):**

| Axis | Meaning | Current shape of R |
|------|---------|-------------------|
| `A1 kit_import` | Every showcase that needs a Python kit can import it without ambient site-packages | Failures of the form `ModuleNotFoundError: sugar_lift_*` |
| `A2 showcase_verdict` | Twin receipts get expected discharge / refuse / unsatisfied | Count of showcases with wrong verdict class |
| `A3 surface_doc` | Documented gate list == `Makefile` `ci` prerequisites | Drift count (docs, workflow comments) |

**Work order:** A1 → A2 → A3. Do not touch Lane B owners in these PRs.

### Lane B — Wall / resident lifetime (explicit only)

**Goal / law:** Every process-lifetime owner in the resident Python kit and the
Rust RPC client is finite by construction. The wall may take many generations;
it must not die from unbounded retention or consistency re-ask divergence.

**R axes (initial):**

| Axis | Meaning | Current shape of R |
|------|---------|-------------------|
| `B1 unbounded_owner` | Census of process-lifetime maps / caches without a bound | Offender count (file:symbol) |
| `B2 wall_progress` | Scoreboard: generations completed, last file, disconnect stage, peak RSS | Incomplete frontier without `frontier.json` is a measured state, not a mystery |
| `B3 consistency_floor` | Canonical question answers survive generation rotate | Re-ask divergence count (already partially instrumented by #4542/#4543) |

**Work order:** Land B1 red first. Only then bound owners in census order.
B2 is the progress instrument so partial wall runs produce `ΔR` without full
completion. B3 is already partially paid; extend only if census or wall death
names it.

Wall stays `workflow_dispatch` / `make pandas-wall` — never re-enters default
`make ci`.

---

## First instruments (do these before the next "fix CI" PR)

### Instrument 1 — Resident ownership census (Lane B, enables all memory work)

**Shape:** `tools/resident_ownership_census.py` (+ focused test).

- Scans declared owner sites in Python kit + RPC client for known-illegal
  shapes: `lru_cache(maxsize=None)`, module-level growing dicts without
  documented bound, process-lifetime caches not on the allowlist.
- Prints `R=<n>` and every offender with replacement shape
  ("bounded LRU", "generation-local", "caller-owned", "spill").
- **Stays red while any offender remains.** Green only at stable zero for
  the declared class.
- Allowlist is explicit and tiny: must name why a site is finite.

This replaces the mole chain: the next memory PR's success is `ΔR` on this
census, not "wall got further."

### Instrument 2 — Showcase kit preflight (Lane A)

**Shape:** `tools/showcase_kit_preflight.py` or a Makefile prerequisite of
`test-showcases`.

- Asserts the exact interpreter/path the showcase manifests use can
  `import sugar_lift_python_source` and `import sugar_lift_py_tests`.
- Fail message names install target (`make build-python` or per-showcase
  venv law), not a cascade of refuse rows.
- Then repair packaging once under that named contract.

### Instrument 3 — Wall progress scoreboard (Lane B)

**Shape:** extend `tools/pandas_wall.py` (or companion) so a partial run
always emits `progress.json`:

```json
{
  "completed_responses": 3871,
  "generation_peaks": 60,
  "last_file": "core/indexes/multi.py",
  "disconnect_stage": "read_line.disconnected",
  "message_id": 32,
  "exit": 1
}
```

Partial failure becomes a comparable receipt. No more reading 40MB
`engine.jsonl` by hand to learn the wall moved from msg 64 to msg 32.

### Instrument 4 — CI surface pin (Lane A orientation)

**Shape:** small check or doc+Makefile comment pin:

- `make ci` prerequisite list is the contract.
- `docs/_surface/gates_ci.md` and workflow header must match or the pin fails.
- Explicit targets (`test-all`, walls, assertion frontier, scoreboards) listed
  as non-default lanes.

---

## What we will not do

- Another one-off bound PR driven only by wall death text.
- Ejecting more instruments from `make ci` without updating the surface pin
  and naming the explicit target that owns them.
- Landing product/seam work (#4517-class) in the same PR as memory or CI
  packaging.
- Treating wall red as blocking mainline merges once Lane A is green.

---

## Immediate next step

1. Freeze Lane B mole merges.
2. Land Instrument 1 (census) red — report current `R`.
3. Land Instrument 2 (showcase preflight) red — report `A1`.
4. Repair under those instruments only, one lane at a time.
5. Refresh gates docs under Instrument 4 once `make ci` composition is
   intentional and green.

`ΔR` is the only progress metric. Green CI that cannot name which residual
moved is not orientation.

---

## Instrument status (landed 2026-07-15)

| Instrument | Command | Status (local 2026-07-15 post-reboot) |
|------------|---------|--------|
| B1 resident ownership | `make check-resident-ownership` | **red** — `R=4` all in `source_tables.py` (`lru_cache(maxsize=None)`) |
| A1 showcase kit preflight | `make check-showcase-kit-preflight` (also prerequisite of `test-showcases`) | **green** — `A1=0` (source PYTHONPATH + fresh editable + sticky venvs) |

Local `A1=0` means the *declared* install contracts work on this host. Hosted CI
`ModuleNotFoundError: sugar_lift_python_source` is therefore either a runner-only
sticky/path divergence (preflight will name it on that host) or an **A2**
verdict/path problem past import. Next Lane A work: run preflight on the CI
runner, then measure showcase verdict residue (`A2`), not another silent eject.

Repair order: confirm `A1` on CI host → `A2` showcase verdicts → Lane B census
`R` (bound `source_tables` first under B1).
