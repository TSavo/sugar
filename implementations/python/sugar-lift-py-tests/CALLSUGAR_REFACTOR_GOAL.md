# GOAL: calls are dumb sugar the factory makes — no side door

**The one belief:** the answer is always *more dumb sugar the factory makes*. Every fork
below resolves to "make the factory build the right dumb sugar," or it **stops** (a clean
`RefuseStrategy` / panic). It never reaches for a helper, a stub, or a renamed constructor.
A side door is a single moment of not believing this; the design below makes that moment
fail loud instead of pass quiet.

## DONE predicate (all must hold, all are machine-checkable)

1. `rg 'FunctionCallSugar|build_function_call_sugar|build_fcs' src` → **empty**. The side
   door does not exist. (A CI guard test asserts this — its absence is the invariant.)
2. `CallSugar.owns` is exactly `return fragment.observed == "Call"` — shape, no `ctx`.
3. `CallSugar.desugar` is exactly `return self.strategy.emit(self, ctx)` — one line, **no
   `if`**. (A CI guard greps the desugar body for branching.)
4. `BridgeStrategy.emit`, `AssertionFactStrategy.emit`, `RefuseStrategy.emit` are real —
   **zero** `NotImplementedError` in the file.
5. **Byte-identity:** the pre-refactor golden of every showcase's `#euf#` contract
   names + CIDs reproduces **byte-for-byte**. (Step 0 pins it; a ratchet test diffs it.)
6. The EUF cross-location contradictory case still resolves **UNSAT/REFUSE** (the conjoin
   still fires — the keys still meet).

## The invariants, EMBEDDED AS STRUCTURE (not a checklist)

- **emit ⟹ enqueue (no dangling symbol).** There is exactly one function
  `bridge_and_dig(callee, args, ctx) -> Term` that *both* builds `callresult_f(args)` AND
  records the dig obligation on `ctx`, atomically. There is **no API that returns a bridge
  term alone.** You cannot emit a use without obligating its definition because the type
  won't let you.
- **#euf# byte-canonical.** Exactly one function `euf_callsite_name(callee, euf_term)` =
  `f"{callee}#euf#{_canonical_term_sig(euf_term)}::assertion"`. The strategy **never spells
  the key itself** — it calls this. Single source of truth ⇒ canonical by construction.
- **dig via the catalog, never a constructor.** `f`'s universe is obtained ONLY by
  `ctx.build_body(<f body fragment>, STATEMENT)` — the catalog, which makes more dumb sugar.
  Because `FunctionCallSugar` is **deleted**, there is no other path to fall into.
- **dig idempotent on `f`.** The obligation queue is keyed by `f`'s identity (a set);
  enqueue is `set.add`. A second callsite of `f` finds the universe already obligated.
- **concrete vs symbolic = a constructor param, not a branch.** `build` constructs
  `BridgeStrategy(keying=CONCRETE)` or `BridgeStrategy(keying=SYMBOLIC)`. Concrete → the
  `#euf#` coalesce key (travels). Symbolic → a **fresh location-keyed name** (structurally
  cannot coalesce ⇒ no name-capture ⇒ no false refusal). The fork lives in `build`; `emit`
  has no `if` about it.
- **inv / no-pre / ::assertion = reuse, don't rebuild.** `AssertionFactStrategy` constructs
  the contract through the **existing** `literal_call_report` construction that already puts
  the assertion in the `inv` slot with no `pre` and the `::assertion` suffix. Reusing the
  correct code is the enforcement; never hand-roll the slot.
- **no side door = deletion + guard.** `FunctionCallSugar` and `build_function_call_sugar`
  are deleted in the SAME step that `BridgeStrategy.emit` becomes real, so there is nothing
  to fall back into, and a guard test keeps them gone.

## STEPS — each gated by `kit green` AND `golden byte-identical`

- **Step 0 — pin the golden.** Before touching anything: lift the EUF examples + the
  base64/showcase, capture every `#euf#` contract name + CID into a fixture. This is the
  byte-identity oracle. Nothing after Step 0 may move a single one of these bytes.
- **Step 1 — single canonical key.** Extract `euf_callsite_name()` (and confirm
  `_canonical_term_sig` is the one keyer). No behavior change; golden unchanged.
- **Step 2 — dumb shell + RefuseStrategy.** `CallSugar` (owns=shape, desugar=delegate,
  build=router) + the clean-refusal cases. `AddSugar.owns` tightened so `np.add` routes to
  `CallSugar`. Kit green; golden unchanged (no call yet emits through the new path).
- **Step 3 — BridgeStrategy.emit for real, side door deleted IN THE SAME STEP.** `emit`
  builds `callresult_f(args)` via `euf_callsite_name` and enqueues the dig via
  `ctx.build_body`. Delete `FunctionCallSugar` + `build_function_call_sugar`. Route the dig
  (`literal_call_report`) through the catalog. **Gate: golden byte-identical** — if a
  showcase CID moved, the emission drifted; revert and fix. This is the load-bearing step.
- **Step 4 — AssertionFactStrategy for real.** Emit the fact via the reused contract
  construction (inv, no pre, ::assertion). Gate: golden byte-identical.
- **Step 5 — the tests that prove the dance.** The normalization invariant
  (`euf_form(curry) == euf_form(nested)`), 3-per-variant (positive/discrimination/
  structural) for each strategy, the `no-side-door` CI guard, the `dumb-desugar` CI guard.

## THE STOP RULE

At any step, if the honest answer is "I cannot make this dumb sugar yet," **stop**: leave a
`RefuseStrategy` / loud panic, commit the sound partial, and say so. A sound stop is a
checkpoint; a side door is a lie that passes green. Stopping is always the legal move; the
helper never is.
