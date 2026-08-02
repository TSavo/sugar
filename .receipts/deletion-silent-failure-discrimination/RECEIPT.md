# Deletion Silent-Failure Discrimination — Red Receipt

## Pins

- Measured main: `ec651f47ea842dbb7d56ca4c7d01479d696f109d`
- Rebased source-law commit: `7b2f0318f`
- Canonical-vocabulary inversion commit: `112ea1752f1f69941aefa4b5be1af7d492ed5dec`
- Prior main: `4accd5433fdf35f2468d4100b0689047d8a97549`
- Test: `tests/test_deletion_silent_failure_discrimination.py`

The four relevant source/test blobs are identical between the prior and measured
main.  The deletion audit regenerated 528 rows with exit 0.  Its 216 stale-reader
rows have the same content-normalized semantic multiset on both pins:
`sha256:29ccbd06c5061008fc71a0cead5537a4e531b6270d9b4788b2abe58a2f4ef1ab`.
There were zero semantic additions and zero removals.  Two uniquely identified
readers in `timeout_zero_tolerance.py` moved down three lines; neither belongs to
the five broken physical coordinates.  Content, rather than line number, keeps
the partition unchanged.

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

Three existing test files read the same recensus wires and still blessed deleted
vocabulary.  They now assert canonical `panic`, `constructed`, and
`unconstructed` testimony:

- `test_recensus_aggregation_keyerror.py`
- `test_recensus_panic_collection.py`
- `test_with_census_conservation.py`

The With teeth explicitly reject `typed_gaps`, preserve both constructed and
unconstructed end-to-end inputs, and remain red at the stale partition entrance.
A same-spelling `construction-panic` assertion in `test_commit_measurement.py`
reads an unrelated `valuesByUnit` container and was not changed.

## First-terminal chains

### Exclusive read of an unproduced key

- Exact worktree SHA: `112ea1752f1f69941aefa4b5be1af7d492ed5dec`
- Input and coordinates:
  - `control_effect_recensus._with_census_partition`, line 377,
    `derived-contract`
  - `control_effect_recensus._with_census_partition`, line 378, `gap:*`
  - `control_effect_recensus.main`, line 1797, `derived-contract`
- Entrance: `_tally_cm_resolutions` producer vocabulary to census quantity
  expressions on the authenticated `cmResolutions` receiver
- First observed terminal: live finding set has 3 rows; pytest fails the empty-set
  law
- After repair: next terminal or constructed result is unmeasured

### Rename-collapsed predicate

- Exact worktree SHA: `112ea1752f1f69941aefa4b5be1af7d492ed5dec`
- Input and coordinate: `control_effect_recensus.main`, first arm line 1657,
  unreachable duplicate arm line 1669, predicate `category == "panic"`
- Entrance: physical `if` / `elif` chain predicate normalization
- First observed terminal: live finding set has 1 physical chain; pytest fails the
  empty-set law
- After repair: next terminal or constructed result is unmeasured

## Exact-SHA combined reproducer

Command, unpiped on battleaxe:

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

- The 528 raw audit rows are not defect claims.
- Additive legacy reads are not claimed to lose mass.
- The known control-effect recensus failure is not attributed to #7150.
- The source discriminator is not claimed to replace the runtime With
  conservation tooth; they inspect static wire identity and end-to-end mass,
  respectively.
- No post-repair next terminal or green result has been measured.
