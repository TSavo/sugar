# Contract Merge Semantics

**Status:** v1.1.0 protocol addendum
**Declared at:** 2026-04-30
**CID:** RECOMPUTE
**Catalog property key:** `contract-merge-semantics`

## Why this exists

Sugar's Rust kit ships two authoring surfaces for contracts:

1. **`.invariant.rs` files** sitting next to each public source file.
   The `sugar-self-contracts` orchestrator pulls them in via
   `#[path]` and drains the kit's process-local `CONTRACT_COLLECTOR`
   after running each `invariants()`.

2. **Native contract annotations such as `#[requires]` and
   `#[ensures]`** placed directly above the function being constrained.
   The annotation surface emits a hidden static `ContractRegistration`
   collected by the `inventory` crate's distributed slice.

Both surfaces produce the same value: a
`sugar_ir_symbolic::ContractDecl` with optional `pre` / `post` /
`inv` formulas, a `name`, and an `out_binding`. Both are intended to
be valid concurrently. Different authors will reach for the surface
that fits the source file at hand. We need a deterministic, fail-loud
discipline for what happens when both surfaces speak about the same
contract `name`.

This spec defines that discipline.

## The four cases

A "contract" is identified by the `name` field on `ContractDecl`. Two
authored ContractDecls share the same `name` iff their `name` strings
are byte-equal after normalization (NFC, no whitespace stripping).
The orchestrator's merge function `merge(decl_a, decl_b)` is defined
piecewise across four mutually exclusive cases.

### Case 1: Identity match (silent dedupe)

If `canonical_bytes(decl_a) == canonical_bytes(decl_b)`, the two
authoring sites have produced byte-identical contracts. The
orchestrator emits a single ContractDecl in the resulting slab and
records both source locations in the merge ledger. No error, no
warning.

`canonical_bytes` is the JCS-encoded IR-JSON of the ContractDecl as
defined in `2026-04-30-canonicalization-grammar.md`. Two identity
matches are signed once, not twice; downstream proof envelopes
contain a single contract memento for both.

### Case 2: Orthogonal slots (merge)

If `decl_a` and `decl_b` populate disjoint slot sets (for example,
`decl_a` provides only `pre` and `decl_b` provides only `post`, with
the `inv` slots both `None`), the orchestrator concatenates them slot
by slot. The merged ContractDecl carries:

- `name = decl_a.name` (equal to `decl_b.name` by identity)
- `pre = decl_a.pre.or(decl_b.pre)`
- `post = decl_a.post.or(decl_b.post)`
- `inv = decl_a.inv.or(decl_b.inv)`
- `out_binding`: the non-default value if exactly one is non-default;
  if both are default ("out") or both are equal, the shared value;
  otherwise see Case 3.

Both source locations are recorded in the merge ledger. The merged
ContractDecl is signed once.

### Case 3: Same slot, different formulas (fail-loud)

If `decl_a` and `decl_b` both populate the same slot (e.g. both have
`pre = Some(...)`), and the canonical bytes of those slot values
differ, this is a build-time error. The orchestrator emits:

```
sugar-self-contracts: contract `<name>` has conflicting <slot>
  authored at <decl_a.source_path>:<decl_a.source_line>
  authored at <decl_b.source_path>:<decl_b.source_line>
hash(decl_a.<slot>) = blake3-512:<...>
hash(decl_b.<slot>) = blake3-512:<...>

Resolve by either:
  (a) deleting one of the authoring sites, or
  (b) using `name = "..."` on one decorator to fork into a new contract.
```

Building does not produce a `.proof` envelope until the conflict is
resolved. There is no "last writer wins" or "decorator beats file" or
similar precedence rule. Both surfaces are equal authors and the
orchestrator refuses to silently drop signal.

The same rule applies to `out_binding` if both sides specify a
non-default value and the two values are unequal.

### Case 4: Cross-language (no merge; bridges only)

A ContractDecl authored in the Rust kit and a ContractDecl authored
in (e.g.) the TypeScript kit are *never* merged, even if they share a
`name`. Each is minted as its own contract memento under its own CID.
Cross-language identification happens through a `BridgeDecl` that
explicitly links a source contract CID (carried by the implementation)
to a target contract CID (the abstract reference spec).

The bridge says: "contract `bafy...js-parseInt-v24` satisfies contract
`bafy...ref-parseInt-v1`." This is a **verifiable claim** — not a symbol
lookup. The framework checks whether the source contract's postcondition
implies the target's. If the implication holds, any proof about the source
transfers to the target, and from there to any other source that also
bridges to the same target.

This gives us **hash-bounded cross-domain verification**:

```
JS parseInt claim ──→ js-parseInt-v24 (CID A)
                          │
                          ▼ via bridge
                   ref-parseInt-v1 (CID C)
                          ▲
                          │ via bridge
Rust parse claim ───→ rust-parse-v1 (CID B)
```

A proof at CID A transfers to CID C, and from CID C to CID B. Each hop
is a separate, content-addressed, verifiable memento. The bridge is not
trusted; it is proven.

The orchestrator's merge is scoped to a single `(language,
implementation)` pair. The Rust `sugar-self-contracts` crate
merges only Rust-authored contracts; cross-language reconciliation
happens at the verifier when bridge mementos discharge.

## Operational consequence

The `sugar-self-contracts` orchestrator's pipeline becomes:

```
1. Walk all `.invariant.rs` files; collect ContractDecls per slab.
2. Walk `inventory::iter::<ContractRegistration>()`; collect
   ContractDecls per macro registration.
3. Group all decls by `name` across both surfaces.
4. For each name's group:
   a. If size == 1, pass through.
   b. If size > 1, run merge(decl_i, decl_j) pairwise:
      - Identity match (Case 1) => dedupe.
      - Orthogonal slots (Case 2) => merge.
      - Same slot, different formulas (Case 3) => abort with the
        diagnostic shown above.
5. Mint each merged ContractDecl as one signed contract memento.
6. Bundle into a single `.proof` envelope.
```

Determinism: the merge result depends only on the byte content of
the inputs, not on iteration order. `inventory`'s iteration order is
implementation-defined across translation units, so step 3's
grouping uses the `name` as the sole key and merge in step 4 is
commutative within Case 1 and Case 2 (Case 3 short-circuits).

## Catalog entry

This spec lives in the catalog as:

```
"contract-merge-semantics": "blake3-512:RECOMPUTE"
```

The CID resolves once the canonical bytes of this document are
finalized; another agent's catalog-CID-recompute pass will fill it
in. Nothing here depends on the CID being final.

## Out of scope

- The build-script wiring that runs the merge and aborts on Case 3.
  The orchestrator currently runs only on the `.invariant.rs` walk;
  extending it to consume `inventory::iter::<ContractRegistration>()`
  is a follow-up task referenced by both the macro crate and this
  spec.
- Bridge verification mechanics. Bridges carry explicit source and target
  contract CIDs; their verification (proving source implies target) is a
  separate producer concern documented in the protocol grammar spec.
- A "soft warning" mode for Case 3. Fail-loud is the only mode.
