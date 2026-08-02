# Prediction: process-resident RSS over a 1421-file pandas walk

**Author:** mr_pink  
**Status:** prediction only — committed **before** any quiet-gated RSS measure  
**Code basis:** `sugar_source_tree/process_resident_file.py` (#7071 SourceFile,
#7078 lexical), `sugar_lift_python_source/resolution_session.py` (#7081 walk
session). Default `SUGAR_PROCESS_RESIDENT_FILE_LIMIT=512`.

This note is how we catch a wrong number instead of believing it. When the
measurement slot opens, compare observed RSS / prepare counts / late-walk
wall against the claims below.

## What residency holds

Two process-global LRU maps (OrderedDict, access-order):

| Map | Key | Value | Cap |
| --- | --- | --- | ---: |
| `_RESIDENT` | whole-file content CID | `ProcessResidentFileContext` (SourceFile shell + prepared MaterializeModule tree) | 512 |
| `_LEXICAL` | `(source_cid, is_package, identities)` | pure lexical import `_Pass` product | 512 |

Eviction: on insert, `move_to_end`; while `len > limit`, `popitem(last=False)`
drops the **oldest**. Dropped objects become GC-eligible; **prepare counters
are not cleared** (`_PREPARE_COUNTS` / `_LEXICAL_PREPARE_COUNTS` grow forever
and record re-pays after eviction).

Hit path: `get_resident` / lexical hit rebinds consumer `construction_context`
and returns the shell without re-MaterializeModule.

## What is *not* LRU-capped

Walk-scoped `SourceResolutionSession` (production open default via
`walk_session_for(root)`):

- `frame_results` / **`frame_holds`** (keeps projected SourceFiles alive)
- `module_materializations` / `prefix_files`
- export / lexical session tables, `dependency_graphs`

These dicts have **no size bound**. They grow for the life of the process
session under one workspace root.

## Predicted RSS shape (1421 enrolled files, one process, sequential open)

Assume default limit 512, pin pandas 3.0.3, populate_derived=True, walk session
shared across the walk.

### Phase A — fill (roughly until ~512 unique content CIDs demanded)

- `resident_size` climbs toward 512.
- `lexical_size` climbs toward 512 (not necessarily in lockstep with
  SourceFile: package role + identity map can diversify keys).
- **RSS rises roughly with fill** — each miss pays MaterializeModule + holds
  a full prepared tree. This is the intended wall-time ↔ memory trade of §4.

### Phase B — at/after the cap

- **`resident_size` and `lexical_size` MUST plateau at ≤512.**  
  If either exceeds the limit, the LRU is broken (instrument failure).
- **RSS need not plateau.** Two independent reasons:

  1. **Walk session maps (primary unbounded risk).** `frame_holds` pins live
     projection SourceFiles for every distinct frame key ever served. Orange
     measured almost no cross-file frame *hits* on a 20-file sample
     (`frame_results` after 20 files ≈ 1), but the **holds still accumulate**
     for every definition projected during populate of *this* file's use-sites.
     Over 1421 consumers that is a large, session-lifetime set — not content-CID
     LRU.

  2. **Allocator high-water.** Even when LRU drops a SourceFile, CPython often
     does not return pages to the OS. RSS can stay near the peak of phase A
     (or keep creeping) while `resident_size` is flat.

### Re-preparation after eviction

- Unique consumer bodies in a once-through walk: each enrolled file's own CID
  is prepared **once** unless the walk revisits the same content later.
- Shared dependency modules (imported from many consumers) are the thrash
  surface: after cap, an old dep CID can be evicted, then re-demanded →
  `_PREPARE_COUNTS[cid] > 1`.
- **Prediction:** `prep_cids_gt1 > 0` and `prep_sum > prep_unique` once the
  walk has demanded more than 512 distinct prepared CIDs (consumers + deps).
  If unique prepared CIDs stay ≤512 for the whole walk, prep_gt1 may stay 0
  and LRU never fires — also a legal observation (narrow dep set).

### Late-walk wall (Q4 vs Q1 mean file time)

| Observation | Read as |
| --- | --- |
| Q4/Q1 ≈ 1.0–1.5 and prep_gt1 moderate | expected: mild thrash + session bloat |
| Q4/Q1 ≫ 2 and prep_gt1 high | eviction thrash is load-bearing — limit too small or working set too large |
| Q4/Q1 high and prep_gt1 ≈ 0 | **not** SourceFile LRU — blame walk-session growth / GC / other |

#7081's own caveat (memory pressure late in a walk) points at session
`frame_holds`, not at the 512 SourceFile cap.

## Falsifiers (measurement must name these)

1. `resident_size_end > 512` or `lexical_size_end > 512` → LRU bug.
2. RSS **flat** after file ~100 while `resident_size` is still rising → RSS
   sampling broken (wrong process, wrong metric).
3. `prep_cids_gt1 == 0` with `prep_unique ≫ 512` → miss path not counting or
   eviction not re-entering prepare (protocol bug).
4. RSS grows unbounded while both LRU sizes stay at 512 and walk-session map
   sizes stay flat → unknown retainer; investigate before blaming residency.

## What a successful measure must report (slot = after black seal)

Under `SUGAR_BX_REQUIRE_QUIET=1` + corpus pin 3.0.3/1421 + lease held:

- `load1_before` / `load1_after`, `lease=held`, `bx-corpus-pin phase=ok`
- RSS start / end / max (`/usr/bin/time -v` Maximum resident set size)
- `resident_size` / `lexical_size` time series or end values vs limit 512
- `prep_unique`, `prep_sum`, `prep_cids_gt1` (and lexical analogues)
- walk-session `len(frame_holds)`, `len(frame_results)`,
  `len(module_materializations)` at end
- quartile mean file wall if available

**Non-claims until measured:** absolute RSS in MiB, whether eviction thrash is
the dominant late cost, whether #7081 must be bounded or reverted.

## Relation to #7081

Process residency (#7071/#7078) is **capped** and is the honest §4 door.
Walk session is the **uncapped** live-Node store. If RSS is the problem at
corpus scale, the first place to bound is session maps (or session lifetime),
not deleting content-CID residency.

---

*No wall-clock numbers in this document. Measurement waits for the fleet
queue after mr_black's seal.*
