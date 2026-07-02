# Proof Envelope and Memento Pool Interface

**Status:** grounded design draft against `sugar-proof-envelope` and `sugar-verifier/src/types.rs`.  
**Date:** 2026-07-02

## 1. Purpose

The proof envelope interface is the trust root for verification. The verifier does not verify arbitrary JSON trees; it loads content-addressed proof members into a typed pool and builds indexes over typed member views.

Current verifier `types.rs` states the design directly: shape compatibility is normalized at the proof-envelope boundary, and the pool stores typed member views rather than raw member envelope JSON trees.

## 2. Proof envelope construction

`ProofEnvelopeInput` and `build_proof_envelope` live in `sugar-proof-envelope/src/proof.rs`.

The build function signs and names a `.proof` bundle from typed inputs. Report witness minting uses it like this:

```rust
let proof = build_proof_envelope(&ProofEnvelopeInput { ... });
let proof_file = out_dir.join(proof_filename(&proof.cid));
```

The resulting filename CID is a trust root: consumers should verify file content against the name before accepting members.

## 3. Graph and member types

Current proof-envelope typed storage includes:

- `MemberKind` in `typed_member.rs`, with contract, bridge, implication, witness, source, plan, and other memento families.
- `StoredMember` and `AnchoredMember` in `proof_graph.rs`.
- `ProofGraph` in `proof_graph.rs`, used by `report_witness.rs` to push witness mementos and by CLI dump/emit tests to inspect members.

Verifier-facing re-exports appear in `sugar-verifier/src/types.rs`:

```rust
pub use sugar_proof_envelope::{
    AnchoredMember, AtomCid, ContractBodyCid, MemberKind, MementoCid, StoredMember,
};
```

## 4. MementoPool type

```rust
pub struct MementoPool {
    pub mementos: BTreeMap<MementoCid, StoredMember>,
    pub atoms: BTreeMap<AtomCid, Vec<u8>>,
    pub body: BTreeMap<ContractBodyCid, Vec<u8>>,
    pub formula_to_memento: BTreeMap<String, MementoCid>,
    pub bridges_by_symbol: BTreeMap<String, MementoCid>,
    pub bridges_by_callsite: BTreeMap<(MementoCid, String, usize, String), MementoCid>,
    pub panic_effect_site_annotations: BTreeMap<(MementoCid, String, usize, String), EffectSiteAnnotation>,
    pub bridge_self_bundle_by_symbol: BTreeMap<String, MementoCid>,
    pub bundle_members: BTreeMap<MementoCid, BTreeSet<MementoCid>>,
    pub load_errors: Vec<LoadError>,
    pub cid_to_name: BTreeMap<MementoCid, String>,
    pub name_to_cid: BTreeMap<String, MementoCid>,
    pub name_to_body_cid: BTreeMap<String, ContractBodyCid>,
    /* opacity and shape indexes */
}
```

The pool is not a cache convenience. It is the verifier's typed view of the proof graph.

## 5. Core pool operations

```rust
pub fn verify_by_hash(&self, formula_cid: &str) -> Option<&StoredMember>
pub fn verify(&self, formula: &Json) -> Option<&StoredMember>
pub fn stored_member(&self, cid: &MementoCid) -> Option<&StoredMember>
pub fn members_by_kind(&self, kind: MemberKind) -> impl Iterator<Item = (&MementoCid, &StoredMember)>
pub fn contract_members(&self) -> impl Iterator<Item = (&MementoCid, &StoredMember)>
pub fn bridge_members(&self) -> impl Iterator<Item = (&MementoCid, &StoredMember)>
pub fn implication_members(&self) -> impl Iterator<Item = (&MementoCid, &StoredMember)>
pub fn witness_memento_members(&self) -> impl Iterator<Item = (&MementoCid, &StoredMember)>
pub fn plan_memento_members(&self) -> impl Iterator<Item = (&MementoCid, &StoredMember)>
```

Design rule: verifier stages should use these typed accessors and indexes. Raw JSON field reads should be isolated to decoder and typed view construction code.

## 6. Addressing semantics

The pool's indexes make several soundness rules explicit:

| Index | Soundness role |
|---|---|
| `formula_to_memento` | Hash is the formula boundary; verify by hash without solver. |
| `bridges_by_callsite` | Prevents same-symbol collisions by scoping bridges to `(bundle, file, line, symbol)`. |
| `bundle_members` | Enforces bundle pinning for bridge targets and avoids last-writer-wins poisoning. |
| `bridge_self_bundle_by_symbol` | Enforces self-pinned target membership when `targetProofCid` is absent. |
| `name_to_body_cid` | Keeps semantic body pointers distinct from contract member identity. |
| opacity indexes | Record loop/try/closure/aliasing/pin invariants by their typed memento keys. |

## 7. Interface obligations for loaders

A proof loader must:

1. decode bundle bytes,
2. verify the bundle/file CID relationship,
3. normalize each member into `StoredMember`,
4. insert each `AnchoredMember` through the pool's typed insertion path,
5. populate every relevant index exactly once,
6. record load failures as `LoadError` rather than panicking or silently dropping.

## 8. Interface obligations for verifier stages

A verifier stage must:

1. use `MementoCid` / `AtomCid` / `ContractBodyCid` newtypes at the API boundary,
2. preserve bundle scope when resolving callsite-specific facts,
3. never treat a human name as proof identity,
4. produce stage receipts or report rows that cite CIDs, not raw object identity,
5. keep raw source/body bytes behind content-addressed pointers.

## 9. Migration target

The target is a verifier where stage code cannot construct illegal proof lookups. That means:

```rust
struct BundleScopedCallsiteKey {
    bundle: MementoCid,
    file: SourcePath,
    line: SourceLine,
    symbol: SourceSymbol,
}

struct VerifiedContract<'pool> {
    cid: MementoCid,
    member: &'pool StoredMember,
    body: Option<ResolvedContractBody<'pool>>,
}
```

Such types would retire auditors that currently look for accidental unscoped lookups or raw JSON member traversal.
