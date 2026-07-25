# Try / ExitSet — staged, do not merge

**Status:** STAGED ONLY. Merge waits on the post-Merkle census gate
(bounded residual + reconciled board). Building against the ExitSet law now
costs nothing while encoder/Merkle finish.

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

## Allowed staged work

- Widen Try construction partitions that already obey the law (authenticated
  except types, try/finally-only, except-as EffectRef)
- Add red/green twins that pin ExitSet routing
- Keep `except*` / TryStar loud until its own sugar

## Forbidden until census gate

- Merge to main
- Soft Incomplete for unhandled handlers
- Absorbing Assign residuals into Try

## Gate to merge

Post-Merkle full census reports a bounded Try residual; board reconciled;
Assign region not in conflict.
