# Static For Post-Bindings Design

## Problem

`ForSugar` exactly unfolds statically known finite iterables and threads the
reduced scope through every iteration, but exports only names pre-classified as
loop-carried inputs. A name definitely constructed by every executed iteration
therefore disappears after the loop. NumPy `test_datetime.py` loses `x` after
three concrete iterations and terminates at `TemporalContext(x)`.

## Design

For a statically known, non-empty iterable, compare the initial temporal scope
with the final reduced iteration scope. Emit `ScopeRebind` for each binding
whose value is new or changed, including the Python-visible loop target. This
uses reduced semantic outcomes; it does not inspect body AST assignments.

An empty static iterable emits no post-loop binding. A runtime-selected
iterable retains the existing symbolic loop behavior. Conditional body
bindings appear only if the body's reduced path join put them in the final
scope. No RuntimeEffect or empty-success arm is added.

## Evidence

- Three concrete elements construct the last iteration's `x` and loop target.
- Empty-list bad twin keeps the post-loop read loud.
- Truthful/lying real-solver witness distinguishes the exact last value.
- Current-main NumPy representative moves off `TemporalContext(x)` with
  conservation and `silent=0`.
