# Recensus as enumeration consumer (not a private walk)

**Status:** design law (binding for implement)  
**Date:** 2026-08-02  
**Layer:** measurement architecture over `sugar.enumerate`  
**Related:**
- `protocol/specs/2026-07-08-enumeration-protocol.md` (§0, §4, §5A)
- `implementations/python/sugar-lift-py-tests/scripts/control_effect_recensus.py` (current side door)
- `implementations/python/sugar-lift-py-tests/scripts/compose_control_effect_board.py` (seal door; stays)

---

## 0. Choice (one door, not two)

**The recensus becomes a `sugar.enumerate` consumer.**

It does **not** remain a wall-style private walk of 1421 independent
`SourceFile` / `populate` / sugar passes that re-derive the same content
because it was reached by a different path or a different open.

An “admitted side door with the same memo law” is **rejected as the target
shape**. A side door that still opens each file as a private process walk is
exactly the §0/§4 violation. The only admissible interim is a **thin adapter**
that calls the **same kit-internal prepare path** enumerate already uses for
process-resident file context under whole-file content CID — not a second
walker. The destination is still: **demand through enumeration, fold for
counts, seal through compose.**

---

## 1. The law it must obey (quoted, then restated)

From `2026-07-08-enumeration-protocol.md`:

> **§0:** Each request is also the only authority to perform work for the node
> named by `at`. … No batch lift or wall-specific traversal may perform the
> same work outside this verb.

> **§4:** One request performs work for exactly the node named by `at` and
> returns only its immediate child keys. … Whole-file and whole-workspace
> reduction are forbidden side doors. Mementos are the only identities.

> **§4 (kit residency):** Inside the Python kit, demanded file context is
> process-resident under the whole-file content CID. A file request parses and
> prepares module temporal context once for that CID; distinct demanded
> descendants reuse it. Changing the file changes the CID and therefore misses
> without a staleness check. Undemanded definitions are never reduced.

> **§4 (demand memo):** The cache key is the content address of the
> JCS-canonical question tuple `(workspace_root, level, at, seek, options)`,
> never the bare node memento. A repeated question is answered without
> re-crossing the wire.

> **§5A:** A receiver decodes the term table once, interns exactly one shared
> node per CID. Enumeration demand remains the only cause of work.

**Invariant (compose-seal style):**

```
WORK(C)  = pure function of content C and the closed enumerate question that names it
AUTHORITY(C) = sugar.enumerate for the memento that pins C
RESIDENCY(C) = process-resident under whole-file content CID (file context)
               and/or question-CID (demand memo) and/or term CID (DAG)
ILLEGAL    = re-derive C because path, open, reporter, shell, or file index differed
```

Path is not identity. `h = h(p)`. Unshared work across files that pin the same
content is a **protocol violation**, not a performance miss.

---

## 2. What the recensus is today (the crime named)

Today `control_effect_recensus.py`:

1. Pins the corpus (legitimate: population identity).
2. Builds a whole-corpus provisional demand table once (acceptable as **options
   shared by questions**, not as a substitute for file context residency).
3. For each of ~1421 files: private `SourceFile` open → `populate_source_derived`
   → `functions()` → per-function `sugar()` — a **private process walk**.
4. Aggregates rows; compose seals the board.

That is “somebody did one file and called it done, 1400 times” outside
`sugar.enumerate`. It re-prepares content under live path identity
(`id(ref)`, `id(reporter)`, `id(construction_context)`, per-open sessions)
instead of under whole-file content CID. Same module content (e.g. dependency
`enum.py`) is re-derived per path of reach. That is the §0/§4 side door.

Compose seal (`compose_control_effect_board`) stays. **Seal is not the crime.**
The crime is **how terminals are produced**.

---

## 3. What the recensus becomes (precise)

### 3.1 Role

| Piece | Role |
|-------|------|
| **Corpus pin** | Who is enrolled (file identity set + aggregate hash). Unchanged. |
| **sugar.enumerate client** | Sole authority that causes construction work for each demanded node. |
| **Fold** | Sums terminals into residual axes (construction families, panics, CM, desugar). |
| **compose_control_effect_board** | Sole mint of `measurementClass=control-effect-recensus` (already landed). |

### 3.2 What it demands

One consistency window = one kit client for the recensus run (protocol §4).

| Demand | `level` / mode | Purpose |
|--------|----------------|---------|
| D0 | (local) corpus pin / enrolled file list | Denominator **files** — population, not construction work |
| D1 | `source_files` seek or kit file memento for each enrolled path | Bind each enrolled path to a **file memento** (content-pinned) |
| D2 | `functions`, scan `at=file_memento` | Function roster per file → **functionsTotal** denominator |
| D3 | per function: construction demand | Construction residual for that definition only |

**D3 shape (kit must expose, if not already):**

Construction of a demanded function is work authorized by enumerate (or the
same kit door enumerate uses for “definition or lower leaf request performs
only that keyed node's construction”). The response must carry enough for the
census axes:

- construction gaps / `SugarNotWritten` families (occurrence-keyed)
- construction panics (file- or definition-scoped as today)
- optional: With/CM resolution partition when With sites are reduced under that
  demand (source-derived CM is **not** a free whole-file populate tax outside
  demand)

**Forbidden demand shapes:**

- Whole-workspace reduction in one call.
- “Open every file and sugar every function” as a side loop that never goes
  through the enumerate question key / content-CID file residency.
- Private `populate_source_derived` of an entire file before any function is
  demanded (that is whole-file reduction of managers — §4 side door).

### 3.3 How it gets its counts

| Axis | Source |
|------|--------|
| `denominator.files.enrolled` | Corpus pin (D0), not enumerate |
| `denominator.functions.total` | Σ over files of \|D2 nodes\| (function mementos returned) |
| `functionsClean` / construction families | Fold of D3 construction outcomes / gaps |
| `R_construction_panics` | Fold of panic terminals from D3 (or file-level panic if kit surfaces it) |
| `cmResolutions` / withCensus | Fold of CM resolution products from demanded With construction under D3 — **not** a separate full-file populate phase |
| Sealed board | `compose_control_effect_board` over complete terminal set (existing seal law) |

**Completeness:** every enrolled file memento must produce a D2 answer (roster
or named gap). Every function memento that the census enrolls for construction
must produce a D3 answer (outcome or gap). Missing demand → UNMEASURED seat
(same crash-banks-measured discipline as shard attendance), not a quiet smaller
denominator.

### 3.4 Memo law the consumer relies on (does not reimplement)

The recensus client **must not** invent a second cache:

1. **Question memo:** repeated `(workspace_root, level, at, seek, options)` →
   same answer without re-work (protocol demand memo).
2. **File context residency:** first demand that needs file F prepares under
   `whole-file content CID(F)` once; later function demands under F reuse it
   (protocol §4 kit residency — pink’s content-CID work is this floor).
3. **Term / construction coordinate:** shared nodes interned by content CID
   (§5A / construction shape CIDs), never by `id(shell)`.

If the kit violates (2) or (3), that is a **kit bug** against the enumeration
protocol; the recensus does not paper over it with a private walk.

---

## 4. Interim adapter (only if wire levels lag)

Until D3 is fully expressible on the wire for construction residuals:

**Admissible interim:** recensus may call **kit-internal functions that are
already the implementation of enumerate’s file prepare + definition
construction**, provided:

1. They register/reuse process-resident context under **whole-file content CID**.
2. Definition construction is keyed by **content / memento**, not by file index
   or path string alone.
3. No second `SourceFile(...)` open of the same content CID in the same process
   without a hit on that residency map.
4. Dependency module materialize/projection is once per **module source_cid**
   inside that preparation window (session or content shelf — not
   `session_or_new(None)` per receipt).

**Inadmissible interim:** today’s loop of 1421 independent opens that ignore
content-CID residency.

The interim must be labeled in code and job log:
`recensus_mode=enumerate-adapter` vs `recensus_mode=enumerate-wire`.
Both modes produce terminals only for compose; neither mints the board class
except through compose.

---

## 5. What is deleted when this lands

| Deleted | Why |
|---------|-----|
| Private per-file “full open + populate + sugar all” as the authority path | §0/§4 side door |
| Treating `populate_source_derived` as a required whole-file tax before any function demand | Whole-file reduction; CM work must hang off demanded construction |
| Path-identity construction keys as the long-term coordinate | Contradicts content residency; fix is content keys + residency, not endless key narrowing |
| Selling LPT shard of the private walk as the root fix | Shards the side door; does not restore the protocol (compose seal remains valid for aggregation) |

**Retained:**

- Corpus pin / enrollment
- Compose seal + dual-belt attendance
- LPT over **enumerate demand units** later (optional wall packing of independent
  demands) — only after each unit is a legal question, not a private open

---

## 6. Implement order (named, not tonight’s full rewrite)

1. **Pink / kit:** process-resident file context under whole-file content CID
   (enumerate §4) — floor the recensus stands on.
2. **Kit surface:** ensure function-level construction demand returns residual
   products the census folds (gaps, panics, CM partition as applicable).
3. **Recensus rewrite:** replace private walk with enumerate client (or
   interim adapter obeying §4 residency); terminals → existing compose.
4. **Tooth:** same content CID prepared once per process under two demand
   orders / two “files” that share a dependency module; second demand does not
   re-parse/re-materialize (discrimination: force-fail if prepare count > 1).
5. **Tooth:** recensus with wire/adapter mode never calls
   `SourceFile(path)` except inside the content-CID prepare door.

---

## 7. One-sentence law

**The control-effect recensus is a fold of `sugar.enumerate` demands over the
pinned corpus population, sealed by `compose_control_effect_board`; it is not
a private 1421-file walk, and any prepare/construct it triggers must be the
same content-CID-resident work the enumeration protocol already requires.**
