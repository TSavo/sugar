# Battleaxe timing measurements (canonical door)

**Wall-clock numbers for pandas recensus / open / walk / k=8 are taken on
battleaxe only.** Not on the Mac. The Mac is an 8-core laptop that hosts the
agent fleet; a number taken there under load is not a slow measurement — it is
not a measurement. Tonight's fake 87% regression and fake single-file 3× came
from that defect.

Wrappers live in the repo (they are **not** on PATH in a bare shell):

| Wrapper | Path | Role |
| --- | --- | --- |
| `brun` | `bin/brun` | Sync workspace to battleaxe, run an arbitrary command there |
| `bpytest` | `bin/bpytest` | Managed pytest on battleaxe (`python-unit` task) |
| `bcargo` | `bin/bcargo` | Cargo on battleaxe |

`bin/brun` is already the harness: it syncs the tip of the current checkout to
`BCARGO_REMOTE_HOST` (default SSH alias `battleaxe`), runs from the same
repo-relative cwd, forwards env with `--env`, and can rsync results back with
`--sync-back`. Do **not** invent a second remote runner.

## Quiet gate + exclusive lease (mandatory for every timing number)

```bash
export SUGAR_BX_REQUIRE_QUIET=1
# optional explicit ceiling (also arms the gate alone):
# export SUGAR_BX_MAX_LOADAVG=8
# optional: refuse immediately instead of queueing behind another measurement
# export SUGAR_BX_TIMING_LEASE_WAIT_S=0
```

**Rule:** a measurement that cannot testify to its own conditions is not a
measurement. Load-at-start alone is not enough — six agents can all pass a free
check then co-run and recreate contention on battleaxe.

When armed, `bin/brun` / `bin/sugarbin run --host bx`:

1. Takes an **exclusive remote flock** on
   `/var/tmp/sugar-bx-timing-measurement.lease` (queue up to
   `SUGAR_BX_TIMING_LEASE_WAIT_S`, default 7200s; `0` → exit **77** immediately
   if another quiet-gated measurement holds it).
2. Under that lock, samples **remote** 1-minute loadavg and `nproc`.
3. **Refuses with exit 76** if `load1 > max` (default `max = max(2.0, nproc/4)`
   → 8.0 on 32-core battleaxe).
4. Runs the command while still holding the lease.
5. Prints `bx-load-gate phase=before|after … lease=held` and
   `bx-timing-lease phase=acquired|release` on stderr.

Ordinary builds leave the gate **unset** (no lease, no load check). Timing
runs always arm it. **Serialized measurement is enforced by the tool**, not by
people agreeing not to overlap.

## One-time remote env (pinned pandas corpus)

From any checkout root (on the Mac; work runs on battleaxe):

```bash
bin/brun -- bash scripts/bootstrap-venv-py312.sh
```

That builds `.venv-py312` on the remote with **CPython 3.12.13 + pandas==3.0.3**
(and the other declared pins). Re-run only when the pin changes.

## Canonical command shapes

Always from the **repo root**. Always with `SUGAR_BX_REQUIRE_QUIET=1`.
Always invoke `bin/brun` by path.

Shared remote body (PYTHONPATH + corpus root from the pin):

```bash
export SUGAR_BX_REQUIRE_QUIET=1
# Optional: pin an explicit SHA the remote checkout already has after sync.
# The sync is the current tip of this worktree; commit id is recorded by the
# recensus via --commit when you pass it.

REMOTE_JSON=/tmp/sugar-bx-measure.json   # path ON battleaxe
LOCAL_JSON=/tmp/sugar-bx-measure.json    # path ON the Mac after sync-back
```

### 1. Single file

```bash
SUGAR_BX_REQUIRE_QUIET=1 bin/brun \
  --sync-back "${REMOTE_JSON}:${LOCAL_JSON}" \
  -- bash -lc '
    set -euo pipefail
    PY=.venv-py312/bin/python
    test -x "$PY" || { echo "missing .venv-py312; run: bin/brun -- bash scripts/bootstrap-venv-py312.sh" >&2; exit 2; }
    CORPUS=$("$PY" -c "import pandas, pathlib; print(pathlib.Path(pandas.__file__).resolve().parent)")
    export PYTHONPATH=implementations/python/sugar-lift-py-tests/scripts:implementations/python/sugar-lift-py-tests/src:implementations/python/sugar-source-tree/src:implementations/python/sugar-lift-python-source/src
    FILE_REL="${FILE_REL:-io/json/_json.py}"
    "$PY" -u implementations/python/sugar-lift-py-tests/scripts/control_effect_recensus.py \
      "$CORPUS/$FILE_REL" \
      --corpus-root "$CORPUS" \
      --repo . \
      --commit "$(git rev-parse HEAD)" \
      --json /tmp/sugar-bx-measure.json
  '
# JSON at $LOCAL_JSON. Trust only if the command exited 0 (not 76).
```

Override the file:

```bash
FILE_REL=core/arrays/categorical.py SUGAR_BX_REQUIRE_QUIET=1 bin/brun ...
```

### 2. N-file walk (subtree or full package root)

Pass a directory under the corpus root as the first positional (still with
`--corpus-root` set to the package root so demand-table identity matches the
full run):

```bash
SUGAR_BX_REQUIRE_QUIET=1 bin/brun \
  --sync-back "${REMOTE_JSON}:${LOCAL_JSON}" \
  -- bash -lc '
    set -euo pipefail
    PY=.venv-py312/bin/python
    CORPUS=$("$PY" -c "import pandas, pathlib; print(pathlib.Path(pandas.__file__).resolve().parent)")
    export PYTHONPATH=implementations/python/sugar-lift-py-tests/scripts:implementations/python/sugar-lift-py-tests/src:implementations/python/sugar-source-tree/src:implementations/python/sugar-lift-python-source/src
    SLICE="${SLICE:-$CORPUS/io/json}"   # or $CORPUS for full package
    "$PY" -u implementations/python/sugar-lift-py-tests/scripts/control_effect_recensus.py \
      "$SLICE" \
      --corpus-root "$CORPUS" \
      --repo . \
      --commit "$(git rev-parse HEAD)" \
      --json /tmp/sugar-bx-measure.json
  '
```

### 3. LPT k=8 (one seat, or plan+all seats via CI)

Plan is not a measurement. Measure a seat with the production worker shape:

```bash
# After plan.json exists under .sugar/pandas-control-effect/ (from the CI plan
# job or tools/plan_control_effect_recensus_shards.py on battleaxe):
SUGAR_BX_REQUIRE_QUIET=1 bin/brun \
  --sync-back "${REMOTE_JSON}:${LOCAL_JSON}" \
  -- bash -lc '
    set -euo pipefail
    PY=.venv-py312/bin/python
    CORPUS=$("$PY" -c "import pandas, pathlib; print(pathlib.Path(pandas.__file__).resolve().parent)")
    export PYTHONPATH=implementations/python/sugar-lift-py-tests/scripts:implementations/python/sugar-lift-py-tests/src:implementations/python/sugar-source-tree/src:implementations/python/sugar-lift-python-source/src
    OUT=.sugar/pandas-control-effect
    SHARD="${SHARD:-0}"
    "$PY" -u implementations/python/sugar-lift-py-tests/scripts/control_effect_recensus.py \
      "$CORPUS" \
      --corpus-root "$CORPUS" \
      --repo . \
      --commit "$(git rev-parse HEAD)" \
      --out-dir "$OUT" \
      --plan-json "$OUT/plan.json" \
      --shard-index "$SHARD" \
      --partial-out "$OUT/partial-s$(printf %02d "$SHARD").json"
    cp "$OUT/partial-s$(printf %02d "$SHARD").json" /tmp/sugar-bx-measure.json
  '
```

Full k=8 board seal remains the compose job in
`.github/workflows/control-effect-recensus.yml` (sole SCOREBOARD door). Local
k=8 timing of a single seat is for latency, not for a sealed board.

### Fleet roles (same door, different SLICE / SHARD / FILE_REL)

**Everyone:** from repo root, `SUGAR_BX_REQUIRE_QUIET=1`, invoke **`bin/brun` by
path** (not on PATH). One-time: `bin/brun -- bash scripts/bootstrap-venv-py312.sh`.
Shared PYTHONPATH + CORPUS block as above. Exclusive lease serializes you —
do not invent a parallel runner. Exit 76/77 = no number.

| Agent | Job | Shape |
| --- | --- | --- |
| **mr_orange** | full 1421-file walk | §2 with `SLICE="$CORPUS"` (full package root) |
| **mr_black** | 200-file before/after | §2 with a 200-file enrolled list or a bounded subtree; same tip+pin both legs; arm quiet both legs |
| **mr_blonde** | LPT k=8 | §3; plan first, then seats `SHARD=0..7` (serialized by lease — queue, don't co-fire) |
| **mr_white** | correctness re-run | §2 full or pin-matched slice; compare verdicts/CIDs not wall-clock alone |
| **mr_pink** | RSS over a walk | §2 + wrap remote body with `/usr/bin/time -v` or `ps` RSS sampling **inside** the quiet-gated brun command so RSS and wall share the same lease/load testimony |
| **mr_brown** | D3 hang repro | §1 single file (or smallest slice that reproduces); `FILE_REL=…`; keep quiet gate so hang timing is not Mac noise |

Do not each invent argv. Copy from this file. Cite stderr `load1_before` /
`load1_after` / `lease=held` with every number.

## How to read the result

| Exit | Meaning |
| --- | --- |
| 0 | Command finished; stderr has `bx-timing-lease phase=acquired`, `bx-load-gate phase=before|after … lease=held`. JSON at sync-back path. |
| 76 | **Refused — host not quiet** (under lease). No number. Do not cite. Wait and retry. |
| 77 | **Refused — another measurement holds the exclusive lease** (or wait timed out). No number. Queue or set wait; do not invent a second runner. |
| other | Remote command failure; also not a trusted number. |

A JSON body without a 0 exit, or without the before load line with `lease=held`,
is not a timing receipt.

## Forbidden

- Any pandas open / walk / census / profile / cProfile / k=8 / demand-table
  scan on the Mac.
- Broad local pytest.
- Reporting a wall-clock taken while `bx-load-gate` was not armed or exited 76.
- Inventing a parallel harness next to `bin/brun`.

## Related

- `docs/build-execution.md` — sugarbin / brun / bpytest routes
- `docs/contributing/heavy-measurement-lease.md` — exclusive heavy jobs on the box
- `bin/brun --help` — options and quiet-gate env vars
