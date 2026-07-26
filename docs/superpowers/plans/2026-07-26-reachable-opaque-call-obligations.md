# Reachable Opaque-Call Obligations Implementation Plan

> **For Codex:** Execute this plan inline with `superpowers:executing-plans`. Keep
> the red/green order; do not add a vendor-name admission arm or run a census.

**Goal:** Let authenticated source construction defer an unresolved named call
to its exact source coordinate, so ordinary Sugar reachability admits the real
`pytest.raises(...)` context-manager route while the reachable legacy callable
route stays typed-loud.

**Architecture:** `sugar-lift-python-source` discovers and parks immutable
`OpaqueSourceCallObligationV1` rows in the lower
`TreeConstructionContextV1`. `sugar-source-tree` consumes a row at the start of
`Call._construct_sugar`, before spread-call selection, and returns the existing
typed `CallSiteSugar` refusal. Ordinary Sugar construction remains the only
reachability engine; unreachable rows remain in the context table.

**Tech Stack:** Python 3, pytest, Rust/Cargo package wrapper where required,
existing `SourceFile`/Sugar construction and manager-summary derivation.

---

## Task 1: Pin the Real Truthful and Lying Twins

**Files:**

- Modify: `implementations/python/sugar-lift-python-source/tests/test_sole_path_manager_construction.py`
- Reference: `implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/manager_construction.py`

- [ ] **Step 1: Add a shared real-pytest source-derived setup**

  Add a small test helper that writes a consumer module, constructs a
  `TreeConstructionContextV1`, calls
  `populate_source_derived_resource_refs`, and returns the tree and context.
  It must use the installed authenticated `pytest` distribution path; do not
  inject a hand-built contract table.

- [ ] **Step 2: Replace the broad opaque-builtin test with the truthful twin**

  Use:

  ```python
  import pytest

  def use_boundary():
      with pytest.raises(ValueError, match="boom"):
          raise ValueError("boom")
  ```

  Assert the exact pre-patch result is
  `ContextManagerResolutionGapV1(kind="opaque-call-target:func", ...)`.
  Then state the post-patch assertions in the same test: the reference is
  `SourceDerivedContextManagerRefV1`, its semantics are
  `EffectBoundarySemanticsV1`, `with_node.sugar()` is
  `WithEffectBoundarySugar`, and reduction completes the matching raise.

- [ ] **Step 3: Add the lying legacy-callable twin**

  Use a real authenticated call shaped as
  `pytest.raises(ValueError, func)`. Assert reduction reaches a
  `SugarNotWritten`/typed construction refusal whose observed value contains
  exactly `opaque-call-target:func`; do not accept arbitrary exceptions.

- [ ] **Step 4: Pre-resolve the test binary with builds forbidden**

  Resolve the `python-lift` cap once with
  `SUGAR_BINARY_ALLOW_BUILD=0`. If the shelf is stale, stop and repair the
  binary explicitly instead of allowing every test to enter the 600-second
  fixture build path.

- [ ] **Step 5: Record the truthful twin red on the unpatched production tree**

  With production files still byte-identical to base
  `e0350dc43693cd86ac14017f7e72729e907d1c36`, run:

  ```bash
  python -m pytest -q \
    implementations/python/sugar-lift-python-source/tests/test_sole_path_manager_construction.py \
    -k 'pytest_raises and truthful'
  ```

  Expected: FAIL because the returned resolution is the named
  `opaque-call-target:func` gap rather than a source-derived EffectBoundary.
  Save the exact command, base SHA, and failure line for the PR body.

- [ ] **Step 6: Run the lying twin before production changes**

  ```bash
  python -m pytest -q \
    implementations/python/sugar-lift-python-source/tests/test_sole_path_manager_construction.py \
    -k 'pytest_raises and lying'
  ```

  Expected: PASS only if it asserts the exact typed refusal.

- [ ] **Step 7: Commit the red tests**

  ```bash
  git add implementations/python/sugar-lift-python-source/tests/test_sole_path_manager_construction.py
  git commit -m "test: pin reachable opaque source call twins" \
    --trailer "Co-authored-by: WOPR <evilgenius@nefariousplan.com>" \
    --trailer "Signed-off-by: WOPR <evilgenius@nefariousplan.com>"
  ```

## Task 2: Add the Typed Obligation Transport

**Files:**

- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/context_manager_resolution.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_context_manager_resolution.py`

- [ ] **Step 1: Write transport law tests**

  Add tests that construct an immutable
  `OpaqueSourceCallObligationV1(coordinate, target_name, resolved_object_cid)`
  and verify:

  - `TreeConstructionContextV1.opaque_source_call_obligations` starts empty;
  - `for_source_call_construction` preserves an explicitly supplied table;
  - a frozen obligation cannot be mutated;
  - its coordinate and authenticated owner CID remain inspectable.

- [ ] **Step 2: Run the new tests red**

  ```bash
  python -m pytest -q \
    implementations/python/sugar-lift-py-tests/tests/test_context_manager_resolution.py \
    -k opaque_source_call_obligation
  ```

  Expected: FAIL because the type and table do not exist.

- [ ] **Step 3: Add the minimum transport type and table**

  Implement:

  ```python
  @dataclass(frozen=True)
  class OpaqueSourceCallObligationV1:
      coordinate: SourceFragmentCoordinateV1
      target_name: str
      resolved_object_cid: str
  ```

  Add `opaque_source_call_obligations: dict = field(default_factory=dict)` to
  `TreeConstructionContextV1`, and add the optional explicit table argument to
  `for_source_call_construction`. Do not serialize it or turn it into a call
  resolution.

- [ ] **Step 4: Run the focused transport tests green**

  Run the Step 2 command. Expected: PASS.

- [ ] **Step 5: Commit the transport**

  ```bash
  git add \
    implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/context_manager_resolution.py \
    implementations/python/sugar-lift-py-tests/tests/test_context_manager_resolution.py
  git commit -m "feat: carry opaque source call obligations" \
    --trailer "Co-authored-by: WOPR <evilgenius@nefariousplan.com>" \
    --trailer "Signed-off-by: WOPR <evilgenius@nefariousplan.com>"
  ```

## Task 3: Park Obligations During Authenticated Frame Preparation

**Files:**

- Modify: `implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/manager_construction.py`
- Modify: `implementations/python/sugar-lift-python-source/tests/test_sole_path_manager_construction.py`

- [ ] **Step 1: Add manager-construction law tests**

  Add a small source fixture with one unreachable unresolved named call and
  assert frame preparation returns a frame while the exact coordinate retains
  one obligation. Add mutation-sensitive tests that:

  - reject two different obligations at one coordinate;
  - reject installing a source-call frame where an obligation exists;
  - reject installing an obligation where a source-call frame exists;
  - leave a source-resolvable external callee on the existing real-frame path.

- [ ] **Step 2: Run the new parking tests red**

  ```bash
  python -m pytest -q \
    implementations/python/sugar-lift-python-source/tests/test_sole_path_manager_construction.py \
    -k 'opaque_call_obligation or source_resolvable_external'
  ```

  Expected: FAIL because eager `_opaque_call_targets` still aborts the whole
  frame and no obligation table is populated.

- [ ] **Step 3: Replace eager aborts with checked coordinate installs**

  Change `_opaque_call_targets` to return exact `(Call, target_name)` demand
  rows. When `_resolve_external_call_frame` returns `None`, install
  `OpaqueSourceCallObligationV1` at `_call_coordinate(call)` instead of
  returning `ManagerConstructionGapV1`.

  Centralize checked installs:

  ```python
  def _install_opaque_call_obligation(context, call, obligation): ...
  def _install_source_call_frame(context, call, frame): ...
  ```

  An identical duplicate obligation is idempotent. Differing testimony or a
  frame/obligation collision raises `BackendDefect`. Preserve source-frame
  recursion and builtin handling unchanged.

- [ ] **Step 4: Run the parking laws green**

  Run the Step 2 command. Expected: PASS.

- [ ] **Step 5: Commit frame preparation**

  ```bash
  git add \
    implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/manager_construction.py \
    implementations/python/sugar-lift-python-source/tests/test_sole_path_manager_construction.py
  git commit -m "feat: park unresolved source calls by coordinate" \
    --trailer "Co-authored-by: WOPR <evilgenius@nefariousplan.com>" \
    --trailer "Signed-off-by: WOPR <evilgenius@nefariousplan.com>"
  ```

## Task 4: Consume Only Reached Obligations

**Files:**

- Modify: `implementations/python/sugar-source-tree/src/sugar_source_tree/nodes.py`
- Modify: `implementations/python/sugar-source-tree/tests/test_formal_substitution_coordinate.py`

- [ ] **Step 1: Add direct `Call.sugar` reachability tests**

  Construct a tree whose context has an obligation for one exact call. Assert:

  - that call returns `CallSiteSugar` with
    `contract_resolution_gap == "opaque-call-target:func"`;
  - desugaring raises `SugarNotWritten` with that exact observed reason;
  - an unrelated call follows the existing path;
  - a spread call with an obligation refuses before `SpreadCallSugar` can
    absorb it.

- [ ] **Step 2: Run the source-tree tests red**

  ```bash
  python -m pytest -q \
    implementations/python/sugar-source-tree/tests/test_formal_substitution_coordinate.py \
    -k opaque_call_obligation
  ```

  Expected: FAIL; current `Call._construct_sugar` selects spread construction
  before it consults any coordinate table.

- [ ] **Step 3: Move coordinate lookup to the start of `Call._construct_sugar`**

  Build the exact `SourceFragmentCoordinateV1` once before `has_spread`.
  If the context table contains an obligation, return a `CallSiteSugar` with:

  ```python
  target_name="python:unresolved-source-call"
  contract_resolution_gap=f"opaque-call-target:{obligation.target_name}"
  ```

  Construct its argument/keyword sugars normally so reached arguments retain
  ordinary semantics. Do not delete the obligation. Then continue through
  spread, preconstruction resolution, source frame, and ordinary call paths
  unchanged when no obligation exists.

- [ ] **Step 4: Run the source-tree tests green**

  Run the Step 2 command. Expected: PASS.

- [ ] **Step 5: Commit reached-coordinate consumption**

  ```bash
  git add \
    implementations/python/sugar-source-tree/src/sugar_source_tree/nodes.py \
    implementations/python/sugar-source-tree/tests/test_formal_substitution_coordinate.py
  git commit -m "feat: refuse opaque calls only when reached" \
    --trailer "Co-authored-by: WOPR <evilgenius@nefariousplan.com>" \
    --trailer "Signed-off-by: WOPR <evilgenius@nefariousplan.com>"
  ```

## Task 5: Close the Real Assertion-With Milestone

**Files:**

- Modify:
  `implementations/python/sugar-lift-python-source/tests/test_sole_path_manager_construction.py`
- Verify only: all files changed in Tasks 1-4

- [ ] **Step 1: Run truthful and lying twins together**

  ```bash
  python -m pytest -q \
    implementations/python/sugar-lift-python-source/tests/test_sole_path_manager_construction.py \
    -k pytest_raises
  ```

  Expected: truthful source-derived EffectBoundary PASS; lying twin PASS
  because it observes exactly `opaque-call-target:func`. Inspect the context
  table in the truthful test and confirm the unreachable obligation remains.

- [ ] **Step 2: Run all three affected Python package suites**

  Run each package separately and print its terminal summary:

  ```bash
  python -m pytest -q implementations/python/sugar-lift-py-tests/tests
  python -m pytest -q implementations/python/sugar-lift-python-source/tests
  python -m pytest -q implementations/python/sugar-source-tree/tests
  ```

  The third package is required because `Call._construct_sugar` changes there,
  even though the initial ownership correction named only the two lift
  packages. Record pre-existing failures separately per package.

- [ ] **Step 3: Run any Cargo-backed owning-package leg without fail-fast**

  Use the repository's `python-lift` task/cap and `--no-fail-fast`, preserving
  per-target result lines. Name the known main failure
  `sugar::term_dispatch::tests::predicate_visitor_folds_nested_deref_bitand_comparison_floor`
  separately; do not let it hide later targets.

- [ ] **Step 4: Verify focused crash and timeout axes**

  Confirm every truthful/lying run completed with zero crashes and zero
  timeouts. This is reproducer-shaped verification only; do not launch a
  corpus sweep, scoreboard, or census.

- [ ] **Step 5: Self-review**

  ```bash
  git diff e0350dc43693cd86ac14017f7e72729e907d1c36 --check
  git diff --stat e0350dc43693cd86ac14017f7e72729e907d1c36
  rg -n "pytest|raises" \
    implementations/python/sugar-lift-py-tests/src \
    implementations/python/sugar-lift-python-source/src \
    implementations/python/sugar-source-tree/src
  git status --short
  ```

  Inspect every new production hit: there must be no pytest/name admission
  arm, no obligation deletion, no second evaluator, no debug code, and no
  unrelated changes.

- [ ] **Step 6: Verify trailers and exact final state**

  ```bash
  git log --format=full -5
  git rev-parse HEAD
  ```

  Every new commit must contain identical WOPR `Co-authored-by` and
  `Signed-off-by` trailers. Attribute all test results to the printed HEAD.

- [ ] **Step 7: Publish the completion receipt**

  Report the red base SHA and named failure, final commit SHA, truthful and
  lying results, parked-obligation inspection, each package summary, known
  pre-existing failures, and crash/timeout zeros. Mention Fizz in the completed
  result. Do not claim a census delta.
