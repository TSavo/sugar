# Battleaxe timing measurements (canonical door)

**Law:** [measurement-conditions.md](./measurement-conditions.md) —
*a measurement must testify to its own conditions* (quiet box, exclusive
lease, correct corpus). This file is the **invocation cookbook**; that file is
the **law and the incidents**.

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

## Three gates (mandatory for every timing number)

**Rule:** a measurement that cannot testify to its own conditions is not a
measurement. Three independent holes closed so far tonight:

| Gate | Proves | Refuse |
| --- | --- | --- |
| **Load** | box was quiet under the lease | exit **76** |
| **Lease** | no concurrent quiet measurement | exit **77** |
| **Corpus pin** | measuring pandas **3.0.3 / 1421 files**, not system 2.3.3 / 1415 | exit **78** |

```bash
export SUGAR_BX_REQUIRE_QUIET=1
# optional: SUGAR_BX_MAX_LOADAVG=8
# optional: SUGAR_BX_TIMING_LEASE_WAIT_S=0   # refuse if lease busy
# pin defaults (override only with cause):
#   SUGAR_BX_REQUIRE_CORPUS_PIN=docs/ledgers/pins/pandas-3.0.3.pin.json
#   SUGAR_BX_CORPUS_PYTHON=.venv-py312/bin/python
# never for fleet wall-clock: SUGAR_BX_SKIP_CORPUS_PIN=1
```

When `SUGAR_BX_REQUIRE_QUIET=1`, `bin/brun` / `bin/sugarbin run --host bx`:

1. Remote shell **cd into the synced checkout root** (`SUGAR_BX_REPO`) before
   any pin path is touched. Relative pin/python paths
   (`docs/ledgers/pins/…`, `.venv-py312/bin/python`) are then resolved under
   that root (absolute paths pass through). Checking the pin file *before*
   this cd always exits **78** even when the pin is synced — only absolute
   `/tmp` pins worked; that was a gate bug, not a missing pin.
2. Exclusive remote flock `/var/tmp/sugar-bx-timing-measurement.lease`
3. Under lock: sample load1 → **76** if over ceiling
4. Under lock: run `tools/bx_corpus_pin_gate.py` against
   `.venv-py312` + banked pin → **78** if version/fileCount mismatch
   (identity mode: version + file count; prints expected aggregate in the
   receipt). `control_effect_recensus` also exits **78** on pin/aggregate refuse.
5. Run the measurement while still holding the lease (measure still cds to
   the caller's repo-relative cwd via `prefix_cmd`)
6. Print load before/after (`lease=held`) and pin `phase=ok` on stderr

## One-time remote env (pinned pandas corpus)

**Never use system python on battleaxe for measurement.** It has carried
pandas **2.3.3 (1415 files)**. The authenticated pin is **3.0.3 (1421 files)**
at `docs/ledgers/pins/pandas-3.0.3.pin.json`.

```bash
# Preferred: bootstrap in *this* checkout's remote root
bin/brun -- bash scripts/bootstrap-venv-py312.sh

# Blonde is bootstrapping .venv-py312 with pandas==3.0.3 on the box.
# Brown found an existing remote checkout that already has the right venv:
#   sugar-bcargo-a978990da5ba  (tag a978990da5ba)
# Reuse only if ` .venv-py312/bin/python -c 'import pandas; print(pandas.__version__)' `
# prints 3.0.3 and the pin gate exits 0.
```

That builds `.venv-py312` on the remote with **CPython 3.12.13 + pandas==3.0.3**
(and the other declared pins). Re-run only when the pin changes.

## Canonical command shapes

Always from the **repo root**. Always `SUGAR_BX_REQUIRE_QUIET=1`.
Always invoke `bin/brun` by path. Always `.venv-py312` as `PY`.
The quiet wrapper authenticates the pin before your command runs.

```bash
export SUGAR_BX_REQUIRE_QUIET=1
export SUGAR_BX_REQUIRE_CORPUS_PIN=docs/ledgers/pins/pandas-3.0.3.pin.json
export SUGAR_BX_CORPUS_PYTHON=.venv-py312/bin/python

REMOTE_JSON=/tmp/sugar-bx-measure.json   # path ON battleaxe
LOCAL_JSON=/tmp/sugar-bx-measure.json    # path ON the Mac after sync-back
```

### 1. Single file

```bash
SUGAR_BX_REQUIRE_QUIET=1 \
SUGAR_BX_REQUIRE_CORPUS_PIN=docs/ledgers/pins/pandas-3.0.3.pin.json \
SUGAR_BX_CORPUS_PYTHON=.venv-py312/bin/python \
bin/brun \
  --sync-back "${REMOTE_JSON}:${LOCAL_JSON}" \
  -- bash -lc '
    set -euo pipefail
    PY=.venv-py312/bin/python
    test -x "$PY" || { echo "missing .venv-py312; bin/brun -- bash scripts/bootstrap-venv-py312.sh" >&2; exit 78; }
    CORPUS=$("$PY" -c "import pandas, pathlib; print(pathlib.Path(pandas.__file__).resolve().parent)")
    export PYTHONPATH=implementations/python/sugar-lift-py-tests/scripts:implementations/python/sugar-lift-py-tests/src:implementations/python/sugar-source-tree/src:implementations/python/sugar-lift-python-source/src
    FILE_REL="${FILE_REL:-io/json/_json.py}"
    "$PY" -u implementations/python/sugar-lift-py-tests/scripts/control_effect_recensus.py \
      "$CORPUS/$FILE_REL" \
      --corpus-root "$CORPUS" \
      --repo . \
      --commit "$(git rev-parse HEAD)" \
      --require-corpus-pin docs/ledgers/pins/pandas-3.0.3.pin.json \
      --json /tmp/sugar-bx-measure.json
  '
# Trust only exit 0. Cite stderr: lease=held, load1_before/after, bx-corpus-pin phase=ok.
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
SUGAR_BX_REQUIRE_QUIET=1 \
SUGAR_BX_REQUIRE_CORPUS_PIN=docs/ledgers/pins/pandas-3.0.3.pin.json \
SUGAR_BX_CORPUS_PYTHON=.venv-py312/bin/python \
bin/brun \
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
      --require-corpus-pin docs/ledgers/pins/pandas-3.0.3.pin.json \
      --json /tmp/sugar-bx-measure.json
  '
```

### 3. LPT k=8 (one seat, or plan+all seats via CI)

Plan is not a measurement. Measure a seat with the production worker shape:

```bash
# After plan.json exists under .sugar/pandas-control-effect/ (from the CI plan
# job or tools/plan_control_effect_recensus_shards.py on battleaxe):
SUGAR_BX_REQUIRE_QUIET=1 \
SUGAR_BX_REQUIRE_CORPUS_PIN=docs/ledgers/pins/pandas-3.0.3.pin.json \
SUGAR_BX_CORPUS_PYTHON=.venv-py312/bin/python \
bin/brun \
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
      --require-corpus-pin docs/ledgers/pins/pandas-3.0.3.pin.json \
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
| 0 | Finished; stderr has lease acquired, load before/after `lease=held`, and `bx-corpus-pin phase=ok`. JSON at sync-back path. |
| 76 | **Host not quiet** (under lease). No number. |
| 77 | **Lease busy** (or wait timed out). No number. Queue — do not invent a second runner. |
| 78 | **Wrong corpus pin** (e.g. system 2.3.3/1415 vs pin 3.0.3/1421). No number. Bootstrap `.venv-py312`. |
| other | Remote command failure; also not a trusted number. |

A JSON body without exit 0, or without load `lease=held` **and** pin `phase=ok`,
is not a timing receipt.

## CI recensus (control-effect k=8)

Human brun timing uses all three gates (76/77/78). The GitHub
`control-effect-recensus` workflow (LPT k=8 + compose seal) **must** run the
**corpus pin gate** on every plan and every shard job before it mints plan or
partial artifacts — **exit 78** if the runner is not pandas **3.0.3 / 1421**
(`docs/ledgers/pins/pandas-3.0.3.pin.json` via `tools/bx_corpus_pin_gate.py`).
A sealed board against the wrong pin is worse than no board.

Load (76) and lease (77) stay brun-path defaults until CI runner topology is
proven shared-vs-private (matrix may already be multi-box). Pin is mandatory
either way.

## Forbidden

- Any pandas open / walk / census / profile / cProfile / k=8 / demand-table
  scan on the Mac.
- Broad local pytest.
- Reporting a wall-clock taken while `bx-load-gate` was not armed or exited 76.
- Inventing a parallel harness next to `bin/brun`.
- CI plan/shard without the corpus pin gate (exit 78).

## Related

- `docs/build-execution.md` — sugarbin / brun / bpytest routes
- `docs/contributing/measurement-conditions.md` — law + incidents (when present on tip)
- `docs/contributing/heavy-measurement-lease.md` — exclusive heavy jobs on the box
- `bin/brun --help` — options and quiet-gate env vars
- `.github/workflows/control-effect-recensus.yml` — pin gate on plan + each seat
