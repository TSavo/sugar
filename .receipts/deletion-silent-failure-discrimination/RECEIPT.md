# Deletion Silent-Failure Discrimination — Red Receipt

## Pins

- Measured main: `4accd5433fdf35f2468d4100b0689047d8a97549`
- Red test commit: `30b6ce510bcb64363ff25be78d7a1e71f43eec0b`
- Prior main: `73647afdebdb483b038519782530ce68075a980b`
- Test: `tests/test_deletion_silent_failure_discrimination.py`

The four relevant source/test blobs are identical between the prior and measured
main.  The deletion audit regenerated 528 rows with exit 0.  Its 216 stale-reader
rows have the same content-normalized semantic multiset on both pins:
`sha256:29ccbd06c5061008fc71a0cead5537a4e531b6270d9b4788b2abe58a2f4ef1ab`.
There were zero semantic additions, zero removals, and zero coordinate changes
among uniquely identified rows.

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

## First-terminal chains

### Exclusive read of an unproduced key

- Exact worktree SHA: `30b6ce510bcb64363ff25be78d7a1e71f43eec0b`
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

Command, unpiped:

```sh
/usr/local/opt/python@3.12/bin/python3.12 -m pytest tests/test_deletion_silent_failure_discrimination.py::test_census_wire_rejects_exclusive_unproduced_reads_but_accepts_additive_reads -q
```

Exit: `1`; result: `1 failed`.

### Rename-collapsed predicate

- Exact worktree SHA: `30b6ce510bcb64363ff25be78d7a1e71f43eec0b`
- Input and coordinate: `control_effect_recensus.main`, first arm line 1657,
  unreachable duplicate arm line 1669, predicate `category == "panic"`
- Entrance: physical `if` / `elif` chain predicate normalization
- First observed terminal: live finding set has 1 physical chain; pytest fails the
  empty-set law
- After repair: next terminal or constructed result is unmeasured

Command, unpiped:

```sh
/usr/local/opt/python@3.12/bin/python3.12 -m pytest tests/test_deletion_silent_failure_discrimination.py::test_category_dispatch_rejects_collapsed_predicates_but_accepts_distinct_arms -q
```

Exit: `1`; result: `1 failed`.

## Deliberately absent projection

No shortened-body statement-count test was authored.  Without a semantic
conservation identity it would encode deleted taxonomy as a historical baseline
and condemn deliberate removal.  The census producer/consumer conservation seal
is the honest enforcement ceiling for that path.

## Not claimed

- The 528 raw audit rows are not defect claims.
- Additive legacy reads are not claimed to lose mass.
- The known control-effect recensus failure is not attributed to either queued
  merge.
- No post-repair next terminal or green result has been measured.
