# ConstructorCallSugar Bulk Initializer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route the decidable local initializer statement subset through the existing reduced-outcome constructor body.

**Architecture:** Preserve the field-only fast path and widen only its statement-door predicate for `If`, `Raise`, and authenticated `super().__init__`. The existing contextualized reducer remains the sole constructor of path-selected fields and exceptional exits, while already-constructed class fields use the shared descriptor-safe class-field constructor.

**Tech Stack:** Python 3.12/3.14, pytest, Sugar floor algebra, real solver witness harness.

## Global Constraints

- Construct or panic; never add empty success.
- Add no RuntimeEffect constructor.
- Trust reduced path outcomes, not guessed AST execution.
- Explicit-base initializers remain owned by #5126.
- Witness raise/error twins are written to files, never echoed.

---

### Task 1: Red discrimination

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_constructor_call_evidence.py`

**Interfaces:**
- Consumes: `_outcome`, `ConstructorCallSugar`, `FactoryPanic`.
- Produces: exact expectations for decidable `If`/`super` and unsupported-call twins.

- [x] Add a concrete-path initializer test whose selected branch constructs the final `self` field.
- [x] Add `self` assignment followed by positional and keyword
  `super().__init__` tests.
- [x] Add a class-field twin proving the source-body strategy preserves static
  class state.
- [x] Assert an arbitrary expression call and explicit-base initializer remain named `ConstructorCallSugar` panics.
- [x] Run the focused tests and observe the construction tests fail for the missing routes.

### Task 2: Minimal statement-door construction

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/constructor_call_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/constructor_strategy.py`

**Interfaces:**
- Consumes: `_source_initializer_needs_statement_door(init, receiver_name)`.
- Produces: `True` only for the supported ordinary-statement subset.

- [x] Route `ast.If` and `ast.Raise` through the statement door.
- [x] Mark the exact existing zero-argument `super().__init__` arm as requiring the statement door.
- [x] Carry statically constructed class fields through
  `SourceBodyConstructorStrategy` using the same descriptor refusal as the
  field-only strategy.
- [x] Keep arbitrary `Expr`, explicit-base calls, imports, and pass outside the door.
- [x] Run the focused discrimination green.

### Task 3: Witness and corpus receipt

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_constructor_call_evidence.py`
- Create: `docs/ledgers/constructor-call-bulk-5151-2026-07-18.md`

**Interfaces:**
- Consumes: 22 named current-main representatives and the real solver harness.
- Produces: SAT/UNSAT witness and a closed conservation table.

- [x] Add a file-backed truthful/lying witness for the constructed initializer.
- [x] Replay all 22 representatives and record completed / advanced loud / unchanged loud / silent.
- [ ] Run direct claim-mass tripwires and re-pin only exact proven movement.
- [ ] Build the release binary at final branch HEAD and rerun the fresh witness.
- [ ] Commit as T Savo, push, and open a non-closing PR with `Part of #5151`.
