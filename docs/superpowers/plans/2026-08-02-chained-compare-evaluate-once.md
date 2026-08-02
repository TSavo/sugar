# Chained Compare Evaluate-Once Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make multi-operand Python Compare evaluate every source operand at most once while preserving short-circuiting and each existing per-leg law.

**Architecture:** `Compare` constructs `ChainedCompareSugar` only when it has more than one operator. The chain evaluates each next operand once, carries its reduced value into the following leg, asks the existing leg sugar to apply its law to reduced operands, and delegates non-final truth selection to the BoolOp short-circuit helper.

**Tech Stack:** Python 3.12, dataclasses, pytest, Sugar source tree and ExitSet outcome algebra.

## Global Constraints

- Work only in `/Users/tsavo/.herdr/worktrees/provekit/hockney-work` on `hockney/work`.
- `Compare._construct_sugar` is the only source-construction door for chained comparisons.
- Do not add categories, kinds, labels, global desugar caching, fabricated bindings, or per-call-site patches.
- Preserve existing per-leg equality, ordering, membership, identity, occurrence, and exceptional-exit owners.
- Run only focused local pytest teeth; do not run pandas walks, corpus scans, profiles, or broad pytest locally.
- Kujan merges; Hockney pushes the branch and never merges it.

---

### Task 1: Add falsifiable evaluate-once teeth

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/tests/test_chained_compare_evaluate_once.py`

**Interfaces:**
- Consumes: production `Compare.sugar()` result with ordered `.values` leg sugars.
- Produces: exact-count, left-to-right, short-circuit, per-leg-ownership, and
  semantic-effect teeth. The count, order, and semantic-effect assertions fail
  on the current BoolOp-of-pairs reduction.

- [ ] **Step 1: Write the shared-middle probe and production-chain fixture**

Use `SourceFile` to construct `0 < 1 < 2`, obtain its production Compare sugar, wrap the one shared middle sugar, and replace both adjacent leg references with that same wrapper:

```python
compare = next(node for node in tree.nodes() if isinstance(node, Compare))
chain = compare.sugar()
middle = _ProbeSugar(chain.values[0].right, evaluations)
first = replace(chain.values[0], right=middle)
second = replace(chain.values[1], left=middle)
instrumented = replace(chain, values=(first, second))
```

- [ ] **Step 2: Write the exact-count regression**

```python
outcome = instrumented.desugar(None)
assert isinstance(outcome, Complete)
assert evaluations == [1]
```

The production mutation caught is removal of the carried reduced-right value: the broken implementation appends twice.

- [ ] **Step 3: Write the observable semantic-effect regression**

Use a `_ChangingMiddleSugar` that returns `TermValue(1)` on its first desugar and `TermValue(2)` on its second. Assert `0 < middle() < 2` returns `TrueBoolLiteralSugar`; the broken implementation returns false because its second leg observes `2 < 2`.

- [ ] **Step 4: Write order, short-circuit, and ownership regressions**

Wrap all three operand sugars with labeled recording sugars. Assert the true
chain trace is exactly `left, middle, right`; assert a false first leg records
only `left, middle`; and assert a mixed `<` then `==` chain retains
`ComparisonOpSugar` then `EqualityOpSugar` legs.

- [ ] **Step 5: Run the focused file and verify RED**

Run:

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src:implementations/python/sugar-source-tree/src:implementations/python/sugar-lift-python-source/src /usr/local/opt/python@3.12/bin/python3.12 -m pytest -q implementations/python/sugar-lift-py-tests/tests/test_chained_compare_evaluate_once.py
```

Expected: three assertion failures for count `2`, the duplicated-middle order
trace, and the false semantic result, with all five tests collected. The
short-circuit and ownership floors already pass.

- [ ] **Step 6: Commit the red teeth**

```bash
git add implementations/python/sugar-lift-py-tests/tests/test_chained_compare_evaluate_once.py
git commit -m "Test chained Compare middle evaluation once"
```

### Task 2: Route chained Compare through one evaluate-once sugar

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/chained_compare_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/bool_op_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/comparison_op_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/equality_op_sugar.py`
- Modify: `implementations/python/sugar-source-tree/src/sugar_source_tree/nodes.py`

**Interfaces:**
- Consumes: adjacent `ComparisonOpSugar`/`EqualityOpSugar` legs with shared child sugar identity.
- Produces: `apply_reduced(left, right, ctx)` on each leg owner, a shared BoolOp truth-selection helper, and `ChainedCompareSugar(values, site)`.

- [ ] **Step 1: Extract BoolOp's existing truth-selection law**

Move the current formal-carrier truth dispatch, exact stopping operand return,
continuing callback, and undecided partition into the module-private function
`select_boolop_operand(value, *, op_kind, site, index, on_continue)`.

Keep `BoolOpSugar.desugar` behavior unchanged by calling the helper from its existing left-to-right fold.

- [ ] **Step 2: Let each comparison leg apply its law to reduced operands**

Add `apply_reduced(left, right, ctx)` to both existing leg types. `ComparisonOpSugar.desugar` evaluates its children and delegates to that method; `EqualityOpSugar.desugar` does the same. The new methods retain the current receiver projection, refinement coordinate, carrier, floor dispatch, and exceptional-exit code.

- [ ] **Step 3: Implement `ChainedCompareSugar`**

Evaluate `values[0].left` once. For each leg, evaluate `leg.right` once, call
`leg.apply_reduced(carried_left, right, ctx)`, return the final leg result raw,
and for non-final legs call `select_boolop_operand` with that comparison value,
`op_kind="And"`, the chain site, the leg index, and
`on_continue=lambda: reduce_from(index + 1, right)`. Delegate `to_term` to the
existing BoolOp-of-leg-pairs construction testimony so canonical testimony
does not drift.

- [ ] **Step 4: Wire the production Compare door**

Keep single-leg behavior unchanged. Replace only the multi-leg return in `Compare._construct_sugar`:

```python
return ChainedCompareSugar(values=pairs, site=self.fragment)
```

- [ ] **Step 5: Run the new focused teeth and verify GREEN**

Run the exact Task 1 pytest command. Expected: `2 passed`.

- [ ] **Step 6: Run focused existing BoolOp/Compare floors**

Run:

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src:implementations/python/sugar-source-tree/src:implementations/python/sugar-lift-python-source/src /usr/local/opt/python@3.12/bin/python3.12 -m pytest -q implementations/python/sugar-lift-py-tests/tests/test_bool_op_operand_sequence.py implementations/python/sugar-lift-py-tests/tests/test_boolop_middle_leg_control.py implementations/python/sugar-lift-py-tests/tests/test_chained_compare_production_instrument.py
```

Expected: all collected focused tests pass with no collection loss.

- [ ] **Step 7: Commit the implementation**

```bash
git add implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/chained_compare_sugar.py implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/bool_op_sugar.py implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/comparison_op_sugar.py implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/equality_op_sugar.py implementations/python/sugar-source-tree/src/sugar_source_tree/nodes.py
git commit -m "Evaluate chained Compare operands once"
```

### Task 3: Verify and hand off without merging

**Files:**
- Modify: none.

**Interfaces:**
- Consumes: committed focused fix.
- Produces: exact focused receipts, pushed `hockney/work`, and a Keyser handoff naming what is and is not measured.

- [ ] **Step 1: Run formatting and static diff checks**

Run `git diff --check HEAD~2..HEAD`. The repository has no mandatory Python
formatter hook for these files, so do not introduce a formatting-only rewrite.

- [ ] **Step 2: Re-run both focused pytest commands from Task 2**

Record the discovered/passed counts and exit codes. Do not quote a corpus or product delta.

- [ ] **Step 3: Push the branch**

```bash
git push -u origin hockney/work
```

- [ ] **Step 4: Notify Keyser with two enters**

Report branch `hockney/work`, exact focused counts on `HEAD`, the original `2 -> 1` middle-evaluation correction, and explicitly state that no pandas corpus delta or broad suite result is claimed.
