# Goal: complete the Trinity in the Python kit — terms, contracts, **implications**

## North Star

The Python kit already emits two pillars of the substrate and drops the third. It produces
**terms** (values, slammed to the floor by reducing through the catalog) and **contracts**
(the `::assertion` facts and `::callable` universes). It does **not** emit **implications** —
the bridge resolve-half and the call-edge obligations that connect one tower to the next.

Complete the Trinity: every callsite the kit lifts must emit all three pillars, so a *chained*
callsite composes. `g` calls `h`, `h` returns a literal → the kit emits g's tower, h's tower,
**and the implication edge between them**, byte-exact, so the verifier's report reads
`Resolved` for every bridge and never `Absent`.

This is doable **without** lifting every sugar. Where the factory cannot lift a shape yet, it
**panics — loudly, through the mouth** — and that panic is **in scope and correct**. The
Trinity is complete when every shape that lifts *at all* emits all three pillars, and every
shape that does not lift **panics cleanly**. The forbidden state is the one in between.

## The one law: complete the Trinity, or panic. Never a half-Trinity.

A half-Trinity is the only real failure here, and it is **silent and green**:

- a contract whose bridge has no defining tower → `call:h` is a free symbol → `Absent` → the
  ground-contradiction check has nothing to fold → the proof passes while proving nothing;
- a bridge emitted with its dig **not** enqueued → the tower is never minted → same dangling
  symbol, same false discharge;
- a `#euf#` key spelled one byte differently in the resolve-half than the enumerate-half →
  the two halves land in **different universes** → they never meet → z3 says SAT because the
  vendor's lie and the truth were never compared.

None of these error. The lift succeeds, the solver runs, the report is green. That is why the
rule is absolute: **emit every pillar with a byte-exact key, or refuse the whole callsite with
a loud FactoryGap.** There is no partial credit and no quiet degradation.

## What the substrate is (so nothing here is invented)

Recap of the mechanism the report audits, so this goal adds nothing new:

- **emit_obligation.rs** — every authoring verb emits one or both of two memento shapes:
  - **bridge memento** (resolve-half): `sourceSymbol → targetContractCid`. The *edge*.
  - **implication contract memento** (enumerate-half): a `contract` whose post carries
    `ctor(name=<fn>, args=[var per param])`, which `enumerate_callsites` matches. The *tower*.
- **consistency.rs** (within-proof): collects the `::callable` universes (`forall`) and the
  `::assertion` ground facts, **specializes each universe only at the concrete callsites in the
  obligation** (callsite-bounded EUF — a pure `g(5)` has one value), folds ground guards
  (`eval_ground_bool`), and the specialized instance gives the solver-independent contradiction
  check its teeth.
- **sugar-linker** (cross-proof): resolves each call edge (CID, else `(name,kit)` symbol),
  derives a bridge, and discharges `source_post ⊃ target_pre` structurally or by solver.
  Unresolved → `unresolved-symbol`. The bundle is a CID.
- **`sugar lift --report`**: per callsite prints `vendor source: Resolved | Absent | Drifted`
  and `conjoin here: local_fact ∧ (instantiated_post)`. **The report is the acceptance test:
  the Trinity is complete when no bridge it can lift reads `Absent`.**

The `#euf#` name is the *only* linkage. There are no other pointers. Composition is byte-exact
EUF congruence on that string, in every layer.

## Invariants (embedded here because they are the things that get dropped)

1. **ONE speller for the `#euf#` key.** The resolve-half (bridge) and the enumerate-half
   (contract) must spell the key with the *same* function (`euf_callsite_name` /
   `euf_call_term`). Never spell a key inline anywhere. Two spellers = two chances to drift =
   silent false discharge.
2. **emit-bridge-AND-enqueue-dig is ONE atomic act.** `BridgeStrategy.emit` emits the bridge
   term **and** appends the dig to `ctx.dig_sink` in the same call. A bridge without its
   enqueued dig is a dangling symbol. They are inseparable by construction, not by convention.
3. **No side doors.** Every tower is built through the factory/catalog (`ctx.build_body`).
   No constructor is reached around the catalog; no reducer/inliner/partial-evaluator is hand-
   rolled. The `test_no_call_side_door` guard stays green. If completing a shape would require
   a side door, the shape **panics** instead — that is correct (see the law).
4. **A call is BRIDGED, never inlined.** Reducing a body that contains a call must yield the
   bridge `call:h(args)` and enqueue h's dig — it must **not** flatten h's body into g. The
   towers stay separate; the implication is the edge.
5. **The construction is leak-proof.** Values come from reducing through the catalog, whose
   arithmetic *is* Python's operators. Never re-implement an operator (that is the vendor trap).
   A concrete arg slams to a literal; a symbolic arg leaves the bridge irreducible (axiomatic).
6. **The dig is transitive and cycle-guarded by the `#euf#` key.** Draining the queue follows
   every bridge to its tower; a tower already minted (same `#euf#` name) is never re-dug — the
   fixpoint that closes a cycle (`f` calls `f`).
7. **Unhandled sugar stays a LOUD panic, and that is in scope.** Completing the Trinity must
   not suppress, swallow, or route around a `FactoryGap`. A shape the factory cannot lift
   refuses cleanly with blame (the mouth). It must **never** degrade into a half-Trinity.
8. **Byte-exact emission; the golden ratchet is the gate.** The `#euf#` names and the emitted
   slots are pinned by `test_callsite_emission_golden`. A drift is either a bug (fix it) or
   deliberate (re-pin, and say why). The kit cannot see a key drift — it is green — so the
   golden is the only thing that can.

## The missing pillar, concretely

Today `_emit_euf_fact` returns a `LiftResult` whose **call-edges list is empty**. The kit emits
contracts but not the implication edges. The transitive construction driver (`_construct_callsite`)
and the dig queue (`ReduceContext.dig_sink`, `BridgeStrategy.emit` enqueue) are the start of
pillar three; they are not finished and not verified. Completing the Trinity means:

- **the edge is emitted.** When g bridges to h, the kit emits the call-edge / bridge memento
  (resolve-half) into the `LiftResult` call-edges, so the linker can resolve g→h and the report
  can audit it. The edge carries the same `#euf#` source symbol as the bridge term.
- **the tower is minted.** The enqueued dig drains into h's own contract (the enumerate-half),
  via the factory, with a byte-exact key that the bridge resolves to.
- **the chain closes.** A multi-hop chain (`f→g→h→literal`) emits a contract per tower and an
  edge per hop, cycle-guarded, every bridge `Resolved`.

## DONE predicate (acceptance)

1. A chained source — `def h(x): return x+1` / `def g(x): return h(x)` / `assert g(5)==6` —
   emits: g's contract referencing `call:h(5)`, h's contract defining `call:h(5)==6`, **and**
   the implication edge g→h. No emitted bridge is left without a defining tower.
2. The construction's `#euf#` name for a callsite is **byte-identical** to the vendor
   assertion's for the same callsite (they conjoin). Verified by a key-equality test, not by
   eye.
3. `rg 'FunctionCallSugar|build_function_call_sugar|build_fcs'` over `src` is **empty**, and
   `test_no_call_side_door` is green — no new side door.
4. A shape the factory cannot lift (e.g. a symbolic-arg arithmetic universe, an unwritten op)
   **still raises a `FactoryGap` with blame** — a `test_*` asserts the panic, and that panic is
   left in place, documented as out of scope. **No half-Trinity is ever emitted in its place.**
5. `test_callsite_emission_golden` is green (or re-pinned with a stated reason). The full kit is
   green except the deliberately-asserted out-of-scope panics.
6. (If the Rust binary is available) `sugar lift --report` on the chained source reads
   `Resolved` for every bridge and prints a `conjoin here` line per callsite. If the binary is
   not built, the Python-level key-match + edge-presence tests stand in for it, and the report
   check is left as a noted follow-up — not silently skipped.

## Steps (each gated by: golden byte-identical AND kit green AND no new side door)

- **Step 0 — pin the current emission.** Extend the golden to capture the call-edges list and
  the per-callsite `#euf#` keys for a chained source, so pillar-three work has a ratchet. (The
  chain currently panics/defers; pin *that* honest state first.)
- **Step 1 — the dig queue.** `ReduceContext.dig_sink`; `BridgeStrategy.emit` emits the bridge
  over any concrete arg **and** enqueues `(callee, arg)`. Symbolic arg → no enqueue. (Started.)
- **Step 2 — the transitive driver.** `_construct_callsite` drains the queue: each item curries
  through the catalog to a literal (swear `==value`) or a bridge (swear `==call:h(arg2)` and the
  enqueue already happened); cycle-guarded by the `#euf#` key. Defers wholesale if nothing
  constructs. (Started — verify it.)
- **Step 3 — emit the implication edge.** `_emit_euf_fact` (or its caller) emits the call-edge /
  bridge memento per hop into the `LiftResult` call-edges, same source symbol as the bridge.
  This is the pillar that is missing.
- **Step 4 — prove composition.** A test asserts: every emitted bridge has a defining contract
  with a byte-identical key (no dangling `call:`); the chain emits N contracts + N−1 edges; the
  vendor key == the construction key. Discrimination: a lie (`g(5)==99`) emits the construction
  `==6` under the same key (the contradiction is present).
- **Step 5 — the guards.** `test_no_call_side_door` green; a `#euf#`-single-speller guard (no
  inline key spelling in `src`); a test that pins an out-of-scope shape as a **loud FactoryGap**,
  so future work can't quietly turn a panic into a half-Trinity.

## STOP RULE

If completing a shape's Trinity would require a side door, an inlined call, a second key
speller, or suppressing a panic — **stop.** Leave that shape as a loud `FactoryGap`, commit the
sound partial (the shapes whose Trinity *is* complete), and say which shapes remain panics and
why. A loud panic is a finished, correct state. A half-Trinity is not. When the honest answer is
"this shape needs sugar we have not written," the answer is the panic, not a quiet edge that
dangles.
