# Worker brief: land Option A for len-as-coordinate (PR #3900) + fix the witness-harness non-hermeticity that blocks it

## The one-paragraph stakes

`len(x)` must be the opaque coordinate `call:len(<x>)` **everywhere** — assertion, argument, and inside dug function bodies — grounded by a *derived fact* `call:len(<x>) == N`, never *collapsed* to the scalar `N`. This is the founding principle of the whole change: **the floor emits a fact, not a substitution; the coordinate never collapses** (recomputable-artifact doctrine — keep the construction, don't bake in the answer). Option A is the only representation that (a) is uniform — the alternative "scalar in bodies" is *already* two-behaviored inside bodies because `len(vendor_call)` is uncountable and forces the coordinate anyway; and (b) lets `len` facts thread through function boundaries by congruence (the cross-library composition story). **Do NOT implement or reintroduce "Option B" (scalar-in-bodies). A is decided.**

## Current state — A is IMPLEMENTED and green in isolation

Branch: `rhs-callsite-coordinate-unify` (PR #3900). Relevant commits, oldest first:
- `939e46e3e` — the floor-honest change: `OpaqueOpCallsite`, `len` construction/symbolic floors emit `call:len(<x>)` (was `py.len` / scalar collapse), companion derived fact on the assertion RHS.
- `a5cf63b30` — `OpaqueOpCallsite._downstream()`: a counted `len` acts as its value for arithmetic/format; an opaque `len` acts as `SymbolicValue(call:len(<x>))`. Fixes 2 numpy floor panics (`format_value_with`, `binary_operator_with` on the opaque case).
- `5e4cc454f` — **Option A itself**: body-dig collects counted `OpaqueOpCallsite` returns (`ControlFlowBodySugar.opaque_returns`) and emits, at universe mint, a separate Derived companion `call:len(...) == N` per counted return. Universe post stays `out == call:len(...)`; a co-located `A() == N` floor fact preserves the `{Stated,Derived}` euf-key sharing so lying twins still refute.
- `d04eb1d1c` — re-blessed the 4 `test_builtin_call_sugar` len goldens (`py.len`→`call:len`, array-literal len is the coordinate carrying `computed`).

**Verified GREEN in isolation (solo, fresh `.sugar`):** every one of the 10 `test_literal_call_residue_rows_emit_derived_fact_and_refute_lie` params (including the 3 len seeds — truthful→sat, lying→**unsat**, refuted through the grounding chain), `test_comprehension_cardinality_bad_twins_refute`, `test_literal_list_comp_bad_twin_flips`, `test_list_literal_shape_has_one_verdict_bearing_owner`, `test_installed_numpy_totality_gate_is_stable_zero`, and all of `test_builtin_call_sugar`.

**No residue-instrument re-model is needed.** A's co-located floor fact preserves the `{Stated,Derived}` shape; the tests pass as-is when run in isolation. (An earlier belief that a re-model was required came from a *polluted* aggregate run — see below.)

## THE ACTUAL BLOCKER: the witness harness is not hermetic

Solo, everything passes. **Aggregate runs fail** — and they fail non-deterministically depending on how much `.sugar` has accumulated:
- Full delta with pre-accumulated `.sugar`: ~10–19 "failures", including `lie→sat` (a lie not refuted) on seeds that have nothing to do with `len` (`format_int`, `object_equality`, `divmod`, `tuple_*`).
- Same delta with `.sugar` deleted immediately before: `5 failed, 17 passed`.
- Each test run solo in its own fresh `.sugar`: **100% pass.**

Root cause (confirmed empirically — moving the repo-root `.sugar` aside makes a solo `format_int` flip from `lie→sat` back to pass): **the sugar binary resolves its persistent component/self-lift pool relative to its own repo-root location, NOT the per-project `.sugar` the harness stages with `cwd=project`.** So `_stage_cli_project` (witness_harness.py:90) writes an isolated `project/.sugar/{config.toml,components,lift}` and runs `mint`/`prove` with `cwd=project` (lines 259/272) — but the binary ignores that and reads/writes one shared pool. Every witness test's minted facts leak into it. A's content-addressed `call:len(array(1,2,3)) == 3` coordinate facts are *identical across tests*, so a truthful test's fact and a later lying test's conflicting fact both land in the shared pool → the pool is internally inconsistent → consistency checks return garbage (`lie→sat`). Pre-A (scalar) facts alias less, which is why this was latent on `main`. **A exposes a pre-existing non-hermeticity bug; it does not cause it.**

## The work, in order

### 1. Fix the harness/binary hermeticity (the real task; unblocks green CI + corpus)
Make each witness invocation use an **isolated pool** so tests cannot contaminate each other. Investigate the sugar CLI's pool/home resolution (start: `bin/sugarbin`, the rust `sugar-cli` prove/mint path, wherever `.sugar/components` and `.sugar/self-lifts` are read). The fix is one of:
- Have the binary resolve its pool from the **invocation cwd / project `.sugar`** (which the harness already stages) rather than the binary's own repo root; OR
- Add an explicit pool/home override (`--pool-dir` flag or `SUGAR_HOME`/`SUGAR_POOL` env) and have `witness_harness.py` point every mint/prove at `project/.sugar`.
Prefer whichever keeps ONE door for pool resolution (no dual path). Acceptance: the **full aggregate** delta below passes on a fresh worktree, and re-running it twice in a row still passes (no cross-run accumulation).

### 2. Verify A green in aggregate (fresh worktree, post-fix)
On a clean checkout (no pre-existing `.sugar`), the full delta must pass:
```
test_comprehension_sugar.py::test_comprehension_cardinality_bad_twins_refute
test_list_comp_sugar.py::test_literal_list_comp_bad_twin_flips
test_sugar_witness_instruments.py::test_list_literal_shape_has_one_verdict_bearing_owner
test_sugar_witness_instruments.py::test_literal_call_residue_rows_emit_derived_fact_and_refute_lie
test_numpy_pandas_panic_audit.py::test_installed_numpy_totality_gate_is_stable_zero
test_builtin_call_sugar.py
```
Hard invariant: **zero `lie→sat`** (grep the trace for `assert 'sat' == 'unsat'` at `test_sugar_witness_instruments.py:1068` — must not appear). A lie returning sat is the cardinal failure.

### 3. Full witness corpus on battleaxe
Run the witness sat/unsat corpus (`test_witness_verify` + `test_sugar_witness_instruments` + `test_witness_oracle`) via `bin/bpytest` on battleaxe AFTER `cargo build --workspace --bins` on the remote (unbuilt component bins give false reds). Must be fully green with the hermeticity fix.

### 4. File the hermeticity bug as its own GitHub issue
It is a pre-existing, general test-infra defect (the witness suite isn't hermetic; the CLI pool resolution ignores per-project isolation). Track it separately even though this PR fixes it, so the "why" is recorded. Reference PR #3900.

## Gotchas / hard rules
- **Never trust an aggregate witness run as a soundness signal.** Until hermeticity is fixed, only *solo, fresh-`.sugar`* runs are meaningful. The entire multi-day debugging spiral on this PR was polluted aggregate runs lying (three separate false "A/B broke soundness" conclusions, all `.sugar` pollution).
- Run pytest with `--import-mode=importlib` and prime `import sugar_lift_py_tests.factory; import sugar_lift_py_tests.context` before `pytest.main` (there is a pre-existing collection-order circular import: `context` ↔ `factory`; priming `factory` first dodges it). Deps: `blake3 pynacl cbor2 numpy pandas scikit-learn pytest`, editable install of `sugar-lift-py-tests`.
- Do **not** collapse the coordinate anywhere. `len([1,2,3])` in a body must stay `out == call:len(array(1,2,3))` + Derived `call:len(array(1,2,3)) == 3`. If you find yourself substituting `3` for the coordinate, that's Option B — stop.
- Do **not** re-model `test_literal_call_residue_rows_emit_derived_fact_and_refute_lie` — it passes solo; if it fails only in aggregate, that's the harness bug, not the test.
- The sugar binary is content-addressed by a stamp; a python-only change does not change the binary (same stamp on main and this branch). If binaries differ, something else is wrong.

## What to read first
- `SHARED-LANGUAGE.md` (repo root) — lift/lower vocabulary.
- This PR's design doc: `docs/superpowers/specs/2026-07-08-rhs-callsite-coordinate-unification-design.md`.
- `floor/opaque_op_callsite.py` (the value), `sugar/control_flow_body_sugar.py` + `factory/literal_call_report.py` `_opaque_op_companion_facts` (A's grounding), `witness_harness.py` `_stage_cli_project`/`mint_and_prove` (the non-hermetic invocation).

## Verify commands (solo pattern that is known-good)
```
cd implementations/python/sugar-lift-py-tests
rm -rf ../../../.sugar   # or the repo-root .sugar of the worktree
uv run --no-project --python 3.14 --with blake3 --with pynacl --with cbor2 \
  --with numpy --with pandas --with scikit-learn --with pytest --with-editable . \
  python -c "import sugar_lift_py_tests.factory; import sugar_lift_py_tests.context; import pytest,sys; \
  sys.exit(pytest.main(['--import-mode=importlib','-p','no:cacheprovider','-q','<TEST::ID>']))"
```
The definition of done: the full aggregate (step 2) passes on a fresh worktree, twice in a row, with zero `lie→sat`, and the battleaxe corpus is green.
