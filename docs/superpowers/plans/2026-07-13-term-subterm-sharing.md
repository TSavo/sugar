# Term Subterm Sharing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make structurally equal Python-kit IR terms share one immutable object identity during each file lift without changing emitted bytes.

**Architecture:** `sugar_lift_py_tests.ir` owns a `ContextVar`-scoped strong intern table and the only public term-construction helpers. `lift_file_payload` opens a fresh scope around the complete file lift and resets it in `finally` via a context manager. Recursive serialization remains unchanged and therefore expands shared nodes exactly as before.

**Tech Stack:** Python 3 dataclasses, `contextvars`, pytest, Sugar Python kit canonicalizer.

## Global Constraints

- One intern table per `lift_file_payload(source, filename)` call, cleared when that call returns.
- Canonical JSON, CIDs, and serialized bytes must remain byte-identical.
- Interned term structures remain immutable and mutation attempts fail loudly.
- Existing structural equality semantics remain unchanged; only equal terms inside one lift gain shared identity.
- Do not introduce DAG wire encoding.
- The real `/tmp/datetime-read` lift is a focused receipt, not a CI gate.

---

### Task 1: Red identity and serialization instrument

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/tests/test_term_subterm_sharing.py`

**Interfaces:**
- Consumes: existing `ctor`, `make_var`, `term_to_value`, `encode_jcs`, and `lift_file_payload` construction path.
- Produces: focused assertions for same-lift sharing, byte invariance, cross-lift isolation, and immutability.

- [ ] **Step 1: Write the failing regression**

Create a nested repeated tree through a small real source lift and a direct scoped construction helper. Walk the resulting terms by structural value, report every equal occurrence whose `id()` differs, and assert `R == 0` with a failure message naming request-scoped hash-consing. Build the same shape from raw frozen dataclasses outside the intern scope and assert `encode_jcs(term_to_value(shared)) == encode_jcs(term_to_value(unshared))`. Assert a second scope yields a distinct root and `dataclasses.FrozenInstanceError` is raised on mutation.

- [ ] **Step 2: Verify red**

Run: `bin/bpytest implementations/python/sugar-lift-py-tests/tests/test_term_subterm_sharing.py -q`

Expected: FAIL because repeated equal `_Ctor` values have different identities and the scoped construction API does not yet exist.

- [ ] **Step 3: Commit the red instrument**

Run:

```bash
git add implementations/python/sugar-lift-py-tests/tests/test_term_subterm_sharing.py
git commit -m "Measure repeated Python term identities"
```

### Task 2: Request-scoped immutable term interning

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/ir.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/lift_rpc.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/proofir/terms/__init__.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/proofir/nodes/function_contract.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_term_subterm_sharing.py`

**Interfaces:**
- Produces: `term_intern_scope() -> Iterator[None]`, plus existing `make_var`, `num`, `str_const`, `real_lit`, `bool_const`, and `ctor` returning the canonical `Term` when a scope is active.
- Consumes: frozen, hashable term variants as structural dictionary keys.

- [ ] **Step 1: Add the scoped construction boundary**

Add a `ContextVar[dict[Term, Term] | None]` after the `Term` union, a context manager that installs a fresh dictionary and resets its token, and `_intern_term(term)` that returns `table.setdefault(term, term)` when active. Route every public term constructor through `_intern_term`.

- [ ] **Step 2: Close direct-construction bypasses**

Replace direct `_Var`/`_Ctor` construction in production rewrites with `make_var`/`ctor`, including substitution and ProofIR normalization, so rewritten nodes use the same boundary.

- [ ] **Step 3: Scope the whole file lift**

Implement `lift_file_payload` as:

```python
from sugar_lift_py_tests.ir import term_intern_scope

with term_intern_scope():
    payload, _gaps = audit_lift_file(source, filename, hold_panic=False)
    return payload
```

- [ ] **Step 4: Verify green**

Run: `bin/bpytest implementations/python/sugar-lift-py-tests/tests/test_term_subterm_sharing.py -q`

Expected: all focused tests pass, `R=0`, serialization bytes equal, cross-lift root identities distinct, mutation loud.

- [ ] **Step 5: Run adjacent CI tests**

Run: `bin/bpytest implementations/python/sugar-lift-py-tests/tests/test_guarded_arithmetic_total.py implementations/python/sugar-lift-py-tests/tests/test_guarded_chain_wall_regression.py implementations/python/sugar-lift-py-tests/tests/test_lift_file_payload.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit implementation**

Run:

```bash
git add implementations/python/sugar-lift-py-tests/src implementations/python/sugar-lift-py-tests/tests/test_term_subterm_sharing.py
git commit -m "Share Python term subtrees per lift"
```

### Task 3: Real construction receipt and publication

**Files:**
- Modify: PR body only, with no repository performance gate.

**Interfaces:**
- Consumes: `/tmp/datetime-read`, the repository's real lift command, `/usr/bin/time -l` wall-clock and peak-RSS output, and the pre-implementation commit.
- Produces: before/after receipt in the PR body.

- [ ] **Step 1: Measure the parent commit**

Run the real `/tmp/datetime-read` lift from the pre-implementation commit under `/usr/bin/time -l`, recording elapsed wall-clock and maximum resident set size. Preserve the output under `/tmp`, outside the repository.

- [ ] **Step 2: Measure the implementation commit**

Run the identical command and environment from the implementation commit, recording elapsed wall-clock and maximum resident set size under `/tmp`.

- [ ] **Step 3: Fresh final verification**

Re-run the focused and adjacent commands from Task 2, inspect `git diff --check`, and confirm the branch contains only intended files.

- [ ] **Step 4: Push and open the PR**

Push `term-subterm-sharing`, then open a draft PR against `main`. The title describes per-lift term sharing. The body contains `Part of #4355` and `Part of #4102`, never closes or fixes either issue, includes focused test and real-lift before/after receipts, flags DAG wire encoding as T's separate adjudication, uses no em dashes, and ends with a Claude Code footer. Do not merge.
