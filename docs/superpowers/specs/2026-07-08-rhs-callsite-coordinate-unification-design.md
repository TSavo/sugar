# RHS callsite coordinate unification (the `py.len` / collapse fix)

Status: DESIGN — awaiting review before implementation.
Related: #3864, #3898 (axiom deletion, the sibling fix), the callsite-lifting model
("one callsite, two contracts").

## The model this enforces

A contract is a whole term; a callsite is a subterm that appears in many contracts.
An operator like `len` is an **opaque uninterpreted symbol carried in the coordinate
name** — never floored, never given a universe. `len(x)` names the coordinate
`call:len(<x>)` and asserts its contract `call:len(<x>) == x_len`, for **all** `x`,
totally. The value `x_len` is filled by whichever admissible source has it:

- `x` is a dug construction → `x_len` is **computed** (derived floor).
- the vendor swears it → `x_len` is the **sworn** value.
- neither → `x_len` stays a symbolic coordinate.

The coordinate spelling must be **identical wherever the same expression appears** —
LHS or RHS, nested or top-level — or congruence cannot connect them.

## The defect (grounded matrix, main @ 658e6a1)

Lifting `assert <body>`, the emitted equality's two term heads:

| assertion | LHS | RHS | verdict |
|---|---|---|---|
| `len(df) == 0` | `call:len(call:pandas.DataFrame())` | `const:0` | ✅ literal, unchanged |
| `df == pd.Series()` | `call:pandas.DataFrame()` | `call:pandas.Series()` | ✅ **bare vendor already symmetric** |
| `len([1,2,3]) == 3` | `call:len(array(1,2,3))` | `const:3` | ✅ LHS coordinate correct |
| `len(df) == len([])` | `call:len(call:pandas.DataFrame())` | `const:0` | ❌ **collapsed** — `call:len(array())` lost |
| `len(df) == len([1,2,3])` | `call:len(call:pandas.DataFrame())` | `const:3` | ❌ **collapsed** |
| `len(df) == len(pd.Series())` | `call:len(call:pandas.DataFrame())` | `py.len(call:pandas.Series())` | ❌ **head mismatch** `py.len` ≠ `call:len` |
| `len(df) == len(len([1]))` | — | — | ❌ **PANIC** (`TermValue.__len__` gap) |

### Root cause — one asymmetry

- **Unknown callee** (a vendor call the factory can't reduce) → falls through to an
  opaque `CallSiteValue` → `call:` coordinate. Symmetric on both sides already.
- **Known builtin operator** (`len`, via `BuiltinCallSugar`) → goes through the
  operator floor, which either **computes a scalar** (`len([]) → 0`) or leaves a
  **`py.`-headed** symbolic term (`py.len(...)`). Neither is the `call:len(...)`
  coordinate the LHS emitter forces.

So the same operator `len` is spelled `call:len` on the left and `py.len` (or
nothing — collapsed to a scalar) on the right. Consequences:

1. **Generalization loss.** `call:len(call:df()) == py.len(call:pandas.Series())`:
   the two `len`s are distinct uninterpreted functions. A vendor law
   `pd.DataFrame() == pd.Series()` will NOT thread through — congruence needs one
   `len` symbol.
2. **Coordinate destruction.** `len([]) → const:0` erases `call:len(array())`, so no
   other assertion mentioning `len([])` can join on the shared subterm.
3. **Nested cascade panic.** `len(len([1]))`: inner collapses to `1`, then outer
   `len(1)` hits `TermValue.__len__` and panics. Had the inner stayed the opaque
   coordinate `call:len(array(1))`, the outer would just be
   `call:len(call:len(array(1)))` — another total coordinate, no gap.

## The fix — one principle

**A builtin operator applied to an argument is an opaque `call:` coordinate,
identical on either side of the equality.** `len(x)` builds `call:len(<x>)`
everywhere. When `x` is a real construction, ALSO emit the derived floor
`call:len(<x>) == value` as a companion `EqualityFact` — keeping the coordinate
(not the bare value) as the term.

This is exactly the sibling of #3898: #3898 said "don't fabricate a universe for the
operator"; this says "don't floor the operator to a scalar or a `py.` symbol —
carry it as the `call:` coordinate, like every other callsite."

### Before → after (target emissions)

| assertion | RHS today | RHS after | extra derived fact |
|---|---|---|---|
| `len(df) == 0` | `const:0` | `const:0` | — (unchanged) |
| `len(df) == len([])` | `const:0` | `call:len(array())` | `call:len(array()) == 0` |
| `len(df) == len([1,2,3])` | `const:3` | `call:len(array(1,2,3))` | `call:len(array(1,2,3)) == 3` |
| `len(df) == len(pd.Series())` | `py.len(call:pandas.Series())` | `call:len(call:pandas.Series())` | — (opaque arg, no floor) |
| `len(df) == len(len([1]))` | PANIC | `call:len(call:len(array(1)))` | `call:len(array(1)) == 1` |
| `len([1,2,3]) == 3` (LHS) | `const:3` | `const:3` | — (LHS already coordinate; RHS literal) |

Net: the solver still closes every case at solve time (transitivity over the shared
`call:len(...)` coordinate). `len(df) == len([])` becomes the two-fact emission we
designed: symbolic equality `call:len(call:df()) == call:len(array())` PLUS derived
`call:len(array()) == 0`; the solver derives `call:len(call:df()) == 0`. No
collapse, generalization preserved, `df == pd.Series()`-style vendor laws now thread
through `len`.

## Where the change lands

`_lift_callsite_assertion` (literal_call_report.py): the RHS-expected path
(`_literal_floor_via_factory(expected_frag)` → `expected_term`). When `expected_frag`
is a callsite whose callee is a builtin operator, build the `call:` coordinate term
(the same construction the LHS uses via `_emit_euf_fact`'s `CallTerm`) instead of the
factory's `py.`/scalar floor, and emit the derived floor as a companion fact when the
arg is a construction. The unknown-vendor-call path is already correct and untouched.

RESOLVED (T, 2026-07-08): land it in the operator floor
(`BuiltinCallSugar` / `TermValue.__len__`), NOT in `_lift_callsite_assertion`. The
floor is where the lie lives — it currently produces a `py.`-headed symbolic term or a
collapsed scalar for a builtin operator. Make the floor **honest**: a builtin operator
applied to an argument floors to the opaque `call:<op>(<arg>)` coordinate natively,
identical to an unknown callee, with the derived value carried as a companion fact when
the arg is a construction. Then LHS and RHS agree by construction (both go through the
same floor), the `py.` spelling is retired at its source, and the fix holds anywhere a
builtin operator appears — not just on the RHS of an equality. Wider blast radius,
paid once, corpus-gated.

## Blast radius / gate

RHS term shape changes wherever a **builtin-operator callsite** sits on the right of
an `==`. Bare vendor calls, literals, and LHS coordinates are unaffected (verified
above). Gate:

- Byte-diff verdict rows on pandas / serde / numpy. Expect changes ONLY on rows with a
  builtin-operator RHS; flag any other row movement before merge.
- Witness sat/unsat corpus stays green (the two-fact emission must still discharge
  SAT where truthful, UNSAT where lying — e.g. `len(df) == 1-1` SAT, `== 1` UNSAT).
- The nested `len(len([1]))` panic converts to a clean coordinate (new positive test).

## Discrimination tests to add

- `len(df) == len([])` emits BOTH `call:len(call:pandas.DataFrame()) ==
  call:len(array())` and derived `call:len(array()) == 0` (no `const:0` collapse).
- `len(df) == len(pd.Series())` RHS head is `call:len`, not `py.len` (congruence
  join test: with vendor law `pd.DataFrame() == pd.Series()`, the len equality
  discharges).
- `len(len([1]))` lifts to a coordinate, does not panic.
- Negative: `len(df) == 1` still UNSAT against a sworn `len(df) == 0` (discrimination
  intact through the coordinate).
