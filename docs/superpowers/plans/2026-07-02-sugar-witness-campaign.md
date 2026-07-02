# Sugar-Witness Campaign — IDD Plan

> **For agentic workers:** This is a CAMPAIGN plan, not an implementation patch. Do NOT flip the enrollment lever from this document's branch, and do NOT start a drain batch before the witness surface + harness exist. The coordinator dispatches slices ONE AT A TIME from current main. Instruments come before drains, every slice is red-first. This campaign makes the capstone law real in BOTH kits: it is the "one dumb test" that closes the composition between the sugar catalog and the ProofIR vocabulary. Python phase first (it holds the freshest scar tissue and the harness seed, PR #3269); Rust phase second. Every protocol claim below is grounded in file:line; re-verify against live main before you build on it.

**Goal:** Every sugar owns its witness pair — a truthful and a lying MINIMAL SOURCE statement in its kit's language — and ONE parametrized test `foreach`-es the catalog, drives each pair through the production lift→compile→solve pipeline, and asserts the TRIPLE: (1) THAT sugar fired, (2) THAT ProofIR came back, (3) THAT verdict (truthful SAT / lying UNSAT). Enrollment is existence: a sugar that cannot testify does not exist in the catalog — enforced by the type system (Rust: a non-defaulted requirement; Python: a registration-time refusal), enumerated by the instrument, made loud by the panic. When this campaign closes, the sugar owns its code example, the ProofIR owns the sat/unsat semantics, and the composition between them is a single executable law.

## The decision of record (T Savo, 2026-07-02 — collapse, do not relitigate)

- **"The sugar owns the code example. The ProofIR owns the sat/unsat semantics. That's the final test composition."**
- The triple: **"given the two statements in python you just construct the factory and assert THAT sugar came back. And assert THAT proofir is SAT."**
- **"One test. One, very dumb, very small test. And it just foreach over all sugar."**
- The capstone law (now in `AGENTS.md` §"The capstone law" lines 252-279, and `HANDOFF.md` lines 122-125, cite both): **"Enrollment is existence, enforced by the type system, enumerated by the instrument, made loud by the panic, and the fix becomes unavoidable by any agent."** Every sugar owns the source statements that construct it (its territory — the only fact it is authoritative about); every ProofIR node class owns the situations that make claims of its kind SAT or UNSAT (its meaning); and ONE parametrized test foreach-es the catalog, drives each sugar's truthful/lying source pair through the production RPC pipeline (`sugar lift` → ir compiler → solver), and asserts the triple. The test itself is deliberately dumb — every ounce of intelligence lives with an owner, every failure mode has exactly one address.

**Provenance condition (non-circularity — load-bearing).** Assertion (1) — "THAT sugar fired" — is what makes ownership non-circular. The sugar's example must provably dispatch to THAT sugar, so recognizer drift or death is caught: a sugar whose recognizer no longer fires on its own witness reds, rather than silently passing because some OTHER sugar happened to lift the source. Without assertion (1), a witness pair only proves "some sugar produced a verdict", which is not ownership.

**Adjacent design context (recorded, NOT part of this campaign's first slices).** `near_miss()` — a sugar declaring the BORDER cases just outside its territory (discrimination witnesses reverse-engineered from a declared shape) — was part of the arc. It is a LATER phase (the shape-declaration layer), planned after this campaign lands the mine-pair + triple + enrollment. See "Future phase".

## Current shape (the machinery mostly exists; it is not yet organized as enrollment)

### Python — self-registration is already the enrollment seam

`sugar/sugar_base.py:18` `class Sugar(ABC)`. It does NOT use `@abstractmethod`; it self-registers every leaf via `__init_subclass__` (`:39-57`) when a subclass passes `role=` in its header (`class AssignSugar(Sugar, role=SugarRole.STATEMENT)`, `sugar/assign_sugar.py:13`), appending a `SugarClaim` to a module-global `_REGISTRY` (`:11`), exposed by `registered_claims()` (`:14`). The three required methods (`owns` `:59`, `build` `:63`, `desugar` `:67`) are stubbed with `raise NotImplementedError`. **The `role=` gate in `__init_subclass__` is the exact seam where a witness requirement can be enforced at registration (import) time** — the strongest Python analogue of "won't compile". The catalog is assembled by `factory/build.py:218` `default_catalog()`, which `importlib`-imports every `sugar/*_sugar.py` module (so every leaf self-registers) and returns `SugarCatalog(registered_claims())`. There are **~58 registrable sugar modules**.

### Python — the harness seed already exists (PR #3269) and the twins already exist (decoratively)

The verdict-witness shape is already minted on the ProofIR side: `idd/proofir_vocab_instruments.py:70` `ProofIrVocabularyWitness{node_class, truthful_sat, lying_unsat}`, counted by `proofir_classes_without_verdict_witnesses` (`:498`) — the exact truthful-SAT/lying-UNSAT invariant, keyed on ProofIR `node_class`. PR #3269 (vocab Slice 2, closes #3233, OPEN) adds the RPC-driven witness harness for the 3 spine node classes. **This campaign generalizes that seed from 3 node classes to every sugar, keyed on the SUGAR.** The truthful/lying source twins ALSO already exist — as the `good`/`bad` projects in the decorative `*_sat_unsat` tests (`tests/test_slice_subscript_sat_unsat.py`, `test_try_sat_unsat.py`, `test_object_binary_dunder_sat_unsat.py`, ~17 files total). But their verdict is FAKE: `_formula_status` (`test_slice_subscript_sat_unsat.py:58`) returns `sat` if `left == right` else `unsat` — a string comparison on the emitted formula dict wearing a verdict's name, never a solver (issue #3272). The production driver `_run_lift_rpc` (copy-pasted per file, e.g. `test_slice_subscript_sat_unsat.py:13`) spawns `python -m sugar_lift_py_tests.lift_rpc --rpc` and returns the lift document.

### Python — the hand-maintained coverage registry this retires

`tests/test_sugar_coverage_registry.py` pins `COVERAGE: dict[str, list[str]]` (`:26-104`, ~60 hand-maintained sugar-module → test-file entries) and asserts every `sugar/*_sugar.py` stem appears exactly once (`:116`) and each named file touches the sugar (`:125`). Enrollment (a sugar owning its witness) replaces this hand table.

### Python — the genuine opt-out set

No `NotVerdictBearing`/opt-out marker exists yet. The genuine set that cannot reach a solver alone reduces to a NON-FOL support/plumbing floor — but NOT all to the same floor: `CommentSugar` (`sugar/comment_sugar.py:12`) desugars to `Complete(SupportValue())` (`:37`, `floor/support_value.py:9`, "contributes nothing to the first-order logic"); `AliasSugar` (`sugar/alias_sugar.py:12`, import-as plumbing) returns `ImportAliasValue` (`floor/import_alias_value.py`), NOT `SupportValue`; and `SubscriptAssignSugar` / `SubscriptDeleteSugar` are support statements. This is why the opt-out must be a TYPED marker ON THE FLOORS (a `non_fol_support` predicate the plumbing floors declare), with the gate pinning the closed set of marked floors — never a hand list of sugar names keyed on one floor type.

### Rust — `desugar` has no default; the catalog is const claim slices

`sugar-lift-rust-tests/src/lib.rs:8981` `trait Sugar { fn reduce(..) { self.desugar(..) } fn desugar(&self, ctx) -> Outcome; }` — `desugar` has NO default (the trait-level enrollment lever precedent). The catalog is hand-maintained `const` slices in `sugar/catalog.rs`: `EXPR_CLAIMS` (`:50`, **204 entries**), `ITEM_CLAIMS` (`:257`, **5 entries**), `STMT_CLAIMS` (`:265`, **5 entries**); 217 sugar source files. Each claim is an `ExprSugarClaim` (`sugar/claim.rs:35`) = `{ name: &'static str (#[allow(dead_code)]), role, comes_before, fallback_well, recognize: fn(&SourceFragment, &SugarBuildCtx) -> Option<Box<dyn Sugar>> }`. **The claim struct's fields are the enrollment lever: a new non-defaulted `witnesses` field forces every `const` claim literal to supply it or the crate does not compile.** Note `name` is `#[allow(dead_code)]` and the slices are crate-private — assertion (1) needs a `pub` name/recognized accessor (a campaign hook that does not exist today).

### Rust — the triple already exists in prototype (driver + verdict), missing enrollment + assertion-1

The production lift entry is `lib.rs:492` `pub fn lift_file(&syn::File, source_path) -> AdapterOutput` (`.decls: Vec<ContractDecl>`). The real verdict path exists: `sugar-ir-compiler-smt-lib::compile_asserted_to_parts` (`:276`) feeding `tests/assertion_lift.rs:15266` `z3_verdict(inv, label) -> Option<bool>` (Some(true)=SAT), bridged by `inv_json(&ContractDecl)` (`:15311`). `assertion_lift.rs` already has **~26 truthful/lying twin tests** (e.g. `const_if_then_branch_correct_value_is_sat:533` vs `..._wrong_value_is_unsat:517`) driving `lift_file → inv_json → z3_verdict`. **What is missing is exactly assertion (1) and enrollment:** verdicts key off `out.decls[0]`, not "which named sugar fired", and there is no catalog `foreach`. The twin (assertion 3) and driver (assertion 2) are done.

### Rust — assertion-2 target and a naming collision to disambiguate

"ProofIR came back" asserts against `sugar_ir_symbolic::ContractDecl` (`src/lib.rs:372`) in-process until the Rust vocab (ProofIR-vocab campaign Slice 9, #3240, post-irterm #3198) lands `sugar_ir_types::Declaration` as the typed assertion target. Separately, `sugar-lift-rust-cargo-test-witness/` is a DIFFERENT "witness" concept (a cargo-test discharge `WitnessPackageMemento`, content-addressed pass/fail) — the campaign must disambiguate: this campaign's artifact is a **sugar SOURCE-witness pair**, not the cargo-test witness package.

## The mechanism this campaign builds

**The witness pair (per sugar):**
- `truthful` — a minimal source statement (Python source for the py kit, Rust source for the rust kit) that this sugar recognizes and whose lifted ProofIR is SAT.
- `lying` — a minimal source statement, same shape, whose lifted ProofIR is UNSAT (the vendor swore something false).
- OR a typed opt-out for a sugar that genuinely cannot reach a solver alone. **This is TYPE/FLOOR-ANCHORED — CLOSED, TYPED, and AUDITED — never a social exemption (T Savo).** The exemption derives from a typed property of the FLOOR the sugar reduces to (inert / non-FOL-contributing), NOT from anything the sugar declares about itself:
  - **TYPED:** the marker lives on the FLOOR TYPES (a `non_fol_support` predicate/trait the inert floors carry: `SupportValue`, `ImportAliasValue`, and the other plumbing floors), not an attribute set on a sugar. A sugar is non-verdict-bearing IFF its `desugar` result floor is a marked inert floor. **A "social exemption" — a sugar claiming opt-out by its own declaration rather than by its floor's nature — must be UNREPRESENTABLE:** there is no per-sugar opt-out flag to set; the only route to exemption is reducing to a marked floor.
  - **CLOSED:** the set of marked floor types is pinned.
  - **AUDITED:** the gate verifies the pinned set MATCHES the marker-derived set (the sugars whose `desugar` floor is marked) — **drift EITHER way is red** (a sugar newly reducing to a marked floor that is not pinned; or a pinned entry whose floor is no longer marked). T verbatim: *"inert/support/plumbing floors that do not contribute FOL alone may opt out. That opt-out set should be closed, typed, and audited."* Current members: `CommentSugar` (→ `SupportValue`), `AliasSugar` (→ `ImportAliasValue`, `floor/import_alias_value.py`, NOT `SupportValue`), and likely `SubscriptAssignSugar` / `SubscriptDeleteSugar` (support statements).
  **An empty default is the side door and is forbidden** — a sugar carries a witness pair OR reduces to a marked non-FOL floor, never nothing; adding a member is a typed floor change (marking a floor), audited against the pin, not a silent list edit.

**Enrollment is existence — the per-kit mechanics:**
- **Python (RATIFIED, T Savo):** add a required `witnesses()` classmethod (returning a `WitnessPair | NotVerdictBearing`) to `Sugar`. THE enforcement is an EXPLICIT class-definition check on registrable leaves inside `__init_subclass__` at the `role=` gate (`sugar_base.py:39`): when a leaf passes `role=`, the hook asserts the class actually overrides `witnesses()` (`"witnesses" in cls.__dict__` / not the base stub) and raises `TypeError` at class-definition time otherwise. This fires when `default_catalog()` imports the module (`factory/build.py:218`), so ONE import sweep lights up every unenrolled registrable leaf — the WHOLE catalog reds at import on flip day, matching Rust's compile-time. T verbatim: *"`__init_subclass__` at the `role=` gate is better than instantiation failure … the real enforcement must be an explicit class-definition check on registrable leaves, not ABC instantiation behavior."* `@abstractmethod` is ONLY a backstop — it must NOT be the enforcement mechanism, because ABC instantiation behavior fires per-instance (via `build()`), not at catalog import, and a sugar that is never instantiated in a given run would slip. The explicit `role=`-gate check is the law; the abstractmethod is belt-and-suspenders.
- **Rust (ONE-LAW FLIP, STAGED DRAIN — T Savo):** the FLIP is a single hard law — add the non-defaulted `witnesses: SugarWitnesses` field to ALL THREE claim structs (`StmtSugarClaim`/`ItemSugarClaim`/`ExprSugarClaim`, `claim.rs:35`) AT ONCE, so one compile enumerates all 214 unenrolled `const` literals in `catalog.rs`. To keep both the one-law flip AND a shippable tree during the drain, `SugarWitnesses` includes a typed `Pending` placeholder: `SugarWitnesses::{Pair(truthful, lying), NotVerdictBearing(reason), Pending}`. The flip PR sets every claim literal to `Pending` (the compiler accepts it, so the tree ships), and the auditor/gate COUNTS every `Pending` as a RED row — `R(unenrolled-sugars)` = the count of `Pending` claims. The drain then replaces `Pending` with a real `Pair`/`NotVerdictBearing`, STAGED BY CLAIM FAMILY/ROLE (Stmt 5, Item 5, then Expr in family batches), each drain PR = one family's witnesses, reviewable as a unit. T verbatim: *"the compile-red flip can still be one hard law, but the drain should be staged by claim family/role … otherwise the PR becomes a bucket of unrelated witness work and review loses signal."* Add a `pub fn name(&self)` / recognized-claim accessor for assertion (1). (This mirrors the ProofIR-vocab Slice-3 return-type-flip staging: one type-level law, a typed placeholder that ships while the drain proceeds, the gate counting the placeholder as red. `Pending` is drained to ZERO and forbidden at close — it is a staging device, not an escape hatch.)

**The flip lands RED with the whole offender list at once** (Python: ~58 sugars at catalog import; Rust: 214 `Pending` claims at the single flip), then drains in review-sized units — Python by batch, Rust by claim family — each enrolling a set of sugars with real truthful/lying pairs (reusing the decorative `good`/`bad` twins as the seed source), ratcheting `R(unenrolled-sugars)` to zero.

**The one dumb test** (`test_sugar_witness_triple.py` / `tests/sugar_witness_triple.rs`): `foreach` claim in the catalog, for each of `{truthful, lying}`: write the minimal source project, drive it through the ONE centralized `_run_lift_rpc` (Python) / `lift_file` (Rust), and assert the triple —
1. **that sugar fired** — the lift report's factory-walk/recognized-claim attribution names THIS sugar (Python: the `factory_walk` row's sugar name; Rust: the claim's `recognize()` returns `Some` and catalog resolution selects THIS claim). Non-circularity.
2. **that ProofIR came back** — a typed node was emitted (Python: the ProofIR-vocab node class once #3269+S4 attribute the graph; until then `doc["ir"][…]` non-empty; Rust: `AdapterOutput.decls` non-empty as `sugar_ir_symbolic::ContractDecl`, upgrading to `sugar_ir_types::Declaration` at #3240).
3. **that verdict** — the emitted formula, driven through the REAL ir compiler + solver (Python: replace `_formula_status` with the `sugar-ir-compiler-smt-lib` path used by #3269's harness; Rust: `z3_verdict`), is SAT for truthful and UNSAT for lying.

## Campaign law

1. **Instruments before drains.** The enrollment auditor + the triple-harness land RED/measuring before the flip; the flip lands RED with the full offender list before any batch enrolls.
2. **Red-first every slice.** A compile error (Rust claim missing `witnesses`) or a catalog-import `TypeError` (Python unenrolled leaf) is a valid red-first transcript. A green-by-accident enrollment is not.
3. **The panic is sacred; enrollment is existence.** A sugar declares a witness pair OR a `NotVerdictBearing(reason)`; never nothing. The opt-out list is CLOSED and PINNED; adding to it is a reasoned, on-the-record change (a floor move), never a silent default.
4. **Assertion (1) is non-negotiable.** Every witness must prove it dispatches to ITS sugar. A verdict without that attribution is not ownership and does not count.
5. **Real solver only.** The triple's verdict is the ir compiler + solver, never a string comparison. Retiring `_formula_status` (#3272) is part of the harness, not a follow-up.
6. **Byte-compat where it applies.** Enrolling a sugar and moving its twin onto the harness must not change emitted lift bytes for existing fixtures; the decorative-test deletion is behavior-preserving on the production path.
7. **Law 8 (grab the type system).** Enrollment is a TYPE mechanism (Rust non-defaulted field; Python registration refusal), not an auditor. The auditor survives only to enumerate the drain progress and to hold the CLOSED opt-out list — with its retirement named (it retires when `R(unenrolled-sugars)=0` and the type mechanism alone holds the line).

## Instruments

### Instrument A — enrollment auditor (drain enumerator)
Enumerate every registrable sugar in each kit's catalog and report `R(unenrolled-sugars)` = sugars with neither a witness pair nor a pinned `NotVerdictBearing`. Print each offender with its module/claim location. Red-first: the flip makes this the offender list. **Law-8 annotation: justification (b) — watches drain progress the type mechanism already forces; retires when `R=0` (the non-defaulted field / registration refusal alone holds the line thereafter).** It also holds the CLOSED opt-out list (the one thing types can't see: "this sugar is legitimately non-verdict-bearing").

### Instrument B — the triple harness (the one dumb test)
The parametrized `foreach`-catalog test. Reports `R(witness-triples-failing)` = pairs where any of {sugar-fired, proofir-emitted, verdict} fails. **Law-8 annotation: justification (b), permanent — the solver verdict is irreducible (types cannot encode SAT/UNSAT), exactly as the vocab campaign's Instrument C. It climbs one rung: a sugar cannot be ENROLLED without a witness the harness runs, so "enrolled but unwitnessed" is unrepresentable; only "wrong witness" remains, which the solver judges.**

### Instrument C — non-circularity (assertion 1) sub-check
Within the harness, assert the recognized-claim attribution names the owning sugar. Reports `R(witnesses-not-dispatching-to-owner)`. Red-first: point a sugar's witness at source another sugar lifts → red. **Law-8 annotation: justification (b) — recognizer drift is a runtime fact types cannot see; no retirement (it is the guard against catalog rot).**

## Ratchet vector

| Signal | Starts as | Target |
|---|---|---|
| `R(unenrolled-sugars)` — Python | S2 flip lands RED (~58). | 0 after the Python drain. |
| `R(unenrolled-sugars)` — Rust | one-law flip (S7) sets all 214 claims to `SugarWitnesses::Pending` (compile ships, gate counts each `Pending` red); drained by family — Stmt+Item (S8), Expr family batches (S9). | 0 (no `Pending`) at close (S10); `Pending` forbidden thereafter. |
| `R(witness-triples-failing)` | S1 measures (harness over the seed set). | 0 at each phase close. |
| `R(witnesses-not-dispatching-to-owner)` | S1 measures. | 0 (assertion-1 holds catalog-wide). |
| `R(decorative-verdict-files)` (#3272) | ~17 files with `_formula_status`. | 0 (migrated onto the real-solver harness). |
| `R(hand-coverage-registry)` | 1 (`test_sugar_coverage_registry.py`). | 0 (enrollment replaces it). |
| `R(sugars-opted-out)` | pinned CLOSED set (comment/alias/support). | stays pinned; growth is a reasoned floor move. |

## Slices

### Slice 0 — Plan PR
Land this document. Post the #3272 and vocab-campaign cross-link comments.
Exit: merged as "Part 1 of the sugar-witness campaign (plan)".

### Slice 1 — Instruments + the triple harness (Python), RED/measuring
Add Instrument A (enrollment auditor over `registered_claims()`), Instrument B (the parametrized triple harness), and Instrument C (non-circularity). Centralize `_run_lift_rpc` into ONE shared harness helper (it is copy-pasted across ~17 files today). Wire the harness's verdict to the REAL `sugar-ir-compiler-smt-lib` path (the same one PR #3269's witness harness uses), NOT `_formula_status`. Run against the current seed set (the sugars whose decorative twins already exist) and pin the vectors.
- **#3269 (the RPC-driven witness harness seed) is MERGED (main `01264a8a9`) — dependency SATISFIED.** Seed the harness from the on-main mechanism.
- Red-first: the harness over a sugar with a deliberately-wrong (lying source that is actually true) witness reds on the verdict; a witness pointing at another sugar's source reds on assertion-1.
- Bad-twins: (a) truthful source → SAT + correct sugar attribution; (b) lying source → UNSAT; (c) mis-attributed witness → assertion-1 red.
Exit: three instruments measuring; `_run_lift_rpc` centralized; the verdict is a real solve; baselines pinned.

### Slice 2 — The witness surface + enrollment flip (Python), RED
Add `witnesses()` (returning `WitnessPair | NotVerdictBearing`) to `Sugar` and enforce it at the `__init_subclass__` `role=` gate (`sugar_base.py:39`) — a registrable leaf without it raises `TypeError` at import, reddening the whole catalog. Define the CLOSED, PINNED opt-out set (`CommentSugar`, `AliasSugar`, Support/plumbing). Land RED with the full ~58-sugar offender list; enroll NOTHING yet beyond the opt-out set.
- Red-first: `default_catalog()` import raises for every unenrolled leaf; Instrument A pins `R(unenrolled-sugars)` at the full count.
- Bad-twin: a leaf declaring neither witness nor opt-out reds; a leaf on the opt-out list passes.
Exit: enrollment is enforced at registration; `R(unenrolled-sugars)` pinned at ~58; the opt-out set is closed and pinned.

### Slice 3 — Drain batch 1 (Python): assertion/verdict-bearing sugars, reuse the decorative twins
Enroll the sugars whose `good`/`bad` decorative twins already exist (the ~17 `*_sat_unsat`/inline-verdict files), MOVING those twins onto `witnesses()` and deleting the decorative `_formula_status` files (#3272). Each enrolled sugar's triple passes through the real harness.
- Bad-twins: per sugar, its truthful → SAT, lying → UNSAT, and assertion-1 names it.
- Ratchet: `R(unenrolled-sugars)` down by the batch; `R(decorative-verdict-files)` down by the migrated files.
Exit: the decorative-verdict files are gone; their sugars are enrolled through the real solver.

### Slice 4 — Drain batch 2 (Python): remaining statement/term sugars
Enroll the remaining registrable sugars with fresh minimal witness pairs. Sugars that genuinely cannot bear a verdict join the pinned opt-out set with a stated reason (reviewed, not defaulted).
- Ratchet: `R(unenrolled-sugars)` → 0 (Python).
Exit: every Python sugar testifies or is pinned non-verdict-bearing.

### Slice 5 — Python close: arm the gate; retire the coverage registry
Arm Instrument B as a GATE (`R(witness-triples-failing)=0` catch-all over the whole catalog). Delete `tests/test_sugar_coverage_registry.py` (enrollment replaces the hand table) and remove the vocab campaign's Instrument C coverage counter's now-redundant role (registration = enrollment). Flip Instrument A from counter to a stable-zero gate.
- Red-first: the gate expects zero; a planted unenrolled sugar reds. Structural grep: `rg -n '_formula_status|COVERAGE\s*[:=]' tests` → no production hits.
Exit: `R(hand-coverage-registry)=0`; the Python triple is an armed catalog-wide gate.

### Slice 6 — Instruments + harness (Rust)
Add the Rust triple harness (`tests/sugar_witness_triple.rs`) reusing `lift_file` + `z3_verdict` + `inv_json`; add the `pub` claim-`name`/recognized accessor for assertion (1). Measure the seed set (the ~26 existing twin tests) and pin the vectors. Assertion-2 targets `sugar_ir_symbolic::ContractDecl` (upgrade to `sugar_ir_types::Declaration` at #3240).
Exit: Rust harness measuring; assertion-1 reachable; baselines pinned.

**Rust enrollment is ONE HARD-LAW FLIP then a STAGED DRAIN (T Savo).** The flip lands once (all 214 claims); the drain stages by claim family for review signal.

### Slice 7 — The one-law flip: non-defaulted `witnesses` on all three structs + `Pending` staging, RED
Define `SugarWitnesses::{Pair(truthful, lying), NotVerdictBearing(reason), Pending}` and add the non-defaulted `witnesses: SugarWitnesses` field to ALL THREE claim structs (`StmtSugarClaim`/`ItemSugarClaim`/`ExprSugarClaim`, `claim.rs`) AT ONCE. rustc reds all 214 `const` literals across `catalog.rs` (STMT 5 + ITEM 5 + EXPR 204). Set every literal to `SugarWitnesses::Pending` so the crate compiles and the tree ships; the auditor/gate counts every `Pending` as a RED row (`R(unenrolled-sugars)` = `Pending` count). `Pending` is a staging device (precedent: the ProofIR-vocab Slice-3 return-type-flip staging), drained to zero and forbidden at close — NOT an escape hatch. Define the `NotVerdictBearing(reason)` opt-out variant here (floor-marker-derived, per the opt-out mechanics).
- Red-first: the field addition reds all 214 literals; setting them to `Pending` ships the tree with the gate pinned at 214 red.
- Bad-twin: a claim literal without the field → compile error (the one-law flip); a `Pending` literal → compiles but counts red.
Exit: the field/type exist on all three structs; `R(unenrolled-sugars)` Rust pinned at 214 (`Pending`); tree ships.

### Slice 8 — Drain the small families: `StmtSugarClaim` (5) + `ItemSugarClaim` (5)
Replace `Pending` with real `Pair`/`NotVerdictBearing` for the two small families (`STMT_CLAIMS:265`, `ITEM_CLAIMS:257`). Two families, reviewable as one unit; each triple passes the Slice-6 harness (truthful SAT / lying UNSAT + assertion-1).
Exit: Stmt + Item drained; `R(unenrolled-sugars)` down by 10; only `ExprSugarClaim` `Pending` remains.

### Slice 9 — Drain `ExprSugarClaim` (204) by family/role batches
Replace `Pending` with real witnesses for `EXPR_CLAIMS` (`catalog.rs:50`), STAGED BY EXPR FAMILY/ROLE (each drain PR = one family's witnesses, reviewable as a unit — the stated review-signal rationale), reusing the ~26 existing `assertion_lift.rs` twins as seed witnesses; genuine non-verdict claims take `NotVerdictBearing`. The gate stays red (nonzero `Pending`) until the last family drains.
- Red-first: `R(unenrolled-sugars)` = remaining `Pending`; each family batch ratchets it down.
Exit: `R(unenrolled-sugars)` Rust → 0 (no `Pending`) across all three structs.

### Slice 10 — Rust close: arm the gate (forbid `Pending`); disambiguate; upgrade assertion-2
Arm the Rust triple as a catalog-wide gate AND forbid `SugarWitnesses::Pending` (a lint/gate row: any remaining or newly-introduced `Pending` is a hard red — the staging placeholder is retired, so enrollment is truly total). Disambiguate the `sugar-lift-rust-cargo-test-witness` naming collision in docs/comments (source-witness vs cargo-test witness). Note the assertion-2 upgrade path: when #3240 lands the `sugar_ir_types::Declaration` typed surface, the harness's "ProofIR came back" assertion upgrades from `ContractDecl` to the typed node — a one-line target change, not a re-architecture.
Exit: both kits' triples are armed catalog-wide gates; `Pending` is forbidden; the composition law is executable.

## Future phase (planned, NOT in these slices)

`near_miss()` — each sugar declaring the BORDER cases just outside its territory (discrimination witnesses reverse-engineered from a declared shape), so the catalog proves not just "my example dispatches to me" but "the case one step outside does NOT". This needs the shape-declaration layer designed first (a sugar declares its recognized shape; `mine()`/`near_miss()` are generated from it). Plan it as a sibling campaign after this one lands mine-pair + triple + enrollment.

## Retirement table

| Retired artifact | Replaced by | Slice |
|---|---|---|
| `tests/test_sugar_coverage_registry.py` (hand name→file table) | enrollment (a sugar owns its witness) | 5 |
| decorative `*_sat_unsat` / `_formula_status` files (#3272) | the real-solver triple harness | 3 (Python), migrated |
| vocab campaign Instrument C coverage counter (at maturity) | registration = enrollment (sugar-keyed) | 5 |
| Rust `assertion_lift.rs` ad-hoc twin tests (decls[0]-keyed) | the catalog `foreach` triple w/ assertion-1 | 6-9 |

## Sequencing with sibling campaigns

- **ProofIR-vocab campaign (#3232-#3240).** Python assertion-2 ("proofir came back") UPGRADES as the vocab graph gets attributed: today `doc["ir"]` rows; at #3269 (S2, MERGED — main `01264a8a9`) the spine node classes; at S4+ the fully-attributed graph. Do NOT block on it — the harness asserts against whatever typed shape is current and tightens as the vocab lands. Rust assertion-2 upgrades at #3240. This campaign is the vocab campaign's capstone consumer: it is where "sugar owns the example, ProofIR owns the verdict" becomes one test.
- **PR #3269 (vocab S2) — the harness seed, NOW MERGED (main `01264a8a9`).** Python Slice 1's dependency is SATISFIED; the RPC-driven witness mechanism is on main and IS the seed the campaign generalizes from 3 node classes to all sugars.
- **irterm-boundary #3198.** Gates the Rust assertion-2 upgrade only (via #3240), not the Rust enrollment/drain — the Rust phase can proceed against `ContractDecl` before #3198.

## Anti-goals

- **No empty-default opt-out.** A sugar declares a witness OR a pinned `NotVerdictBearing`; silence is the side door and is forbidden.
- **No fake verdict.** The triple's verdict is the real ir compiler + solver; `_formula_status` string comparison is deleted, not wrapped.
- **No skipping assertion (1).** A witness that produces a verdict without proving it dispatched to its own sugar does not count.
- **No `near_miss` in the first slices.** Border discrimination is the later shape-declaration phase.
- **No conflation with the cargo-test witness.** This campaign's artifact is a sugar SOURCE-witness pair, distinct from `sugar-lift-rust-cargo-test-witness`.
- **No hand-maintained catalog of the tested set.** Enrollment IS the catalog; do not reintroduce a `COVERAGE`-style table.

## Campaign closure

1. Every registrable sugar in both kits owns a truthful/lying witness pair OR a pinned `NotVerdictBearing(reason)`; `R(unenrolled-sugars)=0` both kits, enforced by the type mechanism (Rust non-defaulted field, Python registration refusal).
2. The one dumb test foreach-es each catalog and asserts the triple through the production pipeline; `R(witness-triples-failing)=0` as an armed gate.
3. Assertion (1) holds catalog-wide; `R(witnesses-not-dispatching-to-owner)=0` — ownership is non-circular.
4. The verdict is the real solver; `R(decorative-verdict-files)=0` (#3272 subsumed).
5. `test_sugar_coverage_registry.py` is deleted; enrollment replaces it; `R(hand-coverage-registry)=0`.
6. The opt-out set is closed and pinned; every entry carries a stated reason.
7. Both kits' suites pass; the composition — sugar owns the example, ProofIR owns the verdict — is a single executable law.
