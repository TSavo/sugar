# Try / ExitSet — gate discharged, merged

**Status:** MERGED as `421ef4157` (#6242). The staging gate was discharged on
the ruling that the landed content is **twins-only, with no production
capability** — it changes no production behavior, and `Try` already rode the
shared `ExitSet` algebra this plan describes.

**Region:** `try_sugar.py` + `exit_set_routing.py`.
**Coordinate with:** Assign (`#6239`) — do not edit the Assign region.

## Try is not a third control model

`Try` inherits the algebra `Store` (#6246) established, `Assign` rode with zero
new sequencing (#6239), and `With` inherited by nesting (#6256). Every
combinator on the path is shared:

| Step | Shared owner |
|------|--------------|
| body → arms | `reduce_block_to_exitset` |
| embedded guarded raises → `Halted` | `promote_raise_halts` |
| tail only over completed arms | `ExitSet.sequence` |
| arm union | `ExitSet.union` / `ExitSet.guarded` |
| cleanup over every exit | `ExitSet.and_finally` |
| membrane back to `Outcome` | `exitset_to_outcome` |

`TrySugar` contributes a **matcher** and an **arm-selection loop**. It
contributes **no sequencing**. `Try` has no `__exit__` contract, so it does not
consult `and_exit` / `exit_disposition_effect` — that seam is the `with`
partition's contract door. `Try`'s completed edge is `else`, and `else` is
already expressed as `ExitSet.sequence` over completed arms only, which is the
same completed-edge discipline #6270 gave the boundary.

## The six-line law

```text
body Completed      → else → finally
body matched Halt   → handler → finally
body unmatched Halt → finally → re-propagate
handler Halt        → finally → re-propagate
finally completes   → preserve incoming exit
finally terminates  → override incoming exit
```

## Law twins

All in `sugar-source-tree/tests/test_try_exitset_law.py` (31). Each law carries
a discrimination arm that bites.

| Twin | Bite |
|------|------|
| handlers in source order, first match only | reversed arm tuple selects the other body; both arms proven to match first |
| `as` uses the routed effect slot | asserts no `effect_slot_identity` reconstruction |
| `else` over completed edges only | two-sided: no-op on an all-halt body, *does* change arms on a body that completes |
| `finally` on all seven exits | seven separate exits, each asserted distinctly |
| `finally` terminates → overrides | force `cleanup_restores` to always-restores; the overridden halt returns |
| bare re-raise same occurrence | occurrence must not be the bare-`raise` line |
| no invented fall-through | unmatched / handler halt leaves no fabricated completion |
| `except*` separately loud | ordinary `except` must not absorb OR rewrite a grouped raise |
| **routes through the shared fold** | behaviour-identical private fold: every behavioural twin stays green, only this goes red |
| **same instrument, two spellings** | `try` and its plain equivalent share arm structure; absorbing arms breaks it |

### Seven exits finally covers

1. Normal completion · 2. Body return · 3. Uncaught raise · 4. Handler
completion · 5. Handler raise · 6. Break · 7. Continue

## `except*`

Out of this cut. Grouped-effect routing is **not** included. `TryStar` stays
typed-loud (`SugarNotWritten`), and the ordinary router is pinned to neither
absorb nor rewrite a `GroupedRaiseEffect`.

## Known gap — reported, deliberately not pinned

A binding established in the `try` body before the raise is **not visible in
the handler**:

```python
def A(z):
    try:
        x = z
        raise ValueError
    except ValueError:
        return x     # → NameErrorEffect on `x`
```

Root cause is `sugar_source_tree.nodes.Try.substitute`: `handler_scope =
dict(scope)` builds the handler scope from the **pre-try** scope, while the
`orelse` correctly gets `body_state = {**scope, **body_net}`. This is a
definite-assignment question in the source tree, not a hole in the ExitSet
algebra, and it is out of this cut's region. No twin here asserts the current
outcome, because that would be asserting the defect.

## Gate to merge

Post-cache authoritative baseline reports a bounded Try residual; ledger
reconciled; Assign region not in conflict.
