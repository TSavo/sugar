# Recensus as `sugar.enumerate` consumer

**Status:** binding design law (T ruled 2026-08-02: **NO side door**)  
**Date:** 2026-08-02  
**Related:**
- `protocol/specs/2026-07-08-enumeration-protocol.md` (§0, §4, §5A)
- `compose_control_effect_board.py` (sole seal door — retained)
- pink owns §4 process-resident file context under whole-file content CID
- black owns this consumer

---

## 0. Ruling

> We don't admit side doors. It should just become an enumeration consumer.
> And it's insane that it's not already. — T

**The control-effect recensus is a `sugar.enumerate` consumer.**  
There is no admitted private walk, no “same memo law side door,” no parallel
`_measure_file` authority path. The old door **retires**.

---

## 1. Protocol law (why this is the only shape)

Quoted from `2026-07-08-enumeration-protocol.md`:

**§0** — *Each request is also the only authority to perform work for the node
named by `at`. … No batch lift or wall-specific traversal may perform the same
work outside this verb.*

**§4** — *One request performs work for exactly the node named by `at` …  
Whole-file and whole-workspace reduction are forbidden side doors. Mementos are
the only identities.*

**§4 kit residency** — *demanded file context is process-resident under the
whole-file content CID. A file request parses and prepares module temporal
context once for that CID; distinct demanded descendants reuse it.*

**§4 demand memo** — *cache key is the content address of the JCS-canonical
question tuple `(workspace_root, level, at, seek, options)`.*

**Invariant:**

```
AUTHORITY(work on content C) = sugar.enumerate(memento pinning C)
RESIDENCY(file F)            = process-resident under whole-file content CID(F)
COUNTS                       = fold of enumerate nodes + gaps only
SEAL                         = compose_control_effect_board only
ILLEGAL                      = private SourceFile/populate/sugar walk of 1421 files
```

The memo is **free** once the recensus is a consumer: §4 residency is pink’s
floor; the census stops re-deriving by **stopping derivation**.

---

## 2. What the census DEMANDS (as enumerate requests)

One kit client / consistency window for the whole run.

| Step | Request | Meaning |
|------|---------|---------|
| **D0** | Corpus pin (local) | Enrolled population — who is measured (not construction work) |
| **D1** | For each enrolled path: bind **file memento** (`file` + `source_cid` / `file_cid`) | Identity for `at` |
| **D2** | `level=functions`, `seek=false`, `at=file_memento`, `workspace_root=corpus` | **Function roster** for that file |
| **D3** | Construction residual for that file (or each function) | **Construction outcomes** |

### D3 — construction residual (precise)

The census needs, per enrolled file (and ultimately per function):

- construction gaps / families (`SugarNotWritten`, …)
- construction panics
- instrument-defects (unresolvable dispatch, …)
- optional desugar residual when sugar succeeded

**Wire today:**

- `level=functions` returns **roster mementos** (and kit may prepare file context
  under content CID as side effect of answering D2 — that prepare is **enumerate’s**
  work, not the recensus’s).
- Construction roll-call residual is already served as an enumerate product via
  **`options.auditFrontier=true`** at **`level=facts`** with `at=file_memento`
  (`_roll_call_audit_leaf`: CollectingReporter + discharge → panics/gaps).

**Demand sequence per enrolled file:**

```
1. sugar.enumerate { level: functions, at: file_memento, seek: false }
      → nodes[] function mementos  → functionsTotal for this file
      → gaps[] if file unreadable / CID mismatch

2. sugar.enumerate { level: facts, at: file_memento, seek: true,
                     options: { auditFrontier: true } }
      → audit.semanticCore.panics / status / sourceAudit
      → construction residual for the demanded file
```

**Future (kit growth, not a recensus side door):** per-function construction
demand (`level=functions` seek with construction options, or a dedicated
construction residual on the function memento) so undemanded definitions stay
unreduced. Until then, **file-scoped construction residual is still an
enumerate demand** (facts+auditFrontier), not a private walk.

### Forbidden

- Calling `SourceFile` / `populate_source_derived` / `function.sugar()` from the
  recensus script as a second path.
- Keeping `_measure_file` as a fallback “if enumerate fails.”
- Whole-corpus reduction outside the verb.

---

## 3. Where COUNTS come from

| Count | Source |
|-------|--------|
| `denominator.files.enrolled` | Corpus pin (D0) |
| `denominator.files.terminal` | One terminal row per enrolled file that completed D1–D3 |
| `functionsTotal` | Σ \|D2.nodes\| over enrolled files (function mementos) |
| `functionsClean` | From D3 residual: functions that constructed without gap (when kit reports it); else derived as `functionsTotal - gap-bearing function loci` from roll-call coordinates |
| `families` / construction gaps | D3 panics/gaps, occurrence-keyed |
| `R_construction_panics` | D3 panics with ConstructionPanic kind |
| instrument-defects | D3 gaps with instrument-defect kinds |
| `cmResolutions` / withCensus | Only if returned on enumerate construction residual; **not** a private populate tax |
| Sealed board | `compose_control_effect_board` over complete terminals |

**Nothing** is counted from a private traversal the recensus invents.

Missing D2 or D3 for an enrolled file → **terminal incomplete** → compose
UNMEASURED / red denominator (crash-banks-measured), not a quiet shrink.

---

## 4. What happens to `_measure_file`

**It is the side door. It does not survive as a second path.**

| State | Rule |
|-------|------|
| Authority | `_measure_file` is **not** the authority for any bankable residual |
| Code | Removed from the production recensus entrypoint (deleted or reduced to a
  test-only helper **outside** the scoreboard path, never called from main) |
| Same law as compose | One door produces terminals: **enumerate**. One door seals:
  **compose**. Serial walk of SourceFile is not left parallel behind a flag |

---

## 5. Coordination with pink (§4 residency)

| Owner | Delivers |
|-------|----------|
| **pink** | Process-resident file context under **whole-file content CID**; D2/D3
  prepare hits that map so second demand for the same CID does not re-parse /
  re-materialize |
| **black** | Recensus as enumerate client + fold + compose; no private walk |

The consumer does not reimplement residency. If prepare still re-derives, that
is a kit §4 bug on pink’s floor, measured by a tooth: same content CID demanded
twice → prepare count = 1.

---

## 6. One-sentence law

**The control-effect recensus is a fold of `sugar.enumerate` demands over the
pinned corpus (function roster + construction residual), sealed only by
`compose_control_effect_board`; `_measure_file` and every private SourceFile
walk are retired side doors, and content-CID file residency is supplied by the
enumeration kit (pink), not reinvented by the census.**
