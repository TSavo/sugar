# Kit manifests (#5907)

This directory holds **declared** kit/bridge contract manifests — evidence
files consumed by `sugar_lift_py_tests.recognition.kit_manifest` via the
`SUGAR_KIT_MANIFEST` environment variable / `corpus_fatal_triage.py
--kit-manifest` flag (wired in #5908).

## Law

- **Nothing here loads by default.** No script, test fixture, or production
  import path reads a file in this directory implicitly. A manifest only
  takes effect when a caller explicitly names its path.
- **A manifest is a declared, hashed act**, not ambient configuration. Every
  load computes and records the file's sha256 so the loaded contract is
  traceable to the exact bytes that authorized it.
- **Without a manifest, rows stay loud.** `R_vendor_special_case = 0` and
  the empty-by-construction default (#5618, #5907) both depend on that: a
  relocated or copy-pasted vendor coordinate into production recognition
  tables is exactly the deleted logo-table pattern and must never happen —
  declaring a coordinate here, and loading it explicitly at mint time, is
  the only lawful path.

## `numpy_families_5907.json`

Declares the five `imported_callee` coordinates for the families re-earned
and merged as of #5907's follow-up:

| Coordinate | Family / issue |
| --- | --- |
| `numpy.all` | #5902 / #5408 |
| `numpy.dtype` | #5902 / #5407 |
| `numpy.issubdtype` | #5903 / #5400 |
| `numpy.isnat` | #5904 / #5402 |
| `numpy.isnan` | #5905 / #5404 |

`call:conv` (#5903 / #5409) is **not** in this manifest — that family was
re-earned via structural assign provenance (`BOUND_SOURCE_CALLABLE`) in
production recognition itself, not via a loaded kit coordinate, so it needs
no manifest entry.

Usage (mint with the contract declared):

```bash
python scripts/corpus_fatal_triage.py numpy \
  --kit-manifest implementations/python/sugar-lift-py-tests/kit_manifests/numpy_families_5907.json
```

Omitting `--kit-manifest` mints with no contract: the five coordinates above
stay unrecognized and their rows stay `FactoryPanic`/unclassified — the
correct, honest default.
