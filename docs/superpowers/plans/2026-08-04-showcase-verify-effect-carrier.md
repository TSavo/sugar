# Showcase Verify-Effect Carrier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve every constructed `VerifyEffect` variant through verification receipts and construct an exact terminal for nonempty required-property attendance gaps.

**Architecture:** Replace the report wire's implicit optional effect with a total `VerifyEffectCarrier::{Effect(VerifyEffect), NoEffect}`. Every `ReportRow` constructor must state one arm, making “not carried” unrepresentable; receipt JSON preserves the full effect variant, and the showcase selector projects only structured variant/property authority. Separately, a closed Python attendance result constructs either complete attendance or a nonempty gap over exact required-minus-observed property identities.

**Tech Stack:** Rust (`serde`, `sugar-verifier`), Python 3, pytest, Bash showcase producers.

## Global Constraints

- Base all source testimony on `c62c2cd79c5839fb309091e0caea29c7a4d2eb13` or a named later main pin.
- Never infer terminal identity from exit codes, prose, reason strings, or overlapping counters.
- Preserve the exact `VerifyEffect` variant; a generic refusal label is forbidden.
- The carrier has exactly `Effect(VerifyEffect)` and positively stated `NoEffect`; an omitted carrier must not compile.
- Write red discrimination teeth before production changes and run only focused battleaxe tests.
- Keep the attendance-gap constructor separate from the effect-carrier commit.

---

### Task 1: Total typed-effect report carrier

**Files:**
- Modify: `implementations/rust/sugar-verifier/src/effects.rs`
- Modify: `implementations/rust/sugar-verifier/src/types.rs`
- Modify: `implementations/rust/sugar-verifier/src/report.rs`
- Modify: `implementations/rust/sugar-verifier/src/runner.rs`
- Modify: direct `ReportRow` fixture constructors named by the compiler
- Test: `implementations/rust/sugar-verifier/src/report.rs`

**Interfaces:**
- Consumes: `ConsistencyResult.effect: Option<VerifyEffect>` at the authoritative producer boundary.
- Produces: `VerifyEffectCarrier::{Effect(VerifyEffect), NoEffect}` on every `ReportRow`; JSON `verifyEffect` retaining carrier state and the exact enum variant.

- [ ] **Step 1: Write the failing carrier discrimination tests**

Add focused tests proving two distinct `VerifyEffect` variants serialize distinctly, explicit `NoEffect` serializes positively, and no `ReportRow` can be built without a carrier.

- [ ] **Step 2: Run the focused Rust tooth and record RED**

Run: `bin/bcargo test -p sugar-verifier report::tests::verify_effect_carrier -- --nocapture`

Expected: nonzero because `VerifyEffectCarrier`/`verifyEffect` do not exist on the pinned base.

- [ ] **Step 3: Add the closed carrier and exhaustive variant serialization**

Define `VerifyEffectCarrier` with only `Effect(VerifyEffect)` and `NoEffect`. Serialize the carrier and the complete `VerifyEffect` enum structurally; do not collapse variants to reason text.

- [ ] **Step 4: Make `ReportRow` require the carrier**

Add a non-optional carrier field. Update the sole report constructors and compiler-named fixtures to pass `NoEffect` positively when no verification effect occurred.

- [ ] **Step 5: Seat both runner entrances through one producer conversion**

Expose one `ConsistencyResult` method that matches its authoritative option into the closed carrier. Both runner loops and the warm/cold wire twin call that method; no caller authors a tag.

- [ ] **Step 6: Run the focused Rust tooth and record GREEN**

Run: `bin/bcargo test -p sugar-verifier report::tests::verify_effect_carrier -- --nocapture`

Expected: zero with the two effect variants distinct and `NoEffect` explicit.

- [ ] **Step 7: Commit the carrier repair**

Commit only the Rust carrier, projection, required constructor updates, and carrier teeth.

### Task 2: Structured receipt terminal selector and five bindings

**Files:**
- Modify: `tools/showcase_terminal_identity.py`
- Modify: `tools/showcase/durable_consistency.py`
- Modify: `examples/std-core-string-predicates/run.sh`
- Test: `tests/test_showcase_terminal_producer.py`

**Interfaces:**
- Consumes: receipt rows containing total `verifyEffect` carrier JSON.
- Produces: first unexpected raw terminal identity derived from the exact effect variant and authenticated property fields, or a positive no-terminal result for fully discharged rows.

- [ ] **Step 1: Write failing selector twins**

Plant one refused row whose `verifyEffect` carrier is absent and assert named refusal; plant two distinct effect variants and assert distinct terminal kinds; plant a discharged `NoEffect` row and assert no terminal.

- [ ] **Step 2: Run the focused Python tooth and record RED**

Run: `bin/bpytest tests/test_showcase_terminal_producer.py -q`

Expected: nonzero because the receipt selector does not exist.

- [ ] **Step 3: Implement the receipt selector without prose inference**

Validate the carrier state and structured effect variant. Derive owner only from the effect's structured property authority; use `propertyCid`/property as structured coordinates, never parse `reason`.

- [ ] **Step 4: Bind the five producers at their shared doors**

Have `require_substantive_discharge` publish the first unexpected effect before its existing prose failure, covering url/semver/num-integer/bitflags. Bind std-core-string at its structured `failed_good` row selection. Preserve existing exit behavior.

- [ ] **Step 5: Run Python teeth and shell syntax checks**

Run: `bin/bpytest tests/test_showcase_terminal_producer.py -q`

Run unpiped: `bash -n examples/std-core-string-predicates/run.sh examples/url-showcase/run.sh examples/semver-showcase/run.sh examples/num-integer-showcase/run.sh examples/bitflags-showcase/run.sh`

- [ ] **Step 6: Commit the selector and five thin bindings**

Commit only the shared selector/helper binding, std-core-string binding, and focused tests.

### Task 3: Nonempty verification-property attendance gap

**Files:**
- Modify: `tools/showcase_terminal_identity.py`
- Modify: `examples/std-core-showcase/run.sh`
- Test: `tests/test_showcase_terminal_producer.py`

**Interfaces:**
- Consumes: declared required property identities and observed receipt property identities.
- Produces: a closed complete-attendance result or `VerificationPropertyAttendanceGap` containing a nonempty ordered missing set and its terminal projection.

- [ ] **Step 1: Write failing complete/gap twins**

Assert exact required-minus-observed membership and order for the gap arm. Assert complete attendance constructs positively and publishes no terminal.

- [ ] **Step 2: Run the focused Python tooth and record RED**

Run: `bin/bpytest tests/test_showcase_terminal_producer.py -q`

Expected: nonzero because the attendance constructor does not exist.

- [ ] **Step 3: Implement the closed attendance constructor**

Construct complete or nonempty gap from structured identities. Project the first missing identity in declared order to witness/v1 while retaining the complete gap in the constructed value; never parse printed prose.

- [ ] **Step 4: Replace the std-core hand check with the constructor**

Keep the existing human-readable missing-property output, but derive it from the constructed gap and publish its terminal before exit.

- [ ] **Step 5: Run focused tests and syntax check**

Run: `bin/bpytest tests/test_showcase_terminal_producer.py -q`

Run unpiped: `bash -n examples/std-core-showcase/run.sh`

- [ ] **Step 6: Commit the attendance construct separately**

Commit only the central attendance constructor, std-core binding, and its twins.
