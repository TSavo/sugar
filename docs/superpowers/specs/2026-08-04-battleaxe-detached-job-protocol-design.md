# Battleaxe Detached Job Protocol Design

## Problem

`bin/brun` currently owns a foreground execution contract. In Docker mode it
starts `docker run --rm` through one SSH session and returns when that container
exits. A caller can put `nohup ... &` inside the container, but that only
detaches from the container's shell. The process, PID namespace, `/proc`, and
`/tmp` receipts still belong to the disposable container and disappear when
the foreground `docker run --rm` owner exits.

Three pandas census launches used exactly that unsupported shape. Their printed
PID and log paths were container-local, so later `brun` probes necessarily
entered a different container and could not observe either. No remote-root
cleanup was requested; the evidence loss was ownership and lifetime, not a
proven signal, OOM, reaper, or SSH failure.

## Decision

Add an explicit host-owned detached-job protocol for managed Docker runs.

- `sugarbin run --host bx --detach <job-id> ...` performs the ordinary sync,
  artifact provisioning, and preflight setup, then gives ownership of the
  complete `docker run --rm` command to `systemd-run --user` on battleaxe.
- `systemd-run --user` is the only detached supervisor. If user systemd or
  `Linger=yes` is unavailable, the command refuses by name. There is no `nohup`
  or tmux fallback.
- A durable job directory lives at
  `$BCARGO_REMOTE_ROOT/.sugar-bx-jobs/<job-id>` on the host. It owns the runner,
  stdout/stderr log, immutable launch testimony, and atomically published final
  exit code.
- The job directory is bind-mounted into the container at
  `/run/sugar-bx-job`, exposed as `SUGAR_BX_JOB_DIR`, so subject receipts can be
  written into the same host-owned lifetime.
- `sugarbin job status` and `sugarbin job collect` are separate operations.
  Status never starts a new container. Collect transfers the complete durable
  job directory, not an inferred `/tmp` path.

The protocol is initially Docker-only. Ambient detachment has a different
artifact and environment lifetime and refuses rather than silently selecting a
weaker owner.

## Refusal Contract

- Invalid job IDs refuse with `crime=invalid-detached-job-id`.
- An existing job directory refuses with `crime=duplicate-detached-job-id`.
- Missing user systemd refuses with
  `crime=detached-supervisor-unavailable`.
- Missing `Linger=yes` refuses with `crime=detached-linger-disabled`.
- `BCARGO_CLEAN_REMOTE_ROOT=success|always` refuses with
  `crime=detached-cleanup-policy-conflict` because the foreground launcher
  cannot delete the root of a running detached job.
- Detached ambient execution refuses with
  `crime=unsupported-detached-execution-route`.
- A launched unit that is neither active nor carrying a final status refuses
  with `crime=detached-job-testimony-missing`.

No refusal falls back to container-local `nohup`.

## Executable Discrimination

The focused contract must prove both arms before implementation is claimed:

1. Original failure: a process detached inside `docker run --rm` does not own a
   durable PID or container-local `/tmp` log after the container owner exits.
2. Host-owned success: launch a delayed job, end the launching SSH session, and
   prove from a second SSH session that the unit remains active and the host log
   is readable.
3. Final success: after completion, status reports exit `0` and collect returns
   the host-owned log/status bytes.
4. Final failure: a subject exiting `23` durably reports exactly `23`.
5. Invalid ID, duplicate ID, unavailable systemd, unavailable linger, cleanup
   conflict, and unsupported route each refuse before subject execution with
   their own crime.

## Alternatives Rejected

`tmux` survives SSH disconnects on battleaxe, but durable status, collision
handling, and log ownership would need a second handwritten supervisor
protocol. Documenting foreground-only execution would stop the false claim but
leave every long corpus measurement structurally tied to an agent turn.

User systemd is already present, has `Linger=yes`, exposes structured cgroup
ownership, and preserved both exit `0` and exit `23` in the measured prototype.
