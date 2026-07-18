# Constructor Explicit Base Initializer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct object state for a source-backed initializer whose already-reduced statements end with an authenticated explicit call to its declared imported base class.

**Architecture:** Extend the existing source-body constructor admission predicate, which already handles local/self assignments plus zero-argument `super().__init__`, to recognize the equivalent explicit `DeclaredBase.__init__(self, ...)` spelling. Admission is structural and provenance-bound: the receiver must be the initializer's `self`, the named base must be one of the class definition's declared bases, and that base must resolve through an import binding. The existing contextualized source-body reducer remains responsible for statement order and final `self.*` bindings; all other expression statements stay loud.

**Tech Stack:** Python 3.14, pytest, Sugar Python factory and witness harness.

## Global Constraints

- Construct or panic; never add empty success.
- Runtime effects require a genuinely runtime operand through the sealed door; this change adds no effect constructor.
- Ground/unrecognized initializer expressions remain `FactoryPanic`.
- A pinned claim-mass fixture that advances must be re-pinned loudly in this PR.

---

### Task 1: Red discrimination

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_constructor_call_evidence.py`

**Interfaces:**
- Consumes: `_outcome`, `Complete`, `ObjectValue`, and `FactoryPanic`.
- Produces: a positive test for an imported declared-base initializer and a bad twin whose non-base call stays loud.

- [ ] Add a test class with `self.value = value` followed by `ExternalBase.__init__(self, value)`, with `ExternalBase` imported and declared as the sole base.
- [ ] Assert construction completes and preserves the concrete `self.value` field.
- [ ] Add a same-shaped call to an imported non-base and assert owner `ConstructorCallSugar` remains loud.
- [ ] Run both tests and confirm only the new positive arm fails at `constructed source initializer`.

### Task 2: Minimal admission rule

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/constructor_call_sugar.py`

**Interfaces:**
- Consumes: `class_site.class_bases()`, `_import_target_for_name`, initializer receiver name, and the existing `SourceBodyConstructorStrategy`.
- Produces: exact admission of `DeclaredBase.__init__(self, ...)` without admitting arbitrary expression statements.

- [ ] Pass class/base context into `_source_initializer_needs_statement_door`.
- [ ] Recognize an explicit `Name.__init__` call only when the first argument is the initializer receiver, `Name` is a declared base, and its import target is resolved.
- [ ] Run the discrimination pair green and the focused constructor evidence suite green.

### Task 3: Representative and soundness receipts

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/constructor_call_sugar.py`
- Modify only if required: claim-mass pin fixture.

**Interfaces:**
- Consumes: pandas `ArrowPeriodType("D")`, ConstructorCallSugar witness registry, and claim-mass tripwire.
- Produces: terminal conservation, fresh truthful/lying witness, and pin safety evidence.

- [ ] Replay `pandas/core/arrays/arrow/extension_types.py` and record `ConstructorCallSugar` terminal 1 to 0, with the next loud owner or completion named and silent 0.
- [ ] Add a verdict-bearing witness pair for the explicit-base initializer and prove truthful SAT / lying UNSAT on the final rebased source provenance.
- [ ] Run the direct claim-mass tripwire; if a pinned fixture advanced, update its pin to the exact proven account and rerun green.
- [ ] Commit as T Savo, push, and open a ready non-closing PR with `Part of #5126`.
