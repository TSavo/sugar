# Late-bound loop-closure negative

This receipt bounds the follow-up to the deferred `reduce_next` defect fixed by
commit `034218936a4e1fb029b83db4fd3f6cdfadfc83fc`. It records a measured
negative; it does not broaden that product change. The equivalent product diff
was restacked onto `73647afdebdb483b038519782530ce68075a980b` before this
receipt was committed; the resulting commit is named in the handoff because a
commit cannot truthfully cite its own not-yet-computed identity.

## Population and detector

The scan parsed **269 non-test Python files** under `implementations/python`
containing **1,612 `ast.For` / `ast.AsyncFor` nodes**. For each loop, it found
every nested `FunctionDef`, `AsyncFunctionDef`, or `Lambda` whose body loaded a
name bound by that loop target without receiving the name as a function
argument. Each finding was then inspected for whether the closure could be
invoked after its creating iteration advanced.

The detector found **7 candidates across 5 files**. The non-empty candidate
set is part of the evidence: the detector recognized real loop-target captures
rather than returning an uncalibrated zero.

## Candidate triage

All **7/7 candidates** were synchronous within their creating iteration;
**0/7 deferred past it**.

1. `scripts/comprehension_iteration_recensus.py`: `construct_file` captures
   `path`, but `_collect_file_construction` immediately calls
   `collect_construction_panic`, whose first operation is `walker()`. The
   callback finishes before the file loop advances.
2. `floor/dict_value.py`: `project` captures `position` and is invoked for the
   guarded true and false faces immediately before returning from the current
   iteration.
3. `floor/string_value.py`: `branch` captures `index` and is invoked for both
   guarded tuple faces immediately before returning from the current
   iteration.
4. `sugar/with_effect_boundary_sugar.py`: `successful` and `failed` capture
   `face`; both helpers are invoked directly while routing that same face,
   before the `body_es.exits` loop continues.
5. `manager_construction.py`: `obligation` and `seat_receipt` capture the
   current `receipt`; every call is direct within the same respective receipt
   iteration, and neither function object is stored or passed onward.

## Result

Within this measured Python population, the reducer's loop-target
late-binding defect is a singleton: **7 candidates found, 7 cleared, 0 sibling
closures deferred beyond their creating iteration**.

This receipt does **not** cover:

- closures defined outside a loop then queued inside it
- indirect callback assembly the syntactic detector cannot recognize
- tests
- Rust
- runtime-generated code

Those exclusions are boundaries of this measurement, not claims that the
excluded mechanisms are clean or corrupt.
