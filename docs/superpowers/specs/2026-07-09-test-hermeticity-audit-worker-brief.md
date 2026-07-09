# Worker brief: make the whole Python test suite hermetic (generalize the witness fix) — closes #3902

## Stakes (read this first)

A shared, ambient sugar pool poisoned this project's tests for *days*. Three separate "Option A broke soundness" conclusions were all one cause: witness tests read a repo-root `.sugar` component/self-lift pool that **accumulated facts across tests**, so a later test's `prove` saw an earlier test's contradictory facts and returned garbage (a lie coming back `sat`). The hard rule that came out of it: **an aggregate witness run is not a soundness signal until the suite is hermetic.** You are making it hermetic so no one loses days to this again.

`fd68df29c` (PR #3900) fixed exactly ONE entry point — `witness_harness.py`'s mint/prove — via an exclusive `SUGAR_HOME` component-discovery door (`component_plan.rs`: when `SUGAR_HOME` is set, only `$SUGAR_HOME/components`, `project/.sugar/components`, and explicit `SUGAR_COMPONENT_PATH` are searched; system / exe-relative / ancestor / `~/.config` roots are suppressed). **Every other test path that shells out to the sugar binary still shares the ambient pool.** Generalize the fix.

## The mechanism you're closing (so you can recognize it)

- The sugar binary, absent `SUGAR_HOME`, resolves its persistent component/self-lift pool relative to its own repo-root location, ignoring the invocation cwd. So per-test `tmp_path/.sugar` isolation is defeated.
- Symptom: **solo runs pass, aggregate runs fail non-deterministically** (worse the more `.sugar` has accumulated). Look for `assert 'sat' == 'unsat'` at `test_sugar_witness_instruments.py:1068` (a lie not refuted) and `statuses=['refused']` — both are pool contamination, not real defects.
- Second, separate axis: the numpy/pandas panic audit (`idd/collect_panic_audit.py`) uses a `~/.cache/sugar/python-panic-audit-workspaces/<hash>/` workspace cache. That's a legitimate content-addressed cache, NOT the pool — do not "fix" it into per-test isolation, but DO confirm its hash keys correctly on the installed numpy/pandas version so a stale workspace can't mask a real lift gap.

## The work

### 1. Audit every test that shells out to the sugar binary / mint / prove
Start from the surface (tests importing subprocess / `resolve_sugar_binary` / `resolven` / `mint_and_prove` / `run_source_through_real_solver` / `ensure_sugar_bin` / `_stage_cli_project`). Known list includes at least:
`test_sugar_witness_instruments.py` (fixed), `test_comprehension_sugar.py`, `test_list_comp_sugar.py`, `test_try_sat_unsat.py`, `test_pandas_sugar_gaps.py`, `test_literal_base64_showcase.py`, `test_joined_str_sugar.py`, `test_ord_sugar.py`, `test_truthy_assertion_sugar.py`, `test_membership_assertion_sugar.py`, `test_projected_equality_assertion_sugar.py`, `test_numpy_literal_call_sibling_red.py`, `test_numpy_fft_membrane.py`, `test_binary_handoff_policy.py`, `test_python_component_plan.py`, `test_python_factory_kernel.py`, plus `idd/collect_panic_audit.py` / `idd/numpy_wall.py` / `idd/pandas_wall.py`.
For each: does it mint/prove against an isolated `SUGAR_HOME=tmp_path/.sugar` with ambient `SUGAR_COMPONENT_PATH` dropped and stale `*.proof` cleared before mint (the `witness_harness.py` recipe)? If not, it can leak.

### 2. Make isolation the default, not per-call boilerplate — ONE door
Do NOT copy the `SUGAR_HOME` dance into 20 test files. Put it in ONE place they all route through:
- Prefer a single helper / fixture (e.g. a `conftest.py` autouse fixture or a `hermetic_project(tmp_path)` helper) that stamps `SUGAR_HOME=tmp_path/.sugar`, drops `SUGAR_COMPONENT_PATH`, and clears stale `*.proof`, and have every mint/prove entry point (`mint_and_prove`, `run_source_through_real_solver`, `resolve_sugar_binary` invocations, the idd wall drivers) go through it.
- Answer the isolation question ONCE in a strong place; a test that forgets to isolate should be *unable* to leak, not merely discouraged. If a test constructs its own project dir, the helper is where `SUGAR_HOME` gets set.

### 3. Add a regression guard that FAILS if the ambient pool leaks
The bug was invisible because nothing tested for it. Add a test that:
- plants a *poisoned* fact in a repo-root `.sugar/components` (or wherever the ambient pool lives) — e.g. a fact that would make a known-lying witness discharge,
- runs a hermetic lying witness that MUST return `unsat`,
- asserts it still returns `unsat` (i.e. the poison was NOT read).
This test must be red on `fd68df29c`-minus-your-generalization for the not-yet-fixed entry points, and green after. It is the thing that keeps the suite hermetic forever.

### 4. Verify
- Full aggregate of the previously-flaky set passes **twice in a row without clearing `.sugar` between runs**, zero `assert 'sat' == 'unsat'`.
- The numpy/pandas panic-audit gate stays green (don't regress the workspace cache).
- On battleaxe via `bin/bpytest` after `cargo build --workspace --bins`: `test_witness_verify.py test_sugar_witness_instruments.py test_witness_oracle.py` fully green.

### 5. Close #3902 with the generalization + the regression guard as the receipt.

## Hard rules / gotchas
- **Do not touch Option A semantics or the len coordinate model.** This is pure test-infra hermeticity. If a witness verdict changes, that's a hermeticity bug you introduced, not a model change.
- Run pytest with `--import-mode=importlib` and prime `import sugar_lift_py_tests.factory; import sugar_lift_py_tests.context` before `pytest.main` (pre-existing `context`↔`factory` collection-order circular import; priming `factory` first dodges it). Deps: `blake3 pynacl cbor2 numpy pandas scikit-learn pytest`, editable `sugar-lift-py-tests`.
- Solo-per-test is the only trustworthy signal until your guard is in place — measure there first.
- ONE door, no dual path (governing rule): don't leave both an ambient-pool path and an isolated path resolvable; when `SUGAR_HOME` is the isolation mechanism, make it the *only* one the tests use.

## What to read
- `fd68df29c` diff — `component_plan.rs` (the exclusive door) and `witness_harness.py` (the recipe: SUGAR_HOME + drop SUGAR_COMPONENT_PATH + clear stale *.proof).
- `witness_harness.py` `_stage_cli_project` / `mint_and_prove` — the reference isolated invocation.
- `idd/collect_panic_audit.py` — the workspace-cache axis (confirm keying, don't over-isolate).
- Issue #3902 — the tracking issue this closes.
