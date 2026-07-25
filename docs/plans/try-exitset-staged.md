# Try / ExitSet — staged, do not merge

**Status:** STAGED ONLY. Merge waits on the **post-V2 / post-Merkle census**
gate (bounded residual + reconciled board). Building against the ExitSet law
now costs nothing while encoder/Merkle finish.

**Region:** `nodes.py` Try / TryStar + `try_sugar.py` / ExitSet routing.  
**Coordinate with:** Assign (`#6239` / unpack residuals) — both touch statement
construction; do not edit Assign.

## Six-line ExitSet law (foundational path)

```text
body
  → guarded ExitSet
  → handler routing over Halted
  → finally over every exit
```

Concrete ownership already in `TrySugar.desugar`:

1. `body → reduce_block_to_exitset` (+ raise promotion)
2. `_route_handlers_over_exits` over Halted (except-as = EffectRef slot)
3. `else` only on Completed fall-through
4. `finally` = `ExitSet.and_finally` over every exit
5. cleanup fall-through restores; cleanup halt/return supersedes
6. `exitset_to_outcome` at the membrane

No second control-effect door. No linear adapter as the production path.

## Law twins (required before any residual claim)

Pinned in `sugar-source-tree/tests/test_try_exitset_law.py` (and the
source-doc pin in `test_try_exitset_law_staged.py`):

| Twin | Meaning |
|------|---------|
| handlers in source order | Arms are tried as written in the source |
| first match only | First matching arm wins; later arms never run |
| `as` uses the routed effect slot | EffectRef/slot + origin, not reconstructed `E()` |
| `else` never after a halt even if handled | Else only on Completed body exit |
| `finally` on all seven exits | See table below |
| bare re-raise same effect occurrence | In-flight RaiseEffect; occurrence is the original raise site |
| no reconstruction | No invented raise at the bare-`raise` line |
| no invented fall-through | Uncaught / handler halt does not fabricate completion |
| `except*` separately loud | Ordinary try ≠ except*; group/ordinary mismatch stays loud |

### Seven exits finally must cover

1. Normal completion (fall-through)
2. Body return
3. Uncaught raise (restore through inert finally)
4. Caught raise → handler completion
5. Caught raise → handler raise
6. Break
7. Continue

## Allowed staged work

- Widen Try construction partitions that already obey the law (authenticated
  except types, try/finally-only, except-as EffectRef)
- Add red/green twins that pin ExitSet routing
- Keep `except*` / TryStar loud until its own sugar is census-gated

## Forbidden until census gate

- Merge to main
- Soft Incomplete for unhandled handlers
- Absorbing Assign residuals into Try
- Claiming Try residual ΔR before post-V2 census

## Gate to merge

Post-V2 / post-Merkle full census reports a bounded Try residual; board
reconciled; Assign region not in conflict.
