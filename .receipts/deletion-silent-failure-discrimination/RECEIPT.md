# Deletion Silent-Failure Discrimination Receipt

## Pins

- Measured main: `8c117c6568039624eead7f69577dae19bf22f3cc`
- Exact tested source-law content: `948660781`
- Rebased source-law commit: `dce9eea3f`
- Canonical-vocabulary inversion commit: `3cf7322ce`
- Producer-door migration commit: `948660781`
- Prior main: `c0a9974dc760d1c1a0a5df6748fbc0181526a36d`
- Test: `tests/test_deletion_silent_failure_discrimination.py`

Content comparison, not line matching, shows that #7152 repaired four of the
five previously broken physical coordinates:

- `_with_census_partition` no longer reads either `derived-contract` or `gap:*`;
  it partitions coordinate-keyed rows into closed `constructed` and
  `unconstructed` outcomes.
- `main` no longer derives `R_cm_derived_contract` from the deleted key; it reads
  `_attested_cm_counts(result)[0]`.
- `test_with_census_conservation.py` no longer blesses the deleted wire; it
  rejects `derived-contract` as an outcome and verifies identical coordinate
  manifests.
- `test_recensus_aggregation_keyerror.py` is blob-identical across the two main
  pins and still uses the stale `construction-panic` category.  This branch
  inverts that remaining test coordinate to canonical `panic`.

The rename-collapsed `elif category == "panic"` arm was also removed by #7152.
Therefore a seal refusal that names all five old coordinates would contradict
the pinned source.  No corpus conclusion is drawn here; Keaton owns that run.

## Discrimination twins

The focused tests execute their truthful and lying twins before scanning live
source:

- `constructed + derived-contract` and `unconstructed + gap:*` are accepted
  because a canonical producer-written key participates in each expression.
- an exclusive `derived-contract` read is rejected because no producer writes
  that key.
- distinct `completed` / `panic` / `instrument-blind` arms are accepted.
- two `category == "panic"` arms in one chain are rejected because the later arm
  is unreachable.

The live positive control authenticates both additive expressions in
`seal_board_from_aggregate`; this is not a spelling grep.

## Existing teeth inverted, not deleted

Three existing test files read the same recensus wires and had blessed deleted
vocabulary.  This branch inverts the aggregation and panic-collection tests to
canonical `panic`; #7152 independently replaces the With test's bucket model
with canonical coordinate-row testimony:

- `test_recensus_aggregation_keyerror.py`
- `test_recensus_panic_collection.py`
- `test_with_census_conservation.py`

The With source now explicitly rejects deleted outcomes and preserves both
constructed and unconstructed coordinate keys.  Its focused runtime result is
unmeasured in this re-pin because the local selection was killed and battleaxe
was reserved for the corpus census.
A same-spelling `construction-panic` assertion in `test_commit_measurement.py`
reads an unrelated `valuesByUnit` container and was not changed.

## First-terminal chains

### Exclusive read of an unproduced key

- Exact repaired source content: `948660781` on main `8c117c656`
- Input and former coordinates: `_with_census_partition`'s exclusive
  `derived-contract` and `gap:*` reads, plus `main`'s exclusive
  `derived-contract` read
- Entrance: `_with_census_partition`'s returned canonical mapping to census
  quantity expressions on the authenticated `cmResolutions` receiver
- First observed terminal before #7152: live finding set had 3 production rows
- After #7152: live finding set is empty; the planted exclusive liar still
  produces exactly 1 finding and the additive control remains accepted

### Rename-collapsed predicate

- Exact repaired source content: `948660781` on main `8c117c656`
- Input and former coordinate: `control_effect_recensus.main`, two arms with
  predicate `category == "panic"`
- Entrance: physical `if` / `elif` chain predicate normalization
- First observed terminal before #7152: 1 physical unreachable chain
- After #7152: live finding set is empty; the planted collapsed liar still
  produces exactly 1 finding and the distinct-arm control remains accepted

## Exact-content isolated source-law reproducer

Command, unpiped locally:

```sh
/usr/local/opt/python@3.12/bin/python3.12 -m pytest -q tests/test_deletion_silent_failure_discrimination.py
```

At exact source-law content `948660781` over main `8c117c656`, local exit was
`0`; result was **2 passed in 0.17s**.  Both tests execute their lying and
truthful planted arms before asserting that the live offender set is empty.

An immediately preceding run against #7152 with the old producer entrance
returned exit `1`, `1 failed, 1 passed in 0.13s`, at the assertion
`producer vocabulary must be non-empty`.  That was detector API drift caused by
the bucket-to-coordinate-row producer rewrite, not the exclusive-read law
firing.  The detector now reads `_with_census_partition`'s returned mapping.

A separate local selection of four legacy recensus tests exited `143` with no
output.  It is discarded, and no pass/fail claim is made for those four tests.
Battleaxe was not used because Keaton owns the census lease.

## Prior combined reproducer

The prior combined run, before PR-A, used this unpiped battleaxe command:

```sh
bin/bpytest -q tests/test_deletion_silent_failure_discrimination.py implementations/python/sugar-lift-py-tests/tests/test_recensus_aggregation_keyerror.py::test_aggregation_survives_legacy_panic_row_without_family_key implementations/python/sugar-lift-py-tests/tests/test_with_census_conservation.py::test_conservation_identity_is_stated_on_partition_and_refusal implementations/python/sugar-lift-py-tests/tests/test_with_census_conservation.py::test_known_constructed_with_item_shows_constructed_gt_zero implementations/python/sugar-lift-py-tests/tests/test_with_census_conservation.py::test_unconstructed_with_item_appears_in_canonical_partition_not_silent_drop
```

Exit: `1`; result: `5 failed, 1 passed`.

Membership is the evidence, not the aggregate count:

- red: 2 source discrimination laws
- red: 3 canonical With conservation teeth
- green: 1 canonical-panic aggregation control

An earlier whole-file battleaxe run also encountered the unrelated pre-existing
`control_effect_recensus._measure_file` retired-side-door terminal.  That row was
excluded from the exact-SHA denominator above; it is not attributed to these
inversions.

## Deliberately absent projection

No shortened-body statement-count test was authored.  Without a semantic
conservation identity it would encode deleted taxonomy as a historical baseline
and condemn deliberate removal.  The census producer/consumer conservation seal
is the honest enforcement ceiling for that path.

## Not claimed

- No corpus result or seal outcome at `8c117c656` is claimed; Keaton owns that
  measurement.
- The four old production/With-test coordinates are not claimed to remain live;
  pinned content shows their replacement.
- The unchanged aggregation-test coordinate is not claimed to be a production
  census failure; it is stale test vocabulary repaired on this branch.
- Additive legacy reads are not claimed to lose mass.
- The source discriminator is not claimed to replace the runtime With
  conservation tooth; they inspect static wire identity and end-to-end mass,
  respectively.
- Keaton's `constructed_zero`, `swallow_panic`, `drop_opaque`, and `crash_mid`
  twins are receipt-level; this family does not claim to replace or duplicate
  them.
- The discarded exit-143 local run is not a test result.
