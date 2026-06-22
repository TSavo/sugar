# Rust standard-library foundation baseline

Foundation v1 advisory catalog of hidden predicates about Rust's
`std::*` builtins. Authored against `rustc 1.81.0`.

Catalog file: [`.sugar/baselines/blake3-512:a9dd90b55fbb89531d8aee8e443b805c53b910cb2dbceb1c8854ac71074fc89a485c38896838e94406f7fe5519903998d0f246b1c780127a7eaf38af7e621ce9.proof`](../../.sugar/baselines/blake3-512:a9dd90b55fbb89531d8aee8e443b805c53b910cb2dbceb1c8854ac71074fc89a485c38896838e94406f7fe5519903998d0f246b1c780127a7eaf38af7e621ce9.proof).

## Disclaimer

```
Foundation baseline catalog: advisory only.

This catalog asserts hidden predicates about the named language's
standard library. It is signed by the Sugar foundation key as a
starting point for users who want to verify proofs about code in
this language.

It is NOT authoritative.

The authoritative signer for this language's contracts is the
language steward (named below). If they sign their own catalog,
prefer it over this one. If they have not, fork this catalog and
sign your own; see docs/contributing/signing-your-own-catalog.md.
```

```
Language: rust
Steward: rust-lang team
Steward signature available: no
Authored against: rustc 1.81.0

Predicate gaps in this baseline (deferred to post-launch):
  - [G6 effect tracking]: side-effect properties (async, throws, IO) not encoded
  - [G7 aliasing]: pointer-aliasing preconditions not encoded for unsafe operations

The authoritative signer for this language can add these predicates;
the foundation baseline ships at the floor density only.
```

The exact disclaimer bytes ship in-bundle as a `kind=disclaimer`
member of the proof envelope. The envelope's `baseline.disclaimer_cid`
metadata field pins the BLAKE3-512 of those bytes; modifying any byte
of the disclaimer changes the CID and forces a re-mint + re-sign.

## Coverage

58 std::* builtins across 7 slabs, with 157 ContractDecls total
(predicate density floor: 2 per builtin; aspirational 3-4 where
structural predicates are natural in the current DSL):

| Slab | Builtins covered | Contracts |
|------|------------------|-----------|
| `std_string` | `str::len`, `str::is_empty`, `str::starts_with`, `str::ends_with`, `str::to_string`, `str::chars`, `str::bytes`, `str::trim`, `String::push_str`, `String::clear` | 27 |
| `std_vec` | `Vec::new`, `Vec::with_capacity`, `Vec::len`, `Vec::is_empty`, `Vec::push`, `Vec::pop`, `Vec::clear`, `Vec::iter`, `Vec::as_slice`, `Vec::capacity` | 28 |
| `std_option` | `Option::is_some`, `Option::is_none`, `Option::unwrap`, `Option::unwrap_or`, `Option::map`, `Option::and_then`, `Option::ok_or`, `Option::take` | 21 |
| `std_result` | `Result::is_ok`, `Result::is_err`, `Result::unwrap`, `Result::unwrap_or`, `Result::unwrap_err`, `Result::map`, `Result::map_err`, `Result::ok` | 23 |
| `std_slice` | `slice::len`, `slice::is_empty`, `slice::iter`, `slice::get`, `slice::first`, `slice::last`, `slice::contains`, `slice::to_vec` | 20 |
| `std_hashmap` | `HashMap::new`, `HashMap::len`, `HashMap::is_empty`, `HashMap::get`, `HashMap::insert`, `HashMap::contains_key`, `HashMap::iter`, `HashMap::remove` | 23 |
| `std_iter` | `Iterator::count`, `Iterator::collect`, `Iterator::fold`, `Iterator::map`, `Iterator::filter`, `Iterator::next` | 15 |

Each contract carries one of three predicate shapes:

- `<builtin>__type_signature`: the static type of the return value via
  the kit-defined `type_of` ctor.
- `<builtin>__determinism`: same input, same output (`forall x. f(x) =
  f(x)`). Vacuously true under Z3 equality, but explicit so
  non-determinism becomes a documented exception.
- `<builtin>__<structural>`: at least one further predicate per builtin
  where structurally natural, length floor, idempotence, post-state
  shape, function congruence with another builtin (`is_empty` agrees
  with `len_eq_zero`), tag-preservation (`Option::map` preserves the
  Some/None tag), etc.

## How this catalog was minted

The mint orchestrator lives at
`implementations/rust/sugar-baseline-rust-std/`. It:

1. Walks the seven slab files (one per std module group), authoring
   ContractDecls via the kit DSL (`forall` / `eq` / `gte` / `ctor` /
   `num` / `str_const` / `must` / `contract`).
2. Mints each ContractDecl as a signed v1.2 layered memento under the
   foundation v0 ed25519 seed.
3. Wraps the disclaimer text as a `kind=disclaimer` member memento so
   the disclaimer ships in-band.
4. Bundles into a `.proof` envelope with advisory metadata per the
   rubric §3 (`signer_role`, `baseline.{version, language,
   language_version, kit_version, disclaimer_cid}`).

To re-mint locally:

```sh
cargo run -p sugar-baseline-rust-std --bin mint-rust-std-baseline -- /tmp/stage
cp /tmp/stage/blake3-512_*.proof .sugar/baselines/
```

Byte-determinism is asserted: the orchestrator mints into two separate
temp dirs and fails if the resulting CIDs differ.

## DSL constraints honored

The pilot uses ONLY the cross-kit byte-equivalent DSL surface locked
for v1.0.0:

- `forall(sort, |v| body)`
- `eq(a, b)`
- `gte(a, b)`
- `ctor(name, args)`: kit-defined operations
- `num(n)` / `str_const(s)`
- `must(name, formula)` / `contract(name, args)`

DSL predicates G1-G4 (`lt`, `lte`, `between`, `member_of`, `or`, `not`)
are tracked in [`dsl-extension-survey.md`](../contributing/dsl-extension-survey.md)
for the post-launch DSL extension PR; using them here would diverge
from sibling kits' surfaces during the parallel #258-#268 mint push.
G5-G10 are research-grade and explicitly deferred (see this file's
disclaimer addendum for the per-language gap notes).

## Change log

### v1: initial publication (2026-05-03)

- 58 builtins covered across 7 slabs (string/vec/option/result/slice/hashmap/iter).
- 157 ContractDecls; predicate density floor (>= 2 per builtin) met
  for every builtin.
- Disclaimer text matches the rubric §4 base verbatim; per-language
  addendum names the rust-lang team as the steward and explicitly notes
  G6 (effect tracking) and G7 (aliasing) as deferred predicate gaps.
- Catalog CID: `blake3-512:a9dd90b55fbb89531d8aee8e443b805c53b910cb2dbceb1c8854ac71074fc89a485c38896838e94406f7fe5519903998d0f246b1c780127a7eaf38af7e621ce9`
- contractSetCid: `blake3-512:76c278afe2f60f5b58ebaf53df1078143204cddbbf47d23119fb9778e17b6488004b3f8d8ca471720c1774483ea0fc7cb6dba0a097c638cc7e8231edb566d5e4`
- disclaimer_cid: `blake3-512:dae426aaf69da3fb28d1b45bc61dd700e3b3e1f0637814d24ec9071071d2fe9f32befb5b4211cd4ae8d6596e67e7a12eecff849ffdbf8a832b376fc7db19bca1`
- Signed at: `2026-05-03T18:00:00Z` (foundation v0 ed25519).

## See also

- [`docs/contributing/baseline-catalog-rubric.md`](../contributing/baseline-catalog-rubric.md) (#254)
- [`docs/contributing/signing-your-own-catalog.md`](../contributing/signing-your-own-catalog.md) (#255)
- [`docs/contributing/dsl-extension-survey.md`](../contributing/dsl-extension-survey.md) (#256)
- Issue #257 (this pilot)
- [`docs/baselines/README.md`](README.md)
