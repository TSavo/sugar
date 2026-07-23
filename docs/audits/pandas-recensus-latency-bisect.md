# Pandas construction recensus latency bisect

Date: 2026-07-23  
Worktree: `pandas-with-recensus-20260723`  
Corpus: installed `pandas==3.0.3`  
Probe: `implementations/python/sugar-lift-py-tests/scripts/pandas_recensus_latency_probe.py`

## Symptom

Single production files in the construction recensus spend **~87–160s** wall time
(e.g. `core/arrays/categorical.py`, `core/arrays/datetimelike.py`) where the
expectation for a construction pass over one module is **milliseconds–low
seconds**.

The recensus path is honest: `production_source_file` (source-derived CM refs +
source-visible call frames) then `function.sugar()` for every function. This
bisect does **not** recommend skipping that door.

## Method

1. Phased single-file probe with `artifact_graph_cache` shared as recensus does.
2. Internal counters on `AuthenticatedImportUseV1.revalidate` and
   `authenticated_import_uses`.
3. Micro-timers around `DependencyArtifactGraph.authenticate`,
   `resolve_import_binding`, and `resolve_source_visible_frame`.

Commands (from repo root, local Mac probe — one/two files only):

```bash
export PYTHONPATH=implementations/python/sugar-lift-py-tests/scripts:\
implementations/python/sugar-lift-py-tests/src:\
implementations/python/sugar-source-tree/src:\
implementations/python/sugar-lift-python-source/src

python3 implementations/python/sugar-lift-py-tests/scripts/pandas_recensus_latency_probe.py \
  --file core/arrays/categorical.py \
  --phase-preconstruction \
  --json /tmp/pandas-latency-categorical-nolog.json
```

Counter run (preconstruction only, two hot files, warm graph cache across files):

```bash
# see /tmp/pandas-latency-bisect-summary.json from the bisect session
```

## Quantified breakdown

### `core/arrays/categorical.py` (3183 lines, 88 functions, 508 Call nodes, 1 With)

| Phase | Seconds | Share |
| --- | ---: | ---: |
| `populate_source_visible_call_frames` | **137.3** | **~92%** |
| `populate_source_derived_resource_refs` | 1.05 | ~0.7% |
| `SourceFile` materialize | 0.05 | ~0% |
| install unresolved CM gaps | 0.07 | ~0% |
| With inventory walk | 0.08 | ~0% |
| all `function.sugar()` (88) | **10.1** | **~7%** |
| **total** | **~149** | 100% |

Top function construction times (after preconstruction): max **1.1s**
(`__init__`), median **16ms**, sum **10.05s**. Construction is not the wall.

Preconstruction-only counter run (shared cache):

| File | preconstruction_s | revalidate_calls | authenticated_import_uses_calls | s/revalidate est. |
| --- | ---: | ---: | ---: | ---: |
| `core/arrays/categorical.py` | **121.2** | **125** | **127** | **0.97** |
| `core/arrays/datetimelike.py` | **159.8** | **169** | **171** | **0.95** |

`auth_uses ≈ revalidate + 2`: the `+2` is the two mint passes
(`populate_source_visible_call_frames` and `populate_source_derived_resource_refs`
each call `authenticated_import_use_receipts` once). Every remaining call is
**one full-module lexical re-scan per import-use receipt** inside
`resolve_import_binding` → `AuthenticatedImportUseV1.revalidate`.

### Inside the call-frame loop (categorical, warm numbers)

| Substep | Seconds | Notes |
| --- | ---: | --- |
| `DependencyArtifactGraph.authenticate(pandas)` | ~22–24 | 2944 files; **once** then cache hit |
| `DependencyArtifactGraph.authenticate(numpy)` | ~9–10 | 1336 files; **once** then cache hit |
| `resolve_import_binding` (all matched receipts) | **~100–106** | **uncached**; second full pass still ~97s |
| `resolve_source_visible_frame` | 0.17 | only 2 receipts reach it |
| `authenticated_import_use_receipts` mint | 0.87 | once per populate_* |

Matched import-use Call receipts: **134** (categorical). Outcomes:

- `dynamic-export` gaps: **99** (still pay full revalidate)
- `target-outside-binding` gaps: **24**
- resolved OK: **2** (then `opaque-call-target` at frame build)

So almost all of the ~100s is spent re-proving lexical import uses that already
failed export resolution — and re-proving them **again on every receipt**.

### Sample `resolve_import_binding` costs (same symbol paid repeatedly)

| elapsed_ms | result | target |
| ---: | --- | --- |
| 1228 | ok | `pandas.core.algorithms.take_nd` |
| 1098 | dynamic-export | `pandas.core.indexes.range.RangeIndex` |
| 1029 / 966 / 955 | dynamic-export | `pandas._config.get_option` (×3) |
| 937 / 929 / 906 | dynamic-export | `pandas.core.construction.sanitize_array` (×3) |
| ~890 | dynamic-export | `numpy.array` / `numpy.bincount` / … |

Per-receipt cost is dominated by `revalidate()` (~**0.72s** average on this
machine for categorical's source), not by `resolve_export` (~3.3s total for the
file).

### Function construction / engine log

- Engine log is **not** on the full recensus path (`run_pandas_recensus_remote.sh`
  does not set `SUGAR_ENGINE_LOG`). Span overhead is therefore not the live
  multi-minute wall.
- When enabled, statement-level `SubstituteStatement` spans are dense; useful for
  bisection, not the primary multi-minute cost here.
- Gaps / `SugarNotWritten` do **not** cause pathological retries in the recensus
  loop (one `function.sugar()` per function; panics are caught and counted).

### Once per file vs once per function

| Work | Frequency |
| --- | --- |
| `populate_source_visible_call_frames` | **once per file** |
| `populate_source_derived_resource_refs` | **once per file** |
| `artifact_graph_cache` authenticate | **once per distribution** (shared across files) |
| `AuthenticatedImportUseV1.revalidate` → full `#6090` lexical pass | **once per import-use receipt** inside that file |
| `function.sugar()` | once per function (~10s total on categorical) |

Cost is **quadratic in the wrong place**: for a file with `R` authenticated
import-use receipts, the resolution door re-runs the **entire** module lexical
pass `R` times → **O(R · size(module_lexical_analysis))** per file, with no
process cache.

## Root cause

### Primary mechanism (dominant)

`resolve_import_binding` always calls `authenticated_use.revalidate()`:

```178:197:implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/import_binding.py
    def revalidate(self) -> None:
        """Re-run #6090 and demand byte identity at the resolution door."""
        rows, outcomes = authenticated_import_uses(
            self.root,
            self.path,
            self.source,
            self.source_cid,
            module_identities=self.module_identities,
        )
        ...
        if outcomes.get(key) != "authenticated-import-use" or self.demand not in rows:
            raise ValueError(...)
```

That re-executes the full non-constructing lexical import-use analysis for the
**whole consumer module** on **every** receipt. Preconstruction then does:

```
for receipt in receipts:          # R ≈ 125–170 on hot pandas files
    resolve_import_binding(...)   # each → full authenticated_import_uses
```

Observed: **R ≈ auth_uses − 2**, **~0.95–0.97s per revalidate**, wall time
**~120–160s/file** before any function construction.

### Secondary (first file / cold process)

`DependencyArtifactGraph.authenticate` hashes every recorded installed file
(pandas ~2944, numpy ~1336) — **~30s** cold. Recensus already shares
`artifact_graph_cache` across files, so this is a one-time process tax, not the
per-file 87–134s after the first hit.

### Non-causes (ruled out)

| Hypothesis | Verdict |
| --- | --- |
| Per-function re-preconstruction | **No** — populate once per file |
| Gap rethrow / retry storms | **No** — single sugar attempt per function |
| Engine-log sync I/O on full recensus | **No** — log not enabled |
| Artifact graph rebuild every file | **No** — cache hits after first authenticate |
| Function construction itself | **No** — ~10s of ~150s |

## Fix shape (one cut)

**Amortize lexical revalidation at the resolution door** — one general
capability, not a pandas special case:

1. **Preferred:** cache `authenticated_import_uses(root, path, source, source_cid, …)`
   process-locally keyed by `(source_cid, path, identity_fingerprint)` with the
   same content-keyed eviction discipline as `source_tables` (finite LRU).
   `revalidate()` becomes O(use-site check) after the first call for that module.
2. **Equivalent batch form:** preconstruction resolves all receipts under one
   shared revalidation snapshot minted once per file, then only checks demand
   membership / CID identity per receipt (no N full rescans).
3. **Keep the law loud:** revalidation must still fail if the demand is not
   byte-identical to the lexical pass; only the **recompute frequency** changes.
4. **Optional second cut (smaller):** memoize `resolve_export` /
   `resolve_import_binding` by
   `(distribution_artifact_cid, module_name, exported_name)` so repeated
   `get_option` / `sanitize_array` / `numpy.array` sites do not re-walk export
   chains after revalidation is fixed (today export is ~3s/file; secondary).

Do **not** “fix” by skipping `production_source_file`, silencing gaps, or
dropping call-frame preconstruction. Those doors are the measurement.

### Expected delta after primary fix

For categorical-class files: **~R × 0.95s → ~1 lexical pass (~1s)** plus real
export work (~3s) plus construction (~10s) → **order-of-magnitude drop** from
~120–160s preconstruction to **low tens of seconds or less** (plus cold
authenticate once per process). Across a full pandas recensus with thousands of
import-use receipts, wall time should fall by **minutes to hours**.

## Red instrument

`test_resolve_import_binding_amortizes_lexical_revalidation` in
`implementations/python/sugar-lift-python-source/tests/test_dependency_artifact_graph.py`
counts `authenticated_import_uses` invocations while resolving **N>1** receipts
from one consumer module and fails while the count remains **Ω(N)**.

That pin stays red until revalidation is amortized; it is a structural budget,
not a flaky wall-clock threshold.

## Probe artifact

`pandas_recensus_latency_probe.py` remains the local/battleaxe single-file
bisection tool (`--phase-preconstruction`, optional `--engine-log`).
