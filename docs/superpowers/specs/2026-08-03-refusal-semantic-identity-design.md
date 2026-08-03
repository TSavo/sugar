# Refusal Vocabulary Semantic Identity Design

**Issue:** #7226

**Design pin:** `a5534eb0084bccd12c4d88575e6e3e69360d286b`

**Scope:** design only; this document does not authorize implementation or census migration

## Problem

The refusal-vocabulary census currently identifies each source occurrence as

```text
path + sha256(normalized whole line) + duplicate ordinal
```

The line number is display-only, but the identity still belongs to source text rather
than to the refusal the source constructs. A repair that preserves the refusal while
changing an identifier, constructor entrance, or line boundary can therefore create a
false vanished row plus a false new row.

That is the wrong answer to the only semantic question the ledger needs to answer:
did this refusal meaning remain present in the statically inspected source, or did it
genuinely disappear?

The current census was measured at the design pin with:

```text
python tools/check-lift-refusal-vocabulary.py
```

The unpiped exit code was `0`. It reported 2,423 occurrences across 195 files,
including 2,269 `lift-output-backlog` occurrences. This is a static source census; it
does not prove runtime reachability.

## Measured sensitivity boundary

Hockney measured three distinct sensitivity classes before this design:

| Change | Current key result | Measured population |
| --- | --- | --- |
| whitespace within a line | no rekey and no classification movement | Black 26.5.1 reformatted 47 scanned-package Python files |
| identifier or call-shape change | rekeys surviving meaning | `self.site` to `site`; direct `RaiseEffect(...)` to `RaiseEffect.for_builtin(...)` |
| line joining or splitting | rekeys surviving meaning | a 366-file sweep joined a two-line `CacheRefuse` into one line, producing net `-1` |

The pinned comparison contained 105 new and 11 stale rows. Exhaustive history
authenticated three new rows and three stale rows as the two sides of spelling-only
churn. Thus 3/105 new rows (2.9%) and 3/11 stale rows (27.3%) are confirmed identity
noise. This does not claim that the remaining 102 new rows are semantically novel.

The replacement identity must therefore be invariant under all three measured
non-semantic transformations: whitespace changes, identifier/call-entrance rewrites
that construct the same refusal, and line joining or splitting.

## Law

Refusal meaning is constructed once by the owner that constructs the refusal. The
census may project that identity; it may not recreate it from spelling, AST shape, or
line layout.

Source location is evidence about where the meaning is seated. It is not the meaning.
The successor schema therefore separates two nouns:

- `meaningCid`: what refusal was constructed;
- `seat`: where the source census observed that meaning.

Changing a seat without changing `meaningCid` is a move. Reducing the multiplicity of
a `meaningCid` is a genuine semantic disappearance from the static population.

## `RefusalMeaningV1`

Every executable refusal occurrence must project a canonical preimage owned by its
construction type:

```json
{
  "schema": "refusal-meaning/v1",
  "language": "python",
  "constructorKind": "RaiseEffect",
  "structuralKey": {"...": "producer-owned canonical fields"}
}
```

`meaningCid` is minted by the repository's existing canonical content-CID constructor
over this preimage; schema v2 does not introduce another hash or canonicalization
profile. Its required properties are:

1. `constructorKind` names the typed construction result, not the spelling of the
   entrance used to obtain it.
2. `structuralKey` is nonempty and is emitted by that constructor's owner.
3. The key contains the fields that distinguish refusal meanings and excludes source
   formatting, local identifier spelling, constructor call spelling, path, line, and
   column.
4. Display fields such as `exception_name` may travel beside the key, but a display
   name alone cannot authenticate type identity. For a `RaiseEffect`, the owner
   projects its authenticated exception-type/effect testimony and its existing
   structural refusal key. Both direct construction and `for_builtin` must reach that
   same projection after they construct the same value.
5. Classification (`speaker`, `wire_marker`, `reason`, and `replacement`) is payload
   compared under an identity. It is not part of `meaningCid`; otherwise a
   classification change would masquerade as removal plus addition.

The census does not contain per-constructor rules. A Python or Rust construction owner
must expose the projection at its existing authoritative door. The language frontend
may locate that owner using the repository's existing source construction and binding
machinery, but it must not define a second table saying that two spellings are
equivalent.

If an executable `refus*` occurrence cannot be joined to one constructed owner and one
nonempty structural key, the entire census refuses with an
`UnownedRefusalMeaning` row naming language, path, span, and observed shape. It never
falls back to normalized text.

## `RefusalSeatV1`

Every semantic occurrence also records source provenance:

```json
{
  "schema": "refusal-seat/v1",
  "meaningCid": "<content CID>",
  "language": "python",
  "path": "<repository-relative path>",
  "owner": "<authenticated enclosing owner>",
  "locus": "<authenticated source locus>",
  "line": 123
}
```

The seat is retained for diagnostics, review, and repair routing. None of its fields is
hashed into `meaningCid`. A path move, helper extraction, identifier rename, or line
join can therefore change the seat while preserving the meaning.

The ledger is a multiset, not a set. Comparison for each `meaningCid` is:

1. pair exact old/new seats first;
2. deterministically pair remaining old/new seats as moves;
3. report unmatched old seats as vanished multiplicity;
4. report unmatched new seats as added multiplicity.

Two equal refusal meanings at different seats therefore remain two occurrences. A
reorder or relocation does not manufacture churn; removal of either one reduces the
multiplicity and stays loud.

## Prose and non-executable vocabulary

Comments, docstrings, documentation strings, and other non-executable vocabulary do
not construct a refusal and must not be laundered into `RefusalMeaningV1`. They remain
in a separate `refusal-lexical/v1` inventory with lexical identity and source seats.

The lexical inventory preserves the vocabulary-removal ratchet but makes no claim
about semantic identity or runtime reachability. Its new/stale rows are never combined
with semantic additions, semantic disappearances, or semantic moves.

An executable occurrence cannot be put into the prose inventory merely because its
owner is unresolved. Unresolved executable identity refuses the run by name. Likewise,
an unparseable scanned Python or Rust file refuses the run; it is not scanned as raw
text and it does not disappear from the denominator.

## Schema-v2 output

The successor census carries four separately conserved collections:

- semantic meanings keyed by `meaningCid`;
- semantic seats referencing those meanings;
- lexical/prose occurrences;
- named instrument refusals, which make the census unmeasured rather than becoming a
  fourth occurrence class.

Summary output reports semantic additions, semantic disappearances, seat moves,
classification changes, and lexical changes separately. A semantic `vanished` row
means the observed multiplicity of a constructed refusal meaning decreased. A moved
seat is never printed as vanished plus new.

## Migration

Migration is a dual-run, not an in-place census rewrite.

1. Freeze schema v1 at the design pin.
2. Run v1 and v2 over the same exact git tree.
3. Emit a migration mapping from every v1 occurrence key to exactly one v2 semantic
   seat or lexical occurrence.
4. Require exact conservation:
   - v1 rows: exactly 2,423;
   - mapped v2 semantic seats plus lexical occurrences: exactly 2,423;
   - missing rows: zero;
   - multiply mapped rows: zero;
   - unowned executable occurrences: zero;
   - unparseable scanned files: zero;
   - classification payload changes introduced solely by migration: zero.
5. Compare the dual-run result against the three authenticated churn examples. They
   must become seat moves with stable `meaningCid`, not vanish/new pairs.
6. Only after all conservation conditions hold may a later, separately authorized
   implementation retire schema v1.

The number 2,423 is a hard gate bound to the design pin. A changed main tree requires a
new pinned measurement and an explicit migration-gate update; an implementation may
not silently bless a different denominator.

## Required discrimination twins

Every sensitivity class needs both a preserving arm and a genuinely changing arm:

1. **Whitespace:** formatting within a line preserves `meaningCid`; any changed display
   span is at most a seat move. Removing the refusal decreases semantic multiplicity.
2. **Identifier:** `self.site` to a bound local `site` preserves `meaningCid`; changing
   the producer-owned structural key creates a new meaning.
3. **Constructor entrance:** direct `RaiseEffect(...)` to
   `RaiseEffect.for_builtin(...)` preserves `meaningCid` when both construct the same
   effect; constructing a different authenticated exception/effect meaning creates a
   new key.
4. **Line joining/splitting:** joining or splitting one `CacheRefuse` construction
   preserves one meaning and one occurrence; adding a second semantic refusal raises
   multiplicity to two.
5. **Genuine removal:** deleting a semantic refusal leaves an unmatched old seat and
   reports one vanished meaning occurrence.
6. **Duplicate multiplicity:** two equal meanings remain count two across reorder or
   relocation; deleting one reports count one, never zero and never a deduplicated
   pass.
7. **Prose separation:** editing prose can move a lexical row without changing the
   semantic ledger; an executable refusal cannot escape into the lexical partition.
8. **Unowned and unparseable:** a source-visible executable refusal without an
   authenticated owner, and an unparseable scanned file, each refuse by name. A
   well-owned, parseable twin completes.

## Cost

The migration requires language-aware source ownership for Python and Rust, a schema
v2 census and comparator, owner-provided meaning projections, an exact v1-to-v2
mapping for all 2,423 rows, and dual-run receipts. The prose split must also preserve
the current speaker and wire-marker classifications.

This is deliberately more work than changing the hash input. The cost buys one
definition of refusal meaning, owned by construction, instead of a growing set of
syntax equivalence rules in the instrument.

## Rejected alternatives

### AST normalization

Canonicalizing AST nodes, alpha-renaming identifiers, or teaching the census that
`RaiseEffect(...)` and `RaiseEffect.for_builtin(...)` are equivalent is rejected. It
creates a second semantic definition beside the constructor. It will drift on the
next unanticipated rewrite, which is the same disease as two ways of knowing one
thing.

### Runtime-only construction identity

Recording only refusal objects observed during execution is honest about every object
it sees, but it is coverage-bound. Unreached source would vanish from the census even
when the refusal remained present. Runtime testimony may corroborate the static
ledger, but it cannot replace this static census alone.

## Result

Schema v2 buys a ledger in which spelling-preserving repairs stop manufacturing
progress and regressions. A seat move says where code went. A semantic addition says a
new refusal meaning appeared. A semantic disappearance says the statically observed
multiplicity of a refusal meaning genuinely decreased. The instrument can then answer
that question directly instead of requiring a manual history investigation.
