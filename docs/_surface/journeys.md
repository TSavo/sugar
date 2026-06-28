# Sugar End-to-End User Journeys

Sugar is a correctness system where vendor code and assertions flow through a lift→verify→proof pipeline, producing recomputable behavior proofs and consumer-side composition. This document maps the concrete workflow patterns.

---

## 1. Vendor Workflow: Ship a `.proof` (Lift → Mint → Witness)

**What:** A library maintainer lifts their code and tests into a signed `.proof` artifact.

**Flow:**
1. Library has source code and tests written in native language (Python, Java, Rust, etc.)
2. Run `sugar mint --project <path>` (driven by configured lift plugins)
3. Lift plugins read language-specific evidence (tests, assertions, decorators, annotations)
4. Emit canonical ProofIR for each contract discovered
5. Sign the proof envelope with ed25519 (kit mints signed MemCIDs per claim)
6. Optionally run `sugar verify` to gate before shipping (real discharge via solver + witness)
7. Ship `.proof` file + witness package (separately deployed audit material)

**Examples:**
- `examples/numpy-vendor/run.sh` — lifts all 2909 numpy functions, no code changes
- `examples/signup-service/prove.sh` — Maven-driven: proves every transitive dependency from source

**Key Commands:**
- `sugar mint --project <path>` — dispatch configured lift plugins, write `.proof`
- `sugar verify` — end-to-end gate: lift, discharge, witness, emit signed receipt

**Existing Docs:**
- `examples/numpy-vendor/README.md` — "ship a `.proof` + a witness package"
- `examples/signup-service/README.md` — supply chain: prove each dependency
- `README.md` §"Ship a `.proof` for a whole library, no shim"

---

## 2. Consumer Workflow: Verify Inherited Correctness (Prove → Compose → Inherit)

**What:** A consumer loads vendor `.proof` files and verifies they still hold in their environment.

**Flow:**
1. Add vendor `.proof` to `.sugar/imports/` directory
2. Write local assertions about vendor code (tests that use vendor APIs)
3. Run `sugar prove --project .`
4. Prover loads vendor proofs, enumerates callsites, conjoins same-named contracts
5. Solver (z3) checks consistency across vendor + consumer contracts
6. Recomputes witness CIDs: vendor's oracle resolves bodies, CLI verifies them
7. Report: contracts are Dug (discharged), Hit (obstacle), refuted (UNSAT), or unclassified

**Inheritance:** If consumer asserts `np.add(2,3) == 6` but vendor proved `== 5`, z3 finds UNSAT and refuses with UNSAT certificate (proof that assumption is false). This is the "consumer demo" pattern: your test goes RED because you wrote a fact that cannot exist in the library's universe.

**Key Commands:**
- `sugar prove --project .` — six-stage verifier: load, enumerate, conjoin, solve, witness
- Files in `.sugar/imports/` are loaded as inherited proofs

**Existing Docs:**
- `README.md` §"The capstone: correctness is inheritable"
- `implementations/python/sugar-lift-py-tests/tests/test_inheritance_e2e.py` — parametrized test
- `implementations/rust/sugar-verifier/src/consistency.rs` — cross_proof_same_named_contracts_are_conjoined

---

## 3. Upgrade Workflow: Sugar Diff (Version → Behavior → Dragons)

**What:** When a dependency is updated, compare old vs new behavior and report coupling impact.

**Flow:**
1. Lift and mint old version of library: `sugar mint` → produces `.proof`
2. Lift and mint new version of library: `sugar mint` → produces new `.proof`
3. Run `sugar diff old.proof new.proof`
4. Diff classifier: each contract is `held` (same), `renamed` (moved name), `new` (added), or `lost` (removed)
5. Report: cohesion surface (vendor's change) + coupling (what you depend on) = blast radius
6. Exit code nonzero if behavior moved or surface dropped

**Pre-commit gate (Python):** `sugar-check check --rev <git-rev>` in `.pre-commit-hooks.yaml` fails if version bump is dishonest (behavior changed but semver did not reflect it).

**Decision loop:** Read the dragons report; either update code to handle new behavior, pin to old version, or accept the risk and bump version honestly.

**Key Commands:**
- `sugar diff <a.proof> <b.proof>` — behavior-based diff, not text
- `sugar diff --frozen` — fail if any behavior delta under pinned dependency
- `sugar diff --require <major|minor|patch>` — enforce honest semver

**Tooling:**
- `sugar-check` (Python pre-commit hook) — behavioral semver enforcement at commit time
- `cargo sugar` (Rust wrapper) — diff integration for Cargo workflows

**Existing Docs:**
- `README.md` §"Why it matters: the version lied, the behavior moved, Sugar saw it"
- `README.md` §"What `sugar diff` measures: your coupling, their cohesion"
- `tools/sugar-check/README.md` — behavioral semver for Python packages

---

## 4. Lift Adapter Workflow (Library → AST → IR → Conformance)

**What:** Add support for a new annotation library or assertion framework.

**Flow:**
1. **Pick library** — select annotation source (pydantic, Zod, Bean Validation, proptest, etc.)
   - Must be widely deployed, have structured annotations, canonicalizable semantics
   - Decide coverage tier (Tier A=all, Tier B=80%, Tier C=cherry-picked)
2. **Walk AST** — implement language-specific AST walker for the annotation library
   - Parse source code in target language
   - Recognize annotation patterns (decorators, attributes, comment blocks)
   - Extract constraint expressions and parameters
3. **Emit canonical IR** — transform recognized annotations into deterministic ProofIR
   - Same logical constraint must emit identical bytes regardless of source variation
   - Normalization ensures `@Min(0) @Max(100)` and `@Range(0, 100)` lift to same IR
4. **Conformance test** — run cross-language conformance harness
   - Feed canonical formula to Python, Java, Rust kits
   - Verify all kits emit identical bytes
   - Harness runs via `make conformance`
5. **Publish** — document coverage, add to kit manifest, open PR

**Output:** New crate/module in `implementations/<language>/sugar-lift-<library>` that the kit's lift plugin calls.

**Key Files:**
- `implementations/rust/sugar-lift-json-schema/src/lib.rs` — example
- `implementations/python/sugar-lift-pydantic/src/sugar_lift_pydantic/` — example
- `implementations/java/sugar-lift-java-beans/src/` — example

**Existing Docs:**
- `docs/contributing/writing-a-lift-adapter/01-pick-a-source-library.md` — library selection rubric
- `docs/contributing/writing-a-lift-adapter/02-walk-the-AST.md` — AST patterns
- `docs/contributing/writing-a-lift-adapter/03-emit-canonical-IR.md` — IR emission
- `docs/contributing/writing-a-lift-adapter/04-conformance-test.md` — conformance harness
- `docs/contributing/writing-a-lift-adapter/05-publishing.md` — PR process

---

## 5. Developer Workflow: Pre-commit Enforcement (sugar-check)

**What:** Enforce honest semver via behavioral diff at commit time.

**Flow:**
1. Add `sugar-check` to `.pre-commit-hooks.yaml` in your Python project
2. On `git commit`, pre-commit hook runs `sugar-check check --rev main`
3. sugar-check lifts working tree and baseline (main) into behavior contracts (pytest assertions)
4. Diffs behavior CIDs (reformat-stable: refactor keeps CID, behavior change moves it)
5. Checks version bump against the diff (if semver is dishonest, hook fails)
6. Commit is blocked if behavior changed but version number does not reflect it

**Modes:**
- `sugar-check check --rev <git-rev>` — check against baseline revision
- `sugar-check check --require none|minor|major` — enforce minimum bump
- `sugar-check diff <a> <b>` — passthrough to `sugar diff`

**Existing Docs:**
- `tools/sugar-check/README.md` — pip wedge for behavioral semver
- README.md §"Honest scope: this works today as cargo sugar (Rust) and sugar-check (Python pre-commit hook)"

---

## 6. Lift Plugin Architecture (Config → Manifest → RPC)

**What:** Framework for registering and dispatching lift adapters to the CLI.

**Flow:**
1. Create `.sugar/config.toml` in project root:
   - List lift plugins by name and surface
   - Configure solvers (z3, etc.)
2. Create `.sugar/lift/<plugin>/<plugin>/manifest.toml`:
   - Command to spawn plugin (e.g., python RPC server)
   - Working directory
   - Capabilities (authoring_surfaces, ir_version)
3. Run `sugar mint --project .`
4. CLI loads config, spawns each plugin subprocess
5. CLI sends JSON-RPC requests: `{"method": "initialize"} → {"method": "lift"} → {"method": "shutdown"}`
6. Plugin walks source, emits ProofIR, sends back via JSON-RPC
7. CLI envelopes IR into `.proof`, signs it
8. Witness flow (if configured): resolve_witness_command runs tests, CLI blake3s results

**Example Manifests:**
- `examples/numpy-vendor/run.sh` lines 64-84 — python-bind-lift + python-pytest-witness
- `examples/signup-service/prove.sh` lines 45-75 — java-test-assertions

**Existing Docs:**
- `docs/contributing/writing-a-kit/` — kit structure and protocol requirements
- `README.md` §"The shape: kits own language, the CLI owns proof"

---

## 7. Consumer Demo Pattern: Test Goes Red Before It Runs

**What:** Show that composition catches impossibilities at the verifier stage, not at test runtime.

**Flow:**
1. Vendor mints `.proof` with contract `np.add(2,3) == 5`
2. Consumer stages vendor `.proof` in `.sugar/imports/`
3. Consumer writes test: `assert np.add(2,3) == 6`
4. Consumer runs `sugar prove --project .`
5. Prover conjoins consumer's `== 6` with vendor's `== 5`
6. Solver finds the conjunction UNSAT
7. **Verifier refuses before test runner ever invokes the code**
8. Exit nonzero; diagnosis: "inherited vendor contract contradicts local assertion"

**This catches the moment of incompatibility at the boundary, not at the seat of execution.**

**Embodied by:**
- Parametrized test: `test_inheritance_e2e.py` with `consumer-agrees-PROVEN` and `consumer-contradicts-REFUSED` cases
- Unit test: `cross_proof_same_named_contracts_are_conjoined` in `sugar-verifier/src/consistency.rs`

**Existing Docs:**
- `README.md` §"The capstone: correctness is inheritable" (consumer contradicts case)

---

## 8. Self-Application Workflow (Sugar Proves Sugar)

**What:** Sugar proves its own assertions and tests, producing a self-referential `.proof`.

**Flow:**
1. Configure Sugar's lift manifest pointing at Sugar's own source + tests
2. Run `sugar prove --project .` from Sugar repo root
3. Lifter walks Sugar's own assertion code
4. Emits ProofIR for Sugar's contracts
5. Solver discharges obligations over Sugar's implementation
6. Recompute witnesses: Sugar's own test harness runs, CLI blake3s results
7. Output: `.proof` file containing Sugar's sworn behavior
8. Deterministic scoreboard (`sugar self-check`) tracks coverage metrics

**Invariants:**
- `false_discharges == 0` (security: no hollow proofs)
- `silent == 0` (completeness: every statement is classified)
- All vectors pinned (cohesion: no unspecified dependencies)

**Current Metrics (as of 2026-06-10):**
- Rust 1.96.0 coretests: 6377 asserts, 0 silent drops, 74.8% discharged
- Rust tokio: 42.5% discharged (macro expander + panic-locus improvements)
- Python grammar campaign: 56.64% coverage across 11 families

**Existing Docs:**
- `docs/self-application/GOAL-sugar-proves-sugar.md` — north star goal
- `docs/self-application/2026-05-28-snake-eats-tail.md` — first run milestone
- `docs/self-application/ASSERTION-ACCOUNTING-LEDGER.md` — total accounting audit
- `docs/self-application/KIT-SETUP-AND-SELF-APPLICATION.md` — runbook

---

## 9. Recognize & Materialize Workflow (Binding Reflection)

**What:** Scan source for sugar binding templates and emit/materialize concept citations.

**Flow:**

### Recognize (Source → Tags)
1. Run `sugar recognize --project <path>`
2. Scanner walks source for shapes matching published sugar binding templates
3. Emits binding tags at matched callsites
4. Output: annotated source with `@sugar.binding(concept=..., cid=...)` citations
5. **Reverse direction of materialize** — reads proof bindings, writes source annotations

### Materialize (Concepts → Source)
1. Run `sugar materialize --project <path>`
2. Resolver loads `.proof` envelope with ConceptBinding mementos
3. For each binding, resolves concept CID to its realization in target language
4. Emits realized source code with concept instances inlined
5. Example: `concept:optional` materializes to `Option<T>` (Rust), `Optional<T>` (Java), `T | None` (Python)

**Use Cases:**
- Auto-annotate source with verifiable binding citations
- Realize abstract concepts into language-specific code
- Pipeline: `recognize → bind → materialize` (paper 20 §9 eight-verb pipeline)

**Existing Docs:**
- `README.md` §"sugar recognize" — description in CLI command list
- `README.md` §"sugar materialize" — description in CLI command list

---

## 10. Cross-Language Composition Workflow (Federate → Compose → Bridge)

**What:** Prove properties that span multiple languages and libraries.

**Flow:**
1. Vendor A (Rust) ships `.proof` with contract `tokio::Mutex::lock() → Option<Guard>`
2. Vendor B (Python) ships `.proof` with consumer code that calls async-await over tokio
3. Consumer (TypeScript) wants to compose both in a unified proof
4. Consumer runs `sugar compose` with both proofs
5. Composition engine:
   - Loads both `.proof` envelopes
   - Extracts contracts by callsite + CID
   - Bridges language boundaries (tokio Rust ↔ asyncio Python ↔ Promise TypeScript)
   - Conjoins matching contracts via concept CID
   - Solves unified FOL formula
6. Report: cross-language obligations are satisfied or unsatisfiable

**Concept Bridge:** Each `(concept, language)` pair has a content-addressed realization; composition uses the concept hub as the common reference point, not byte-for-byte API matching.

**Existing Docs:**
- `README.md` §"The shape: kits own language, the CLI owns proof"
- `protocol/specs/2026-05-09-contract-composition-protocol.md` — formal spec
- `implementations/rust/sugar-cli/src/cmd_compose.rs` — JSON-RPC subprocess transport

---

## 11. Kit Setup & Conformance Workflow (Build → Test → Ship)

**What:** Build a kit for a new host language, test it conformantly, ship it.

**Flow:**
1. **Conformance first** (step 1) — byte-determinism and cross-kit agreement
   - Same canonical formula → every kit emits identical bytes
   - `make conformance` runs cross-language fixtures
2. **Canonicalizer** (step 2) — deterministic IR output
   - Input: language-native evidence (tests, annotations, etc.)
   - Output: canonical bytes (CBOR, deterministic ordering)
3. **Claim envelope** (step 3) — transport for contracts
   - Schema for carrying claim metadata (names, loci, signatures)
4. **Proof envelope** (step 4) — bundle mementos into signed `.proof`
   - Signed wrapper around claim/source/witness/implication mementos
5. **Self-contracts** (step 5) — kit proves its own correctness
   - Kit's code becomes the test surface
   - Lantern test: kit discharges its own contracts
6. **Bridge IR** (step 6) — language-to-language mapping
   - How language-specific types map to ProofIR sorts
7. **Contract CID vs Attestation CID** (step 7) — semantic identity
   - Vendor's contract CID ≠ consumer's attestation CID
   - Bridging mechanism resolves the semantic boundary
8. **Version chains** (step 8) — upgrade and migration
   - Track protocol version, kit version, adapter versions
   - Enable backward compatibility and migration paths

**Exit Criteria:**
- `make conformance` passes (bytes agree across kits)
- `make ci` runs no format/clippy/lint (those are the harness, not the kit)
- Self-contracts discharge and witness reproducibly
- Kit ships as a conformant federation seat

**Existing Docs:**
- `docs/contributing/writing-a-kit/` (8 sequential steps)
  - 01-conformance-first.md
  - 02-canonicalizer.md
  - 03-claim-envelope.md
  - 04-proof-envelope.md
  - 05-self-contracts.md
  - 06-bridge-IR.md
  - 07-contract-cid-vs-attestation-cid.md
  - 08-version-chains.md

---

## 12. Release Gate Workflow (Audit → Publish → Distribute)

**What:** Gate a release on proof correctness and semantic honesty.

**Flow:**
1. Maintainer bumps version and prepares release
2. Run `sugar diff <previous-proof> <current-proof>`
3. Diff report shows: held / renamed / new / lost behaviors
4. Maintainer compares diff against semver bump claim
5. If dishonest (behavior lost but semver is minor), gate fails
6. Resolve dishonesty: either update version or revert behavior change
7. Run `sugar verify` to gate: all proofs discharge, all witnesses recompute
8. Emit signed release receipt (release-gate exit artifact)
9. Publish `.proof` + witness package + receipt to registry
10. Consumer can verify release integrity before pulling the code

**Gating Rules:**
- `--frozen`: any behavior delta under pinned version fails
- `--require <major|minor|patch>`: enforce minimum bump
- No contradictory proofs allowed in same binary

**Existing Docs:**
- `README.md` §"Why it matters: the version lied, the behavior moved"
- `docs/contributing/release-process.md`

---

## Open Questions

1. **Recognize tooling maturity:** How complete is the `recognize` implementation for production use? What annotation vocabularies does it currently handle?

2. **Materialize language coverage:** Which target languages have realization support? Is the pipeline (recognize → bind → materialize) fully tested end-to-end?

3. **Concept hub population:** What is the current size and composition of the concept CID hub? How many `(concept, language)` cells are populated vs. planned?

4. **Witness oracle trust model:** The Rust CLI blake3s witness bodies untrusted; how is drift (honest re-run that differs) distinguished operationally from broken oracle (wrong content for CID)? Is there a diagnostic format?

5. **Cross-language bridge scope:** What are the current limitations on bridge-able abstractions? Do all 12+ language pairs currently compose, or only a subset?

6. **Kit self-application:** Are all shipped kits (Python, Java, Rust) at parity on self-contracts discharge? Or do some kits not yet have self-contracts implemented?

7. **Pre-commit sugar-check adoption:** Is sugar-check available on PyPI? What is the current adoption footprint?

8. **Lift adapter registry:** Is there a canonical list of all shipping adapters per language? Where does new adapter work surface for discovery?

9. **Conform harness CI integration:** Do PR gates currently enforce `make conformance` on every kit change, or is that still a manual check?

10. **`.proof` versioning:** What is the current `.proof` schema version? How are migrations handled as the envelope format evolves?

---

## References

- **README.md** — Product overview, core concepts, demos
- **docs/contributing/** — On-ramps for contributors
- **docs/papers/** — Sustained arguments about the substrate thesis (26 papers)
- **docs/self-application/** — Self-application roadmap and scoreboard
- **examples/** — Runnable end-to-end demonstrations
- **implementations/rust/sugar-cli/src/main.rs** — Authoritative CLI command reference
- **protocol/specs/** — Formal protocol specifications
