# First sealed pandas frontier receipt

## Authority

- Measured commit: `1b3ac2dd9675b00507ea438a7580306dd95015f7`
- Corpus: pandas `3.0.3`, 1,421 content-pinned Python files
- Corpus aggregate SHA-256: `bbb70a76f4032eda3362102c8bd872ca769b6f8143a91f60a36374fa1066b76c`
- Corpus manifest CID: `sha256:a223a4499d0909f22190748b4aca9144e35a58fec31e84cb924e2c25fd3c03d0`
- Status: `sealed`; measured: `true`
- Frontier width: `477`
- Complete files: `944 / 1421`; panicked files: `477 / 1421`; missing files: `0`

`477` is a **first-terminal lower bound**, never remaining work. Each terminal
halts its file, so descendants behind that terminal are unmeasured. The
frontier is concentrated: 944 of 1,421 files complete.

## Owner drain list

Owners are ranked from the sealed `constructionPanics` rows. The complete
coordinate/source-CID index is `owner-coordinate-breakdown.json`.
`drain-list.json` adds every row's observed shape, requested construction, fix
text, entrance, and construction trace, then groups rows by the strongest
shared-construct claim the sealed evidence supports.

1. `With._construct_sugar`: 471 rows at 471 unique coordinates.
2. `populate_same_module_class_manager`: 3 rows:
   - `io/parsers/readers.py` — `TextFileReader`
   - `io/pytables.py` — `HDFStore`
   - `io/stata.py` — `StataReader`
3. `roll_call.discharge`: 3 rows:
   - `core/sorting.py:1:0-737:0[Module]`
   - `tests/base/test_misc.py:95:4-102:35[FunctionDef]`
   - `tests/dtypes/test_inference.py:214:4-216:19[FunctionDef]`

The agreed dispatch partition of the 471 With rows is:

- 301 named boundary rows: 290 pytest plus 11 stdlib.
- 94 open artifact-provenance diagnosis rows.
- 76 actionable remainder rows.

The sealed rows directly authenticate the 290 pytest, 11 stdlib, and 95 pandas
off-population observations. The `94 artifact-provenance / 76 actionable`
division is a derived dispatch view over the sealed With coordinates, not a
third product terminal category and not a field minted by the receipt.

The receipt does not carry the per-row discriminator that separates the prior
94-row artifact-provenance diagnosis from the one remaining pandas
off-population row. `drain-list.json` therefore keeps those 95 rows together
and marks the group `not-yet-triaged`; it does not invent the missing mapping.
Likewise, generic `runtime-selected` rows remain an adjacency bucket rather
than being asserted to be one construct. No `not-yet-triaged` group is ready
for implementation dispatch until existing-door triage closes it.

## Sealed board terms

- `R_construction_panics = 477`
- `R_cm_constructed = 0`
- `R_cm_unconstructed = 8058`
- `functionsTotal = 28264`
- `functionsConstructClean = null`
- `cleanRatioRefused = true`

The clean ratio refused because eight files encountered a context-manager
resolution panic after their function roster was known. This receipt therefore
does not claim a clean-function count or ratio.

## Seal identities

- Body CID: `blake3-512:e244a8f173af043f9086a2e8f2a3dd97b2dc5a3e74c675c34ae00021335e3124aa615e57f40e9118982ea1acd1f162add1c10c94bb12dfd33686f73552b1bf85`
- Plan CID: `blake3-512:a4c4688783dd697c01d8d542e227854e5e729812b0efdff02752b348a45424c2e02882702df9449fb9f34ee5a344e2374c373977505d77e390c415e187af6e56`
- Compose CID: `blake3-512:dba05c9f65fd382ba022b23eb3446dd585a447dbb006f177dfc9969af443f7145308ad97a03e2a21dc2e58a5ae9347257b078c30cda970cb3c21f79df8bf1bf7`
- Shard `s00` CID: `blake3-512:b9457f88dd9c5b60190ae71307fc42c7eb8912a5368d869a1727d7685572288e78a2d4925c08d03b39570bf5c4de7f11ca32ca8c500fd4267d6c7ddacec5dd16`
- Runtime CID: `blake3-512:7847022ce2a79bec43b01bc0305fcbf69a921cb0526feb9704efc4c230afc864db299851f08ea07d410ce2a4b3cc472840406b6e991f41f57cd7eabfc7be18bc`
- Instrument failures: `0`

The compressed `recensus.json.gz` is the complete sealed artifact, including
the carried key manifests, per-terminal provenance and construction traces,
stage map with loaded source CIDs, edge witnesses and diffs, conservation
witness, runtime identity, partial/body CIDs, and the disjoint-union seal.

## Byte identity

The source artifact was read from battleaxe at:

`/home/tsavo/remote/sugar-bcargo-6eea67202ea9/sugar/.sugar/attested-census-1b3ac2dd9/recensus.json`

Remote and local uncompressed bytes both measured:

- Size: `156717415`
- SHA-256: `cedb430388de1bd85b8bddcdc4d547a8dfcba3954e00e8930d8419bc936274b4`

`gzip -dc recensus.json.gz | shasum -a 256` reproduces the same SHA-256.
`manifest.json` binds the banked compressed artifact and coordinate index.
