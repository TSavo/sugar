# Deletion Silent-Failure Discrimination — Red Receipt

## Pins

- Measured main: `c0a9974dc760d1c1a0a5df6748fbc0181526a36d`
- Exact tested worktree: `1509a08a827079181b1e39b83edbea1e02f22ee6`
- Rebased source-law commit: `1a158dedc`
- Canonical-vocabulary inversion commit: `09912412a`
- Prior main: `ec651f47ea842dbb7d56ca4c7d01479d696f109d`
- Test: `tests/test_deletion_silent_failure_discrimination.py`

The three coordinate-bearing source/test blobs are identical between the prior
and measured main: `control_effect_recensus.py`,
`test_recensus_aggregation_keyerror.py`, and
`test_with_census_conservation.py`.  That authenticates all five physical
broken coordinates by content, not by line number.  The live additive control
in `compose_control_effect_board.py` survived PR-A unchanged within its enlarged
function even though that file's blob changed.

The deletion audit regenerated **542 raw rows** with unpiped exit 0 against the
measured main: 73 shortened-body observations, 241 removed qnames, 2 removed
modules, 224 stale-reader candidates, and 2 parent parse rows.  The increase
from the prior 528 is 14 query observations introduced by PR-A's composer
rewrite: 6 body-diff observations and 8 stale-vocabulary observations at 4
physical coordinates.  They are not deletion-defect claims.  The 4 physical
reader additions inspect the new terminal attestation or a fixture that authors
that testimony; the compose readers validate and refuse on missing testimony,
so they cannot produce the confident-zero failure selected by this test.

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

- Exact worktree SHA: `1509a08a827079181b1e39b83edbea1e02f22ee6`
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

- Exact worktree SHA: `1509a08a827079181b1e39b83edbea1e02f22ee6`
- Input and coordinate: `control_effect_recensus.main`, first arm line 1657,
  unreachable duplicate arm line 1669, predicate `category == "panic"`
- Entrance: physical `if` / `elif` chain predicate normalization
- First observed terminal: live finding set has 1 physical chain; pytest fails the
  empty-set law
- After repair: next terminal or constructed result is unmeasured

## Exact-SHA isolated source-law reproducer

Command, unpiped on battleaxe:

```sh
bin/bpytest -q tests/test_deletion_silent_failure_discrimination.py
```

At exact worktree `1509a08a827079181b1e39b83edbea1e02f22ee6`,
exit was `1`; result was **2 failed in 0.69s**:

- exclusive-read tooth: 3 live production findings
- rename-collapse tooth: 1 live physical chain

This test file parses source with `ast`; it neither imports nor executes
`compose_control_effect_board`.  Its output contains no frontier-attestation or
conservation-seal refusal.  Therefore these two reds are the source laws firing,
not PR-A's intended refusal.

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

- The 542 raw audit rows at `c0a9974dc` are not defect claims; neither are the
  14 observations newly exposed by PR-A's source rewrite.
- Additive legacy reads are not claimed to lose mass.
- PR-A's frontier-attestation refusal is intentional and is not counted as one
  of the two source-law reds.
- The source discriminator is not claimed to replace the runtime With
  conservation tooth; they inspect static wire identity and end-to-end mass,
  respectively.
- Keaton's `constructed_zero`, `swallow_panic`, `drop_opaque`, and `crash_mid`
  twins are receipt-level; this family does not claim to replace or duplicate
  them.
- No post-repair next terminal or green result has been measured.
