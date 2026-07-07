# Examples, Showcases & Marquee Proofs

This is the wall of real-library correctness proofs and runnable demonstrations. Each example shows Sugar proving a concrete piece of a real library, across languages and proof shapes. Most examples include both a `good` suite (contracts that should discharge) and a `bad` suite (contradictory twins that should be refused).

## Core Standard Library Proofs

### rust-coretests-report
**Summary:** The honest ledger of Rust std-core assertion coverage. Walks the pinned Rust 1.96.0 `library/coretests` corpus, lifts all assertions, and accounts for every one (warranted, unresolved, refused, refuted, support).

- **Key paths:** `/examples/rust-coretests-report/` (run.sh, README.md, corpus/)
- **Audience:** End-user, contributor (measuring stick for Rust lift quality)
- **Doc priority:** P0 (flagship coverage report)
- **Existing docs:** `./examples/rust-coretests-report/README.md`

### std-core-showcase
**Summary:** Point-wise scalar correctness proofs on Rust core: `cmp::min_by`, `size_of::<T>()`, `Duration::div_duration_f64`, `Option::test_and`, `TypeId`, pointer-index predicates, const-path integer indexing, and 160+ other vendor rows.

- **Key paths:** `/examples/std-core-showcase/` (run.sh, README.md)
- **Audience:** End-user, contributor (Rust std correctness demonstration)
- **Doc priority:** P0 (major library logo)
- **Existing docs:** `./examples/std-core-showcase/README.md`

### std-core-bodyguard-precondition
**Summary:** Precondition guard lifting from Rust core: function bodies that raise on invalid input (e.g., `if x < 2 or x > 36: raise`), lifted as flat FOL preconditions.

- **Key paths:** `/examples/std-core-bodyguard-precondition/` (run.sh, README.md)
- **Audience:** Contributor (guard-shape technique)
- **Doc priority:** P1 (demonstrates flat guard lifting)
- **Existing docs:** `./examples/std-core-bodyguard-precondition/README.md`

### std-core-string-predicates
**Summary:** String and char predicate correctness: direct call-result string equality, ASCII char predicates, and string method-chain rows from `core::fmt` and `alloc` tests.

- **Key paths:** `/examples/std-core-string-predicates/` (run.sh, README.md)
- **Audience:** Contributor (string/char predicate coverage)
- **Doc priority:** P1 (residual closure)
- **Existing docs:** `./examples/std-core-string-predicates/README.md`

## Rust Library Logos

### serde-json-showcase
**Summary:** Real Rust library proof: `serde_json 1.0.150` serialization correctness. Lifts vendor test rows (`test_write_null`, `test_write_u64`, `test_write_str`, `test_write_bool`), good suite discharges, bad contradiction twin is UNSAT.

- **Key paths:** `/examples/serde-json-showcase/` (good/, bad/, run.sh, README.md)
- **Audience:** End-user (first Rust library logo)
- **Doc priority:** P0 (flagship library)
- **Existing docs:** `./examples/serde-json-showcase/README.md`

### regex-showcase
**Summary:** `regex 1.12.4` correctness: point-wise invalid-regex rejection rows and valid-regex acceptance. Good suite passes vendor tests; bad suite contains contradiction on `Regex::new("(((?x)))").is_ok()`.

- **Key paths:** `/examples/regex-showcase/` (good/, bad/, run.sh, README.md)
- **Audience:** End-user (library proof)
- **Doc priority:** P0 (major library)
- **Existing docs:** `./examples/regex-showcase/README.md`

### rust-regex-membership
**Summary:** Regex-match lifted to z3 string theory. `re.is_match(s)` becomes `str.in_re(s, R)` with the pattern as a RegLan term. Compositional operands (const patterns, `concat!`, format!) desugar through child Sugars.

- **Key paths:** `/examples/rust-regex-membership/` (good/, bad/, nonregular/, run.sh, README.md)
- **Audience:** Contributor (regex-theory lowering, composition frontier)
- **Doc priority:** P1 (advanced lifting)
- **Existing docs:** `./examples/rust-regex-membership/README.md`

### base64-showcase
**Summary:** Base64 encoding/decoding proof of concept (vendor TBD). Demonstrates lift shape on encoding library, with good and bad suites.

- **Key paths:** `/examples/base64-showcase/` (good/, bad/, run.sh)
- **Audience:** Contributor (encoding library template)
- **Doc priority:** P2 (prototype)
- **Existing docs:** none

### bitflags-showcase
**Summary:** Bit-flag manipulation correctness from the `bitflags` crate. Point-wise flag-set operations (union, intersection, subtraction).

- **Key paths:** `/examples/bitflags-showcase/` (good/, bad/, run.sh)
- **Audience:** Contributor (bit-manipulation proof)
- **Doc priority:** P2 (prototype)
- **Existing docs:** none

### itertools-showcase
**Summary:** Iterator-combinator correctness from the `itertools` crate. Collection and transformation rows.

- **Key paths:** `/examples/itertools-showcase/` (good/, bad/, run.sh)
- **Audience:** Contributor (iterator template)
- **Doc priority:** P2 (prototype)
- **Existing docs:** none

### num-integer-showcase
**Summary:** Integer arithmetic and bit manipulation from the `num-integer` crate.

- **Key paths:** `/examples/num-integer-showcase/` (good/, bad/, run.sh)
- **Audience:** Contributor (integer-math proof)
- **Doc priority:** P2 (prototype)
- **Existing docs:** none

### semver-showcase
**Summary:** Semantic versioning comparison correctness from the `semver` crate.

- **Key paths:** `/examples/semver-showcase/` (good/, bad/, run.sh)
- **Audience:** Contributor (version-comparison proof)
- **Doc priority:** P2 (prototype)
- **Existing docs:** none

### url-showcase
**Summary:** URL parsing and formatting correctness.

- **Key paths:** `/examples/url-showcase/` (good/, bad/, run.sh)
- **Audience:** Contributor (URI/URL proof)
- **Doc priority:** P2 (prototype)
- **Existing docs:** none

### uuid-showcase
**Summary:** UUID generation and formatting correctness.

- **Key paths:** `/examples/uuid-showcase/` (good/, bad/, run.sh)
- **Audience:** Contributor (UUID proof)
- **Doc priority:** P2 (prototype)
- **Existing docs:** none

### polars-showcase
**Summary:** Polars (Rust DataFrame library) scalar correctness. Mirrors numpy-showcase for Rust: one real scalar assertion lifted on consistency and witness axes.

- **Key paths:** `/examples/polars-showcase/` (run.sh, README.md)
- **Audience:** End-user (dataframe library proof)
- **Doc priority:** P1 (data-science logo)
- **Existing docs:** `./examples/polars-showcase/README.md`

## Python Library Logos

### pandas-showcase
**Summary:** Pandas correctness: `Series.sum()` scalar row and `assert_frame_equal` with exact equality. Good suite discharges both consistency (z3) and witness (pytest rerun); bad contradiction is refused both ways.

- **Key paths:** `/examples/pandas-showcase/` (run.sh, README.md, .sugar/vocab-exceptions/)
- **Audience:** End-user (flagship Python data library)
- **Doc priority:** P0 (major logo)
- **Existing docs:** `./examples/pandas-showcase/README.md`

### numpy-showcase
**Summary:** NumPy correctness: one real `numpy.rot90` operation lifted across the Sugar lifecycle (lift → mint → prove). Shows public-symbol resolution, lean SourceMemento lift, consistency and witness verification.

- **Key paths:** `/examples/numpy-showcase/` (run.sh, README.md, app.py, test_numpy_rot90.py)
- **Audience:** End-user (foundational Python library)
- **Doc priority:** P0 (core library)
- **Existing docs:** `./examples/numpy-showcase/README.md`

### sklearn-showcase
**Summary:** Scikit-learn correctness: `accuracy_score`, `zero_one_loss`, `mean_shift_zero_bandwidth` from vendor test suite. Both consistency and witness axes.

- **Key paths:** `/examples/sklearn-showcase/` (run.sh, README.md, test_*.py)
- **Audience:** End-user (ML library proof)
- **Doc priority:** P1 (major library)
- **Existing docs:** `./examples/sklearn-showcase/README.md`

### numpy-vendor
**Summary:** NumPy vendor test harness: unpacks installed numpy source, lifts its assertions, provides oracle interface for materialize.

- **Key paths:** `/examples/numpy-vendor/` (run.sh, README.md)
- **Audience:** Contributor (witness oracle setup)
- **Doc priority:** P1 (infrastructure)
- **Existing docs:** `./examples/numpy-vendor/README.md`

### numpy-attribute-safety-showcase
**Summary:** NumPy attribute access safety: proving that accessing an attribute does not raise an exception or violate contract preconditions.

- **Key paths:** `/examples/numpy-attribute-safety-showcase/` (run.sh, README.md)
- **Audience:** Contributor (attribute-safety technique)
- **Doc priority:** P1 (technique demonstration)
- **Existing docs:** `./examples/numpy-attribute-safety-showcase/README.md`

### python-double
**Summary:** Python scalar-assertion consistency and witness. Mirror of rust-double: good scalar lifts to SAT, bad contradiction lifts to UNSAT.

- **Key paths:** `/examples/python-double/` (run.sh, README.md, test_double.py)
- **Audience:** Contributor (Python consistency-axis template)
- **Doc priority:** P1 (Python learning example)
- **Existing docs:** `./examples/python-double/README.md`

### python-bodyguard-precondition
**Summary:** Python precondition guard lifting, mirroring Rust. Function guard `if x < 2 or x > 36: raise ValueError` lifts as flat precondition. Proves cross-language guard equivalence via CID comparison.

- **Key paths:** `/examples/python-bodyguard-precondition/` (run.sh, README.md, .work/)
- **Audience:** Contributor (cross-language federation)
- **Doc priority:** P1 (federation demo)
- **Existing docs:** `./examples/python-bodyguard-precondition/README.md`

### python-guard-shapes
**Summary:** Python guard condition variations: complex boolean expressions, nested ifs, guard composition patterns.

- **Key paths:** `/examples/python-guard-shapes/` (run.sh, README.md)
- **Audience:** Contributor (guard-lifting residuals)
- **Doc priority:** P2 (edge cases)
- **Existing docs:** `./examples/python-guard-shapes/README.md`

### python-urlsafe-seam
**Summary:** Cross-language base64 URL-safe encoding: Java `Base64.getUrlEncoder()` vs Python `urllib.parse.quote_from_bytes`. Seam proof showing surface equivalence despite different implementations.

- **Key paths:** `/examples/python-urlsafe-seam/` (run.sh, README.md, java-shim/, python-test/)
- **Audience:** Contributor (seam proofs, cross-language library equivalence)
- **Doc priority:** P1 (federation technique)
- **Existing docs:** `./examples/python-urlsafe-seam/README.md`

## Java Contract Examples

### signup-service
**Summary:** An ordinary Maven project lifting real dependencies (gson, hibernate-validator, commons-codec, commons-text). Shows `prove.sh` minting one `.proof` per transitive artifact. The proven set is ground; the GAP lines show undeclared surfaces.

- **Key paths:** `/examples/signup-service/` (pom.xml, src/main/java, src/test/java, prove.sh, README.md)
- **Audience:** End-user (real-world Maven application)
- **Doc priority:** P0 (integration demo)
- **Existing docs:** `./examples/signup-service/README.md`

### java-commons-codec-crc32
**Summary:** Commons Codec library proof: CRC32 checksum correctness. Lifts JSR-380 `@NotNull`, `@Min` contract annotations plus JUnit assertions.

- **Key paths:** `/examples/java-commons-codec-crc32/` (good/, bad/, run.sh, PROVENANCE.md)
- **Audience:** End-user (library proof)
- **Doc priority:** P0 (major library)
- **Existing docs:** none (PROVENANCE.md present)

### java-b64-strong
**Summary:** Base64 encoding exact correctness, "strong" variant: standard and URL-safe encodings with strict byte-equality rows.

- **Key paths:** `/examples/java-b64-strong/` (good/, bad/, run.sh, PROVENANCE.md)
- **Audience:** Contributor (encoding precision)
- **Doc priority:** P1 (encoding proof)
- **Existing docs:** none

### java-codec-universe
**Summary:** Codecs as a universe: multiple encoding schemes (Base64, URL, Hex, etc.) in one proof context. Lifts the codec abstraction as FOL predicates.

- **Key paths:** `/examples/java-codec-universe/` (good/, bad/, run.sh, PROVENANCE.md)
- **Audience:** Contributor (abstraction lifting)
- **Doc priority:** P1 (technique)
- **Existing docs:** none

### java-crc32-universe
**Summary:** CRC32 universe: properties and invariants over the checksum algorithm. Lifts multiple CRC32 operations into a single consistent universe.

- **Key paths:** `/examples/java-crc32-universe/` (good/, bad/, run.sh, PROVENANCE.md)
- **Audience:** Contributor (algorithm universe)
- **Doc priority:** P1 (algorithm proof)
- **Existing docs:** none

### java-mt-reference
**Summary:** Multithreading reference implementation: thread-safe counter operations proven via model-based contracts. Good suite proves atomicity; bad suite contains data-race twin.

- **Key paths:** `/examples/java-mt-reference/` (good/, bad/, run.sh, PROVENANCE.md)
- **Audience:** Contributor (concurrency proof)
- **Doc priority:** P1 (multithreading)
- **Existing docs:** none

### java-mt-strong
**Summary:** Multithreading strong correctness: memory visibility, ordering, and atomicity constraints. More precise than reference variant.

- **Key paths:** `/examples/java-mt-strong/` (good/, bad/, run.sh, PROVENANCE.md)
- **Audience:** Contributor (concurrency precision)
- **Doc priority:** P1 (threading precision)
- **Existing docs:** none

### java-urlsafe-seam
**Summary:** Cross-language seam proof for URL-safe Base64. Java `Base64.getUrlEncoder()` proven equivalent to Python/Rust variants via lifted assertions. Illustrates the "seam gap" in universal API contracts.

- **Key paths:** `/examples/java-urlsafe-seam/` (good/, bad/, run.sh, PROVENANCE.md)
- **Audience:** Contributor (seam proof, federation)
- **Doc priority:** P1 (federation demo)
- **Existing docs:** none

### java-voltron
**Summary:** Voltron collection: multiple Java libraries joined through contract composition. Shows how independent proofs link via shared interfaces.

- **Key paths:** `/examples/java-voltron/` (good/, bad/, run.sh, PROVENANCE.md)
- **Audience:** Contributor (composition)
- **Doc priority:** P1 (cross-library composition)
- **Existing docs:** none

### java-abs-flagship
**Summary:** Abstract class correctness (flagship variant): inheritance hierarchy and abstract method dispatch.

- **Key paths:** `/examples/java-abs-flagship/` (good/, bad/, run.sh, PROVENANCE.md)
- **Audience:** Contributor (OO proof)
- **Doc priority:** P1 (inheritance)
- **Existing docs:** none

### java-abs-model
**Summary:** Abstract class modeling: treating abstract classes as models in FOL. Contract refinement through inheritance.

- **Key paths:** `/examples/java-abs-model/` (good/, run.sh, PROVENANCE.md)
- **Audience:** Contributor (OO modeling)
- **Doc priority:** P2 (OO technique)
- **Existing docs:** none

### java-abs-universe
**Summary:** Abstract class universe: multiple abstract classes and their concrete subclasses in a single FOL universe.

- **Key paths:** `/examples/java-abs-universe/` (good/, bad/, run.sh, PROVENANCE.md)
- **Audience:** Contributor (OO universe)
- **Doc priority:** P2 (universe technique)
- **Existing docs:** none

### java-abs-bound
**Summary:** Abstract method contract bounds: precondition and postcondition constraints on abstract methods, proved across all implementations.

- **Key paths:** `/examples/java-abs-bound/` (bad/, run.sh)
- **Audience:** Contributor (abstract-contract bounds)
- **Doc priority:** P2 (OO bounds)
- **Existing docs:** none

### java-b64-tails
**Summary:** Base64 "tails" edge cases: end-of-input padding, truncation, and non-standard input lengths.

- **Key paths:** `/examples/java-b64-tails/` (good/, bad/, run.sh, PROVENANCE.md)
- **Audience:** Contributor (edge-case coverage)
- **Doc priority:** P2 (residuals)
- **Existing docs:** none

### java-crc32-valuepin
**Summary:** CRC32 with value pinning: contracts that pin the exact computed value (not just properties). Demonstrates precision limits.

- **Key paths:** `/examples/java-crc32-valuepin/` (good/, bad/, run.sh, PROVENANCE.md)
- **Audience:** Contributor (value precision)
- **Doc priority:** P2 (value-pin technique)
- **Existing docs:** none

### java-instance-universe
**Summary:** Instance-method dispatch in a universe of objects. Lifts method calls as relation operators over instance identity.

- **Key paths:** `/examples/java-instance-universe/` (good/, bad/, run.sh, PROVENANCE.md)
- **Audience:** Contributor (instance-dispatch modeling)
- **Doc priority:** P2 (OO modeling)
- **Existing docs:** none

### java-pattern-regex
**Summary:** JSR-380 `@Pattern` annotation universe. Regex match lifted to z3 string theory (mirroring rust-regex-membership). Bad suite tests non-regular languages.

- **Key paths:** `/examples/java-pattern-regex/` (good/, bad/, run.sh, PROVENANCE.md)
- **Audience:** Contributor (cross-language regex equivalence)
- **Doc priority:** P1 (validation technique)
- **Existing docs:** none

### java-assertion-consistency
**Summary:** JUnit assertion consistency: plain `assert` and `assertEquals` rows lifted as consistency obligations.

- **Key paths:** `/examples/java-assertion-consistency/` (good/, bad/, run.sh)
- **Audience:** Contributor (JUnit template)
- **Doc priority:** P1 (JUnit learning)
- **Existing docs:** none

### java-testng-consistency
**Summary:** TestNG assertion consistency: `assertTrue`, `assertEquals` rows from TestNG test suites.

- **Key paths:** `/examples/java-testng-consistency/` (good/, bad/, run.sh)
- **Audience:** Contributor (TestNG support)
- **Doc priority:** P2 (test-framework variant)
- **Existing docs:** none

### java-bound-federation
**Summary:** Contract-bound federation: two Java libraries with shared interfaces, proofs linked via boundary contracts.

- **Key paths:** `/examples/java-bound-federation/` (good/, bad/, run.sh)
- **Audience:** Contributor (federation via bounds)
- **Doc priority:** P1 (federation)
- **Existing docs:** none

### java-callbind-consistency
**Summary:** Call binding and dynamic dispatch consistency: method invocation resolved through inheritance hierarchy.

- **Key paths:** `/examples/java-callbind-consistency/` (good/, bad/, run.sh)
- **Audience:** Contributor (dispatch consistency)
- **Doc priority:** P2 (dispatch proof)
- **Existing docs:** none

### java-forall-loop
**Summary:** Quantified loop invariant: `forall` over collection elements proven true through loop iteration.

- **Key paths:** `/examples/java-forall-loop/` (good/, bad/, run.sh)
- **Audience:** Contributor (loop quantification)
- **Doc priority:** P2 (loop invariant)
- **Existing docs:** none

### java-panama-bridge
**Summary:** Project Panama native bridge: Java-to-native FFI contracts, proven through the interop boundary.

- **Key paths:** `/examples/java-panama-bridge/` (run.sh, native-contract/, native-shim/)
- **Audience:** Contributor (FFI proof)
- **Doc priority:** P2 (FFI integration)
- **Existing docs:** none

### java-witness-recompute
**Summary:** Java witness recompute: re-running vendor test suite and content-addressing witness body for stale-proof detection.

- **Key paths:** `/examples/java-witness-recompute/` (good/, bad/, run.sh)
- **Audience:** Contributor (witness infrastructure)
- **Doc priority:** P2 (witness verification)
- **Existing docs:** none

## Async / Effects Proofs (Tokio)

### tokio-channel-implication-edge
**Summary:** Channel implication edge: proves that a message send with postcondition `result == 6` feeds a consumer with precondition `x == 6` through a local `tokio::sync::mpsc` channel. Bad suite weakens the send postcondition to `== 5`, causing the edge to refuse.

- **Key paths:** `/examples/tokio-channel-implication-edge/` (good/, bad/, run.sh, README.md)
- **Audience:** End-user (async proof pattern)
- **Doc priority:** P1 (async flagship)
- **Existing docs:** `./examples/tokio-channel-implication-edge/README.md`

### tokio-await-implication-edge
**Summary:** Await-boundary implication: async function postcondition fed to caller precondition across `.await`. Good suite discharges; bad contradictory assertions refuse.

- **Key paths:** `/examples/tokio-await-implication-edge/` (run.sh, README.md, good/, bad/)
- **Audience:** End-user (async proof technique)
- **Doc priority:** P1 (async proof)
- **Existing docs:** `./examples/tokio-await-implication-edge/README.md`

### tokio-mutex-implication-edge
**Summary:** Mutex implication edge: lock-guard contract flows through acquire/release to critical-section consumer.

- **Key paths:** `/examples/tokio-mutex-implication-edge/` (run.sh, README.md, good/, bad/)
- **Audience:** Contributor (lock-contract proof)
- **Doc priority:** P1 (lock proof)
- **Existing docs:** `./examples/tokio-mutex-implication-edge/README.md`

### tokio-effect-consistency
**Summary:** Async effects consistency: plain `#[tokio::test]` assertion over `.await` result (`async_value().await == 6`) lifted structurally. Good suite SAT, bad contradiction UNSAT.

- **Key paths:** `/examples/tokio-effect-consistency/` (run.sh, README.md, good/, bad/)
- **Audience:** Contributor (async-effects technique)
- **Doc priority:** P1 (async learning)
- **Existing docs:** `./examples/tokio-effect-consistency/README.md`

## Solver & Verification Infrastructure

### multi-solver-demo
**Summary:** Verifier multi-solver modes: runs a single obligation against single, chain, portfolio first-wins, portfolio consensus, and per-fragment dispatch modes. Uses stub solvers for CI; swappable with z3, cvc5, vampire.

- **Key paths:** `/examples/multi-solver-demo/` (run.sh, README.md, Cargo.toml)
- **Audience:** Contributor (solver orchestration)
- **Doc priority:** P1 (solver reference)
- **Existing docs:** `./examples/multi-solver-demo/README.md`

### forall-vampire-showcase
**Summary:** First-order quantified obligation routed to Vampire solver. Proves an associative-group algebra theorem. Shows z3 timeout vs Vampire UNSAT; bad suite is false universal, refused by Vampire.

- **Key paths:** `/examples/forall-vampire-showcase/` (run.sh, README.md, good/, bad/)
- **Audience:** Contributor (first-order solver)
- **Doc priority:** P1 (FOL solver demo)
- **Existing docs:** `./examples/forall-vampire-showcase/README.md`

## Witness & Build Proofs

### build-witness-showcase
**Summary:** Build script determinism proof. Compares repo-vs-distributed configure script, distributed-vs-rebuilt output artifact. Proves script CID equality and output CID equality; detects tampering via stale witness recompute.

- **Key paths:** `/examples/build-witness-showcase/` (run.sh, README.md, good/, bad-script/, bad-output/, tampered-script/, tampered-output/)
- **Audience:** End-user (supply-chain proof)
- **Doc priority:** P1 (build proof)
- **Existing docs:** `./examples/build-witness-showcase/README.md`

### pytest-witness-dummy
**Summary:** Pytest witness test infrastructure: runs pytest under real library, records witness body and CID for recompute verification.

- **Key paths:** `/examples/pytest-witness-dummy/` (run.sh, README.md)
- **Audience:** Contributor (witness infrastructure)
- **Doc priority:** P1 (witness harness)
- **Existing docs:** `./examples/pytest-witness-dummy/README.md`

## Tool Integration & Framework Support

### lsp-plugins
**Summary:** Language Server Protocol plugin architecture. Reference implementation showing how to write plugins in Rust, Go, C#, C++, Zig. Plugins expose parse() method over NDJSON-RPC, receive source files, return contract annotations.

- **Key paths:** `/examples/lsp-plugins/` (README.md, rust/main.rs, go/main.go, csharp/Program.cs, cpp/main.cpp, zig/main.zig)
- **Audience:** Contributor (plugin author guide)
- **Doc priority:** P0 (tool-integration reference)
- **Existing docs:** `./examples/lsp-plugins/README.md`

### ir-compiler-plugins
**Summary:** IR compiler plugin architecture (Lean, Coq, Maude backends). Shows how ProofIR lowers to multiple target logics.

- **Key paths:** `/examples/ir-compiler-plugins/` (echo-compiler/)
- **Audience:** Contributor (backend developer)
- **Doc priority:** P1 (compiler plugin reference)
- **Existing docs:** none

### sugar-shim-numpy
**Summary:** NumPy shim layer for Sugar: provides a NumPy-compatible surface that records all operations as assertions for lifting.

- **Key paths:** `/examples/sugar-shim-numpy/` (run.sh, README.md)
- **Audience:** Contributor (framework integration)
- **Doc priority:** P2 (integration technique)
- **Existing docs:** `./examples/sugar-shim-numpy/README.md`

## Test Fixtures & Dummies

### numpy-consumer-demo
**Summary:** NumPy consumer test fixtures: demonstrates calling numpy functions and making assertions over results.

- **Key paths:** `/examples/numpy-consumer-demo/` (test_add_consistent.py, test_add_contradictory.py)
- **Audience:** Contributor (test-fixture template)
- **Doc priority:** P2 (fixture reference)
- **Existing docs:** none

### numpy-testing-dummy
**Summary:** NumPy.testing vocabulary dummy: provides test helpers (assert_array_equal, etc.) for lift harness exercising.

- **Key paths:** `/examples/numpy-testing-dummy/` (test_npt_consistent.py, test_npt_contradictory.py)
- **Audience:** Contributor (vocabulary fixture)
- **Doc priority:** P2 (fixture reference)
- **Existing docs:** none

### pandas-source-accounting
**Summary:** Pandas source-tree accounting: walks pandas source, lifts assertions, produces ledger of covered/uncovered assertions.

- **Key paths:** `/examples/pandas-source-accounting/` (run.sh, good/)
- **Audience:** Contributor (library auditing)
- **Doc priority:** P2 (accounting technique)
- **Existing docs:** none

### python-array-map-sugar
**Summary:** Python array map operation lifted as Sugar. Demonstrates collection-operation contract lifting.

- **Key paths:** `/examples/python-array-map-sugar/` (bad/, good/)
- **Audience:** Contributor (collection proof)
- **Doc priority:** P2 (proof pattern)
- **Existing docs:** none

### python-consistency-dummy
**Summary:** Python consistency-axis test fixture (mirror of java-assertion-consistency, rust-test-assertion-consistency).

- **Key paths:** `/examples/python-consistency-dummy/` (test_approx_consistent.py, test_approx_contradictory.py, test_approx_different_targets.py, test_attribute_consistent.py, test_attribute_contradictory.py)
- **Audience:** Contributor (consistency testing)
- **Doc priority:** P2 (test fixture)
- **Existing docs:** none

### python-literal-base64
**Summary:** Python base64 literal string assertions: proving properties of base64-encoded strings as FOL predicates.

- **Key paths:** `/examples/python-literal-base64/` (bad/, good/, run.sh)
- **Audience:** Contributor (string literal proof)
- **Doc priority:** P2 (proof pattern)
- **Existing docs:** none

### python-native-map-callable
**Summary:** Python native map() with callable predicates: lifting functional programming constructs.

- **Key paths:** `/examples/python-native-map-callable/` ()
- **Audience:** Contributor (functional proof)
- **Doc priority:** P2 (functional technique)
- **Existing docs:** none

### rust-double
**Summary:** Rust scalar-assertion consistency fixture: good suite SAT, bad UNSAT (mirror of python-double).

- **Key paths:** `/examples/rust-double/` (good/, bad/)
- **Audience:** Contributor (Rust consistency fixture)
- **Doc priority:** P2 (test fixture)
- **Existing docs:** none

### rust-missing-edge
**Summary:** Rust implication edge with missing premise: demonstrates failed premise for a consumer contract.

- **Key paths:** `/examples/rust-missing-edge/` (good/, bad/)
- **Audience:** Contributor (implication failure case)
- **Doc priority:** P2 (edge-case proof)
- **Existing docs:** none

### rust-witness-showcase
**Summary:** Rust witness recompute showcase: cargo-test witness axis with real Rust test suite.

- **Key paths:** `/examples/rust-witness-showcase/` (run.sh, good/, bad/)
- **Audience:** Contributor (witness infrastructure)
- **Doc priority:** P2 (witness demo)
- **Existing docs:** none

### forall-loop-showcase
**Summary:** Quantified loop showcase: `forall` predicate over loop iterations.

- **Key paths:** `/examples/forall-loop-showcase/` (good/, bad/, run.sh)
- **Audience:** Contributor (loop quantification)
- **Doc priority:** P2 (loop proof)
- **Existing docs:** none

### itsdangerous-token-padding
**Summary:** itsdangerous library token/padding fixtures: encoding and padding correctness assertions.

- **Key paths:** `/examples/itsdangerous-token-padding/` (bad/, good/, run.sh)
- **Audience:** Contributor (token-encoding proof)
- **Doc priority:** P2 (proof pattern)
- **Existing docs:** none

### serde-value-totality-fixture
**Summary:** Serde JSON value totality: ensures all JSON value constructors are accounted for in assertions.

- **Key paths:** `/examples/serde-value-totality-fixture/` ()
- **Audience:** Contributor (totality fixture)
- **Doc priority:** P2 (fixture reference)
- **Existing docs:** none

### stage3-serde-totality-fixture
**Summary:** Serde totality stage 3: extended fixture covering edge cases.

- **Key paths:** `/examples/stage3-serde-totality-fixture/` ()
- **Audience:** Contributor (totality coverage)
- **Doc priority:** P2 (fixture reference)
- **Existing docs:** none

### stage4-serde-multiline-totality-fixture
**Summary:** Serde multiline totality: totality over multi-line JSON constructs.

- **Key paths:** `/examples/stage4-serde-multiline-totality-fixture/` ()
- **Audience:** Contributor (totality coverage)
- **Doc priority:** P2 (fixture reference)
- **Existing docs:** none

### oracle-hover-fixture
**Summary:** Oracle hover LSP fixture: test data for source oracle hover/materialize operations.

- **Key paths:** `/examples/oracle-hover-fixture/` (src/, Cargo.toml)
- **Audience:** Contributor (LSP testing)
- **Doc priority:** P2 (LSP fixture)
- **Existing docs:** none

### panic-freedom-fixture
**Summary:** Panic-freedom proof fixture: proving that a function cannot panic under valid inputs.

- **Key paths:** `/examples/panic-freedom-fixture/` (src/, Cargo.toml)
- **Audience:** Contributor (panic proof)
- **Doc priority:** P2 (safety proof)
- **Existing docs:** none

### sugar-rpc-minimal
**Summary:** Minimal RPC server fixture: test infrastructure for witness RPC services.

- **Key paths:** `/examples/sugar-rpc-minimal/` ()
- **Audience:** Contributor (RPC testing)
- **Doc priority:** P2 (infrastructure)
- **Existing docs:** none

### agent-plugins
**Summary:** Agent plugin examples: fixtures for extensibility and plugin architecture testing.

- **Key paths:** `/examples/agent-plugins/` (doubleledger-fixture/, echo-agent/)
- **Audience:** Contributor (plugin testing)
- **Doc priority:** P2 (plugin reference)
- **Existing docs:** none

### zero-touch-demo
**Summary:** Zero-touch proof demo: minimal setup for proving a library without custom adapters.

- **Key paths:** `/examples/zero-touch-demo/` ()
- **Audience:** Contributor (zero-touch technique)
- **Doc priority:** P2 (demo)
- **Existing docs:** none

---

## Open Questions

1. **Java examples without READMEs:** 27 Java examples have `PROVENANCE.md` but no `README.md`. These appear to be part of a systematic campaign but lack user-facing documentation. Should they each have short READMEs?

2. **Examples without run.sh:** Some fixtures (e.g., `oracle-hover-fixture`, `panic-freedom-fixture`) lack `run.sh`. Are these meant to be manually invoked or included as libraries?

3. **Organizational structure:** Are the 88 examples meant to be grouped by language, by proof technique, or by maturity level? Current repo has them flat; should examples.md provide navigation hints?

5. **Library coverage gaps:** Several patterns are "prototype" (base64, bitflags, itertools, etc.) with run.sh but no README and no PROVENANCE. Are these stable enough to document publicly?

6. **Witness oracle completeness:** Do all Python/Java witness examples actually run vendor tests, or are some fixtures? Audit needed.

7. **Fixture vs. showcase distinction:** The line between "test fixture" and "runnable showcase" is blurry. Should we add a `fixture/` or `test/` subdirectory to clarify intent?
