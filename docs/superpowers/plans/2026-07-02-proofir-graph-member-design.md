# ProofIRGraphMember — Concrete Two-Kit Design

> **Companion to** `docs/superpowers/plans/2026-07-02-proofir-semantic-vocabulary-campaign.md` (the campaign) and its decision of record (T Savo, 2026-07-02: ProofIR is the semantic carrier; every emission is a constructor call on a typed node class that owns its FOL denotation, constructor invariants, and its own solver-anchored verdict witnesses; the graph is fully attributed). This document is the CONCRETE shape — real Rust and Python, grounded in current repo types with file:line — that the campaign's slices build. It is design, not prose: where it shows code, that code is the target the slice writes. Every existing-type citation is verbatim from live main; re-verify before building.

## What a `ProofIrMember` IS

A `ProofIrMember` is ONE leaf of the proof graph: a single typed node that a sugar/consumer constructs when a floor meets an assertion or contract position. It is a LEAF — composition is graph edges by CID, never object nesting (see "Composition"). Its entire contract is five methods; `toProofIR()` is the one T named, and it is the LEAST interesting (it is just serialization at the edge). The load-bearing ones are `denotation`, `cid`, `provenance`, and the class-level `verdict_witnesses`.

| Method | Returns | What it does | Where the type comes from |
|---|---|---|---|
| `to_proof_ir()` | `String` | JCS wire form. `String` exists ONLY here — at the edge, via `encode_jcs`. Nowhere else in the member is anything stringly-typed. | lowers to `sugar_ir_types::Declaration` (CDDL wire, `sugar-ir-types/src/lib.rs:16`), then `encode_jcs`. |
| `denotation()` | `Rc<Formula>` (Rust) / `Formula` (Python) | The FOL formula the node instantiates — a template over the EXISTING term algebra. This is where "semantics lives once". | `sugar-ir-symbolic` `Formula`/`Rc<Formula>` (Rust); `ir.py` `Formula` (Python). Never a new DSL. |
| `cid()` | `MementoCid` | Content-address of the wire form. Structural CID equality IS the #3220 collapse: two nodes with the same wire form ARE the same node. | `MementoCid` (`sugar-proof-envelope/src/proof_graph.rs:131`), `from_bytes(encode_jcs(...).as_bytes())`. |
| `provenance()` | `Provenance` (non-optional) | `{node_class, construction_site, warrant}` where `warrant = Stated(locus) \| Derived(floor_chain)`. NOT `Option`. A node cannot exist unattributed. | new typed struct; `Stated`/`Derived` mirror the campaign's `EqualityFact` provenance rule. |
| `verdict_witnesses()` (class-level) | `WitnessPair` | The `{truthful → SAT, lying-twin → UNSAT}` pair the harness (Instrument C) runs through the REAL solver. Class-level: associated fn (Rust) / classmethod (Python). Registration refuses a witness-less class. | the vocabulary harness; sugars never touch the solver. |

There are NO other behaviors. No `.merge()`, no `.and()`, no fluent mutation. A member is immutable and total the instant it is constructed, or it refuses at the door.

## The closed set — Rust: `enum ProofIrMember` + a sealed trait

**Decision: a closed enum, each variant a struct with total constructors, plus a SEALED trait for the shared five-method behavior. NOT trait objects.** Justification is the house religion (AGENTS.md enforcement ladder; `MemberKind`/`StoredMember` precedent): a closed enum makes "adding a member kind" a compile error in every exhaustive match — the Gang-of-Four Visitor-with-abstract-method rung the manifesto names ("adding a variant makes every visitor that does not handle it refuse to compile"). Trait objects (`Box<dyn ProofIrMember>`) give open extension, which DEFEATS totality and reopens the side door one level down. The sealed trait gives shared behavior WITHOUT the open-extension hole (only this crate can impl it).

The wire kinds ALREADY EXIST as a closed enum — `MemberKind` (`sugar-proof-envelope/src/typed_member.rs:62-83`, 19 variants, `contract`/`bridge`/`factory-walk-memento`/`source-memento`/`implication`/`assertion-surface-memento`/`effect-site-annotation`/…). The campaign does NOT invent a wire vocabulary; it types the CONSTRUCTION side so it produces those exact kinds. Each `ProofIrMember` variant's `kind()` returns the matching `MemberKind`, which is what makes byte-compat mechanical.

```rust
// new crate: sugar-proofir-vocab (a library, depended on by sugar-lift-rust-tests AND sugar-walk;
// NOT a -tests crate — mirrors the irterm-boundary "algebra becomes a library" rule).

use std::rc::Rc;
use sugar_ir_symbolic::{Formula, Term};          // denotation algebra (sugar-ir-symbolic/src/lib.rs:106,:371)
use sugar_ir_types::Declaration;                  // CDDL wire shape (sugar-ir-types/src/lib.rs:16)
use sugar_proof_envelope::{MementoCid, MemberKind}; // identity + closed wire kind

/// Sealed: only this crate impls it. Shared five-method behavior; no open extension.
mod sealed { pub trait Sealed {} }
pub trait ProofIrNode: sealed::Sealed {
    fn kind(&self) -> MemberKind;                 // maps to the existing closed wire kind
    fn denotation(&self) -> Option<Rc<Formula>>;  // None only for RefusalRecord (honest absence)
    fn provenance(&self) -> &Provenance;          // non-optional
    fn to_declaration(&self) -> Declaration;      // the typed wire node (pre-JCS)
    fn to_proof_ir(&self) -> String {             // default: lower then JCS at the edge
        sugar_canonicalizer::encode_jcs(&self.to_declaration())
    }
    fn cid(&self) -> MementoCid {                 // content-address of the wire form
        MementoCid::from_bytes(self.to_proof_ir().as_bytes())
    }
    fn verdict_witnesses() -> WitnessPair where Self: Sized;  // class-level, solver-anchored
}

pub enum ProofIrMember {
    Equality(EqualityFact),      // Class A  → MemberKind::Contract (a #euf# assertion row)
    Contract(FunctionContract),  // Class C+F→ MemberKind::Contract (function-contract)
    Refusal(RefusalRecord),      // Class D  → (no Declaration; a diagnostic/effect member)
    Edge(CallEdge),              // Class B  → MemberKind::Bridge / call-edge
    Memento(SourceMemento),      // Class E  → MemberKind::{SourceMemento, FactoryWalkMemento}
    Diagnostic(Diagnostic),      // Class G  → vendor-conjoin / diagnostic row
}
```

`Provenance` — non-optional, the attributed-graph payoff:

```rust
pub struct Provenance {
    pub node_class: MemberKind,      // which vocabulary class licensed the fragment
    pub site: ConstructionSite,      // file:line / sugar shape that constructed it
    pub warrant: Warrant,
}
pub enum Warrant {
    Stated(VendorLocus),             // the vendor swore it (assertion locus)
    Derived(FloorChain),             // we derived it (the force_floor reduction chain)
}
```

### `EqualityFact` — the spine variant (Class A)

The denotation is exactly what `AssertionFactStrategy.fact_formula()` builds today (`sugar/call_sugar.py:724`, `eq(euf_term, expected)`) / what `warrant_conjoined_with_vendor_terms` conjoins in Rust (`source_contract.rs:337`, `eq(make_var("out"), asserted_out)`). The floor is HANDED IN, never fetched:

```rust
pub struct EqualityFact {
    euf_key: String,     // the #euf# contract name, spelled by the ONE canonical speller
    call_term: Rc<Term>, // euf_call_term(callee, args) — the Ctor head
    rhs: Rc<Term>,       // the value: from the floor, via to_term / project_callsite_with
    provenance: Provenance,
}

impl EqualityFact {
    /// TOTAL constructor. Refuses at the door if the terms are not well-sorted.
    /// `rhs` is produced by the projection seat (floor.to_term / project_callsite_with);
    /// this ctor NEVER sees a dict and never re-derives a value.
    pub fn new(euf_key: String, call_term: Rc<Term>, rhs: Rc<Term>, provenance: Provenance)
        -> Result<Self, FactoryGap>
    {
        require_ctor_head(&call_term)?;              // call_term must be a Ctor (call:callee(..))
        require_sort_agree(&call_term, &rhs)?;       // rhs sort == call return sort, or refuse
        Ok(Self { euf_key, call_term, rhs, provenance })
    }
    fn denotation_(&self) -> Rc<Formula> {
        eq(self.call_term.clone(), self.rhs.clone())  // sugar_ir_symbolic::eq
    }
}
impl sealed::Sealed for EqualityFact {}
impl ProofIrNode for EqualityFact {
    fn kind(&self) -> MemberKind { MemberKind::Contract }
    fn denotation(&self) -> Option<Rc<Formula>> { Some(self.denotation_()) }
    fn provenance(&self) -> &Provenance { &self.provenance }
    fn to_declaration(&self) -> Declaration {
        // lowers to the SAME wire shape emit_value_contract produces today
        Declaration::Contract {
            name: self.euf_key.clone(),
            out_binding: "out".into(),
            pre: None, post: None,
            inv: Some(raise_ir_formula(&self.denotation_())), // Rc<Formula> -> IrFormula at the edge
        }
    }
    fn verdict_witnesses() -> WitnessPair {
        WitnessPair {
            // truthful: A()->B()->0 with vendor ==0 collapses to one two-warrant node -> SAT
            truthful: sat_case("eq(call:A(), 0)", &["eq(call:A(), 0)"]),
            // lying twin: vendor ==1, derived ==0 -> two nodes, same key -> UNSAT
            lying:    unsat_case(&["eq(call:A(), 1)", "eq(call:A(), 0)"]),
        }
    }
}
```

`require_sort_agree` refusing is the parse-don't-validate teeth: an ill-sorted equality is UNREPRESENTABLE — you cannot hold an `EqualityFact` whose rhs sort disagrees, so no downstream check is needed.

### `FunctionContract` — the ONE staged case → a typestate builder (Classes C, F)

`FunctionContract` is the only genuinely staged member: warrants accumulate as a body is walked (mirroring `warrant_conjoined_with_vendor` folding `inv` then conjoining `eq(out, ...)`, `source_contract.rs:330-341`). Leaf facts get NO builder (a fluent chain is a legal partially-built state, which parse-don't-validate forbids); this one gets a TYPESTATE builder whose intermediate states are not `ProofIrMember`, so a half-built contract cannot enter the graph. The precedent to copy is the phantom-state marker already in the tree — `SugarBody<F: BodyFloor>` (`sugar-lift-rust-tests/src/sugar/factory.rs:143`, sealed `BodyFloor` marker + unit witnesses); there is no classic `Missing→Present` builder to copy, so we establish it in that phantom style:

```rust
pub struct NeedsPost;   // typestate markers (sealed)
pub struct Ready;
mod bstate { pub trait BuilderState {} impl BuilderState for super::NeedsPost {} impl BuilderState for super::Ready {} }

pub struct ContractBuilder<S: bstate::BuilderState> {
    symbol: String,
    formals: Vec<String>,
    pre: Option<Rc<Formula>>,
    post: Option<Rc<Formula>>,
    warrants: Vec<MementoCid>,
    _state: PhantomData<S>,
}
impl ContractBuilder<NeedsPost> {
    pub fn new(symbol: String, formals: Vec<String>) -> Self { /* pre=None, post=None */ }
    pub fn warrant(mut self, cid: MementoCid) -> Self { self.warrants.push(cid); self }
    pub fn post(self, post: Rc<Formula>) -> ContractBuilder<Ready> { /* moves state, sets post */ }
}
impl ContractBuilder<Ready> {
    // build() exists ONLY on Ready — a contract with no post is UNBUILDABLE, statically.
    pub fn build(self, provenance: Provenance) -> Result<FunctionContract, FactoryGap> {
        require_out_binding(&self.post)?;   // door refusal for the residual invariants types can't see
        Ok(FunctionContract { /* ... */ })
    }
}
```

The builder TYPE is not a `ProofIrMember` variant, so `ContractBuilder<NeedsPost>` cannot be put in the graph. `.build()` is the only door to a `FunctionContract`, and it exists only on `Ready` — the "contract without a post" bug is unrepresentable at compile time, not detected at runtime.

### `RefusalRecord` — the `Incomplete` expression (Class D)

`denotation()` is `None` — honest absence carries NO formula. Constructed FROM the typed refusal, never a fact:

```rust
pub struct RefusalRecord { effect: Effect, provenance: Provenance } // Effect: lib.rs:9056
impl RefusalRecord {
    pub fn from_incomplete(inc: Outcome /* Incomplete(Effect) */, prov: Provenance)
        -> Result<Self, FactoryGap> { /* refuse if inc is Complete — an Incomplete has ONE expression */ }
}
impl ProofIrNode for RefusalRecord {
    fn denotation(&self) -> Option<Rc<Formula>> { None }   // no formula, by design
    /* kind -> effect-site-annotation / diagnostic; to_declaration -> a diagnostic member, not a Contract */
}
```

## The closed set — Python: frozen dataclasses + an ABC, refusing at `__post_init__`

Python mirrors the Rust shape with `@dataclass(frozen=True)` variants under a shared ABC, and refuses at construction via `__post_init__` raising `FactoryGap` — the pervasive house precedent (`BridgeStrategy.__post_init__` raises `TypeError` on a non-factory-built field, `sugar/call_sugar.py:63-68`; ~25 such sites). Python has no compiler to enumerate offenders, so the door-refusal is the panic rung the campaign's return-type flip (Slice 3) leans on — the seam raise that recruits the test suite.

```python
# new module: sugar_lift_py_tests/vocab/proofir_member.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from sugar_lift_py_tests.ir import Formula, Term, eq, encode_jcs, formula_to_value
from sugar_lift_py_tests.factory import FactoryGap, FactoryGapInfo, FactoryAuditRow

class ProofIrMember(ABC):
    @abstractmethod
    def denotation(self) -> Formula | None: ...   # None only for RefusalRecord
    @abstractmethod
    def provenance(self) -> "Provenance": ...       # non-optional
    @abstractmethod
    def to_declaration(self) -> dict: ...           # the typed wire node (pre-JCS)
    def to_proof_ir(self) -> str:                   # String ONLY here, at the edge
        return encode_jcs(self.to_declaration())
    def cid(self) -> str:                           # content-address of the wire form
        return blake3_512_of(self.to_proof_ir())
    @classmethod
    @abstractmethod
    def verdict_witnesses(cls) -> "WitnessPair": ... # class-level, solver-anchored


@dataclass(frozen=True)
class EqualityFact(ProofIrMember):
    euf_key: str
    call_term: Term          # euf_call_term(callee, args)
    rhs: Term                # HANDED IN by the projection seat (floor.to_term / project_callsite_with)
    provenance: "Provenance"

    def __post_init__(self) -> None:
        # refuse at the door — parse-don't-validate. Never sees a dict.
        _require_ctor_head(self.call_term, owner="EqualityFact")   # raises FactoryGap
        _require_sort_agree(self.call_term, self.rhs, owner="EqualityFact")

    def denotation(self) -> Formula:
        return eq(self.call_term, self.rhs)          # the SAME formula AssertionFactStrategy builds today

    def to_declaration(self) -> dict:
        # lowers to the SAME BodyUniverseDto wire shape emitted today
        return BodyUniverseDto(
            name=self.euf_key, out_binding="out",
            inv=formula_to_value(self.denotation()),  # typed Formula -> Value at the edge, no stored dict
            source_warrants=[self.provenance.warrant_memento()],
        ).to_rpc()

    @classmethod
    def verdict_witnesses(cls) -> "WitnessPair":
        return WitnessPair(
            truthful=sat_case(eq_call("A", 0), warrants=["Stated", "Derived"]),  # collapses to one node -> SAT
            lying=unsat_case([eq_call("A", 1), eq_call("A", 0)]),                # two nodes, same key -> UNSAT
        )
```

The Python staged case (`FunctionContract`) uses a builder whose `build()` IS the refusing constructor (there is no static typestate in Python), backed by the same `__post_init__` / seam raise:

```python
class ContractBuilder:
    def __init__(self, symbol, formals): self._post = None; ...
    def warrant(self, memento): self._warrants.append(memento); return self
    def post(self, post: Formula): self._post = post; return self
    def build(self, provenance) -> "FunctionContract":
        if self._post is None:
            raise _factory_gap("FunctionContract", "contract has no post — cannot build")
        return FunctionContract(self._symbol, tuple(self._formals), self._post, ..., provenance)
```

## How floors flow in — the member never fetches, never sees a dict

Per the campaign's "codomain of `Outcome<floor>`": the projection seat HANDS the member its typed inputs. Today `CallsiteProjectionOperation.project_literal` already returns a typed `Formula` = `eq(call_term(), receiver.to_term(owner=...))` (`operations/callsite_projection_operation.py:18-20`), and `to_term` is the existing gap-refusing bridge (`floor/floor_value.py:11`, raises `FactoryGap` on an unprojectable floor). The member consumes exactly those:

- `EqualityFact.rhs` ← `floor.to_term(owner="EqualityFact")` (the floor IS the well-formedness witness; an unprojectable floor refuses HERE, before a member exists).
- `EqualityFact` from a bridge pointer ← `project_callsite`'s `eq(call_term, receiver.term)` shape (`callsite_projection_operation.py:22`).
- `RefusalRecord` ← the `Incomplete(effect)` the reduction returned (`outcome/incomplete.py`), never a synthesized fact.

No arrow into a constructor carries a `dict` or `str`. That is the campaign's parse-don't-validate line, made concrete.

## Composition = edges by CID, not object nesting

Members are LEAVES; the graph is the composite. A `CallEdge` does not embed its target contract — it REFERENCES it by `MementoCid` (exactly as `LinkerCallEdge` carries `source_contract_cid`/`target_contract_cid: Option<String>` today, `sugar-linker/src/lib.rs:95-108`, and `CallEdgeDecl` carries `source_contract_cid`/`target_contract_cid`/`evidence_term`, `ir.py:642`). The edge's `evidence_term` is the composition obligation `post_B ⊃ pre_A` (SHARED-LANGUAGE's implication; `LinkerCallEdge.evidence_term_json` comment `:106`).

```rust
pub struct CallEdge {
    source_contract: MementoCid,          // by CID, not the object
    target_contract: Option<MementoCid>,  // None => cross-kit, resolve by symbol
    target_symbol: String,
    call_site: ConstructionSite,
    evidence: Rc<Formula>,                // post_B ⊃ pre_A
    provenance: Provenance,
}
```

**Dedup = structural CID equality.** Two `EqualityFact`s with the same wire form have the same `cid()` → they ARE the same node. That is the #3220 collapse, mechanically: the truthful bridge-chain fact and the truthful demanded-floor fact hash identically and collapse to one node bearing two `Warrant`s; the lying pair (`==1` vs `==0`) hash DIFFERENTLY → two nodes → the solver's UNSAT survives. No dedup logic — CID equality is the collapse, provenance is the two-warrant carrier.

## Integration with `StoredMember` / `MementoCid`

`StoredMember` (`sugar-proof-envelope/src/proof_graph.rs:877-901`, `{cid, kind, body, fields}`, built by `from_envelope`) is the READ side of the graph — how a member is stored and looked up after ingestion. A `ProofIrMember` is the WRITE/CONSTRUCTION side: `to_proof_ir()` produces the envelope bytes whose `MementoCid` (`from_bytes`/`from_layered_envelope`, `proof_graph.rs:143,:158`) is the member's identity, and that envelope is exactly what `StoredMember::from_envelope` later parses back. The two share `MemberKind` (each `ProofIrMember` variant's `kind()` returns the wire kind `StoredMember` will read). The campaign types the construction side so the thing `StoredMember` stores was born typed, not assembled as a `dict`.

## BEFORE / AFTER at the two real seats

### Seat 1 — `_emit_euf_fact` (`factory/literal_call_report.py:744-800`)

BEFORE (verbatim, the flatten at `:774`):
```python
fact = AssertionFactStrategy(callee_name, tuple(arg_terms), value_term)
contract_name = fact.contract_name()
inv = _formula_to_rpc(fact.fact_formula())          # typed Formula -> dict[str,Any]  ← the door
contract = BodyUniverseDto(name=contract_name, out_binding="out", inv=inv, source_warrants=[memento])
```

AFTER (Slice 4 — construct an `EqualityFact`; the DTO is produced BY the member at the edge):
```python
member = EqualityFact(
    euf_key=fact.contract_name(),
    call_term=fact._euf_term(),                      # the Ctor head, typed
    rhs=value_term,                                  # handed in (floor.to_term / project result), never a dict
    provenance=Provenance(node_class=MemberKind.CONTRACT, site=_site(stmt, filename),
                          warrant=warrant),           # Stated(assertion locus) or Derived(floor chain)
)
contract = member.to_declaration()                   # BodyUniverseDto.to_rpc() built FROM the typed node
```
The two call sites of `_emit_euf_fact` (vendor path `:732`, demanded-floor path `:976`) each pass their `warrant` (`Stated` vs `Derived`); the single seat constructs the member; CID equality collapses the truthful duplicate, provenance carries both warrants. Byte target: the repr-snapshot golden `callsite_emission_golden.json` field set (`bridge_source_symbol, formals, inv, kind, name, out_binding, post, pre`) and the `'<fn>#euf#c:call:<fn>(<args>)::assertion'` name convention — reproduced by `to_declaration`, re-pinned where the #3220 collapse deliberately drops the duplicate row.

### Seat 2 — the call-edge builder (`factory/literal_call_report.py:1580-1596`)

BEFORE (verbatim — note it hand-builds a `dict` with keys `sourceContract`/`targetContract` and OMITS `evidenceTerm`, diverging from the canonical shape):
```python
edge: dict[str, Any] = {
    "kind": "call-edge", "schemaVersion": "1",
    "sourceContract": source_contract,
    "targetSymbol": target_symbol,
    "targetContract": binding.get("name") if binding is not None else None,
    "targetContractCid": _binding_cid(binding) if binding is not None else None,
    "callSiteLocus": {"file": memento_file, "line": item["line"], "column": item["column"]},
}
```

AFTER (Slice 7 — reuse the EXISTING typed `CallEdgeDecl`, `ir.py:642`, whose `call_edge_decl_to_value` already fixes JCS key order and carries `evidenceTerm`):
```python
edge_decl = CallEdgeDecl(
    source_contract_cid=source_contract,
    target_contract_cid=_binding_cid(binding),       # canonical: *Cid, not the bare name
    target_symbol=target_symbol,
    call_site_locus=Locus(memento_file, item["line"], item["column"]),
    evidence_term=post_implies_pre,                  # the composition obligation, now REQUIRED
)
edge = call_edge_decl_to_value(edge_decl)            # canonical JCS shape
```
This is a DELIBERATE byte change (it fixes the divergent `sourceContract`/`targetContract`/missing-`evidenceTerm` shape and aligns Python with Rust's `LinkerCallEdge.evidence_term_json`). It is documented + re-pinned in Slice 7, per campaign law 6.

### Rust seat — `source_value_contract` (`source_contract.rs:985`)

The Rust in-memory `ContractDecl` (`sugar-ir-symbolic/src/lib.rs:371`, `Rc<Formula>`, no serde) is ALREADY typed; the Rust residual is only the `serde_json::json!` locus/diagnostic scaffolds. So the Rust `EqualityFact`/`FunctionContract` variants wrap that existing typed `ContractDecl` + `Provenance` and lower to `Declaration::Contract` (`sugar-ir-types/src/lib.rs:19`) via `to_declaration()`. The wire type `Declaration` is CDDL-GENERATED (`DO NOT EDIT`, `sugar-ir-types/src/lib.rs:3`), so the member CANNOT live in `sugar-ir-types` — it lives in the new `sugar-proofir-vocab` lib and lowers TO `Declaration`.

## Census-class → variant → slice map

| Census class | `ProofIrMember` variant | Wire `MemberKind` | Lands in |
|---|---|---|---|
| A EqualityFact / `#euf#` row | `Equality(EqualityFact)` | `Contract` | Slice 4 (#3235) |
| C GuardedPost / body-step | folded into `Contract(FunctionContract)` | `Contract` | Slice 5 (#3236) |
| F UniverseMint / function-contract | `Contract(FunctionContract)` (typestate builder) | `Contract` | Slice 5 (#3236) |
| D RefusalRecord | `Refusal(RefusalRecord)` | `effect-site-annotation` / diagnostic | Slice 6 (#3237) |
| B Bridge / CallEdge | `Edge(CallEdge)` (+ `Bridge`) | `Bridge` / call-edge | Slice 7 (#3238) |
| E SourceAudit / walk-memento | `Memento(SourceMemento)` | `SourceMemento` / `FactoryWalkMemento` | Slice 7 (#3238) |
| G VendorConjoin / Diagnostic | `Diagnostic` (+ `Contract` w/ Stated+Derived) | diagnostic | Slice 7 (#3238) |
| Rust residual `json!` scaffolds | same variants, Rust impls | as above | Slice 9 (#3240) |

No slice mapping changed from the campaign plan — this doc adds shape, not scope. No issue-body edits required.

## Design tensions found (flagged per T's ask)

1. **`to_proof_ir` is pinned by the CDDL wire, not chosen.** `sugar-ir-types` is generated from `protocol/sugar-ir.cddl` (`DO NOT EDIT`). The member's `to_declaration()`/`Serialize` MUST reproduce `Declaration::Contract`'s exact serde renames (`outBinding`, `skip_serializing_if = Option::is_none` on `pre`/`post`/`inv`, `sugar-ir-types/src/lib.rs:19-30`). The typed shape does NOT get to pick its wire form — byte-compat means the member is a typed FRONT for a frozen wire node. This is fine (it is the whole point) but it means "add a field to the member" is a wire/CDDL change, out of campaign scope.

2. **Two `ContractDecl`s in Rust — name collision to resolve.** The in-memory typed contract is `sugar_ir_symbolic::ContractDecl` (`Rc<Formula>`, no serde, `:371`); the wire contract is `sugar_ir_types::Declaration::Contract` (serde, `IrFormula`, `:19`). `EqualityFact`/`FunctionContract` hold the FORMER (denotation over `Rc<Formula>`) and lower to the LATTER. The before/after must be explicit about which layer it touches; the member is a THIRD layer above `ContractDecl`, carrying provenance the in-memory struct lacks. Recommend the member OWNS provenance and delegates denotation to a wrapped `ContractDecl` rather than duplicating its fields.

3. **The Python golden is a repr-snapshot, not JCS.** `callsite_emission_golden.json` stores Python `repr` strings (`'None'`, `"[]"`, single-quoted), so it pins field-set + ordering + the `#euf#` name convention, NOT the true JSON wire. The member's Python `to_declaration()` must keep that snapshot stable AND (separately) the Rust/verifier JCS path must match `Declaration`. Two byte targets, one member — the design handles it because `to_declaration()` returns the `BodyUniverseDto.to_rpc()` dict the snapshot captures, while `to_proof_ir()` is the JCS edge. Worth a dedicated byte-compat bad-twin in Slice 4 covering BOTH.

4. **`StoredMember` lives in `proof_graph.rs`, not `typed_member.rs`.** (`typed_member.rs` has a parallel typed `Member` enum + the `MemberKind`/`MemberError` vocabulary.) The write-side `ProofIrMember` and the read-side `StoredMember` are different types that meet at the envelope bytes + `MemberKind`; do not conflate them or try to make one subsume the other.

5. **`MementoCid` has no `FromStr`; parse is `try_parse`.** (`proof_graph.rs:150`.) The member's `cid()` uses `from_bytes(encode_jcs(...))`, the construction path — not a parse. Fine, but a slice that needs to reference a CID from wire input uses `try_parse` (the typed-error path), never `new` (which asserts/panics, `:135`).

6. **`Incomplete.effect: object` (Python) is the one untyped hole feeding `RefusalRecord`.** Rust already types it (`Effect`, `lib.rs:9056`). Slice 6 must type Python's `Effect` union FIRST (or `RefusalRecord.from_incomplete` has nothing well-typed to consume) — a small ordering constraint already reflected in Slice 6.


## Addendum (2026-07-02, post-S2 review — decision of record, T Savo)

**Two identities per member.** `cid()` (artifact identity: full wire form including warrants/provenance — the memento layer's address) is joined by `semantic_cid()` (claim identity: provenance-free wire form — `euf_key` + denotation only). Graph-level dedup/merge keys on `semantic_cid`: equal semantic_cid + different provenance = ONE node, warrant union (the #3220 collapse); equal semantic_cid + equal provenance = idempotent duplicate; different formula = different semantic_cid = never merged (the stated-vs-derived lie conjunction is preserved by construction). Rationale: the claim and the record of who swore it are different objects — hashing warrants into the only identity made structural collapse impossible (found by adversarial review of PR #3269, finding 1).

Also from that review: the verdict-witness registry must RUN every registered pair through the real solver (labels are not verdicts — Instrument C parametrizes over the registry), and the XSugar-bypass auditor exemption must be default-deny (exempt only provably-proofir builder receivers; receiver-name allowlists invert the instrument's polarity).
