# and_then construction panic partition (board-ready)

## Purpose

When control_effect_recensus produces a **tip** `recensus.json`, run:

```bash
python3 implementations/python/sugar-lift-py-tests/scripts/and_then_construction_panic_partition.py \
  --board /path/to/recensus.json \
  --json-out /tmp/and-then-partition.json
```

Do **not** fire a second recensus from this script. Measurement authority is the
sole scoreboard (`control_effect_recensus.py`).

## Why

Deferred Exit design needs the tip split of and_then-related construction
panics. A stale 9a board showed `native=0, pending-contract=283, guarded=25` of
a larger mass — **refuting** “283 = Deferred / NativeOperationExitCarrierV1”.
Tip R for those buckets is unknown until the live board lands.

## Live instrument (no curated corpus list)

| Layer | Source |
| --- | --- |
| Mouth census | AST of production modules that call `construction_panic_gap` for and_then / exit conversion |
| Board rows | `desugarConstructionPanics` + `constructionPanics` on the recensus artifact |

Buckets: `native_deferred` | `pending_contract` | `guarded` | `other`.

## Deferred acceptance (owner ruling)

Deferred is typed “not yet discharged”. Undischarged Deferred at a terminus
must **panic**. Accept only if loud incompleteness mass is preserved or
increased (relocated), never silenced.

## Ladder

1. Type forbid undischarged carrier at terminus? Not yet (Deferred not built).
2. One door? `outcome_to_exitset` + carrier mouths — this instrument **measures** them.
3. Panic? Yes at undischarged native; pending-contract and guarded have their own.
4. Auditor: this partitioner. **Retires** when Deferred + contract algebra make
   mislocated mid-sequence panics unrepresentable and terminus panics are the
   only incompleteness for those faces (stable tip split at Deferred design).

## Shell deleted

Banking “Deferred mass = 283” from a stale board without tip re-partition.
This instrument makes that claim unbankable without a live board run.
