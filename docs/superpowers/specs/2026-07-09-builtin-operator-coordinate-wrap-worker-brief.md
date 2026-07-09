# Worker brief: coordinate-ize builtin operators via ONE wrap (not per-operator)

**Task:** make every pure builtin *operator* a `call:<op>(<args>)` coordinate, uniformly, by wrapping once at the recognition point — `BuiltinCallSugar`. `len` (#3900) becomes the first instance of the general rule, not a special case.

**Base:** `main` (post #3900 Option A + #3903 hermeticity — both merged, so the suite is hermetic; solo-first discipline still applies).

## The principle (same as len)
A builtin operator is an uninterpreted symbol carried in the coordinate name; its value is a *derived fact*, never a substitution; the coordinate never collapses. Today these produce the wrong shapes — `py.str`/`py.int`/`py.format` on opaque args (a *different symbol* than `call:`, so congruence can't join), and bare folds on concrete args (the collapse we rejected). One rule fixes both.

## The rule — one wrap, at `BuiltinCallSugar._build`
```
result = perform_operation(op, arg, ...)
return OpaqueOpCallsite(callee=self.name, arg=argument,
                        computed = result if it folded to a concrete value else None)
```
`OpaqueOpCallsite.callee` is already generic; `_downstream()`, `_opaque_op_companion_facts`, and Option-A body-dig all read `callee`/`computed` generically. So this wrap is the whole mechanism. Everything that looked per-operator falls out:
- **Sort** is read from `computed`'s own value (`str(12)`→`StringValue`→String companion; `len(...)`→`TermValue`→Int). No sort table.
- **`hash`/opaque** → the op returns a symbolic result → `computed=None` automatically. Never fabricate a hash.
- **`str(12)` folds** → op returns concrete `StringValue` → `computed` set automatically.
- **The `StrCoercion`/`__int__`/`format` entry points** all funnel back through `_build`'s single `return` — the one wrap site.

## It's *less* code
- **Delete** the `py.str`/`py.format`/`py.int` productions in `symbolic_value.py` — replaced by the uniform `call:<op>` from the wrap.
- **Subsume** len's dedicated `__len__`→`OpaqueOpCallsite` handlers (array/tuple/set/dict/symbolic) into the general wrap — len stops being special. Do this as a refactor step, re-running the len corpus (55/55) to prove no regression, BEFORE extending to other ops.

## FIRST CHECK (the one genuine decision, made once)
Partition the owned builtin set — **only pure value operators become coordinates.** From the actual set (`_BUILTIN_DUNDER_METHODS` + `str`/`next`/`dir` + `GetattrBuiltinSugar`/`DivmodBuiltinSugar`/`FormatBuiltinSugar`):

- **Coordinate (pure value op):** `abs round floor ceil trunc int float complex operator.index len hash repr bytes str format divmod` — deterministic functions of their args; `call:<op>(args)` is a meaningful join point.
- **LEAVE AS-IS (stateful / lazy / reflective):** `next` (advances an iterator, has state), `reversed` (lazy iterator), `dir` (runtime attribute inventory), `getattr` (runtime attribute access — already has a runtime-boundary path). Coordinate-izing these is noise or wrong; keep their current effect/runtime handling.

Confirm this partition against the owned set before flipping the whole thing. If any pure-value op has a reason to stay concrete, name it.

## The one predicate to implement
"Did the op fold to a concrete value or a symbolic one?" — `computed = result if concrete else None`. The op already returns distinguishable types (concrete `StringValue`/`TermValue`/`BoolValue` vs symbolic `SymbolicValue`/`OpaqueOpCallsite`), so it's a clean type check at the wrap site. Decide it once.

## Verify (hermetic, solo-first)
- Refactor len onto the general wrap first → len corpus 55/55 unchanged before extending.
- Then the wrap covers all pure-value ops at once. Re-bless the `py.*` goldens (`test_builtin_call_sugar.py` — the len re-bless is the pattern).
- Solo-per-test first; aggregate green; **zero `lie->sat`**.
- numpy/pandas totality gate: `str`/`int`/`repr` are everywhere in numpy tests — expect a few new construction gaps surfaced (like len surfaced nested-ClassDef); drain or file each.
- Battleaxe witness corpus (`bin/bpytest test_witness_verify test_sugar_witness_instruments test_witness_oracle` after `cargo build --workspace --bins`) green.

## Hard rules
- **Never collapse the coordinate** (`str(12)` = `call:str(12)` + computed `"12"`, not bare `"12"`).
- **Never fabricate a value for a non-folding op** (`hash` = `computed=None`).
- **One door / no dual path** — the wrap is the only place a builtin operator result is produced.
- **Refactor len first, prove 55/55, then extend** — don't flip everything blind.
- pytest: `--import-mode=importlib`, prime `import sugar_lift_py_tests.factory; import sugar_lift_py_tests.context` before `pytest.main` (collection-order circular import). Deps: `blake3 pynacl cbor2 numpy pandas scikit-learn pytest`, editable `sugar-lift-py-tests`.

## What to read
- #3900 template: `floor/opaque_op_callsite.py`, `_opaque_op_companion_facts` + Option-A body-dig in `literal_call_report.py`/`control_flow_body_sugar.py`, re-blessed `test_builtin_call_sugar.py`.
- `sugar/builtin_call_sugar.py` (`_build`, `_BUILTIN_DUNDER_METHODS`, `_OWNED_BUILTIN_CALLS`, the `str`/`next`/`dir`/`getattr`/`divmod`/`format` paths) — the single wrap site and owned set.
- `floor/{symbolic_value,string_value,term_value}.py` — where `py.*`/bare folds are produced today (to be deleted/subsumed).
