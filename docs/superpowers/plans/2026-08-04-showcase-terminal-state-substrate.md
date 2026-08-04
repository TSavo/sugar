# Showcase Terminal State Substrate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the dormant three-state showcase terminal contract without activating `run_shard` enforcement.

**Architecture:** The producer witness file becomes a closed `ShowcaseTerminalStateV1` envelope. Existing producer identities are wrapped as `witnessed`; `no-owner-possible` exists only as an explicit producer-owned pending-ruling shape; `terminal-construct-missing` has no exemption variant. Dormant scope helpers validate exact terminal-state conservation and classify cross-run terminal transitions, while the live runner continues its additive, non-consuming behavior.

**Tech Stack:** Python 3, pytest through authenticated `bin/bpytest`, JSON witness files, existing `showcase_terminal_identity` and `showcase_scope` authorities.

## Global Constraints

- Do not activate terminal-state enforcement in `tools/showcase_scope.py::run_shard`.
- Missing files never mint `no-owner-possible`; only explicit producer testimony can construct that state.
- `terminal-construct-missing` has no exemption or waiver arm.
- Malformed testimony raises `ScopeRefusal`; it is not a fourth terminal state.
- Terminal-state conservation is exact: `terminalWitnessed + noOwnerPossible + terminalConstructMissing == nonzero executed rows`, with no overlap.
- Preserve existing showcase exit behavior and additive producer publication.
- Do not add a path allowlist or encode the historical nine as current authority.

---

### Task 1: Closed Producer Envelope

**Files:**
- Modify: `tools/showcase_terminal_identity.py`
- Modify: `tests/test_showcase_terminal_producer.py`
- Test: `tests/test_showcase_terminal_state.py`

**Interfaces:**
- Consumes: existing `validate_terminal_identity(raw)` and `write_from_environment(raw)` producer door.
- Produces: `validate_showcase_terminal_state(raw)`, `witnessed_terminal_state(identity)`, `no_owner_possible_terminal_state(...)`, and `terminal_construct_missing_state(...)` returning canonical JSON dictionaries.

- [x] **Step 1: Write red envelope tests**

Add tests proving an existing identity is published as:

```python
{
    "schemaVersion": 1,
    "state": "witnessed",
    "terminalIdentity": IDENTITY,
}
```

Add strict-shape tests proving `no-owner-possible` requires explicit producer contract, entrance, named reason, and `pending-ruling`; `terminal-construct-missing` accepts only its expected contract and named missing reason; and fields from two variants in one envelope refuse.

- [x] **Step 2: Run red teeth**

Run: `bin/bpytest -q tests/test_showcase_terminal_state.py tests/test_showcase_terminal_producer.py`

Expected: focused failures because the state schema and witnessed envelope do not exist.

- [x] **Step 3: Implement the minimal closed schema and writer wrapper**

Implement exact field sets per `state`, canonical field order, and strict validation. Change only the shared writer boundary so existing identity-producing callers publish `witnessed_terminal_state(validate_terminal_identity(raw))`. Do not change producer selection or runner consumption.

- [x] **Step 4: Re-run focused teeth**

Run: `bin/bpytest -q tests/test_showcase_terminal_state.py tests/test_showcase_terminal_producer.py`

Expected: all selected tests pass.

---

### Task 2: Dormant Conservation and Join Substrate

**Files:**
- Modify: `tools/showcase_scope.py`
- Test: `tests/test_showcase_terminal_state.py`

**Interfaces:**
- Consumes: canonical `ShowcaseTerminalStateV1` dictionaries.
- Produces: `validate_terminal_state_conservation(outcomes, counts)` and `classify_terminal_transition(before, after)`.

- [x] **Step 1: Write red conservation teeth**

Plant a balanced population containing one row in each terminal state. Plant a nonzero row without any terminal state and require a named conservation refusal. Plant a `witnessed` envelope carrying `no-owner-possible` fields and require a no-overlap refusal.

- [x] **Step 2: Write red transition teeth**

Prove witnessed rows distinguish `cleared`, `still-failing-same-terminal`, and `moved-to-named-terminal`. Prove either non-witness state yields an explicit `unmeasured` transition carrying the state, never an inferred identity.

- [x] **Step 3: Run red teeth**

Run: `bin/bpytest -q tests/test_showcase_terminal_state.py`

Expected: failures naming absent conservation and transition helpers.

- [x] **Step 4: Implement dormant validation and transition classification**

Derive terminal-state counts from nonzero executed rows, reject terminal state on pass/retired rows, reject missing state, compare every claimed count, and classify transitions without reading prose or A2 counters. Do not call these helpers from `run_shard`, `seal_shard_body`, or attendance yet.

- [x] **Step 5: Re-run focused teeth**

Run: `bin/bpytest -q tests/test_showcase_terminal_state.py`

Expected: all selected tests pass.

---

### Task 3: Activation Exclusion and Final Verification

**Files:**
- Modify: `tests/test_showcase_terminal_state.py`
- Verify: `tools/showcase_scope.py`

**Interfaces:**
- Consumes: the completed dormant substrate.
- Produces: structural evidence that live `run_shard` still supplies but does not consume `SHOWCASE_TERMINAL_WITNESS`.

- [x] **Step 1: Add an activation-exclusion tooth**

Assert the live runner still records a nonzero producer as the legacy failed row without adding `terminalState`, while the terminal witness file contains the new envelope. This proves the producer schema is live and enforcement is not.

- [x] **Step 2: Run the focused authenticated module**

Run: `bin/bpytest -q tests/test_showcase_terminal_state.py tests/test_showcase_terminal_producer.py tests/test_showcase_retirement.py`

Expected: all selected tests pass.

- [x] **Step 3: Audit forbidden activation and vocabulary**

Run:

```bash
git diff --check
git diff origin/main -- tools/showcase_scope.py
rg -n "allowlist|exempt" tools/showcase_terminal_identity.py tools/showcase_scope.py tests/test_showcase_terminal_state.py
```

Expected: clean diff; no `run_shard` consumption of terminal state; no exemption arm on `terminal-construct-missing`.

- [ ] **Step 4: Commit and push the substrate**

Commit only the plan, schema, validators, and focused tests. Push the exact branch head and report the full 40-character remote SHA, parent, focused receipt, and explicit nonclaim that enforcement remains inactive.
