# Ground Operator Family Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the decidable subset of the 18 current-main arithmetic/bitwise terminals while preserving every genuinely runtime or unbuilt operand as loud frontier mass.

**Architecture:** Keep construction at the value floors that possess the needed evidence. Concrete numeric operands fold; concrete zero divisors construct a source-cited `ZeroDivisionError`; boolean/predicate carriers construct exact boolean algebra; an already-selected exceptional exit propagates without evaluating the operator. Static coordinates lacking value testimony and runtime call results remain loud.

**Tech Stack:** Python 3.14, pytest, Sugar floor algebra, Sugar real-solver witness harness.

## Global Constraints

- Construct or panic; never add empty success.
- Ground values never mint RuntimeEffect authority.
- RuntimeEffect is legal only for genuine runtime dependence through the sealed RuntimeOperand door.
- An unbuilt recognizer or missing vendor/native value proof remains a FactoryPanic.
- If a claim-mass-pinned fixture advances, update its exact pin in this PR and run the direct pytest tripwire.

## Measured current-main vector

`bitwise_or=3`, `bitwise_and=2`, `bitwise_invert=1`,
`bitwise_xor=1`, `left_shift=1`, `add=4`, `floor_divide=2`,
`modulo=1`, `unary_minus=2`, `subtract=1`; total `18`.

The recensus `NoneValue.bitwise_invert` row is already retired on current main
and is excluded from the live count.

---

### Task 1: Red discrimination instrument

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/tests/test_ground_operator_family.py`

**Interfaces:**
- Consumes: value-floor operator methods and `_outcome` over source expressions.
- Produces: ground-result, exact-exception, and loud non-ground arms for every charged operator.

- [x] Pin ground folds for `|`, `&`, `^`, `~`, `<<`, `+`, `//`, `%`, unary `-`, and binary `-`.
- [x] Pin exact `ZeroDivisionError` exits for `5 // 0` and `5 % 0`.
- [x] Pin `True & PredicateValue`, `False & PredicateValue`, and `PredicateValue | SymbolicValue`.
- [x] Pin propagation of an existing exceptional exit through floor division.
- [x] Pin a static native coordinate as loud for each operator family; no test may accept a ground RuntimeEffect.
- [x] Run the focused file and observe failures only at the missing floors.

### Task 2: Minimal value-floor construction

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/ground_zero_division_error.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/term_value.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/true_bool_literal_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/false_bool_literal_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/predicate_value.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/exceptional_exit_value.py`

**Interfaces:**
- Consumes: ground operands, boolean formulas, symbolic terms, and source-cited `RaiseEffect`.
- Produces: exact folds/coordinates or `Complete(RaiseValue(ZeroDivisionError))`.

- [x] Implement the relative-locus/source-hash zero-division helper.
- [x] Route concrete zero divisors in `TermValue.floor_divide` and `TermValue.modulo` to it.
- [x] Implement bool/predicate `&` and boolean `~` folds.
- [x] Combine `PredicateValue | SymbolicValue` as the exact symbolic operator coordinate.
- [x] Preserve `ExceptionalExitValue` across floor division.
- [x] Run the discrimination file green.

### Task 3: Witness and conservation receipt

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_ground_operator_family.py`
- Modify only if proven necessary: claim-mass pin fixture.

**Interfaces:**
- Consumes: the 18 named current-main representatives and real solver.
- Produces: per-owner delta, silent-zero conservation, and truthful SAT / lying UNSAT.

- [x] Add a witness source whose guarded zero-divisor path contributes exact exceptional testimony and whose continuing path uses every charged operator.
- [x] Prove truthful SAT and lying UNSAT on the final commit.
- [x] Replay all 18 representatives and report completed, advanced-loud, and unchanged-loud counts by operator.
- [x] Run direct claim-mass tripwires; no owned pin moved. The known current-main requests failure remains external.
- [ ] Commit as T Savo, push, and open a non-closing PR with `Part of #5139`.
