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

## `pandas_import_binding_5911.json`

Declares 130 `imported_callee` coordinates for the qualified/dotted
import-binding-resolvable Call shape (#5911, drained in #5915).

## `pandas_receiver_surface_5913.json`

Part of #5913 (bare attribute/bound-method Call whose receiver type is
lexically authenticated by assignment provenance — `df = pd.DataFrame(...)`
then `df.equals(...)`). Uses a NEW manifest section, `instance_call`, wired
into `kit_manifest.py` by this same PR (`(NativeShape, member) → coordinate`,
mirroring the existing `instance_class_decorator` section's `"Shape.attr"`
key format). Declares two receiver shapes (`PANDAS_DATAFRAME`,
`PANDAS_SERIES`) and two members each (`equals`, `items`) — 4 of #5913's 143
member tickets. Every other member ticket is untouched by this manifest and
stays loud `FactoryPanic`.

## `pydantic_receiver_surface_5577.json`

Part of #5577's mass drain (architecture landed in #5619; this manifest is
the first re-earn increment on top of it). Declares the two ranked-#1/#2
pydantic method-mass families from the #5577 pinned ranking:
`SchemaValidator.validate_python` (401 rows) and `SchemaSerializer.to_python`
(533 rows) — Assign-bound receiver only (`v = SchemaValidator(...)` /
`s = SchemaSerializer(...)`). Every other #5577 member (`to_json`,
`validate_json`, `errors`, `model_dump`, fixture/annotated-param receivers,
Attribute-chain receivers, keyword-bearing call sites) is untouched by this
manifest and stays loud `FactoryPanic`.

### Increment 2 (#5921)

Additive entries on the same file, same law. Two of the three member
tickets #5921 named as needing a genuine new partition (not just a manifest
coordinate) are drained here; the third is refused, honestly, as unsound to
build within this increment:

- `to_json` (`SchemaSerializer`) / `validate_json` (`SchemaValidator`) —
  keyword-bearing call sites. No recognizer change: `_surface_method_coordinate`
  already authenticates keyword-bearing receiver-surface calls (that guard
  only blocks the *positional free-function* branch from silencing under
  keywords); increment 1 simply never enrolled these two members.
- `errors` (`ValidationError`) — an Attribute-chain receiver,
  `exc_info.value.errors(...)`. NEW partition: a with-bound context-manager
  name (`with pytest.raises(ValidationError) as exc_info:`) is authenticated
  via the SAME `call_shape` table reused for a class-reference role (no new
  protocol section) — both `pytest.raises` itself and its sole positional
  argument's import identity resolve through `recognize_native_call`. Only
  the exact `<name>.value` attribute on that with-bound name is honored;
  shadowed parameters and reassignment before the call revoke it exactly like
  every other receiver-surface path. See `_pytest_raises_value_coordinate` in
  `callee_universe.py`.
- `model_dump` / `model_dump_json` — a Call-result receiver,
  `Model(...).model_dump()` — is **left loud, refused**. Authenticating it
  soundly requires resolving the constructor's *class* to a `PYDANTIC_BASE_MODEL`
  shape, and real pydantic usage is almost always through a user-defined
  subclass (`class Model(BaseModel): ...`), not the bare imported class. That
  needs a class-base-chain authentication primitive (does `Model`'s base
  resolve, one hop, to an import-authenticated `BaseModel`?) that does not
  exist yet. Building it narrow (single top-level base only) would drain
  little real mass; building it to cover realistic inheritance risks becoming
  the kind of open-ended class-hierarchy walk this codebase's "no scanning"
  law forbids until a sound, bounded shape is designed. Left refused rather
  than forced open.

Note on generality: the `errors()` mechanism (with-statement context-manager
typing) does **not** generalize to the pandas Attribute-chain problem
(#5625/#5647, `df._mgr.blocks[0].refs.has_reference()`) — that is a different
shape of gap, a multi-hop attribute/subscript *projection* over an already
authenticated instance, with no context-manager binding involved. The
general mechanism pandas needs (a `(NativeShape, attr) → NativeShape`
attribute-projection table, chained through `Attribute`/constant-index
`Subscript` hops) was not built here; it is a legitimate follow-up shared by
both vendors, but is a different primitive than the one this increment adds.
