# Fix note: opaque-operator body-dig grounding (unblocks #3906; shared with #3905)

## The regression #3906 hit (corpus, not the aggregate)
Battleaxe witness corpus on #3906 (`opaque-builtin-coordinate`): **1 failed, 51 passed, 3 errors** — all one root. The failing seeds return `statuses=['refused']` (prover gets no verdict):
- `builtin_hash_callsite`
- `display_conversion` (str/repr conversion shape)
- the 3 "errors" are cascade: the all-seeds setup crashes on `builtin_hash_callsite`.

The worker's aggregate (35 passed) and a local byte-check of len/str shape both MISSED this. Only the 55/55 witness corpus caught it. Standing rule reconfirmed: **an aggregate/local-shape check is not a soundness signal; the witness corpus is the gate.**

## Precise mechanism (verified by probe, do not take on faith)
Lifting on #3906's tip:

- **Direct** `assert hash([1,2,3]) == 5` → `hash#euf#c:call:hash(c:array(i:1,i:2,i:3))::assertion`. **Works** — euf-keyed, grounded by the sworn assertion. (Same as `df.shape == (0,0)` in #3905.)
- **Body-dig** `def A(): return hash([1,2,3])` + `assert A() == 5` → emits ONLY `A#euf#c:call:A()::assertion`. **`call:hash` is absent** — no body universe post, no coordinate. `call:A()` is ungrounded → **refuse.**

Contrast the *foldable* body-dig that works: `def A(): return len([1,2,3])` emits THREE rows — universe `out == call:len(array(1,2,3))`, Derived companion `call:len(array(1,2,3)) == 3`, assertion `call:A() == 3`.

**Root cause:** Option A's body-dig grounding (`ControlFlowBodySugar.opaque_returns` + `_opaque_op_companion_facts` at universe mint) only fires for **foldable** returns (`OpaqueOpCallsite.computed != None`). An **opaque** return (`hash`, `str`/`repr` of a symbolic arg — `computed is None`) is skipped, so the body universe never states `A() == call:<op>(...)`. With nothing saying what `A()` returns, the sworn `A() == N` floats and the prover refuses.

This is the len-in-body gap, reborn for the operators that *can't* fold — so they lean entirely on grounding that the body walker doesn't emit for them.

## The fix (extend grounding to opaque returns — do NOT defer hash)
Earlier instinct was "defer `hash` like `divmod`." Wrong: `divmod` was deferred for a *structural* reason (tuple result needs a subscript surface); `hash` refuses for a *grounding* reason that #3905 already shows how to close. Fix, don't cut.

In the body-dig path (`sugar/control_flow_body_sugar.py` collects `opaque_returns`; `factory/literal_call_report.py` emits companions at universe mint):
1. Emit the body universe coordinate for **opaque** returns too: `out == call:<op>(<arg>)` (the same universe post foldable returns get), **without** a companion (there is no value to ground — the coordinate is opaque, grounded by the sworn assertion via the shared `call:A()` euf key, exactly as `df.shape` grounds in #3905).
2. `computed is None` returns get the universe post; only `computed is not None` returns additionally get the Derived companion. Today the opaque branch is dropped entirely — stop dropping it.

**Verify the self-grounding empirically** (this is the risk): with `out == call:hash(...)` in the universe post and `call:A() == 5` sworn, does the truthful case discharge (sat) and a lying `A() == 6` refute (unsat)? A `call:` coordinate in a universe post grounded only by the assertion (no companion) must be confirmed to discharge, not itself refuse — the Option-A history shows universe-post coordinates *can* work when grounded, but confirm for the no-companion case before declaring done.

## #3905 relationship (why "look at 3905")
#3905 (`vendor-attr-brief`, implemented at `d08456c28`) routes attribute access `df.shape` through the callsite-euf door — the working pattern for an **opaque coordinate grounded by the sworn assertion**, direct case. #3906's opaque *direct* case already works the same way. The gap both share is the **body/dug opaque case**: #3905's routing lives in `_lift_assert` (assertion path), not the body walker, so a body returning `df.shape` will refuse the same way `hash` does.

Therefore: **one shared fix** — opaque-return body-dig grounding — serves both hash (builtin) and `df.shape` (attribute). Land #3905 first (it is the direct-opaque-grounding reference and is corpus-cleaner), then #3906 builds its opaque-body case on the same grounding, and add a body-dig-opaque discrimination seed to both.

## Definition of done (for #3906 to clear the gate)
1. `def A(): return hash([1,2,3]); assert A() == 5` — truthful **sat**, lying `== 6` **unsat** (refuted). Same for a `str`/`repr` body-dig (the `display_conversion` shape).
2. Full battleaxe witness corpus **green (no refused, zero lie->sat)** — the seeds `builtin_hash_callsite`, `display_conversion`, and the 3 all-seeds tests pass.
3. len foldable body-dig unchanged (regression assertion).
4. Add a body-dig-opaque witness seed (hash-in-body) so this exact refuse can't come back silently.

## Hard rules
- **The witness corpus is the gate**, not the aggregate and not a local shape probe. Do not merge #3906 on anything less than 55/55.
- **Do not defer `hash`** — ground it.
- **Never fabricate a value for an opaque op** (`hash` stays `computed=None`; the grounding is the sworn assertion, never an invented value).
