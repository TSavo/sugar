# Native Bridge Producer Contract

**Status:** DESIGN SPIKE (sugar#3700) — spec only, no implementation
**Date:** 2026-07-09
**Layer:** kit-membrane wire protocol (extends `sugar.enumerate`) + linker join discipline
**Sequencing:** #3700 is a parallel design track, NOT on the Python critical path
(#3686). Python closes with bridge-target-missing as an honest named red per
criterion 11; this spec exists so the rust/java/C lanes have an instantiable
contract the moment #3686 unblocks fleet work on them.
**Related:**
- `~/.claude/plans/sugar-compiler-liftshift.md` Part 6 (`Kit → SourceFile →
  Function → CallSite → {universe, assertions → facts, contract,
  implication}`; the SourceOracle mint/lookup pair; the fluent scan/seek
  grammar; the two conformance laws)
- `protocol/specs/2026-07-08-enumeration-protocol.md` (the ONE wire verb this
  spec adds a level to — a new capability is a new address-space level, never
  a new method)
- `implementations/rust/sugar-compiler/src/kit.rs` (rendezvous, the
  unforgeable handle; `testimony`/`source` verbs)
- `implementations/rust/sugar-compiler/src/linker_inputs.rs` (`derive_linker_inputs`
  — absence→`UnresolvedSymbol`, the mechanism this spec's cross-kit join reuses)
- `implementations/rust/sugar-linker/src/lib.rs` (`Symbol`, `EdgeTarget`,
  `bind`, `LinkerErrorKind`)
- `examples/java-panama-bridge/` (Panama teaches the bridge SHAPE — a
  consumer downcalling a native symbol — not producer semantics; the
  producer side there is a hand-written Rust re-implementation, not a
  spec'd contract kit)
- `examples/polars-showcase/` (the worked example: `call:scalar_sum`'s
  missing `_plr` C-extension producer, #3654)
- sugar#3445 (ADT tester atoms, Parts 1/2, precede this per T's sequencing),
  sugar#3865/#3668 (AliasFloor receiver identity — the `call:`/`method:`
  vocabulary lesson this spec's symbol format must not repeat)

## Table of contents

0. Purpose and non-goals
1. The shape: how a producer kit is constructed and driven
2. The handshake across kits: driver-mediated bridge resolution
3. The join: symbol format, key discipline, EUF coordinate
4. The honest absences: partial producer coverage stays loud
5. Instantiability: the producer-conformance checklist
6. The polars row, end to end
7. Open questions carried forward (not blocking, named)

---

## Section 0. Purpose and non-goals

A **producer kit** is a kit whose job is not to lift a consumer's own
assertions but to answer, for a set of exported native symbols, "what does
calling this symbol mean" — an operator-level, ∀-shaped domain claim a
consumer's callsite can bind to. Today exactly one producer exists in the
tree, and it is not a kit: `examples/java-panama-bridge/native-contract/`
is a hand-written Rust crate whose ONE job is to carry a single
`#[test] assert_eq!(3, decoded_len_estimate(4))` so the existing Rust lift
kit mints ONE contract row matching the Panama bridge's `targetSymbol`
(`examples/java-panama-bridge/run.sh:1-30`; the contract crate's own doc
comment: "exists ONLY to mint the single contract row that the Java Panama
bridge binds to"). That is Panama teaching the bridge SHAPE (a consumer
callEdge with a `bridgeSourceSymbol`, resolved against a same-language
Rust contract) — it is not a producer that answers arbitrary exported
symbols for an arbitrary consumer. This spec is: what would it take for
`native-contract/` to be replaced by a real producer kit that any
consumer's `bridgeSourceSymbol` could ask, and any language lane
(Rust/C/Java-via-Panama) could implement to that same contract.

**Non-goals:** no code changes this pass. No new wire method — the
handshake in Section 2 is a level added to `sugar.enumerate`
(`protocol/specs/2026-07-08-enumeration-protocol.md:19`), not a second
verb. No decision on which language lane ships first (T's sequencing:
Rust producer is the first vertical once #3686 unblocks, per the issue's
ruling).

---

## Section 1. THE SHAPE

### 1.1 Construction: a producer kit IS a Kit

A producer is not a new noun. It rendezvous exactly like any lift kit
today: `Kit::rendezvous(manifest) -> Kit` performs the live handshake —
spawn, `initialize`, `sugar.plugin.kit_declaration`, `shutdown`
(`sugar-compiler/src/kit.rs:154-196`) — and the returned handle is
unforgeable by the same law (no `Kit::new`, no `From<Value>`; see
`kit.rs`'s `rendezvous_tests`). What is [NEW] is what its
`KitDeclaration` declares, not a new minting path.

`KitDeclaration` (`sugar-claim-envelope/src/lib.rs:82-95`) already has the
exact three fields a producer capability needs, unchanged:

```rust
pub struct KitDeclaration {
    pub kit: KitIdentity,                       // id, language, version — EXISTS
    pub rpc: KitDeclarationRpc,                  // methods: Vec<{name, required}> — EXISTS
    pub proof_resolution: KitProofResolution,    // strategy + rpcMethod — EXISTS
    pub oracle_host: Option<KitOracleHost>,      // EXISTS, unused by this spec
    pub residue_categories: Vec<KitResidueCategory>,  // EXISTS
}
```

**[NEW]** A producer kit's declaration states its capability by
listing an `enumerate` method with a producer-only `level` in its
`rpc.methods` (Section 1.2), and declares its `proof_resolution.strategy`
as `"exported-symbol-contracts"` (a new strategy string alongside the
existing `"rpc-proof-bytes"` example at `lib.rs:211`) — the strategy
field is already a free string, not a closed enum, so this is a value
addition, not a schema change. No new top-level field on
`KitDeclaration` is needed: **the producer capability is declared through
the SAME two fields (`rpc.methods`, `proof_resolution.strategy`) every
kit already uses to declare what it answers.** This directly answers the
brief's design question 1 in favor of "no new struct field" — a producer
is a kit that declares a different `level` value and a different
resolution strategy, not a kit with an extra capability flag. Whether it
IS a producer is discoverable the same way any RPC capability is
discoverable today: read the declaration, check what it claims to serve.

### 1.2 Driving a producer: `exports` is a new `sugar.enumerate` level, not a new method

The brief's design question forces a choice: is a producer's exported-symbol
surface reachable as `SourceFiles`/`Functions` (reusing the existing
levels), or does it need a dedicated level? **Decision: a dedicated level,
named `exports`, added to the existing `level` enum
(`source_files | functions | call_sites | assertions | facts | universe |
exports [NEW]`)** in `protocol/specs/2026-07-08-enumeration-protocol.md`
Section 1. Justification against the one-verb law
(`enumeration-protocol.md:19-20`: "adding a level to the tree means adding
a `level` value here, not a new RPC method"):

- Reusing `source_files`/`functions` would force every producer (a `.so`
  header, a C source tree, a JVM class with `native` methods) to fake a
  source-file/function shape it may not have (a prebuilt shared object with
  no accompanying source has no "file" the existing levels' kit-side
  backing (`_iter_python_files`, `lift_source`) knows how to walk).
- The exported surface is a DIFFERENT kind of enumeration answer than
  `SourceFile`/`Function`: its nodes are `ExportedSymbol` records (Section
  1.3), not AST-shaped claim nodes, and they have no `assertions`/`facts`
  children the way a `CallSite` does — the producer tree is a strict two
  level: `exports (scan/seek by mangled or plain symbol) → contract (seek
  only, one per export)`.
- A new level is exactly the extension mechanism the enumeration protocol
  already names for growth (`enumerate_conformance.rs`'s two conformance
  laws generalize unchanged to a new level — see Section 5).

```json
{
  "method": "sugar.enumerate",
  "params": {
    "level": "exports",
    "at": <ExportLocator-as-JSON> | null,
    "seek": <boolean>,
    "workspace_root": "<producer artifact root>"
  }
}
```

- Scan (`at: null, seek: false`): "give me every exported symbol this
  producer answers for." Response `nodes` are `ExportedSymbol` records
  (memento + audit + payload, same envelope shape as every other level,
  `enumeration-protocol.md:59-68`).
- Seek (`at: <ExportLocator>, seek: true`): "give me the contract for
  exactly this export" — this is how a driver resolves ONE
  `bridgeSourceSymbol` without walking the whole producer surface (Section
  2.3). `plural()[i] ≡ singular(plural()[i].memento)` (the existing
  coherence law, `enumeration-protocol.md:149-153`) must hold for
  `exports` exactly as for every other level — this is what makes a
  targeted seek trustworthy without a full scan first.
- **`payload`** at the `exports` level, unlike every existing level's
  `payload` (only populated at `facts`, `enumeration-protocol.md:73`), is
  populated here too: it carries the `FunctionContract` (Section 1.3) — an
  ∀-shaped, operator-level domain claim, not a ground fact. This is a
  deliberate, named departure from the current single-payload-level rule,
  because a producer's answer to a symbol IS a contract, not a claim about
  one call site; Section 1.3 states why this is sound and not a second
  payload shape hiding as one field.

### 1.3 `ExportedSymbol` and `FunctionContract`

```rust
// [NEW] sugar-compiler/src/producer.rs (proposed home; sits beside
// tree.rs's existing node types, same crate)
pub struct ExportedSymbol {
    pub memento: SourceMemento,        // EXISTS type (sugar-walk/source_oracle.rs:18)
                                        // — the export's own durable locator
    pub symbol: String,                // wire-format identity, Section 3.1
    pub abi_signature: AbiSignature,   // [NEW]
    pub artifact: ArtifactProvenance,  // [NEW]
    pub calling_convention: String,    // [NEW] e.g. "C", "system", "rust-extern-c"
    pub warrant: WarrantKind,          // [NEW] Source | Stub | GeneratedContract
}

pub struct AbiSignature {              // [NEW]
    pub formals: Vec<Sort>,            // EXISTS type (sugar-ir-types::Sort)
    pub returns: Sort,
    pub platform_abi_tag: String,      // e.g. "x86_64-unknown-linux-gnu", "aarch64-apple-darwin"
}

pub struct ArtifactProvenance {        // [NEW]
    pub header_or_source_cid: Option<String>,  // CID of the .h/.rs/.java source, if any
    pub object_cid: String,                    // CID of the .so/.dylib/.o/.class the symbol resolves in
}

pub enum WarrantKind {                 // [NEW] — the honesty tier, analogous to
    Source,             // producer read the actual source (like native-contract/'s test)
    Stub,               // producer declares the ABI but has no body-level claim (link-legal, weaker)
    GeneratedContract,  // producer synthesized a contract from a spec (e.g. a header-only decl)
}

pub struct FunctionContract {          // the `exports` seek payload
    pub contract: sugar_linker::LinkerContract,  // EXISTS type — reuse, not reinvent
    pub euf_coordinate: Option<EufCoordinate>,   // EXISTS field on LinkerContract (currently None everywhere)
}
```

`FunctionContract` deliberately reuses `LinkerContract`
(`sugar-linker/src/lib.rs`, already carrying `name`, `kit`, `contract_cid`,
`pre_json`/`post_json`, `formals`/`formal_sorts`, `euf_coordinate`) rather
than inventing a parallel contract type — the brief's own wording
("receive the target `FunctionContract` + ProofIR universe") names a new
noun, but the fields it needs are the exact fields `LinkerContract`
already carries into `bind` (`sugar-compiler/src/linker_inputs.rs:106-125`
constructs one from a pool row today). The only field that changes
meaning is `kit`: today `derive_linker_inputs` leaves it empty because "no
real kit string here would change anything observable"
(`linker_inputs.rs:66-71`) — for a cross-kit producer join it MUST be
populated, because `Symbol::qualified(kit, name)` is exactly the join key
(Section 3).

T's ruling grounds the `universe` field directly: "a producer's universe
is the operator's domain claim" — this is `FunctionContract.contract.pre_json`
/`post_json` (already `IrFormula`, already ∀-shaped when the producer
states a domain-wide claim rather than one instantiated call). No new
universe type is needed; `Universe` in the Part 6 tree (currently
`NotModeled`, `enumeration-protocol.md:98,121-124`) and a producer's
`FunctionContract.contract` are the SAME shape — a producer answering
`exports.seek` is exactly the missing kit-side handler that would let
`CallSite::universe()` stop returning `NotModeled` for a bridged callee.

---

## Section 2. THE HANDSHAKE ACROSS KITS

**Kits never compose.** The DRIVER (the process holding both `Kit`
handles — today, `sugar-cli`'s orchestration, migrating to
`sugar-compiler` per the liftshift plan) is the only party that talks to
more than one kit. Neither kit's RPC surface ever names the other.

### 2.1 What exists today, unchanged

A consumer kit already emits a `callEdge` (Panama's `callEdgeJson`,
`JavaPanamaFfmRpc.java:545`) carrying a `bridgeSourceSymbol` — the bare
native symbol name the Panama downcall targets
(`Linker.downcallHandle(..., lookup.find("sym").orElseThrow(), ...)`,
`JavaPanamaFfmRpc.java:15-18`). Today's resolution is NOT cross-kit at
all: the driver feeds the Rust producer's `.proof` (from `native-contract/`)
into the SAME pool the Java-derived callEdge is checked against, and
`derive_linker_inputs`'s pool-membership check
(`linker_inputs.rs:129-137,153-157`) does the join by bare contract CID —
because both sides happen to live in one pool with one contract named by
one bare symbol, same-kit-shaped even though the languages differ.

### 2.2 What is [NEW]: driver discovers a producer is needed

1. **Discovery.** The driver folds a consumer kit's lift result into a
   `ProofGraph` (per the liftshift plan's `feed`) and finds a `CallEdge`
   with `target_contract_cid: None` and a non-empty
   `bridgeSourceSymbol`/`target_symbol` naming a FOREIGN calling
   convention (i.e. the symbol's declared ABI does not match the consumer
   kit's own language — the Panama case: a Java callEdge naming a C ABI
   symbol). This is exactly today's `LinkerCallEdge` with
   `target_contract_cid: None` (`linker_inputs.rs:153-157`'s `filter`
   arm) — no new detection mechanism, the SAME absence-is-the-signal
   pattern `derive_linker_inputs`'s module doc already documents
   (`linker_inputs.rs:13-55`, "unresolved in production is not a marked
   state anywhere in the pool; it is the shape you get for free").
2. **Ask.** The driver holds (or rendezvous-mints, per its own producer
   registry — Section 5's conformance checklist is how a driver knows
   which kits to ask) a producer `Kit` for the target language/ABI. It
   issues `sugar.enumerate {level: "exports", at: <symbol-derived-locator>,
   seek: true}` against that kit. **[NEW]:** the locator for a seek-by-symbol
   request is not itself a memento the driver already holds (unlike every
   other seek in the enumeration protocol, whose `at` is always a
   previously-returned `memento` — `enumeration-protocol.md:43-46`). This
   is the one deliberate exception: the driver DOES fabricate this one key,
   because the `bridgeSourceSymbol` string IS the durable, wire-stable
   identity a consumer already emitted — Section 3.1 states its exact
   format so this fabrication is well-defined and total, not ad hoc.
3. **Receive.** The producer answers with an `ExportedSymbol` node whose
   `payload` is the `FunctionContract` (Section 1.3), or a `gaps` entry
   (Section 4) if the symbol is not one it exports.
4. **Mint.** The driver turns the resolved `callEdge` into bridge IR by
   generalizing the #3671 same-bundle CID-rewrite pattern: identity comes
   FROM THE POOL (the producer's own `contract_cid`, already content-addressed
   at the producer's mint time), never re-derived by the driver. Concretely,
   this is `derive_linker_inputs`'s existing `target_contract_cid` slot
   (`linker_inputs.rs:153-157`) populated with the producer's answered CID
   instead of staying `None` — `bind` (`sugar-linker/src/lib.rs:776+`)
   then resolves it through the SAME `SymbolTable::resolve` path
   (`lib.rs:1038`) every same-language edge already uses. **No new linker
   mechanism** — the cross-kit case is the SAME bind, fed a
   `LinkerContract` whose `kit` field is now non-empty (Section 3).

### 2.3 Why seek-not-scan is the default path

A driver resolving ONE consumer callEdge should not need to enumerate a
producer's entire exported surface (which, for a system library or a
large native extension, could be thousands of symbols). Seek-by-symbol
(2.2 step 2) is the hot path; a full `exports` scan exists for the
conformance/coverage question (Section 4's "is this symbol covered at
all" audit) and for tooling that wants to list what a producer claims,
not for the per-callEdge resolution loop.

---

## Section 3. THE JOIN

### 3.1 Symbol format at the language wall

**Decision: `<kit>:<bare-symbol>`, matching `sugar-linker`'s existing
`Symbol::qualified` format exactly** (`sugar-linker/src/lib.rs:143-145`),
extended with the `call:`/`method:` prefix discipline already load-bearing
inside `bare-symbol` for same-language EUF identity
(`sugar-verifier/src/consistency.rs:2287-2288`, `sugar-lift-rust-tests/src/lib.rs`'s
`AliasFloor` receiver-identity fix, #3865/#3668).

- `kit` is the producer's OWN `KitIdentity.id` from its `KitDeclaration`
  (`sugar-claim-envelope/src/lib.rs:99`) — e.g. `"rust-native-producer"`,
  not a source-language label like `"rust"` or `"c"`. This matches
  `Symbol::qualified(kit, name)`'s existing contract, where `kit` already
  means "which kit answers this name," never "which language."
- `bare-symbol` is the MANGLED-OR-PLAIN export name exactly as the
  producer's ABI resolves it (a `dlsym`/`LOOKUP.find` lookup string for a
  C ABI symbol; a JVM-mangled name for a `native` method; a Rust
  `#[no_mangle] extern "C"` symbol's link name) — **not** re-derived by
  the consumer or the driver. This is the concrete answer to "mangled C
  exports or qualified `kit:symbol`": it is BOTH, composed — `kit:` is
  the cross-kit qualifier the linker join needs (Section 3.2), and
  whatever comes after `:` is the producer's native ABI name, untouched.
- **The `call:`/`method:` lesson, applied:** #3865/#3668's AliasFloor fix
  established that a bare `method:foo` name erases receiver identity —
  two distinct receiver types calling a same-named method collide unless
  the identity carries the receiver type, not just the method name
  (`consistency.rs:2287-2288`'s `starts_with("call:")`/`"method:"` split
  exists precisely to keep a stdlib-boundary call distinguishable from a
  user method of the same bare name). A native export has no receiver in
  this sense (C ABI symbols are global, not method-dispatched) — but the
  SAME drift is possible if two producers export the same bare symbol
  name (e.g. two different `.so`s both export `decode`). **The
  `kit:`-qualifier is exactly the AliasFloor fix generalized to producers:
  the kit qualifier IS the receiver-equivalent identity**, so
  `rust-native-producer:decoded_len_estimate` and
  `other-native-producer:decode` never collide even if their bare names
  did. A producer join that used bare symbol names ALONE (no kit
  qualifier) would repeat exactly the #3865 drift at the cross-kit layer;
  this spec forbids that by construction (`Symbol::qualified` is already
  the ONLY constructor the linker's `name_kit_index` accepts,
  `lib.rs:734-736`).

### 3.2 The join key, precisely

`bind`'s existing `SymbolTable::resolve` (`sugar-linker/src/lib.rs:1038-1066`)
is the join, unchanged:

```
EdgeTarget::Unbound(sig) => name_kit_index
    .get(&Symbol::qualified(sig.kit, sig.symbol))
    .ok_or(UnresolvedSymbol)?
```

For a producer-resolved edge, the driver populates
`ImportSignature{kit, symbol}` (`sugar-linker/src/lib.rs:435-449`) with the
producer's `KitIdentity.id` and the `ExportedSymbol.symbol` returned in
Section 2.2 step 3, and the pool's `name_kit_index` gains an entry for
every producer contract fed in (via `LinkerContract{kit: <producer id>,
name: <symbol>, contract_cid, ...}` — Section 1.3's reuse). The join is
therefore, precisely: **`bridgeSourceSymbol` (consumer's declared target)
== `<producer kit id>:<producer's own exported symbol>` (producer's
declared identity), formals/actuals checked by `ImportSignature::check`
against the producer's `AbiSignature` (Section 1.3) exactly as
`SignatureMismatch` is checked today** (`lib.rs:1058-1064`), **and the EUF
coordinate, when present, threading through unchanged** on
`LinkerContract.euf_coordinate` — a field that already exists and is
already always `None` in every current call site
(`linker_inputs.rs:124`); this spec is what would first populate it for a
real cross-language edge.

---

## Section 4. THE HONEST ABSENCES

A consumer callEdge whose producer coverage doesn't exist yet has THREE
distinct honest terminals, mirroring the existing link-vs-UNSAT law
(`sugar-compiler/src/orchestrate.rs`, `Outcome::LinkError` vs
`Outcome::Verdicts`) and criterion 11's own vocabulary:

1. **No producer kit rendezvous'd for the target ABI at all.** The
   driver never issues an `exports` request. This is today's polars
   shape exactly — `Outcome::LinkError(UnresolvedSymbol)`, the SAME typed
   red `derive_linker_inputs` already emits for any unbound edge
   (`linker_inputs.rs:44-56`). No protocol change needed; this spec adds
   NOTHING to this case except naming which producer registry entry is
   missing (an operational/tooling detail, not a wire concern).
2. **A producer kit exists and answered, but the specific symbol is a
   gap.** The producer's `exports.seek` response returns a `gaps` entry
   (`enumeration-protocol.md:63-68`'s existing `{memento, reason}` shape,
   reused unchanged — GAPS ARE NODES, same address space, Section 1.2's
   new level inherits this for free). `reason` names why: "symbol not
   exported by this artifact," "ABI signature undecidable from header
   alone," etc. This is still `UnresolvedSymbol` at bind time (the
   producer answered but had nothing bound), distinct from case 1 by
   audit trail only — the driver KNOWS it asked and got a named gap,
   versus never having asked.
3. **Partial producer surface — some exports covered, most not.**
   Mirrors criterion 14's total-line-accounting law applied to a
   producer: a scan of `exports` (Section 1.2) enumerating N symbols with
   M covered (Source/Stub/GeneratedContract warrant) and N-M gapped is
   the producer's OWN conservation ratchet —
   `covered + gapped == total_exported_surface`, computable the same way
   `sugar lift --report --visual`'s line accounting is computable
   (`sugar#3686` criterion 14), because Section 1.3's `WarrantKind` is
   exactly the warrant/support/effect three-terminal split generalized to
   symbols instead of lines.

None of these three is ever silently folded into `Unsatisfied` — a
producer's missing coverage is a LINK-class absence (like every other
`UnresolvedSymbol`), never treated as "the producer claims this returns
nothing," which would be a fabricated `Some(vacuous-universe)` and
therefore forbidden by the same doctrine that forbids a fake-dig EUF
lift (`feedback_euf_dig_needs_teeth`).

---

## Section 5. INSTANTIABILITY

A language lane (Rust, Java/Panama, C) claims producer conformance by
satisfying, in order:

1. **The two existing kit conformance laws, unchanged, extended to
   `exports`:**
   - **Fold == blob:** folding `exports().flat_map(|e| e.contract())`
     over the producer's whole declared surface must equal the same
     `ProofGraph` a hypothetical whole-surface single-shot lift would
     produce — the SAME law `enumeration-protocol.md:143-147` states for
     `source_files`/`functions`/etc., unchanged in shape, applied to the
     new level.
   - **Scan/seek coherence:** `exports()[i] ≡ export(exports()[i].memento)`
     — `enumeration-protocol.md:149-153`'s law, verbatim, on the new
     level. This is what makes Section 2.3's seek-first hot path
     trustworthy: a driver that seeks one symbol gets the byte-identical
     answer a full scan would have given it at that index.
2. **`KitDeclaration` conformance (Section 1.1):** `rpc.methods` lists
   `sugar.enumerate` (already required by every kit); `proof_resolution.strategy
   == "exported-symbol-contracts"`; `validate()`
   (`sugar-claim-envelope/src/lib.rs:156-180`) passes unchanged (no new
   required-field check needed — the existing `EmptyField` checks on
   `proof_resolution.strategy` already cover the new value).
3. **Exports enumerated totally (Section 4.3):** the producer's `exports`
   scan accounts for every symbol in its own declared artifact (its
   `.so`'s dynamic symbol table, its C header's declarations, its `.class`
   file's `native` method table) — `covered + gapped ==
   total_exported_surface`, no silent omission, matching criterion 14's
   line-accounting law generalized to symbols (Section 4 point 3).
4. **Contracts are ∀-shaped:** every `FunctionContract.contract.pre_json`/
   `post_json` a producer returns for a `Warrant::Source`-tier export is a
   domain claim over the operator's formal sorts (an `IrFormula` with the
   formals free, as `native-contract/`'s single test already models by
   accident — `assert_eq!(3, decoded_len_estimate(4))` is ONE instantiated
   point of what should be an ∀-shaped estimate formula; a real producer
   generalizes that one test into the closed-form claim, `(encoded_len / 4
   + (encoded_len % 4 > 0)) * 3`, the way the crate's own doc comment
   already states the general formula in prose but only tests one point).
   `Warrant::Stub`/`GeneratedContract` tiers may carry a weaker ABI-only
   claim (formals/returns sorts, no `pre`/`post`) — link-legal (signature
   checking still works) but not discharge-strength; this is the honest
   gradient the `WarrantKind` enum exists to name, not a hidden weakening.
5. **Symbol format compliance (Section 3.1):** every `ExportedSymbol.symbol`
   is the producer's own bare ABI name; every join key the driver
   constructs is `Symbol::qualified(producer_kit_id, bare_symbol)`, never
   a bare name alone (the #3865-generalization requirement).

A lane satisfying all five is producer-conformant; nothing more is
required to be driven by the SAME enumeration protocol and SAME `bind`
already in the tree.

---

## Section 6. THE POLARS ROW, END TO END

Today (`docs/audits/walls/polars/README.md`'s "#3654 relationship"
section): `call:scalar_sum` in `examples/polars-showcase/good/src/lib.rs`
calls into polars' compiled `_plr` extension; the showcase's own row is a
named, honest `bridge-target-missing` red — "bridge target CID not loaded
from the proof pool" — because no producer contract exists for polars'
native module. Walking this spec's sections against that ONE row:

- **Section 1** gives polars' `_plr` a producer kit: something that
  rendezvous'(s) declaring `proof_resolution.strategy:
  "exported-symbol-contracts"` and answers `sugar.enumerate {level:
  "exports"}` over `_plr`'s dynamic symbol table (or, more practically for
  a Rust-native extension like polars, over the `pyo3`-generated `#[pyfunction]`
  export list — a Rust producer lane reading the SAME source polars itself
  built from, `Warrant::Source` tier).
- **Section 2** is the driver noticing `scalar_sum`'s lift emits a
  `CallEdge` targeting a foreign (compiled-extension) symbol with
  `target_contract_cid: None`, asking the `_plr` producer kit
  `exports.seek` for that symbol, and receiving back a `FunctionContract`
  (or a named gap, if `sum`/`i32` isn't the producer's covered symbol yet).
- **Section 3** is the join: `bridgeSourceSymbol` from the Python/Rust
  consumer side resolved against `<plr-producer-kit-id>:<mangled-or-plain
  sum-export-name>`, formals/returns checked against the `Series::i32().sum()`
  callsite's actual types.
- **Section 4** is what stays loud if `_plr`'s producer only covers a
  fraction of polars' native surface: the SPECIFIC uncovered symbols stay
  named `UnresolvedSymbol` reds, never silently passed.
- **Section 5** is the conformance bar a `_plr`-producer lane must clear
  before its answers are trusted at all — fold==blob and scan/seek
  coherence over polars' actual compiled export list.

Once implemented, `call:scalar_sum`'s row moves from "bridge-target-missing,
no producer path" to either **discharged** (producer answers, `bind`
succeeds, consistency check runs and is SAT) or a **sharper, still-honest**
`Unsatisfied`/`SignatureMismatch` if the producer's contract and the
consumer's claim actually disagree — never a silent pass. The showcase's
`good`/`bad` twin structure (already present for the Panama example, absent
for polars) is the discrimination test this spec implies for polars once
a real `_plr` producer lands: a `bad` variant asserting a wrong sum must
still refuse.

---

## Section 7. Open questions carried forward (named, not blocking)

- **Which lane ships first.** T's ruling: Rust producer, "ONE native
  export → minted target contract → stable bridgeSourceSymbol/EUF → one
  consumer callEdge → pool loads target CID → resolve_target succeeds →
  good/bad twin proves non-vacuous composition" — this spec does not
  pick the specific first symbol; that is implementation-sequencing, not
  design.
- **Producer registry / discovery mechanism** (how a driver learns WHICH
  producer kit to rendezvous for a given foreign ABI) is sketched in
  Section 2.2 step 2 as "the driver's own producer registry" but its
  concrete shape (a manifest entry keyed by platform/ABI tag? a
  `KitDeclaration`-driven census extension?) is [NEW], deliberately
  underspecified here — it is a driver-side selection-policy concern, the
  same category the liftshift plan already keeps out of `sugar-compiler`
  proper (census/selection stays in the thin client, per `kit.rs`'s own
  scope note at lines 30-42).
- **`GeneratedContract` warrant provenance** (how a header-only decl gets
  synthesized into a contract, and what makes that synthesis trustworthy
  rather than a fake-dig) is named as a tier in Section 1.3/5.4 but its
  synthesis mechanism is explicitly out of scope for this spike — flagged
  for the first vertical's own design, not invented here.
