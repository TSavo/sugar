# Construction Panic Census Escape Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ConstructionPanic` propagate unchanged through the three unsanctioned census catches while preserving enrollment at the three sanctioned per-file audit membranes.

**Architecture:** Add a named, pure re-raise arm immediately before each existing broad catch. The existing broad catches remain the owner of ordinary instrument failures; no helper, compatibility category, or new membrane is introduced. Focused runtime teeth plant one panic object at each repaired entrance and prove object identity, then plant panics at the sanctioned roster, context-manager, and residual membranes and prove typed enrollment.

**Tech Stack:** Python 3, pytest, `monkeypatch`, the production `ConstructionPanic`/`ConstructionGap` types, and the in-process census scripts.

## Global Constraints

- Pinned base: `b1824eb6217fb92c5013743401bfe6edce2abcfa`.
- Only the named per-file audit enumerators or production typed-gap classification may hold a `ConstructionPanic`; production outside those membranes may only pure re-raise.
- Do not modify the four sanctioned membrane sites or the #7186 scanner.
- Do not widen `_instrument_failure_row` or add a helper that catches `ConstructionPanic`.
- Run focused tests locally with explicit `PYTHONPATH`; do not run broad pytest or take the battleaxe lease.

---

### Task 1: Pin the three unsanctioned catches red

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/tests/test_recensus_construction_panic_escape.py`

**Interfaces:**
- Consumes: `control_effect_recensus.terminal_after_measure_escape`, `control_effect_recensus.main`, and `recensus_enumerate_consumer.measure_file_via_enumerate`.
- Produces: three regression tests that require the exact planted `ConstructionPanic` instance to escape.

- [ ] **Step 1: Add a planted-panic factory and script loaders**

```python
def _panic(owner: str) -> ConstructionPanic:
    return ConstructionPanic(
        ConstructionGap(
            owner=owner,
            blame=f"fixture.py:{owner}",
            observed="planted census catch",
            requested="pure ConstructionPanic propagation",
            fix="pure re-raise outside the sanctioned audit membrane",
        )
    )
```

Load `recensus_enumerate_consumer` under its production module name before loading `control_effect_recensus`, so the latter's local imports receive the monkeypatched consumer object.

- [ ] **Step 2: Add the outer roster-escape identity tooth**

Monkeypatch `recensus_enumerate_consumer.demand_function_roster` to raise one planted object. Call `terminal_after_measure_escape` with a real one-function fixture and assert `pytest.raises(ConstructionPanic).value is planted`.

- [ ] **Step 3: Add the source-identity identity tooth**

Monkeypatch `sugar_lift_python_source.source_oracle.path_source` to raise one planted object. Call `measure_file_via_enumerate(..., contract_refs={})` and assert the raised object is the planted object.

- [ ] **Step 4: Add the main-file-producer identity tooth**

Create a one-file authenticated test corpus, derive `_PANDAS_3_0_3_AGGREGATE_HASH` and `_PANDAS_3_0_3_MANIFEST_SHAPE_CID` from it, monkeypatch the production consumer's `measure_file_via_enumerate` to raise one planted object, invoke the real `control_effect_recensus.main()` with that corpus, and assert the raised object is the planted object.

- [ ] **Step 5: Run the three teeth and record red**

Run unpiped:

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src:implementations/python/sugar-lift-python-source/src:implementations/python/sugar-source-tree/src \
  python -m pytest --noconftest -q \
  implementations/python/sugar-lift-py-tests/tests/test_recensus_construction_panic_escape.py \
  > /tmp/fenster-7185-red.log 2>&1
```

Expected on the pinned base: `3 failed, 3 passed`; roster escape is swallowed, source identity becomes an `instrumentFailure`, and main-file producer becomes an `instrumentFailure`, while the sanctioned controls enroll. Capture the direct pytest exit before reading the log. `--noconftest` is required because these script-only teeth do not need a Sugar binary and the package autouse fixture enters the unavailable build rung.

### Task 2: Prove the sanctioned membranes remain discriminating controls

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_recensus_construction_panic_escape.py`

**Interfaces:**
- Consumes: `recensus_enumerate_consumer.measure_file_via_enumerate` and its existing roster, context-manager-resolution, and residual demand doors.
- Produces: a parameterized three-case positive control proving those named membranes enroll rather than propagate.

- [ ] **Step 1: Add three membrane planters**

For each phase, monkeypatch only that production demand function to raise a planted panic while earlier phases return the minimum authenticated testimony needed to reach it:

```python
cases = (
    "roster",
    "context-manager-resolutions",
    "residual",
)
```

- [ ] **Step 2: Assert typed enrollment**

For each case, assert the call returns a row with `category == "panic"`, `terminalKind == "construction-panic"`, one `constructionPanics` entry, and payload fields matching the planted panic's owner and coordinate. The call must not raise.

- [ ] **Step 3: Run all six arms before production edits**

Run the same unpiped focused command. Expected: the three repaired-site teeth fail for their own propagation reason while all three sanctioned-membrane controls pass.

### Task 3: Pure re-raise at the three production entrances

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/scripts/control_effect_recensus.py`
- Modify: `implementations/python/sugar-lift-py-tests/scripts/recensus_enumerate_consumer.py`

**Interfaces:**
- Consumes: `sugar_lift_py_tests.gap.panic.ConstructionPanic`.
- Produces: exact identity propagation at all three unsanctioned catches; ordinary exception behavior is unchanged.

- [ ] **Step 1: Import the panic type in both scripts**

```python
from sugar_lift_py_tests.gap.panic import ConstructionPanic
```

- [ ] **Step 2: Repair both catches in `control_effect_recensus.py`**

Insert this arm immediately before the broad roster and main-file-producer handlers:

```python
except ConstructionPanic:
    raise
```

Do not modify the body of either existing `except BaseException` arm.

- [ ] **Step 3: Repair source identity in `recensus_enumerate_consumer.py`**

Insert the same pure re-raise arm immediately before its existing broad handler. Do not modify the sanctioned roster, context-manager, or residual handlers.

- [ ] **Step 4: Run the six-arm focused test green**

Run the Task 1 command unpiped. Expected: `6 passed`, exit `0`.

- [ ] **Step 5: Run the existing panic enrollment and catch-law teeth**

Run unpiped:

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src:implementations/python/sugar-lift-python-source/src:implementations/python/sugar-source-tree/src \
  python -m pytest --noconftest -q \
  implementations/python/sugar-lift-py-tests/tests/test_recensus_panic_collection.py \
  implementations/python/sugar-lift-py-tests/tests/test_construction_panic_catch_law.py \
  > /tmp/fenster-7185-existing.log 2>&1
```

Record the collected count and the direct pytest exit. The separately tracked #7186 repository scan is expected to remain red at seven stale candidates, including pure re-raises and sanctioned membranes; report it separately rather than changing it in this lane.

- [ ] **Step 6: Commit and push the topic branch**

Stage only the plan, the focused test, and the two scripts. Commit with `Purely propagate census construction panics`, push `fenster/7185`, and report the branch plus full 40-character SHA. Do not merge.

## Self-Review

- Spec coverage: all three unsanctioned sites propagate exact identity; all three sanctioned handler paths exercise enrollment; no permitted catch is widened.
- Placeholder scan: no deferred implementation or test step remains.
- Type consistency: every repaired arm catches the canonical `ConstructionPanic`; every control checks its authenticated serialized payload because a membrane intentionally converts the exception into testimony.
- Retirement path: these runtime teeth can retire when a typed census-result boundary makes `ConstructionPanic` uncatchable by ordinary instrument-failure handlers; Python's current exception hierarchy cannot encode that distinction at compile time.
