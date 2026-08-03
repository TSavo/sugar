# ConstructionPanic census escape receipt

## Pins

- Current pinned main: `2c4bd291825a8b08a673818bc0ad1f72f14524fa`
- Original red pin: `b1824eb6217fb92c5013743401bfe6edce2abcfa`
- Rebased implementation commit: `e0204c1ecb4bffea53b95adacb1aadfa0a30977a`
- Worktree: `/Users/tsavo/.herdr/worktrees/provekit/fenster-work`
- Branch: `fenster/7185`

The three production files were verified by content at the pinned main before
editing. The earlier discrimination head
`01dfab7e80b994bc3ab8f615126f3b3856051dc6` is not an ancestor of this pin, so
it was preserved on `fenster/work` rather than rewritten.

Re-pin verification compared both production scripts and the existing panic-test
surfaces from `b1824eb6` to `227089c8`; `git diff --exit-code` returned `0`.
After restacking, the three changed production/test files were byte-identical to
the pre-rebase branch (`git diff --exit-code 5c31b59e..HEAD -- <three paths>`,
exit `0`). The focused family then passed `6/6` in `0.68s`, unpiped exit `0`.

The next re-pin compared the same production and existing-test surfaces from
`227089c8` to `c710309d`; the content diff again returned `0`. Four unchanged
combined attempts returned, in order: `143` after one passing arm, `6/6` exit
`0`, `143` after two passing arms, and `6/6` exit `0`. An isolated six-process
sweep had five exit `0` and one empty-log `143`; that exact context-manager arm
then passed unchanged, exit `0`. No assertion failed at this pin, but the host's
intermittent SIGTERM behavior is not claimed green. These commands loaded no
package conftest and did not invoke `sugarbin`, so this receipt also makes no
claim about #7211's migrated binary resolve path.

At `ccea5292`, #7210 changed the same consumer function by moving contract-ref
fallback after per-file roster enrollment. It did not change the source-identity
catch repaired here. After restacking, the six #7185 arms and #7210's new
`test_contract_ref_fallback_panic_stays_loud_after_roster_bank` tooth ran
together: `7 passed in 0.73s`, unpiped exit `0`. The branch diff against this
pin remains exactly three pure re-raise arms plus their tests and receipts; no
#7210 fallback code was duplicated or changed.

At `2c4bd291`, #7214 changed only `no_call_body_attribution.py`; every #7185
production and existing-test surface was content-identical to `ccea5292`
(`git diff --exit-code`, exit `0`). After restacking, the same seven combined
teeth passed in `0.70s`, unpiped exit `0`; `py_compile` also returned `0`.

## Red instrument

Command, run unpiped with the exit captured before the log was read:

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src:implementations/python/sugar-lift-python-source/src:implementations/python/sugar-source-tree/src \
  python -m pytest --noconftest -q \
  implementations/python/sugar-lift-py-tests/tests/test_recensus_construction_panic_escape.py \
  > /tmp/fenster-7185-red-combined.log 2>&1
```

Measured on `b1824eb6217fb92c5013743401bfe6edce2abcfa`:

```text
pytest_unpiped_rc=1
FFF...                                                                   [100%]
3 failed, 3 passed in 0.77s
```

All three failures were `DID NOT RAISE ConstructionPanic`. The three passing
arms were the sanctioned roster, context-manager-resolution, and residual
membranes enrolling authenticated construction-panic terminals.

`--noconftest` is deliberate: these script-only teeth do not need a Sugar
binary. The package autouse fixture invokes `bin/sugarbin` and the unavailable
local build rung terminated the otherwise focused run with exit `143`. That
terminated run was discarded and no counts were taken from it.

## First-terminal chains

### Outer roster recovery catch

- Input and coordinate: planted `ConstructionPanic` from
  `demand_function_roster`, `fixture.py:outer-roster-escape`.
- Entrance: `control_effect_recensus.terminal_after_measure_escape`.
- First observed terminal on pinned main: the planted panic vanished and the
  function returned the earlier outer-error row.
- After fix: the exact planted exception object is the next terminal
  (`caught.value is planted`).

### Source-identity catch

- Input and coordinate: planted `ConstructionPanic` from `path_source`,
  `fixture.py:source-identity`.
- Entrance: `recensus_enumerate_consumer.measure_file_via_enumerate`, phase
  `source-identity`.
- First observed terminal on pinned main: an `instrumentFailure` row with phase
  `source-identity`.
- After fix: the exact planted exception object is the next terminal.

### Main-file-producer catch

- Input and coordinate: one authenticated one-file corpus; planted
  `ConstructionPanic` from `measure_file_via_enumerate`,
  `fixture.py:main-file-producer`.
- Entrance: `control_effect_recensus.main`, phase `main-file-producer`.
- First observed terminal on pinned main: a checkpointed `instrumentFailure`
  followed by compose refusing the unmeasured run.
- After fix: the exact planted exception object is the next terminal before a
  checkpoint can misclassify it.

## Green instrument

The red command was rerun unchanged after the three pure re-raise arms:

```text
pytest_unpiped_rc=0
......                                                                   [100%]
6 passed in 0.69s
```

This proves three exact-object propagation arms plus three sanctioned enrollment
controls. It does not claim a corpus result, a frontier width, or a broad Python
suite result.

## Separate scanner axis

The current repository scanner was run separately and remained red:

```text
current_catch_law_unpiped_rc=1
R_construction_panic_catches_outside_audit = 7
auditor_errors = 0
```

Its seven candidates include the three repaired pure re-raises and four
sanctioned conversion sites. This is the known #7186 stale-discriminator axis;
it was not changed, counted as a #7185 defect, or used to invalidate the runtime
identity evidence.
