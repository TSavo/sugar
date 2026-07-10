# Probe: Chained call Obligation seam (`array(x).sum()`)

**Date:** 2026-07-11  
**Mode:** PROBE ONLY — no production code change  
**Law:** `match(Sugar){ Some => cite_or_effect, None => panic!() }` (post-#4035)  
**Lane:** Part of #4016 / #3809  

---

## 0. Question answered

Can we replace inline `force_floor` composition in `CallSiteValue.call_method_with` with
`Obligation{post: Post_receiver, pre: Pre_method}` (`post ⊃ pre`), quantify over the
receiver universe, and mint at composite coordinate `array.sum` — so
`assert np.array([1,2,3]).sum() == 6` swims and the lying twin refuses?

---

## 1. Seam confirmation (cited sites)

| Site | Role |
|------|------|
| `CallSiteValue.call_method_with` (`implementations/python/sugar-lift-py-tests/.../floor/call_site_value.py:116-138`) | Unconditional `force_floor(..., project_callsite=False)` then `perform_operation(receiver=floor, operation=<method>)` |
| `CallSiteValue.force_floor` (`:140-223`) | Dig body; gaps → `_force_floor_gap` → `factory_panic` → `os._exit(1)` (`:299-333`) |
| `mint_universe` (`.../factory/literal_call_report.py:3292-3320`) | Digs a **FunctionDef** by name; mints `FunctionContract`; keys `callable_contracts[bridge_source_symbol]` (e.g. `call:<name>`) |
| `Obligation.as_implies` (`implementations/rust/sugar-linker/src/lib.rs:1280-1298`) | Real `IrFormula::Implies { operands: [post, pre] }` — **Rust linker only** |
| Python implication surface | `ImplicationDto` by contract **name** + binding flags (`literal_call_report.py:_precondition_implications_from_call_edges` ~4889–4922); `claim_envelope.mint_implication` is hash-seal only, not floor-time logic |

---

## 2. Answers (exact)

### Q1. At `call_method_with` (runtime), are `Post_receiver` and `Pre_method` reachable as IrFormulas?

**No.**

**Why:** That method only sees `CallSiteValue` fields (`target_name`, `arg_values`,
`parameters`, `term`, `body`) plus `MethodCallOperation` (`name`, `arguments`) and
reduce `ctx`. It does **not** see:

- `callable_contracts` (local dict inside the `mint_universe` / `floor_fact` closure in
  `literal_call_report.py`)
- Any `FunctionContract.post` / `.pre` / `PostCondition.ir_formula` / `PreCondition.ir_formula`
- Rust `Obligation` / `as_implies`

Contracts exist only after report-time dig of a readable `FunctionDef` via
`mint_universe` / `_function_universe` / `_dig_universe`. Floor reduce never loads them.

---

### Q2. If `call_method_with` is the wrong seam, what is the right seam?

**For the teeth case `np.array(...).sum()`, `call_method_with` is not even on the path.**

#### Live reduce path (confirmed empirically)

```
MethodCallStrategy.emit
  → receiver = ExternalBridgeStrategy → SymbolicValue(call:numpy.array(...))
  → SymbolicValue.call_method_with
  → OpaqueOpCallsite(callee='sum', arg=<SymbolicValue>, computed=None)
  → term = call:sum(call:numpy.array(...))
```

No `CallSiteValue`, no `force_floor`.

#### Where both contracts would co-exist (if they existed)

| Layer | File:function | What co-exists |
|-------|---------------|----------------|
| Report-time dig/mint | `literal_call_report.py:mint_universe` + `_function_universe` / `_dig_universe` | `FunctionContract` for diggable callees; `callable_contracts` map |
| Report-time implication names | `literal_call_report.py:_precondition_implications_from_call_edges` | `ImplicationDto` only when **both** bindings have `has_post`/`has_inv` and `has_pre` — name/slots, not IrFormula |
| Link-time discharge | `sugar-linker` Obligation derive/discharge on bound edges | Real `post ⊃ pre` as `IrFormula::Implies` when contracts are in the pool |

**Right seam for `Post_array(x) ⊃ Pre_sum(x)` as a real formula:**  
**linker Obligation discharge** (`sugar-linker` per bound edge: resolve source post + target pre → `Obligation::as_implies`), **after** both contracts are in the pool from mint.

**Report-time precursor:** only if both `FunctionContract`s are actually minted — today
`mint_universe` cannot mint either for opaque numpy builtins.

**Not the right seam:** `CallSiteValue.call_method_with` (no contracts; wrong path for
`np.array().sum()`).

#### Immediate teeth blocker (post-#4035)

```
build_literal_call_report
  → _resolve_imported_callees
  → _source_funcdef("numpy", "array")
  → inspect.getsource(builtin) → TypeError
  → _record_dig_refusal → dig_boundary_panic → os._exit(1)
```

File:function: `literal_call_report.py:_source_funcdef` → `_record_dig_refusal` →
`factory_gap.py:dig_boundary_panic`.

Dies **before** method composition or Obligation build.

---

### Q3. THE NUMPY PROBLEM: is there a *dug* contract for `sum`?

**No dug contract for method `.sum()` on `np.array`.**

| Callee | Dig? | Contract? |
|--------|------|-----------|
| `numpy.array` | **No** — C `builtin_function_or_method`; `inspect.getsource` fails | No `Post_array` from dig |
| `ndarray.sum` / method `sum` | **No** Python body dig of the method as a FunctionDef on this path | No `Pre_sum` / `Post_sum` from dig |
| Live floor shape | `OpaqueOpCallsite` / EUF `call:sum(call:numpy.array(...))` with `computed=None` | Coordinate only, uninterpreted |

#### Options

| Option | Meaning | Honest? | Soft third state? |
|--------|---------|---------|-------------------|
| **(a) Cited external post** | Vendor-stated (or kit-cited) behavior becomes the contract; warrant is cite, not dig | **Yes** — Some ⇒ cite | No, if absence still panics |
| **(b) EUF-only** | `call:sum(...)` stays uninterpreted; compose by congruence; only legality/shape of composition | **Yes** for *composition of coordinates* | No — but **cannot** refute `==6` vs `==7` without a grounding companion or cited post |
| **(c) Fabricate dig / soft dig-boundary** | Pretend dig worked or catch panic into incomplete | **No** | **Yes — forbidden post-#4035** |
| **(c′) Kit-fold concrete args** | If receiver floors to countable construction, fold `.sum()` like `BuiltinCallSugar.sum` on `ArrayLiteral` | Honest only for *constructed* floors, not as dig of numpy | Not soft if gap still panics when fold impossible |

**Honest for opaque numpy:** **(a)** and/or **(b)**.  
**(b)** alone does not make lying twins unsat.  
**(a)** is required for value discrimination (`==6` swim / `==7` refuse).  
Inventing post/pre from unreadable bodies is fabrication.

---

### Q4. Recommended seam + can `array([1,2,3]).sum()==6` SWIM honestly?

#### Recommended seam

1. **Do not cut `CallSiteValue.call_method_with` for this teeth case** — wrong path; no IrFormulas.
2. **Composition of coordinates** already lives at  
   `SymbolicValue.call_method_with` → `OpaqueOpCallsite`  
   (`floor/symbolic_value.py` ~77–110):  
   `call:sum(call:numpy.array(...))`. That is EUF join, not Obligation.
3. **Obligation `Post ⊃ Pre`** only when **both contracts exist in the pool** — linker  
   (`sugar-linker` Obligation on bound edges). Report-time  
   `_precondition_implications_from_call_edges` is the name-level precursor, not the SMT formula.
4. **numpy unreadable dig:** either external-bridge without treating dig-refusal of known
   opaque builtins as a dig_boundary panic *while still citing*, or a **cited** external
   universe — never soft incomplete.

#### Can `np.array([1,2,3]).sum() == 6` SWIM honestly?

| Goal | Honest without vendor-cited (or kit-cited) contract? |
|------|--------------------------------------------------------|
| Lift / emit EUF coordinate `call:sum(call:numpy.array(...))` | Yes — already (reduce); report currently panics on dig-resolve of `numpy.array` |
| Governed sat for `==6` and unsat for `==7` | **No** — needs grounding: cited post, Derived companion with real warrant, or fold of a **constructed** floor — not dig of C numpy |
| Pretend dig produced `Post_array` / `Pre_sum` | Fabrication — forbidden |

**Real answer for value-governed teeth:**  
**Cite, do not dig.** Opaque C numpy has no dug body contract. Swim/unsat discrimination
requires a **vendor- or kit-cited** contract (or a deliberate countable fold with a
Derived warrant that does not pretend to be dig). EUF-only composition is honest for
*joinability* and refuses only when something else contradicts — not for numeric 6 vs 7
alone.

Existing corpus seed `test_vendor_method_body_dig.py` already states: free opaque
`call:sum` body dig keeps **both** `A()==6` and `A()==7` **sat** (no companion). That is
the honest EUF limit, not a bug to paper over.

#### Local diggable contrast (not numpy)

`make()` returning `[1,2,3]` then `.sum()`:

- Hits `CallSiteValue.call_method_with` → `force_floor` **succeeds** → `ArrayLiteral`
- Then `ArrayLiteral.call_method_with("sum")` → **factory_panic** (no method floor)

So force_floor-on-opaque is **not** that residual; missing `ArrayLiteral.sum` floor is.

---

## 3. Gaps summary (build blockers)

| Piece | At `call_method_with`? | Elsewhere? |
|-------|------------------------|------------|
| `Post_receiver` IrFormula | **No** | Only after dig of readable FunctionDef |
| `Pre_method` IrFormula | **No** | No dug sum-method contract for numpy |
| `Obligation.as_implies` | **No** (Python floor) | Rust linker |
| Composite mint `array.sum` | **No** | Live address is nested EUF, not `array.sum` |
| `∀x∈U_receiver` | **No** | Only `forall(formal, sort, body)` on formals |
| Teeth path uses this seam? | **No** | SymbolicValue + OpaqueOpCallsite; report dies earlier |

---

## 4. Verdict

**STOP. Do not build Obligation-compose at `call_method_with`.**

- Seam lacks Post/Pre IrFormulas.
- Teeth path does not use that seam.
- Numpy sum has **no dug** contract; value governance needs **cite**, not dig.
- EUF composition is honest for coordinates; not for 6-vs-7 without a cited/grounded post.

**Ruling needed before any cut:**  
Which product goal — (b) EUF join only, (a) cited external contracts for numpy array/sum,
or a kit-fold Derived companion for concrete literal args — and which seam owns it
(report mint vs linker Obligation vs floor OpaqueOp)?

---

## 5. Probe method notes

- Checkout: `part-4016-factory-gap-none-panic` (post-#4035 soft-third-state delete).
- Empirical reduce of `np.array([1,2,3]).sum()` → `OpaqueOpCallsite` / `computed=None`.
- Empirical report panic stack: `_resolve_imported_callees` → `_source_funcdef` → dig_boundary_panic.
- Paths under `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/`
  (workspace `sugar` → provekit symlink).
