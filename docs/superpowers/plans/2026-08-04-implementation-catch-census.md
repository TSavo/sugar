# Authenticated Implementation Catch Census Implementation Plan

> **For Codex:** Follow the repository's red-instrument-first discipline. Keep
> the existing ConstructionPanic classifier authoritative; do not duplicate its
> sanctioned membrane registry.

**Goal:** Add an authenticated, implementation-only AST census that conserves
the complete handler population, separately identifies ConstructionPanic and
SugarNotWritten candidates, and reports lawful, suppression, or unresolved
construction-reachability outcomes without turning instrument errors into a
number.

**Architecture:** A new script wraps the existing
`construction_panic_catch_law.py` predicates for ConstructionPanic semantics,
adds the missing production roots and a separate SugarNotWritten hierarchy,
and emits carried canonical manifests plus CIDs. Reachability is conservative:
directly authenticated throws/calls and statically resolved local call edges
may establish construction reachability; dynamic calls remain unresolved.
Source/read/parse/conservation failures emit only an unmeasured envelope.

**Tech stack:** Python 3.12, `ast`, repository BLAKE3/JCS canonicalization,
pytest through `bin/bpytest` for authenticated remote evidence.

---

## Task 1: Pin the wrapper contract with red tests

**Files:**

- Create: `implementations/python/sugar-lift-py-tests/tests/test_implementation_catch_census.py`
- Create: `implementations/python/sugar-lift-py-tests/scripts/implementation_catch_census.py`

1. Write fixture tests for separate exception hierarchies: `Exception` catches
   SugarNotWritten but not ConstructionPanic; `BaseException` and bare catches
   enter both candidate manifests.
2. Write a planted ConstructionPanic soft-return test that must be classified
   through the existing scanner authority, not a locally copied rule.
3. Write a planted pure re-raise and exact sanctioned membrane control.
4. Run only the new test file through the authenticated `bin/bpytest` entrance
   and record the intended import/API reds.
5. Implement only the minimum public scan/receipt surface needed to turn these
   tests green.

## Task 2: Add source-authenticated manifests and refusal

**Files:**

- Modify: `implementations/python/sugar-lift-py-tests/scripts/implementation_catch_census.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_implementation_catch_census.py`

1. Plant a temporary declared population with multiple files and assert exact
   file/site members, stable row identities, source CIDs, and manifest CIDs.
2. Plant an equal-count site substitution and assert conservation refusal.
3. Plant missing-root, read, and parse failures and assert an unmeasured
   envelope with no measured totals.
4. Implement declared-root enumeration, canonical site identity, carried
   manifests, CIDs, and raw missing/extra/duplicate diffs.
5. Implement the CLI output contract and unpiped exit behavior: measured red
   for live suppression/unresolved rows; measured green only at zero; exit red
   unmeasured for instrument failures.

## Task 3: Add conservative construction reachability

**Files:**

- Modify: `implementations/python/sugar-lift-py-tests/scripts/implementation_catch_census.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_implementation_catch_census.py`

1. Plant direct raise/call fixtures for each panic hierarchy and assert
   `reachability=direct`.
2. Plant a uniquely resolved local call edge and assert
   `reachability=transitive` with the full call path.
3. Plant an unrelated broad catch and assert `outside-construction`, not
   suppression.
4. Plant a dynamic attribute call and assert `unresolved`, red, without
   fabricating a target.
5. Implement a source-owned function index and only the statically authenticated
   same-module/import-alias/self-method call edges needed by the teeth. Unknown
   dynamic edges remain unresolved.
6. Rank direct lifter/mint sites above transitive construction callers,
   recensus/report membranes, scripts, and outside-construction rows.

## Task 4: Prove compatibility with the existing scanner

**Files:**

- Modify only if needed:
  `implementations/python/sugar-lift-py-tests/scripts/construction_panic_catch_law.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_implementation_catch_census.py`

1. Assert the new census and existing scanner agree on planted CP soft catch,
   pure re-raise, sibling precedence, and exact sanctioned membrane shapes.
2. Assert the current existing scanner test surface remains green unchanged.
3. If importability requires factoring predicates, move them once into an
   importable module and make both scripts consume it; never duplicate or
   relax the sanctioned-shape registry.

## Task 5: Fire the authenticated implementation census

**Files:**

- Modify: `implementations/python/sugar-lift-py-tests/scripts/implementation_catch_census.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_implementation_catch_census.py`

1. Run focused tests through `bin/bpytest` on battleaxe under the repository's
   authenticated Python environment.
2. Run the new census unpiped from the exact branch head over the four declared
   implementation roots.
3. Verify the receipt byte identity after sync-back and record exact commit,
   file/site/candidate counts, suppression/unresolved rows, instrument failures,
   manifest CIDs, command, and exit.
4. Report candidates separately from findings. Never report the 172 preliminary
   broad candidates as suppressions.
5. Commit and push the branch. Do not merge it.

## Verification boundary

The focused tests and authenticated census prove only the exact measured
implementation commit and declared roots. They do not classify pandas source
handlers, repair the contaminated process-floor run, or claim dynamic call
reachability where the source graph cannot authenticate it.
