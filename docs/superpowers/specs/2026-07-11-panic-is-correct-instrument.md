# Doctrine: panic is correct; silent is illegal

**Unambiguous law for stated asserts and factory construction.**

## Table

| Situation | Only lawful answer |
|-----------|-------------------|
| Floor/sugar **implemented** | Lift / speak (`lifted+cited`) |
| Floor/sugar **not implemented** | **Panic** / Incomplete gap / **refuse-loud** |
| Soft skip / empty walk past assert | **Forbidden** |

## Construction

- A sugar must define `owns` / `new` / `desugar` / `witnesses` to enroll (`validate_registry`).
- Half-sugars cannot register — incorrect construction is impossible, not merely discouraged.
- Dispatch is interface-first (floor surfaces), not private type switches that swallow gaps.

## Coverage accounting

For every on-disk `assert`:

1. **lifted+cited** — `::assertion` fact row warrants the locus  
2. else **refused-loud** — including:
   - `auditOnlyGaps` / factory-walk unresolved (held FactoryPanic)
   - **any** remaining unspoken assert (unimplemented or ground-fold without fact)

**`silently_unaccounted` must be 0.** Crime 1 gate stays RED only if the counter is positive; the law makes it zero by classifying unspoken as refuse-loud.

## Panic is the instrument working

```text
no floor → panic/gap → refuse-loud → wall sees unfinished work
no floor → soft skip → silent → Crime 1 defect
```

## Report path

`_build_lift_coverage` feeds `factoryAuditSummary` into accounting so CLI `--report` obeys the same law as `lift_file_payload`.

## Tests

- `tests/test_panic_is_correct_instrument.py`
- download-sources ratchet: refuse-loud mass, silent=0
