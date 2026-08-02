# BoolOp Constructed Probe Drift Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the 12 BoolOp operand-sequence tests without reopening the deliberately closed `ConstructedTermSugar` door, then bind the test-only names left by two measured mechanical rewrites.

**Architecture:** The product contract stays unchanged. The test-only evaluation probe joins the existing `ConstructedTermSugar` hierarchy and supplies canonical fixed testimony; test-only missing bindings are repaired at their files and tied to raw two-commit evidence.

**Tech Stack:** Python 3.12, dataclasses, pytest, git history.

## Global Constraints

- Work only in `/Users/tsavo/.herdr/worktrees/provekit/hockney-work`.
- Do not loosen `BoolOpSugar.values` or its runtime admission.
- Do not widen history beyond `bf847eb93` and `1eeb80bb3`.
- Run only focused local tests; no broad suite or corpus scan.

---

### Task 1: Repair the stale BoolOp test probe

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_bool_op_operand_sequence.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_bool_op_operand_sequence.py`

**Interfaces:**
- Consumes: `ConstructedTermSugar.to_term(*, owner: str) -> Term`
- Produces: `_ProbeSugar`, an admissible constructed term retaining its existing evaluation log and floor-value result

- [ ] **Step 1: Preserve the red receipt**

Run the first test with `--noconftest`. Expected: `TypeError` naming
`BoolOpSugar.values`, `ConstructedTermSugar`, and `_ProbeSugar`.

- [ ] **Step 2: Promote the test fixture at the existing door**

Replace the base import and class base, then add fixed canonical testimony:

```python
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar

@dataclass(frozen=True)
class _ProbeSugar(ConstructedTermSugar):
    ...

    def to_term(self, *, owner: str):
        del owner
        return str_const(self.label)
```

- [ ] **Step 3: Verify the exact file is green**

Run all of `test_bool_op_operand_sequence.py` with `--noconftest`. Expected:
`12 passed` with no collection loss.

- [ ] **Step 4: Verify the closed product door remains green**

Run `test_constructed_term_sugar.py::test_constructed_term_nested_children_are_closed_at_construction` with the `bool-op` parameter. Expected: the good constructed child is admitted and arbitrary `Sugar` remains rejected.

### Task 2: Repair bounded test-only rewrite casualties

**Files:**
- Modify: fourteen tests that load `AuthenticatedRaiseLocus` without importing it
- Modify: five tests retaining ten unbound `_identity` loads
- Create: `.receipts/authenticated-raise-rewrite-casualties/RECEIPT.md`

**Interfaces:**
- Consumes: exact AST load/binding deltas for `bf847eb93` and `1eeb80bb3`
- Produces: zero unbound locus/identity loads in the measured current test files, plus raw coordinates and first-terminal chains

- [ ] **Step 1: Bind the fourteen locus test files**

Import `AuthenticatedRaiseLocus` from its defining module in every measured
test file. Do not alter the product constructor to admit unbound callers.

- [ ] **Step 2: Repair the five remaining identity expectations**

Use existing builtin identity testimony for builtin exceptions. For the
source-defined cleanup exception, derive identity from the typed source name;
do not fabricate a builtin coordinate from spelling.

- [ ] **Step 3: Verify bindings and preserve raw evidence**

Run the AST binding detector to zero, run the 12 BoolOp tests, compile all
changed tests, and preserve all 187 introducer coordinates, current survivors,
and first-terminal chains. Do not infer a suite-failure count.
