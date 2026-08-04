# Managed Entrance Precondition Gate Design

## Status

Approved by the explicit 2026-08-03 direction to build the entrance gate from
declared requirements and falsify it against the nine observed axes.

## Problem

Battleaxe execution currently discovers several environmental preconditions
only after synchronization, artifact resolution, compilation, or proof-binary
resolution. The observed failures are not nine independent requirements to
copy into a checklist. They are evidence that the managed entrance has three
authorities whose obligations are not checked at their boundary:

- `sugar-build.toml` and adjacent toolchain manifests declare the tools and
  components required by the selected command;
- `bin/lib/sugar-bx.sh` chooses the remote root, cache, shelf, build, staging,
  and lock paths plus the foreground SSH lifetime;
- the required-artifact manifest declares the binaries a managed payload will
  execute.

The current authority is incomplete for `make test-showcases`: it is not a
named managed task, and its 64 enrolled scripts own additional declarations.
The gate must therefore derive from both the selected command closure and its
checked-in manifests. It must not encode the nine incidents as policy.

## Rejected Designs

### Hand-maintained precondition list

A new JSON/TOML file containing `git`, `rust-src`, shelf paths, and the other
observed incidents would reproduce the defect in a tidier form. It would not
change when a command, toolchain manifest, binary set, or path mode changes.

### Per-showcase checks

Adding `command -v` and write probes to individual `run.sh` files leaves the
failure after synchronization and binary resolution, duplicates ownership,
and cannot protect `bpytest`, `brun`, or `bcargo` callers of the same entrance.

## Design

### Managed command authority

An entry is managed only when the caller selects a named task with `--task`
and the broker obtains its command and closure from `sugar-build.toml`. The
showcase task adds one declarative closure descriptor:

```toml
[tasks.showcases]
capabilities = ["python-test", "python-scientific", "solver-z3", "solver-coq", "java", "node", "vampire"]
binaries = []
command = ["make", "test-showcases"]
network = "required"

[tasks.showcases.closure]
kind = "make-roster"
path = "Makefile"
variable = "SHOWCASE_RUNS"
retirements = ".github/showcase-retirements.json"
adjacent_manifests = ["rust-toolchain.toml"]
required_commands = ["git"]
artifacts = [
  "release:sugar",
  "debug:sugar-ir-smt-lib",
  "debug:sugar-ir-lean",
  "debug:sugar-ir-coq",
  "debug:sugar-ir-maude",
  "debug:sugar-walk-rpc",
  "debug:rust_test_assertions_rpc",
  "debug:witness_rpc",
  "debug:discharge_cli",
]
```

The closure describes where authority lives; it does not copy the enrolled paths or
the `rust-src` component. The resolver reads `SHOWCASE_RUNS`, subtracts only
the source-controlled retirements, and discovers `rust-toolchain.toml` beside
each active script. A raw battleaxe command whose argv matches a registered
task command is an authority bypass and refuses with
`crime=unmanaged-command-closure`, naming the task that must be selected.
Unrelated ad-hoc `brun` commands remain possible because no registered task
claims their argv. The profile-qualified artifact list moves the existing
Makefile literals into the task closure; the Makefile consumes the resolved
list instead of retaining a second binary roster.

The broker produces one deterministic precondition plan before remote work.
The plan is a projection of existing declarations, never an authored result:

1. Resolve the selected named task or explicit command.
2. Expand `make test-showcases` through the authoritative `SHOWCASE_RUNS`
   roster and retirement manifest.
3. Read adjacent declarative manifests in the selected command closure.
   In particular, `rust-toolchain.toml` supplies the exact channel and
   components such as `rust-src`.
4. Project core broker commands from the execution route itself. `git` is a
   broker requirement because repository identity and source-stamp discovery
   call it; it is not inferred from a prior missing-git log.
5. Project artifact, ABI, cache, shelf, and lock checks from the requested
   binary set and the transport-selected access mode.
6. Project process lifetime from the route. Battleaxe execution is foreground:
   the SSH session remains the owner until the child exits. Detached remote
   work is outside this entrance and cannot be reported as a managed run.

The canonical JSON plan names its source declarations and the derived checks.
Each check has a stable kind (`command`, `toolchain-component`,
`artifact-manifest`, `artifact-abi`, `cache-access`, `shelf-access`,
`rebuild-lock`, `process-lifetime`, or `declared-interpreter`). The kinds are
closed vocabulary; incident names never enter production policy.

The plan is checked in two stages:

- A lightweight host/image preflight runs before workspace synchronization or
  artifact construction. It checks required commands, exact declared versions,
  toolchain components, remote-root/path creation, and a disposable lock
  create/write/heartbeat/remove cycle. Each check emits its name, elapsed time,
  and pass/refusal outcome.
- The transport-owned pre-subject wrapper runs inside the selected managed
  image after the existing entrypoint authenticates the mounted artifact
  manifest. It proves each ELF artifact is loadable by that exact image,
  distinguishing ABI incompatibility from a product exit. Stage two bakes the
  same verifier into the newly published image entrypoint; stage one cannot
  change an entrypoint already sealed into an immutable image.

The preflight never repairs state. A failed write probe, missing component,
missing manifest, or ABI mismatch exits before the subject with a named
`crime=` terminal. Publication authority remains separate: a read-only shelf
consumer is checked for readable complete cells and is never probed for a
write it is not allowed to perform.

## Delivery Stages

### Stage one: authority and refusal instruments

Stage one lands the named showcase task and command closure, canonical plan
derivation, unmanaged-command refusal, finite rebuild-lock refusal, and
artifact ABI authentication. It also lands a nine-axis falsification fixture
which maps the empirical incidents to derived check kinds and requires every
row to be predicted by the plan.

Stage one does **not** publish an image. The current core image lacks `git` and
the declared `rust-src` component, so a showcase task under stage one refuses
before expensive work with those exact missing preconditions. That red is the
instrument correctly observing the current capability gap.

### Stage two: satisfying capability image

Stage two changes the Dockerfile through the single image entrance, installs
the declared command and toolchain component closure, publishes the immutable
image, updates the checked-in digest, and activates the profile-qualified
artifact provisioning already declared by stage one. It turns the stage-one
precondition red green without weakening, relocating, or bypassing any check.
Image publication and digest replacement are excluded from stage one because
they are an independently reviewable supply-chain change.

## Rebuild Lock Law

The rebuild single-flight loop must have a finite refusal arm. Failure to
create or write the lock parent, lock directory, PID, or heartbeat is a named
terminal. When stale reclaim cannot remove the lock, the resolver refuses once
with the exact lock path and observed holder/heartbeat state. It never loops on
`holder_pid=unknown heartbeat_age=999999`.

This strengthens the existing single-flight instrument without raising its
staleness threshold or silently bypassing serialization.

## Nine-Axis Falsification Account

The derived plan must explain every empirical axis:

- missing `git`: broker-command projection;
- missing shelf manifest: requested-binary artifact projection;
- GLIBC mismatch: mounted-ELF loadability projection;
- foreign cargo locks: route-selected cache/build-root write projection;
- read-only `.incoming`: shelf access-mode projection;
- missing `rust-src`: adjacent `rust-toolchain.toml` component projection;
- phantom rebuild lock: disposable lock-cycle projection plus terminal reclaim;
- detached process loss: foreground lifetime projection, with no managed
  detached success claim;
- bare Python dependency loss: named-task interpreter projection, already
  enforced by #7293.

If any axis lacks a producing declaration or route fact, the preflight reports
the authority gap and the run is unmeasured. It does not fill the gap with a
guessed requirement.

## Instrumentation and Tests

Focused shell contracts plant both arms:

- each manifest-derived tool/component is accepted when present and refuses by
  name when absent;
- a complete required-artifact set passes, a missing manifest refuses, and an
  ELF with an unavailable loader/version refuses before subject execution;
- readable read-only shelf consumption passes while a requested publisher must
  prove writable staging;
- a writable lock cycle passes, while an unwriteable PID/heartbeat or
  unreclaimable stale lock terminates with a named refusal;
- a foreground remote child preserves its exit code; no detached outcome is
  minted by the broker;
- the static derivation receipt accounts for all nine observed axes without an
  incident-name list in production code.

The existing enrolled sugarbin Docker and shelf contracts call these teeth, so
the gate has a current workflow execution edge rather than existing only as a
referenced test.

## Non-Claims

This change does not make detached remote processes durable, repair old remote
roots or shelf cells, infer arbitrary shell dependencies, or claim showcase
semantics. It moves declared preconditions to the entrance and makes missing
authority refuse before expensive work. Detached remote execution remains
unsolved: stage one authenticates foreground SSH ownership and deliberately
declines to mint any managed success claim for a child detached from that
session.
