# BoolOp Constructed Probe Drift Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the 12 BoolOp operand-sequence tests without reopening the deliberately closed `ConstructedTermSugar` door, then enumerate other caller drift introduced by `df07b3f88`.

**Architecture:** The product contract stays unchanged. The test-only evaluation probe joins the existing `ConstructedTermSugar` hierarchy and supplies canonical fixed testimony; a bounded commit audit reports other stale caller shapes without fixing them.

**Tech Stack:** Python 3.12, dataclasses, pytest, git history.

## Global Constraints

- Work only in `/Users/tsavo/.herdr/worktrees/provekit/hockney-work`.
- Do not loosen `BoolOpSugar.values` or its runtime admission.
- Do not fix other `df07b3f88` caller drift in this lane.
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

### Task 2: Audit the source commit for sibling drift

**Files:**
- Read: commit `df07b3f88`
- Read: callers of every narrowed annotation, removed parameter, and new runtime admission found in that commit

**Interfaces:**
- Consumes: the exact `df07b3f88` diff and repository callers on current `origin/main`
- Produces: a door-by-door list with measured caller sites and current/stale status

- [ ] **Step 1: Extract candidate doors from the bounded diff**

Inspect only changed Python production files for type narrowing, signature
removal, and new `isinstance`/admission checks.

- [ ] **Step 2: Trace every candidate to its callers**

For each candidate, compare old and new signatures and search current Python
callers for the removed or rejected shape.

- [ ] **Step 3: Report without repairing sibling doors**

State the number of doors inspected, the site count for each stale caller set,
and what the audit does not claim. Commit only the focused BoolOp fixture repair
and these design/plan receipts.
