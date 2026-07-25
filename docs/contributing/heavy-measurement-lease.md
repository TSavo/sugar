# The machine-wide heavy-measurement lease

## The defect

`python-package-suite.yml` had its own repository-wide concurrency group with
`cancel-in-progress: false`, and it still produced **zero artifacts across five
runs**: `dea47f1f8`, `e0a78ec52`, `d243fcacf`, `6d9db3a8f`, `f0cddfd76` were all
cancelled. The first artifact this repo ever banked came from run
`30174018299` at `421ef4157`, and only because merges were frozen around it.

`Python sole-construction floors` failed the same way one layer down: on a
single PR, three rapid pushes produced three cancellations (20:26:50, 20:27:52,
20:28:35) while every lighter job completed.

The cause is not the setting. It is what the setting can and cannot do:

* `cancel-in-progress: false` protects a run that has **already started**.
* GitHub keeps exactly **one pending run per concurrency group**. A new run
  evicts the queued one.

So our own merge rate was deleting our heaviest instruments, and a single
*shared* group across the heavy classes would have made it worse: then every
heavy class competes for that one pending slot.

## The ruling

Two responsibilities were being asked of one mechanism. They are now split:

```
GitHub queue: preserve every requested measurement   -> NO concurrency group
BX lease:     only one heavy measurement executes    -> tools/heavy_measurement_lease.py
```

Every heavy run is retained by GitHub. Overlap is settled on the box.

## The mechanism

`tools/heavy_measurement_lease.py` wraps the measured command in a
machine-wide `flock` on `/var/tmp/sugar-heavy-measurement.lease`
(`$SUGAR_HEAVY_LEASE_PATH`):

```bash
python3 tools/heavy_measurement_lease.py \
  --class python-package-suite \
  --record "$GITHUB_WORKSPACE/lease-record.json" \
  --embed-into "$GITHUB_WORKSPACE/suite-report.json" \
  -- bash sweep.sh
```

`fcntl.flock` **is** `flock(2)` — the same kernel lock `flock(1)` takes, on the
same file, interoperable with it. Python holds it rather than the util-linux
binary so the release paths can be tested on every platform we develop on;
`flock(1)` does not exist on macOS, and an untested release path on a lease
that deadlocks the whole box is not acceptable.

Release properties, each covered by a test in
`tests/test_heavy_measurement_lease.py`:

| path | released by |
| --- | --- |
| success | explicit unlock + fd close |
| non-zero exit | explicit unlock + fd close |
| timeout (never acquired) | nothing to release; command never ran |
| SIGINT / SIGTERM / SIGHUP | handler forwards, then unlock + fd close |
| SIGKILL | **the kernel**, when the last holder's fd closes |

The lease descriptor is deliberately **inheritable**: the measured command
holds the same lock. SIGKILL the wrapper and the orphaned census keeps the
lease until it exits, so nothing starts on top of it.

On timeout the wrapper prints stale-owner diagnostics and **exits 75 without
running the command**. It never "recovers" by running concurrently: a timing
number taken beside another census is not a slow measurement, it is not a
measurement.

## The status vocabulary

```
queued -> lease-waiting -> measuring -> completed
                                          |- findings
                                          \- zero-findings
queued / lease-waiting -> cancelled-before-measurement
measuring              -> interrupted-during-measurement
```

**Only `completed/zero-findings` may support a zero claim.** Cancelled,
interrupted, refused, and absent are all *no measurement* — never green. This
is what makes an evicted run structurally different from a clean floor; those
eight lost runs went unnoticed because from outside they looked identical.

Every receipt carries `measurementStatus` and a single derived boolean,
`supportsZeroClaim`.

## Artifact telemetry

The receipt is written on every exit path and embedded into the measurement's
own artifact as `leaseRecord`, so there is one schema, not two:

| field | meaning |
| --- | --- |
| `leaseClass` | which heavy class held the lease |
| `acquired`, `timedOut` | whether the measured section was entered at all |
| `measurementStatus`, `supportsZeroClaim`, `zeroClaimStatus` | the vocabulary above |
| `requestedAtUnix`, `acquiredAtUnix`, `releasedAtUnix` | request, acquisition, release |
| `waitSeconds`, `heldSeconds` | queue time and measured time |
| `measuredCommit` | the exact commit measured |
| `owner.*` | run ID, attempt, workflow, job, ref, runner name, holder PID |
| `command`, `commandExitStatus` | what ran and how it ended |
| `leaseIdentity.bootId/device/inode` | kernel identity and the lock's identity |
| `staleOwnerDiagnostics` | who held it, when refusal happened |

## The checks

* `tools/heavy_measurement_lease_gate.py --record R --require-commit SHA`
  — red unless the lease was acquired, for that commit, with a readable
  interval. Add `--require-zero-claim` wherever an R = 0 claim is made.
* `... --scope-check A --scope-check B` — receipts sharing a `bootId` must
  share a lock `inode`, and their intervals must not overlap. This is what
  stops the lease from being per-container theatre: if the runner containers
  do not share the lease path, the inodes differ and this goes red.
* `tools/heavy_measurement_attendance.py --commit SHA` — the roll call. Roster
  minus attended is `R_attendance`; those instruments did not report, and their
  silence is not a clean floor.

## Known limitation: no dedicated heavy runner label

Every Linux runner registered on this repo carries exactly
`[self-hosted, Linux, X64]` (checked via `gh api
repos/TSavo/sugar/actions/runners`). There is no `sugar-heavy` label to route
lease-waiting jobs onto, so a job waiting for the lease **does** occupy a
general runner slot. Fixing this properly means registering the battleaxe
runners with an extra label — a change to runner registration, not to this
repo — after which each heavy workflow's `runs-on:` gains that label. It is
deliberately not approximated here.

The related open question is whether `/var/tmp` is shared across runner
containers on battleaxe. If it is not, the lease is per-container and
serializes nothing — which is exactly why every receipt records
`bootId`/`device`/`inode` and why `--scope-check` exists. That check is the
measurement; do not assume the answer.
