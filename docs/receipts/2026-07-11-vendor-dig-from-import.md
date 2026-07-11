# Vendor dig foundations — TupleValue.to_term + from_imports maps

## Shipped
1. **TupleValue.to_term** — `(a, b)` projects as `tuple(...)` for assert equality
   (return_timestamp-style vendor faces).
2. **`_module_import_maps`** — `import_aliases` + `from_imports` seeded on
   `FactoryBuildContext` for every def (not temporal-only).
3. Ratchets for tuple eq, maps, coordinate sign/unsign.

## Suite (itsdangerous sdist)
| | before | after |
|--|-------:|------:|
| lifted | 34 | **36** |
| refused | 23 | **21** |
| silent | 0 | **0** |

## Not yet (honest)
Full install-source **body** dig on `Signer.sign` (CallSugar still `body=None`) —
coordinate + maps are the membrane; body dig attaches next when dig enqueue
uses from_imports + `_sugar_file` tags.
