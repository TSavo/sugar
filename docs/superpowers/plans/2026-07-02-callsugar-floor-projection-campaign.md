# CallSugar Floor-Projection Campaign - IDD Plan

> **For agentic workers:** This is a CAMPAIGN plan, not an implementation patch. Do NOT delete `literal_call_report.py`'s mini-interpreter from this document's branch, and do NOT start the deletion slice first. The coordinator dispatches slices ONE AT A TIME from current main. Instruments come before drains, every slice is red-first, and the mini-interpreter dies only after the double-dispatch projection arms exist, the force_floor seat can pull a floor up through a multi-statement body, and the second-engine auditor pins zero. If you are handed a single slice, read the whole plan for orientation, then execute only the slice named in your task. Every protocol claim below is grounded in file:line; re-verify it against live main before you build on it.

**Goal:** Delete the second reduction engine inside `factory/literal_call_report.py` (issue #3150, Debt 4 of #3010) — the largest standing factory-or-side-door violation in the Python kit — and replace its transitive tower-digging with the factory's own object-oriented double-dispatch reduction. When this campaign closes there is ONE reduction semantics: a value's FLOOR TYPE selects behavior by dispatching an operation onto it (`floor.<verb>_with(operation, ctx)`), never an `isinstance` ladder in `literal_call_report`. The callsite term carries its bridge unconditionally and its floor exactly when factory reduction terminated; a local instrument checks the two projections agree.

## The decision of record (T Savo, 2026-07-02 — collapse, do not relitigate)

A callsite is ONE recognition event with TWO projections. Both come from the same factory recognition; neither is chosen by a policy.

1. **The bridge is unconditional.** When the factory recognizes a call, `CallSugar` (via `BridgeStrategy.emit`, `sugar/call_sugar.py:70-98`) emits the abstraction edge `call:<callee>(args)` — this callsite points at the callee's `::callable` contract. `A(){ return B() }` means `post(A) = post(B)`.
2. **The floor is pulled up by ordinary factory recursion.** The callee body is just another term the factory can reduce. `A() -> B() -> 0` bottoms out at the literal `0`; `call:A()` carries floor `0`. This is `CallSiteValue.force_floor` (`floor/call_site_value.py:31-58`) driving the same reduction spine that reduces every other body.
3. **There is NO dispatch policy and NO chooser.** The term always has the bridge; it has the floor exactly when reduction terminated; the consumer's QUESTION selects the projection: `verify` discharges through the bridge; a stated value assertion (`assert A() == 1`) reads the floor; opaque/effectful/non-terminating territory makes the floor honestly ABSENT (a `DigRefusal`), bridge only.
4. **The floor pull-up rides the existing double-dispatch spine.** The value returned by reducing a callee body is projected to a callsite fact by dispatching an operation onto its floor type — not by an `isinstance` ladder in `literal_call_report`. The mini-interpreter's ladders are the anti-pattern this campaign removes.
5. **Agreement over silence.** Wherever BOTH projections exist, `floor(A)` must model `post(A)` (floor ⊨ contract). Today two engines compute the two sides and can diverge SILENTLY; after this campaign the check is LOCAL to the term and becomes a counting instrument, then a gate.

**Worked example (teach it):**

```python
def B(): return 0
def A(): return B()
def t(): assert A() == 1     # a VENDOR-STATED fact, and it is a LIE
```

- **The fact (always):** the assertion mints `eq(call:A(), 1)` under `A#euf#...::assertion`. The vendor swore `A() == 1`.
- **The bridge (always):** `A`'s `::callable` universe says `out == call:B()`; `B`'s says `out == 0`.
- **The floor (because reduction terminated):** reducing `A`'s body `return B()` yields a `CallSiteValue` for `call:B()`; forcing its floor reduces `B`'s body `return 0` to `TermValue(0)`. Projecting that floor swears `eq(call:A(), 0)`.
- **The decision:** `eq(call:A(), 1)` and `eq(call:A(), 0)` conjoin under the same `#euf#` key; z3 sees `1 == call:A() == 0` → UNSAT. The lie is caught.
- **Where the floor is absent:** make `B` effectful (`return input()`). Reducing its body yields an `Incomplete` effect; the projection arm has nothing to swear, records a `DigRefusal`, and leaves only the bridge. The vendor's word stands unrefuted — correctly weaker, never a false discharge.

## The reduction machinery today (double dispatch through floors)

Every protocol decision below rests on machinery that ALREADY EXISTS. Read it before designing on top of it.

### The dispatch trampoline

`operations/perform_operation.py:11` is the whole double-dispatch spine:

```
perform_operation(receiver=<floor>, method_name="<verb>_with", operation=<Operation>, ctx)
   -> getattr(receiver, method_name)(operation, ctx)
```

The FLOOR type resolves the arm (`getattr(receiver, method_name)`); the OPERATION object carries the algorithm and its parameters; `ctx` threads state. A missing arm raises a `FactoryGap` with `gap_kind="Floor"`, `gap_locus="construction"` (`perform_operation.py:20-40`) — the honest refusal at a reduction seam. `perform_operation` also calls `ctx.record_operation(...)` (`:41-43`) so the temporal/dunder frontier instruments SEE every dispatch. `FloorValue` (`floor/floor_value.py:4`) supplies base defaults (e.g. `inplace_binary_operator_with -> operation.inplace_default(self, ctx)`, `:5-6`) and the `to_term` projection whose own missing case raises `gap_kind="Floor"`, `gap_locus="Projection"` (`:8-46`).

The floors are the 27 classes in `floor/` (`floor_value.py` base + `term_value`, `bool_value`, `bv32_value`, `string_value`, `symbolic_value`, `call_site_value`, `return_value`, `guarded_return`, `raise_value`, `guarded_raise`, `block_value`, `bound_var`, `array_literal`, `tuple_literal_value`, `sequence_constructor`, `object_value`, `object_method_value`, `function_callable`, `lambda_callable`, `builder_state`, `slice_value`, `encoded_string_value`, `import_alias_value`, `predicate_value`, `support_value`, `object_field`). Existing arms are named `<verb>_with`: `add_with`, `guard_with`, `route_raises_with`, `map_with`, `attribute_with`/`call_method_with` (`floor/object_value.py:18,36`), plus the temporal receiver's `curry_with`/`rewrite_with`/`bind_with`. The operations are the 30 classes in `operations/` (one algorithm each). This is the OO pattern the projection must join, not sidestep.

### Currying and the temporal rewrite table

`temporal/` is the same trampoline for a `TemporalContext` receiver (`perform_temporal_operation`). `bind_temporal(ctx, name, value, ...)` dispatches `BindValueOperation.bind_with` → `TemporalContext._bind_value` (`temporal/context_helpers.py:96`, `bind_value_operation.py`). `curry_temporal(ctx, params, arg_values, ...)` dispatches `CurryArgumentsOperation.curry_with` (`context_helpers.py:122`, `temporal_context.py:305`). `rewrite_temporal` dispatches `AddAssignRewriteOperation.rewrite_with`, which reads the current value and re-binds (`add_assign_rewrite_operation.py:45`). A `BoundVar` (`floor/bound_var.py:9`) is a name ALIASING an expression: it carries `.source` (the rhs's composed `SugarBody`, recomposable) and `.scope` (the ctx as it stood at binding time), so `x = x + 1` recomposes `source` against the DEFINITION scope and terminates instead of looping. `NameSugar.desugar` (`sugar/name_sugar.py:38-45`) recomposes a `BoundVar` by reducing `value.source` against `value.scope`.

`CallSiteValue.force_floor` (`floor/call_site_value.py:31-58`) is the callsite pull-up: it curries `self.arg_values` onto `self.parameters` via `_ctx_with_curried_args` → `curry_temporal` (`:74-88`), reduces `self.body`, and recurses through nested `CallSiteValue`s with a `seen` set keyed on `repr(term)` (`:32-36`). It RAISES a raw `TypeError` on recursion, on `self.body is None`, on an arity mismatch, and on an `Incomplete` (`:37-56`) — these are the seams that must become honest, dispatch-shaped refusals.

### BlockSugar: statement-sequence composition through a body

`sugar/block_sugar.py` composes a body. `BlockSugar.desugar` reduces each child statement, then folds the result by floor type: `SupportValue` absorbed, `BoundVar` threaded via `bind_temporal`, `ReturnValue`/`RaiseValue` become guarded exits, `BlockValue` flattened, `Incomplete` bubbled unchanged (execution halts). Pending `if`-guards are applied to an exit by dispatching `ControlFlowGuardOperation.guard_with` through `perform_operation` (`_guard_exit`). The output is a `BlockValue` carrying the exit statements. **This is the composer the mini-interpreter's `Block.of(callee.node.body).reduce()` (`literal_call_report.py:982-984`) duplicates by hand** — and BlockSugar's own statement fold is itself an `isinstance` ladder, but it is the SANCTIONED owner of block sequencing (ratcheted at threshold 6 in `test_floor_projection_gate.py`).

### TrySugar: routing a raised floor through a handler

`sugar/try_sugar.py` reduces a body then routes raises: `_try_exit` reduces `self.body`; if the outcome is a `BlockValue`, it dispatches `RouteRaisesOperation.route_raises_with` (`operations/route_raises_operation.py:14`), which matches each `RaiseValue`/`GuardedRaise` frontier statement against the handlers, reducing a matched handler in the raise's own scope (`_route_statement`, `route_block_raises`). A raise is DATA on the block frontier (`floor/raise_value.py`, `guarded_raise.py`), not an abort — so a raise under an inner `if` can be caught by a wrapping handler. Only a genuinely unhandled raise stays as a residual effect. **The mini-interpreter does the opposite:** it catches `(TypeError, ValueError, FactoryGap)` around its body reduce and on an `Incomplete` simply `continue`s (`literal_call_report.py:985,994-995`), dishonestly dropping a routable raise.

### MapSugar / function-map: element-wise pull-up

`MapOperation.map_array` (`operations/map_operation.py:11`) applies `self.mapper.apply(item, ctx)` element-wise over an `ArrayLiteral`'s items; `CallableMapOperation` (`callable_map_operation.py:10`) applies a `FunctionCallable` element-wise. The refusal seam is a non-`ArrayLiteral` receiver (`MapOperation over BuilderState must produce ArrayLiteral`, `map_operation.py`). A mapped closure's floor pulls up per element. **The mini-interpreter cannot dig a map at all:** `_concrete_return_value` (`literal_call_report.py:1042-1048`) accepts only `len(statements)==1 and isinstance(statements[0], ReturnValue)`; a callee that maps over its arg returns `None` and silently falls to the symbolic universe.

## The protocol: reducing through a floor as OO double dispatch

The dig is not a walk with an `isinstance` ladder. It is the factory's reduction spine, driven on demand from the callsite, with ONE new operation (`CallsiteProjectionOperation`) whose arms live on the floors. The chain, per step:

1. **Enter the callee (currying).** The callsite recognizes as a `CallSugar`/`BridgeStrategy`, producing a `CallSiteValue` whose `arg_values`, `parameters`, and `body` are set (`call_sugar.py:83-98`). `force_floor` curries the args onto the params in a fresh temporal frame via `curry_temporal`/`CurryArgumentsOperation.curry_with` (`call_site_value.py:74-88`). The curried arg frame crosses the call boundary; the callee's own local binds are scoped to that frame. Prior assignments in the enclosing function thread as `BoundVar`s through `BlockSugar`'s `bind_temporal` — NOT through a second replay in `literal_call_report`.

2. **Reduce the body (composition).** The callee body reduces through `BlockSugar.desugar` (multi-statement / control-flow) or a single-expression `SugarBody`. Statement floors fold into a `BlockValue`; `if`-guards apply via `ControlFlowGuardOperation.guard_with`; a `return` becomes a `ReturnValue`/`GuardedReturn`; a `raise` becomes `RaiseValue`/`GuardedRaise` frontier data.

3. **Route raises (TrySugar).** If the callee body has a `try`, `RouteRaisesOperation.route_raises_with` matches raised frontier floors against handlers during the dig; a matched handler reduces in scope. An unmatched raise stays a residual effect → the floor is honestly absent.

4. **Project the exit (floor dispatch — THE new arm).** The reduced value is projected to a callsite fact by dispatching `CallsiteProjectionOperation` via `perform_operation(receiver=<floor>, method_name="project_callsite_with", ...)`. The FLOOR TYPE selects the projection; there is no ladder:
   - `TermValue.project_callsite_with` / `BoolValue` / `StringValue` / `Bv32Value` → the literal floor: swear `call:callee(args) == to_term(self)`.
   - `CallSiteValue.project_callsite_with` → the bridge pointer: the term is `self.term` (`call:h(arg2)`); swear `call:callee(args) == self.term`. The transitive enqueue is already done by `BridgeStrategy.emit`'s `dig_sink` append (`call_sugar.py:88-92`).
   - `SymbolicValue.project_callsite_with` → the irreducible residue: no floor fact (universe/bridge only).
   - `ReturnValue.project_callsite_with` → transparent unwrap: re-project `self.value`.
   - `BlockValue.project_callsite_with` → take the single exit statement and re-project; multiple exits are a universe post, not a single floor.
   - `FloorValue.project_callsite_with` (base default) → honest refusal: a `FactoryGap`/`DigRefusal` naming the floor type, exactly like `perform_operation`'s missing-arm gap. "Write more Floor" for a shape not yet projectable.

**Roles, per T's list — floor types, arm owner, honest refusal, discrimination test:**

| Seam | Floor types | Arm owner (dispatch) | Honest refusal | Discrimination test |
|---|---|---|---|---|
| **Floor dispatch (projection)** | `TermValue`, `BoolValue`, `StringValue`, `Bv32Value`, `CallSiteValue`, `SymbolicValue`, `ReturnValue`, `BlockValue` | `CallsiteProjectionOperation` via `project_callsite_with` on each floor; base `FloorValue` default refuses | Base arm raises `FactoryGap` (gap_kind=Floor, gap_locus=Projection) → `DigRefusal` | terminating `A()->B()->0` projects the exact literal `0`; an unprojectable floor (e.g. `ObjectValue`) refuses loudly |
| **Temporal rewrite & currying** | `BoundVar` (source+scope), curried arg frame | `CurryArgumentsOperation.curry_with`, `BindValueOperation.bind_with`, `AddAssignRewriteOperation.rewrite_with` on `TemporalContext` | rebind that cannot read a prior value → temporal gap; recursion terminates via `.scope` | `x = f(5); assert x == 9` lifts identically to `assert f(5) == 9`; `x = x + 1` reads the old `x` and terminates |
| **BlockSugar (sequence)** | `SupportValue`, `BoundVar`, `ReturnValue`/`GuardedReturn`, `RaiseValue`/`GuardedRaise`, `BlockValue`, `Incomplete` | `BlockSugar.desugar` + `ControlFlowGuardOperation.guard_with` | an unfoldable statement floor bubbles `Incomplete`; guard dispatch must preserve one exit | a two-branch `if/else` body projects a guarded-return universe; a straight-line body projects one literal |
| **TrySugar (raise routing)** | `RaiseValue`, `GuardedRaise` on the block frontier | `RouteRaisesOperation.route_raises_with`; handlers match `.effect` | unmatched raise stays a residual effect → floor absent (`DigRefusal`), never a dropped `continue` | a dug body that raises `ValueError` caught by an inner handler still projects a floor; an uncaught raise refuses |
| **MapSugar (element-wise)** | `ArrayLiteral`, `TupleLiteralValue`, `FunctionCallable`, `BuilderState` | `MapOperation.map_array` / `CallableMapOperation`; new `ArrayLiteral.project_callsite_with` | a non-`ArrayLiteral` map receiver raises; an element whose floor won't project → per-element `DigRefusal` | a callee mapping `x -> x+1` over a literal list projects the exact mapped list; a symbolic element refuses |

## Machinery gaps (what the floors cannot express yet — these become slices)

The protocol is mostly ASSEMBLY of existing machinery, but four capabilities do not exist today and are load-bearing:

1. **No `project_callsite_with` arm anywhere.** The projection is currently an `isinstance` ladder in `_construct_callsite` (`:1003-1012`) plus `_concrete_return_value` (`:1042-1048`). New operation `CallsiteProjectionOperation` + arms on the floors listed above + base refusal. (Slice 2.)
2. **`CallSiteValue.force_floor` cannot pull a floor up through a multi-statement body.** `BridgeStrategy` sets `body=self.body if isinstance(self.body, SugarBody) else None` (`call_sugar.py:96-98`), so a control-flow / try / map callee has `body=None` and `force_floor` raises "no resolved body to demand" (`call_site_value.py:37-40`). To reduce such a body through `BlockSugar` and project the resulting `BlockValue` exit, `CallSiteValue` must CARRY the multi-statement body (a `FunctionBodyUniverse`/block `SugarBody`) and `force_floor` must reduce it via the block composer. This is the single biggest new capability. (Slice 3.)
3. **`force_floor`'s raw `TypeError` seams are not the honest, dispatch-shaped refusal.** They must become `FactoryGap` floor-gaps recordable as `DigRefusal`, matching `perform_operation`'s missing-arm shape, with a dig budget for non-terminating / mutual recursion beyond the `repr(term)` `seen` guard. (Slice 3, folded with the body pull-up.)
4. **Raise routing and map digging are reachable only once (2) lands.** A `try` body or a mapped body can only be dug when `force_floor` carries and composes the block body. Routing already exists (`RouteRaisesOperation`); map already exists (`MapOperation`); the projection arm for `ArrayLiteral`/`TupleLiteralValue` is the only new piece. (Slices 5 and 6.)

## Campaign law

1. **Red-first every slice.** The first artifact is a red instrument, not a fix. An auditor row naming `Block.of(callee.node.body).reduce()` is a valid transcript; so is a projection bad-twin (`ObjectValue` return) that must refuse before the arm exists.
2. **The panic is sacred; never suppress the floor.** `DigRefusal` and `FactoryGap` are honest floors. No slice softens a refusal, turns a panic into a silent `return None`, or drops an `Incomplete` with a bare `continue`. Absent floor is said loudly.
3. **Factory-or-side-door; double dispatch, not ladders.** Every reduction goes through the factory spine (`perform_operation`, `BlockSugar`, `force_floor`). The projection is `project_callsite_with` arms owned by the floors — `literal_call_report` must not `isinstance`-ladder floor types. The `test_floor_projection_gate.py` ratchet is the judge.
4. **No second engines.** Deletion is the point, judged by Instrument A. Do not relocate the worklist into a helper and call it migrated.
5. **Agreement over silence.** `floor ⊨ post` is a counter first (Instrument B), armed as a gate only after the migration proves zero on real fixtures.
6. **Instruments before drains.** No drain slice merges without its bad-twins (a dig that must refuse, a disagreement that must alarm, a terminating dig that must produce the exact literal), one per affected seam.

## Instruments

### Instrument A — second-engine auditor

A collector/gate, same shape as the temporal auditor and the XSugar build-bypass auditor (#3151 — its SIBLING; share one collector, disjoint predicates). It flags reduction of a callee body OUTSIDE the factory spine: `Block.of(<callee>.node.body)` followed by `.reduce(`; a hand-rolled `while worklist` loop that reduces a callee body inline; any `build_body(... callee body ...).reduce(` in `literal_call_report.py` that is not the `force_floor`-seated demand path; and (coordinating with the floor-projection gate) any `isinstance` ladder over floor types in `literal_call_report` deciding a projection. Red-first: plant one `Block.of(...).reduce()`; the gate goes red naming file:line and the replacement (`force_floor` + `project_callsite_with`). Pin the current offender set (Slice 1) and ratchet DOWN.

### Instrument B — floor ⊨ contract agreement counter

For every callee where both projections exist in a lift (a `::callable` post AND a `project_callsite_with` floor fact under the same `#euf#` head), check the floor value models the post. Start as a COUNTER in the payload diagnostics (alongside `DigRefusal`s), reporting `R(agreement-violations)`. Pure local check on the two terms already in hand — no re-derivation. Arm as a gate (Slice 7) after the migration drives it to zero.

### Instrument C — regression floors (existing)

- The full `sugar-lift-py-tests` package suite is the behavior floor; the migration is byte-behavior-preserving on the pinned assertion fixtures unless a slice uncovers a genuine soundness bug (then stop and file).
- `test_floor_projection_gate.py`'s `_RATCHETED_NON_PROJECTION_LADDERS` is live: the migration must REMOVE the `factory/literal_call_report.py:_construct_callsite` and `:_ctx_with_prior_assignments` entries (threshold 3 each), never raise a threshold. The new `project_callsite_with` arms live in `floor/` and so are exempt by `_ALLOWED_DIRS`.
- The `DigRefusal` ledger (`test_dig_refusal_ledger.py`) is the honest-refusal frontier: same or MORE-precise refusals, never fewer.

## Ratchet vector

| Signal | Starts as | Target |
|---|---|---|
| `R(second-engine-body-reductions)` | Slice 1 measures (`_construct_callsite` worklist `Block.of(...).reduce` + `_ctx_with_prior_assignments` replay). | 0 after the deletion slice. |
| `R(literal_call_report floor isinstance-ladders)` | 2 gate entries (`_construct_callsite:3`, `_ctx_with_prior_assignments:3`). | 0 (both removed); logic lives in `project_callsite_with` arms. |
| `R(callsite floors lacking project_callsite_with)` | Slice 2 measures (every floor a callsite body can reduce to). | 0 for the reachable set; base `FloorValue` refuses the rest. |
| `R(callsite-values-with-null-multistatement-body)` | 1 (`BridgeStrategy` drops non-`SugarBody` bodies → `force_floor` cannot dig control-flow/try/map). | 0 after the body-carry slice. |
| `R(mini-interpreter-consumers-not-reading-terms)` | 1 (`_lift_assert` reaches the floor only via `_construct_callsite`). | 0 after consumer migration. |
| `R(agreement-violations)` | Slice 1 counter (expected 0; nonzero ⇒ pre-existing silent divergence — file it). | 0, then armed as a gate. |
| `R(dig-refusal-regressions)` | 0 (ledger green). | 0 — same or more precise. |
| `R(rust-force_floor-touched)` | 0. | 0 (that is #3017's item). |

## Slices

### Slice 0 — Plan PR

Land this document only. Post the #3150 comment (draft below).

Exit: merged as "Part 1 of #3150 (floor-projection campaign plan)".

### Slice 1 — Instruments (auditor + agreement counter + baselines)

Add Instrument A and Instrument B; run RED/measuring against main; pin the vectors. Coordinate the collector with #3151.

- Auditor classifies every offending site in `literal_call_report.py` and records `R(second-engine-body-reductions)` with the replacement path per row (`force_floor` + `project_callsite_with` for the worklist; `dig_sink` for the transitive drain; `BlockSugar` reduction of the enclosing block for the prior-assignment replay).
- Agreement counter emits `R(agreement-violations)` on the pinned fixtures. NONZERO on main ⇒ STOP and file a soundness issue (a pre-existing silent divergence between the two engines).
- Bad-twins: plant one `Block.of(...).reduce()` (auditor red; delete before merge); plant a contract post contradicting a known floor (counter increments).

Exit: auditor names every second-engine site and its dispatch-shaped replacement; counter reports a pinned baseline.

### Slice 2 — `CallsiteProjectionOperation` + `project_callsite_with` arms (floor dispatch)

Add the new operation `operations/callsite_projection_operation.py` and the arms on the floors: `TermValue`, `BoolValue`, `StringValue`, `Bv32Value` (literal → `call:callee(args) == to_term`); `CallSiteValue` (bridge pointer → `self.term`); `SymbolicValue` (no floor fact); `ReturnValue` (unwrap+re-project); `BlockValue` (single-exit → re-project, multi-exit → universe, not a floor); base `FloorValue.project_callsite_with` → honest `FactoryGap`/`DigRefusal`. Do NOT yet re-point `_construct_callsite`; this slice adds the arms and unit-tests them in isolation via `perform_operation`.

- Red-first: `perform_operation(receiver=ObjectValue(...), method_name="project_callsite_with", ...)` must raise the base floor-gap BEFORE any arm is added, then a real callee arm turns its own case green.
- Bad-twins: (a) `TermValue(0)` projects the exact literal fact; (b) a nested `CallSiteValue` projects its bridge term (not a forced value); (c) an unprojectable floor (`ObjectValue`) refuses loudly.
- Pinned tests: new `test_callsite_projection_dispatch.py`; existing `test_floor_projection_gate.py` stays green (arms live in `floor/`).

Exit: the projection is an owned dispatch table; `R(callsite floors lacking project_callsite_with)` measured and zero for the reachable set.

### Slice 3 — `CallSiteValue` carries the body; `force_floor` pulls up through `BlockSugar` with honest refusal

Make `BridgeStrategy` set `CallSiteValue.body` to the multi-statement body (a `FunctionBodyUniverse`/block `SugarBody`), not `None`, for control-flow/try/map callees (`call_sugar.py:96-98`). Make `CallSiteValue.force_floor` reduce that body through `BlockSugar` and hand the resulting exit to `CallsiteProjectionOperation` (via `perform_operation`) — the single pull-up seat. Replace `force_floor`'s raw `TypeError` seams (`call_site_value.py:37-56`) with a `FactoryGap` floor-gap recordable as `DigRefusal`, and add a dig budget (visited-depth/visited-set beyond the `repr(term)` `seen` guard) that refuses honestly when exceeded.

- Red-first: a test that a control-flow-body callee (`def f(x):\n if x: return 1\n return 0`) forces a floor at all (today `body=None` raises "no resolved body to demand").
- Bad-twins: (a) terminating chain `A()->B()->0` returns the exact literal `0`; (b) mutual recursion `A()->B()->A()` refuses honestly (recordable `DigRefusal`, no hang, no false literal); (c) an effectful callee refuses (routes to residual effect, floor absent).
- Pinned tests: `test_transitive_construction.py` (chain + self-recursion), the shared `force_floor` dunder/operation suites (`test_object_*_dunder.py`) — the seat is shared, must stay green.

Exit: `force_floor` pulls a floor up through single-return AND multi-statement bodies via `BlockSugar` + `project_callsite_with`, terminates under a budget, and refuses in the dispatch-shaped way; `R(callsite-values-with-null-multistatement-body)=0`.

### Slice 4 — Consumer migration (literal_call_report reads the term)

Re-point `_lift_assert`'s floor projection (`literal_call_report.py:337-363`) off `_construct_callsite`'s engine and onto the factory term: build the callsite via the factory with a `dig_sink` on the reduce context (bridges self-enqueue, `call_sugar.py:88-92`), read the floor via `force_floor` + `project_callsite_with`, emit via `_emit_euf_fact` (unchanged), record a `DigRefusal` on refusal. Drain the transitive chain from `dig_sink`, not the hand-rolled `seen`/`worklist`. Keep the `::callable` universe minters (`_function_universe`, `_dig_universe`) and `_ctx_with_prior_assignments` (Slice 5). Behavior byte-preserving on the pinned fixtures.

- Bad-twins: (a) `assert A()==1` with `A()->B()->0` → floor `call:A()==0` conjoins with vendor `==1` → UNSAT; (b) `assert A()==0` truthful → SAT; (c) an effectful callee → bridge only, `DigRefusal` recorded.
- Pinned tests: `test_transitive_construction.py`, `test_callsite_literal_expected.py`, `test_callsite_emission_golden.py`, `test_dig_refusal_ledger.py` — `#euf#` keys and formulas golden-stable.

Exit: `_lift_assert` reaches the floor only through `force_floor`/`project_callsite_with`/`dig_sink`; `R(mini-interpreter-consumers-not-reading-terms)=0`; golden-stable.

### Slice 5 — Prior-assignment replay off its second reduce; try-body routing through the dig

Delete `_ctx_with_prior_assignments`'s second reduce + `BoundVar`/`BlockValue` `isinstance` ladder (`literal_call_report.py:506-537`) in favor of reducing the enclosing block through `BlockSugar` (which already binds via `bind_temporal`). Confirm that a dug callee body with a `try`/`except` routes raised frontier floors through `RouteRaisesOperation.route_raises_with` DURING the dig (reachable now that Slice 3 carries the block body), instead of the mini-interpreter's dropped `continue` (`:994-995`). Retire the `_ctx_with_prior_assignments` gate entry.

- Bad-twins: (a) `x = f(5); assert x == 9` lifts identically to `assert f(5) == 9` (pins `_resolve_bound_lhs`, `:194-209`); (b) a dug body that raises `ValueError` caught by its own inner handler still projects a floor; (c) an uncaught raise refuses honestly (no silent drop).
- Pinned tests: `test_bound_call_normalization.py`; a new try-in-callee dig test.

Exit: no standalone second-reduce replay remains; try-in-callee digs route honestly; the `_ctx_with_prior_assignments` gate entry is gone.

### Slice 6 — Map-body projection arm (dig through a sequence transformation)

Add `ArrayLiteral.project_callsite_with` (and `TupleLiteralValue`) so a callee that maps a closure over its arg (`MapOperation`/`CallableMapOperation`, `operations/map_operation.py`) projects the exact mapped-sequence floor, with an honest per-element refusal when an element's floor won't project. This closes the shape the mini-interpreter silently could not construct (`_concrete_return_value` single-return-only).

- Bad-twins: (a) a callee mapping `x -> x+1` over a literal list projects the exact mapped list; (b) a symbolic element refuses (per-element `DigRefusal`); (c) a non-`ArrayLiteral` map receiver refuses.
- Pinned tests: a new map-dig test; `factory/array_map_report.py`-adjacent suites stay green.

Exit: map-transforming callees dig via the factory; no floor shape falls silently to the symbolic universe for lack of a projection arm.

### Slice 7 — Deletion + agreement-gate arming

Delete `_construct_callsite`'s worklist and `_concrete_return_value` and any now-dead helpers; Instrument A pins `R(second-engine-body-reductions)=0`; remove the `_construct_callsite` gate entry. Flip Instrument B from counter to GATE (`R(agreement-violations)=0`).

- Red-first: the auditor gate flips to expect zero; deletion turns it green. Structural grep in the PR body: `rg -n 'Block\.of\(.*\.node\.body|while worklist|_concrete_return_value' implementations/python/sugar-lift-py-tests` → no production hits.
- Bad-twins: re-run the Slice 4 discrimination trio against the deleted-engine build (lie caught, truth SAT, effect refuses); plant a `::callable` post that disagrees with the floor for one callee → agreement gate red; remove → green.
- Pinned tests: full `sugar-lift-py-tests` suite green; `test_floor_projection_gate.py` green with both `literal_call_report` ladder entries gone.

Exit: no second reduction engine remains; auditor + structural grep agree on zero; floor ⊨ contract is an armed gate.

## Anti-goals

- **No eager whole-program evaluation.** The floor is pulled up on DEMAND via `force_floor`, one callsite at a time, budget-guarded.
- **No dispatch policy / no chooser.** The term always has the bridge; it has the floor iff reduction terminated; the consumer's question selects.
- **No `isinstance` ladder on floor types in `literal_call_report`.** Projection is `project_callsite_with` arms owned by the floors. The gate is the judge.
- **No contract-layer wiring changes.** Transporting the bridge's obligation to the contract layer is #3017 Phase 4's seam decision (the `IrTerm`/`Rc<Term>` boundary).
- **No softening `DigRefusal` or the mouth.** Refusals stay loud and get MORE precise.
- **No touching the Rust kit.** `CallSiteValue::force_floor` on the Rust spine is #3017's own item.
- **No relocating the worklist.** Deletion means the second engine is gone, judged by the auditor.

## Campaign closure

1. `literal_call_report.py` has no `Block.of(<callee>.node.body).reduce()`, no hand-rolled callee-body worklist, no second `build_body(...).reduce()`, and no `isinstance` ladder over floor types deciding a projection.
2. The floor is READ off the `CallSiteValue` term via `force_floor` + `CallsiteProjectionOperation`; the transitive drain is `BridgeStrategy`'s `dig_sink`; block/try/map bodies dig via `BlockSugar`/`RouteRaisesOperation`/`MapOperation`.
3. Instrument A pins `R(second-engine-body-reductions)=0`; structural grep agrees.
4. Both `literal_call_report.py` entries are gone from `_RATCHETED_NON_PROJECTION_LADDERS`; the new arms live in `floor/`.
5. Instrument B (floor ⊨ contract) is an armed gate at zero on the pinned fixtures.
6. `DigRefusal` ledger shows same-or-more-precise refusals.
7. The full `sugar-lift-py-tests` suite passes; the pinned fixtures are golden-stable (the vendor-lie fixture still goes UNSAT through the factory path alone).

## Draft #3150 comment (coordinator posts)

> **Decision of record (T Savo, 2026-07-02) + campaign plan.**
>
> A callsite is one recognition event with two projections, both from the factory, neither chosen by a policy: the **bridge** (`CallSugar`/`BridgeStrategy` emits `call:<callee>(args)`, transporting the stated obligation to the callee's `::callable` universe) and the **floor** (ordinary demand-driven factory recursion — `CallSiteValue::force_floor` reduces `A()->B()->0` to `0`). The term always has the bridge, has the floor iff the dig terminated, and the consumer's question selects (verify → bridge; `assert A()==1` → floor; opaque/effect/non-terminating → floor absent as a `DigRefusal`, bridge only).
>
> HOW the dig reduces through a floor is object-oriented double dispatch on the existing spine (`perform_operation(receiver=floor, method_name, operation, ctx)`): currying via `CurryArgumentsOperation.curry_with`; body composition via `BlockSugar`; raise routing via `RouteRaisesOperation.route_raises_with`; element-wise via `MapOperation`; and a NEW `CallsiteProjectionOperation.project_callsite_with` arm on each floor (`TermValue`→literal, `CallSiteValue`→bridge pointer, `SymbolicValue`→no fact, base→honest refusal) that REPLACES the mini-interpreter's `isinstance` ladders. `literal_call_report` stops running its own `Block.of(callee.node.body).reduce()` worklist and READS the floor off the term. Wherever both projections exist, a local `floor ⊨ post` check replaces the two engines that can diverge silently today.
>
> Four real machinery gaps become slices: the `project_callsite_with` arms do not exist; `CallSiteValue` drops non-single-return bodies so `force_floor` cannot dig control-flow/try/map (`body=None`); `force_floor`'s raw `TypeError` seams must become dispatch-shaped `DigRefusal`s with a dig budget; and `ArrayLiteral.project_callsite_with` is needed for map digs.
>
> Plan: `docs/superpowers/plans/2026-07-02-callsugar-floor-projection-campaign.md`. Slices: plan → instruments (auditor coordinated with #3151; floor⊨contract counter) → projection arms → body-carry + budgeted force_floor → consumer migration → prior-assignment/try routing → map arm → deletion + agreement-gate. Rust `force_floor` stays with #3017; the contract seam stays with #3017 Phase 4.
