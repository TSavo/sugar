# Authenticated Implementation Catch Census Design

## Goal

Measure the catch sites in our Python implementation that can intercept
`ConstructionPanic` or `SugarNotWritten`, and make every relevant site testify
whether it preserves the construct-or-panic law. This is a census of our own
implementation. It never scans or classifies `ExceptHandler` nodes in the
authenticated pandas corpus.

The census answers a different question from the pandas process-floor
`R_bare_exceptions` axis. That floor currently emits per-file lift terminals;
it does not enumerate source `ExceptHandler` sites and cannot measure our
implementation suppression surface.

## Existing authority and non-duplication

`scripts/construction_panic_catch_law.py` remains the authority for
`ConstructionPanic` handler semantics. It authenticates sanctioned recensus
membranes by exact path, enclosing function, caught type, and canonical AST
shape; honours semantic sibling-catch precedence; admits pure re-raise; and
goes red on a planted soft catch.

The new census reuses that classification rather than defining a competing
allowlist. The shared predicates and sanctioned witnesses may be factored into
one importable implementation module, but the existing law and the census must
consume the same definitions.

The census is nevertheless a wider instrument:

- the existing ConstructionPanic law scans only
  `sugar-lift-py-tests/src/sugar_lift_py_tests` and
  `sugar-lift-py-tests/scripts`;
- it does not scan `sugar-lift-python-source/src` or
  `sugar-source-tree/src`;
- it does not enumerate the `SugarNotWritten` / `SourceTreePanic` catch
  population; and
- it reports offenders, not a complete authenticated site manifest carrying
  lawful rows, suppression rows, and the evidence needed to recompute the
  population.

At commit `3c0e08e552d46d1e40b2bf840b81972d6bf0be4b`, the existing law was green
when executed separately over both of its declared roots. A source-authenticated
inventory over the four proposed roots found 592 total `ExceptHandler` sites,
28 handlers syntactically capable of catching `ConstructionPanic`, and 172
handlers syntactically capable of catching `SugarNotWritten` through an exact
or broad exception type, with zero read or parse errors. Six of the 28
ConstructionPanic-capable handlers are outside the existing law's roots. The
172 are candidates before construction-reachability discrimination, not 172
claimed suppressions.

## Exception domains stay separate

The two exception classes have different transport semantics:

- `ConstructionPanic` derives from `BaseException`, so `except Exception`
  cannot catch it;
- `SugarNotWritten` derives from `SourceTreePanic`, which derives from
  `Exception`, so `except Exception` can catch it.

The census therefore derives and seals two separate candidate manifests. It
must not infer one from the other or sum them as independent sites, because one
handler can belong to both manifests.

## Declared implementation population

V1 scans exactly these implementation roots:

1. `implementations/python/sugar-lift-python-source/src`;
2. `implementations/python/sugar-source-tree/src`;
3. `implementations/python/sugar-lift-py-tests/src`;
4. `implementations/python/sugar-lift-py-tests/scripts`.

Tests, generated environments, authenticated pandas source, worktree receipts,
and unrelated repository tools are outside the declared population. A future
root expansion changes the witness schema or declared root manifest; it cannot
silently widen V1.

Every admitted Python file contributes its repository-relative path, source
CID, and parse result to the file manifest. Missing roots, unreadable files, or
parse failures are instrument failures and make the run unmeasured.

## Site identity and candidate derivation

Every `ExceptHandler` receives a stable site identity derived from:

- repository-relative file path;
- source CID;
- enclosing module and qualified function/class path;
- exact handler start/end coordinate;
- normalized caught-type expression; and
- location-free canonical handler AST CID.

Candidate membership is semantic and hierarchy-specific:

- ConstructionPanic-capable: exact `ConstructionPanic`, `BaseException`, or a
  bare catch, including tuple members and authenticated import aliases;
- SugarNotWritten-capable: exact `SugarNotWritten`, `SourceTreePanic`,
  `Exception`, `BaseException`, or a bare catch, including tuple members and
  authenticated import aliases.

An earlier sibling exact catch that pure re-raises can prove that a later broad
handler is unreachable for that panic, matching the existing scanner's
precedence rule. The row remains in the complete handler manifest but is not in
that panic's effective candidate manifest.

## Construction reachability and classification

Catch capability alone does not prove suppression. A generic `except Exception`
around unrelated filesystem code is capable of holding a
`SugarNotWritten` value in the type-theoretic sense but cannot suppress one if
no construction refusal can enter its `try` body.

Each effective candidate therefore carries a separate reachability result:

- `direct`: the guarded body directly invokes or contains a construction door
  authenticated from the source;
- `transitive`: an authenticated local call edge reaches such a door;
- `outside-construction`: the guarded body is proven not to reach a
  construction door in the declared implementation graph;
- `unresolved`: dynamic or incomplete call identity prevents proof either way.

Only `direct` and `transitive` sites enter the law population. An unresolved
reachability row is not called lawful or suppression and keeps the census red;
it is named work needed to authenticate the entrance. It is not an instrument
failure because the source was measured successfully, and it is not product
panic testimony. `outside-construction` sites remain in the complete site
manifest as denominator evidence but do not enter the law population.

Relevant sites have exactly two lawful outcomes:

- `lawful`: every path re-raises, or the handler exactly matches a sanctioned
  typed membrane that emits its attested refusal row;
- `suppression`: any relevant path returns `None`, passes, continues, manufactures
  a success/absence value, or otherwise completes without the panic or an
  authenticated typed refusal leaving the handler.

For ConstructionPanic, classification delegates to the existing scanner's
semantic predicates and sanctioned AST witnesses. SugarNotWritten uses the
same law and witness structure but its own exception hierarchy and sanctioned
membrane registry. A handler is never made lawful by filename or prose.

Rows are ranked separately from classification. `direct` production lifter and
mint sites rank above transitive construction callers, recensus/report
membranes, measurement scripts, and sites outside construction. Rank is triage
testimony, not a severity threshold and not permission to suppress a lower row.

## Receipt schema and conservation

The receipt is `implementation-catch-census/v1` and carries:

- `measuredCommit` and the declared root manifest;
- the complete input file manifest with source CIDs and its CID/count;
- the complete `ExceptHandler` site manifest with row identities and its
  CID/count;
- separate ConstructionPanic and SugarNotWritten candidate manifests with
  CIDs/counts;
- for every candidate: caught hierarchy, sibling precedence evidence,
  reachability result and evidence, classification when relevant, exact
  coordinate, canonical handler AST CID, and proximity rank;
- lawful, suppression, outside-construction, and unresolved raw row manifests;
- missing, extra, and duplicate file/site rows;
- scanner stage map with module/qualname and loaded source CID; and
- `instrumentFailures`.

The manifests themselves are carried, not only their CIDs. The final seal
requires the complete site manifest to equal the disjoint union of
non-candidate sites and the two hierarchy-specific candidate memberships after
accounting for their explicit overlap. Within each hierarchy, effective
candidates equal the disjoint union of outside-construction, unresolved,
lawful, and suppression rows. Equal counts with substituted members refuse.

Any source read/parse failure, missing stage witness, CID mismatch, missing,
extra, or duplicate row makes the receipt `unmeasured`; no suppression total is
emitted. A measured receipt may remain red because suppression or unresolved
rows are present.

## Discrimination teeth

Focused tests plant and authenticate:

1. a direct `except ConstructionPanic: return None` suppression;
2. a direct `except Exception: continue` that can catch SugarNotWritten but not
   ConstructionPanic;
3. an exact sanctioned typed membrane that emits an attested row;
4. a pure re-raise admitted as lawful;
5. a broad unrelated catch proven outside construction and therefore not
   mislabeled suppression;
6. a dynamic construction call whose reachability remains explicitly
   unresolved and red;
7. an earlier exact pure re-raise proving a later broad sibling cannot hold the
   panic;
8. a missing/read/parse failure producing an unmeasured envelope rather than an
   empty or partial population; and
9. an equal-count substituted site manifest failing conservation.

The current repository test for `construction_panic_catch_law` remains green,
and its planted bare-catch tooth must still go red through the shared
classifier.

## Enforcement rung and retirement

V1 is an authenticated AST auditor. Python's dynamic call graph prevents the
type checker from proving every broad catch unreachable from every construction
door, so the open-domain reachability residue remains an auditor.

The local classification should climb higher where possible: construction
functions should avoid broad catches by type/ownership; sanctioned membranes
should accept a typed terminal and return an attested result through one
constructor. When that makes an illegal catch unrepresentable, the
corresponding census axis and witness should be deleted rather than retained as
ceremony.

## Non-claims

This census does not classify pandas source handlers, does not rescue the
contaminated eight-seat process-floor receipts, does not claim every broad
`Exception` handler suppresses construction, and does not infer runtime catch
reachability from adjacency or name spelling. Its counts describe only the
exact measured implementation commit and declared roots.
