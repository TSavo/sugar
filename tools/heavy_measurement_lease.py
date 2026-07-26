#!/usr/bin/env python3
"""Machine-wide heavy-measurement lease. ONE door for every heavy class.

THE DEFECT THIS FIXES
=====================

GitHub ``concurrency`` was being asked to do two incompatible jobs at once:

    1. preserve every requested measurement, and
    2. ensure only one heavy measurement executes at a time.

It cannot do (1). GitHub keeps exactly ONE pending run per concurrency group,
so a third queued run EVICTS the second -- even with
``cancel-in-progress: false``, which only protects a run that has already
STARTED. ``python-package-suite.yml`` was starved inside its own group by our
own merge rate: five runs (dea47f1f8, e0a78ec52, d243fcacf, 6d9db3a8f,
f0cddfd76) cancelled, zero artifacts. A single shared group across the heavy
classes does not fix this; it makes it worse, because then every heavy class
competes for the one pending slot.

So the two jobs are split, and this program is half two::

    GitHub queue: preserve every requested measurement   (no concurrency group)
    BX lease:     ensure only one heavy measurement runs (this program)

Every heavy class -- the authoritative package suite, the sole-construction
corpus floors, the pandas/NumPy censuses, the restored-suite sweep -- wraps its
measured command here. Overlapping GitHub runs all START and all survive; only
one is ever inside the measured section.

WHY A FILE LOCK, AND WHY NOT ``flock(1)``
=========================================

``fcntl.flock`` IS ``flock(2)`` -- the identical kernel lock the ``flock(1)``
utility takes, on the identical file, fully interoperable with it. What the
Python form buys is that the lease has ONE implementation on every platform we
develop on: ``flock(1)`` is util-linux and absent on macOS, so a shell wrapper
around it would have been a mechanism whose release paths could only ever be
exercised on the runner that must not deadlock. The teeth in
``tests/test_heavy_measurement_lease.py`` run everywhere because of this
choice.

The lock lives on an open file descriptor. The KERNEL releases it when that
descriptor closes: on success, on failure, on timeout, on SIGINT/SIGTERM/SIGHUP,
and on SIGKILL, which no handler can catch. A leaked lease deadlocks all heavy
work on the box, so release must not depend on our own bookkeeping running. The
handlers below exist to write the RECEIPT and to propagate the signal; they are
not what frees the lock.

NEVER "RECOVER" BY RUNNING CONCURRENTLY
=======================================

If the lease cannot be taken within ``--timeout``, this program prints
stale-owner diagnostics and exits 75 (EX_TEMPFAIL) WITHOUT running the command.
A timing number taken beside another census is not a slower number; it is not a
measurement. Refusing is the honest outcome, and the receipt says so in a field
``tools/heavy_measurement_lease_gate.py`` can read.

Usage::

    python3 tools/heavy_measurement_lease.py \\
        --class python-package-suite \\
        --record "$GITHUB_WORKSPACE/lease-record.json" \\
        [--embed-into suite-report.json] [--timeout 14400] \\
        [--lease ~/.cache/sugar/binaries/.sugar-heavy-measurement.lease] \\
        -- <command> [args...]

The default lease path already resolves correctly from both sides of the bind
mount, so `--lease` is normally unnecessary. NEVER point it at /var/tmp: that
path is per-container on battleaxe and a lease there serializes nothing.

Exit status: the command's own status, or 75 if the lease was never acquired.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import os
import signal
import subprocess
import sys
import time

EX_USAGE = 64
EX_TEMPFAIL = 75

# THE STATUS VOCABULARY
#
#   queued -> lease-waiting -> measuring -> completed
#                                             |- findings
#                                             \- zero-findings
#   queued / lease-waiting -> cancelled-before-measurement
#   measuring              -> interrupted-during-measurement
#
# ONLY `completed/zero-findings` MAY SUPPORT A ZERO CLAIM.
#
# Five package-suite runs and three sole-construction-floor runs were lost
# because "cancelled before it started" and "ran and found nothing" are the
# same silence from outside. They are not the same fact: one is R = 0, the
# other is R UNMEASURED. This vocabulary is what makes them different objects
# in the artifact, so no reader and no gate can confuse them again.
STATUS_QUEUED = "queued"
STATUS_LEASE_WAITING = "lease-waiting"
STATUS_MEASURING = "measuring"
STATUS_COMPLETED_FINDINGS = "completed/findings"
STATUS_COMPLETED_ZERO_FINDINGS = "completed/zero-findings"
STATUS_CANCELLED_BEFORE = "cancelled-before-measurement"
STATUS_INTERRUPTED_DURING = "interrupted-during-measurement"

# The one status a zero claim may rest on.
ZERO_CLAIM_STATUS = STATUS_COMPLETED_ZERO_FINDINGS

# THE LEASE MUST LIVE ON A HOST-SHARED PATH, AND THIS ONE DOES.
#
# The first live run of this mechanism proved the point the hard way. Two heavy
# jobs took the lease on /var/tmp with a wait of 0.0007s each and OVERLAPPED,
# because battleaxe's runners are containers and /var/tmp is per-container:
#
#   suite  host cad95bf8f5de  bootId d257d14e...  dev/ino 1048601/1740385
#   floors host 7d0e695e838d  bootId d257d14e...  dev/ino 1048637/2882278
#
# Same kernel, different inode: a lease that serialized nothing. The receipts
# caught it on day one, which is exactly why they record bootId and dev/ino.
#
# `~/.cache/sugar/binaries` is bind-mounted from the SAME host directory into
# every runner container (verified across all twelve live containers), so a lock
# file there is one lock for the whole machine.
#
# THE DEFAULT IS `~`, NOT A HARDCODED `/home/runner`, AND THAT MATTERS.
#
# The bind mount joins two names for one directory: inside a runner container
# HOME is `/home/runner`, on the host it is the owning user's home, and both
# resolve to the same host inode. A hardcoded `/home/runner` is therefore
# correct in exactly one of the two places a caller can stand. Off-runner it
# does not exist and is not writable, so every interactive caller died in
# `os.makedirs` with a bare `PermissionError` traceback -- no named refusal, no
# statement of the right path.
#
# That failure mode has already cost a real overlap. Faced with the traceback,
# the obvious workaround is `--lease /var/tmp/...`, which is per-container on
# battleaxe and is precisely how two heavy jobs took the lease 0.0007s apart and
# ran side by side. A default that fails opaquely teaches the one workaround
# that breaks the invariant.
#
# `expanduser` resolves correctly from both sides of the mount. It is not
# trusted blindly: `_require_machine_wide` still proves the resolved path is not
# container-private before any measurement runs, and `_require_usable_directory`
# turns an unusable directory into a named refusal that states the correct path
# instead of a traceback.
DEFAULT_LEASE_PATH = os.environ.get(
    "SUGAR_HEAVY_LEASE_PATH",
    os.path.expanduser("~/.cache/sugar/binaries/.sugar-heavy-measurement.lease"),
)
DEFAULT_TIMEOUT_SECONDS = float(
    os.environ.get("SUGAR_HEAVY_LEASE_TIMEOUT_SECONDS", "14400")
)
# Poll interval while waiting. LOCK_EX|LOCK_NB in a loop rather than a blocking
# LOCK_EX so the wait is interruptible, bounded, and reports progress -- a
# blocking acquire that is still blocking at the job timeout leaves no receipt.
POLL_SECONDS = 2.0


def _boot_id():
    """The kernel's identity -- shared by every container on this machine.

    Container hostnames are per-container, so hostname cannot tell us whether
    two runners are the same machine. ``boot_id`` can.
    """
    try:
        with open("/proc/sys/kernel/random/boot_id", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return "unavailable"


def _log(message):
    print(f"heavy-measurement-lease: {message}", file=sys.stderr, flush=True)


class LeaseNotMachineWide(Exception):
    """The lease file is private to this container. It serializes nothing.

    A lock nobody else can see is worse than no lock: it produces a receipt
    saying `acquired` while two censuses run side by side. That is the exact
    shape of dishonesty this mechanism exists to remove, so it is a REFUSAL,
    not a warning.
    """


class LeaseDirectoryUnusable(Exception):
    """The lease file's directory cannot be created or written.

    Raised INSTEAD of letting `os.makedirs`/`open` surface a bare `OSError`
    traceback. The distinction is not cosmetic: the traceback names a path and
    an errno, and the obvious workaround it invites is `--lease /var/tmp/...`,
    which is per-container on battleaxe and has already produced two heavy jobs
    overlapping with a 0.0007s wait. So the refusal has to carry the correct
    path, not merely the failure.
    """


class LeaseTimeout(Exception):
    """The lease was not acquired. The command must not run."""


class LeaseCancelled(Exception):
    """A stop signal arrived while still waiting. No measurement happened.

    This is the eviction case made visible: the run was told to stop before it
    ever entered the measured section, so its artifact must say
    `cancelled-before-measurement` and can support no claim at all.
    """


class HeavyMeasurementLease:
    """Holds the machine-wide lease for the duration of one measured command."""

    def __init__(self, lease_class, lease_path, timeout_seconds, status_file=None):
        self.lease_class = lease_class
        self.status_file = status_file
        self.status = STATUS_QUEUED
        self.lease_path = lease_path
        self.timeout_seconds = timeout_seconds
        self.owner_path = lease_path + ".owner"
        self.boot_id = _boot_id()
        self.fd = None
        self.acquired = False
        self.timed_out = False
        self.requested_at = None
        self.acquired_at = None
        self.released_at = None
        self.stale_owner = None

    # -- status -------------------------------------------------------------

    def set_status(self, status):
        """Advance the status and write it out immediately.

        Written eagerly, not at the end: a run killed mid-wait leaves a file
        saying `lease-waiting`, and a run killed mid-census leaves one saying
        `measuring`. The status a process never got to update is itself the
        testimony about how it died.
        """
        self.status = status
        _log(f"status={status}")
        if not self.status_file:
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.status_file)) or ".",
                        exist_ok=True)
            with open(self.status_file, "w", encoding="utf-8") as handle:
                handle.write(status + "\n")
        except OSError as exc:
            _log(f"WARNING could not write status file: {exc}")

    # -- acquisition --------------------------------------------------------

    def _require_usable_directory(self):
        """The lease directory must exist and be writable, or REFUSE by name.

        A bare `PermissionError` from `os.makedirs` states an errno and invites
        `--lease /var/tmp/...` as the fix -- the one workaround that silently
        destroys the invariant, because /var/tmp is per-container here. So this
        names the correct path in the refusal itself.
        """
        directory = os.path.dirname(self.lease_path) or "."
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            raise LeaseDirectoryUnusable(
                f"cannot create the lease directory {directory}: {exc}. "
                f"The lease must live on the ONE host-shared directory every "
                f"runner container bind-mounts, which is `~/.cache/sugar/"
                f"binaries` from whichever side you are standing on: "
                f"/home/runner/... inside a runner, the owning user's home on "
                f"the host. Point SUGAR_HEAVY_LEASE_PATH (or --lease) at that "
                f"directory. Do NOT use /var/tmp: it is per-container on "
                f"battleaxe, and a lease there reports `acquired` while a "
                f"second census runs beside you."
            ) from exc
        if not os.access(directory, os.W_OK):
            raise LeaseDirectoryUnusable(
                f"the lease directory {directory} exists but is not writable by "
                f"uid {os.getuid()}. A lease you cannot take is not a lease. "
                f"Point SUGAR_HEAVY_LEASE_PATH (or --lease) at a host-shared "
                f"directory you own -- never /var/tmp, which is per-container "
                f"here and serializes nothing."
            )

    def acquire(self, interrupted=None):
        self._require_usable_directory()
        self.requested_at = time.time()
        self.set_status(STATUS_LEASE_WAITING)
        _log(
            f"requesting class={self.lease_class} lease={self.lease_path} "
            f"run={os.environ.get('GITHUB_RUN_ID', 'local')} "
            f"commit={os.environ.get('GITHUB_SHA', 'unknown')}"
        )
        # O_CREAT, never O_TRUNC: truncating the lease file is harmless to the
        # lock but would race with a holder's own descriptor for no gain.
        self.fd = os.open(self.lease_path, os.O_RDWR | os.O_CREAT, 0o666)
        # INHERITABLE ON PURPOSE. flock is held by the open file DESCRIPTION,
        # so a child that inherits this descriptor holds the same lease, and
        # the kernel frees it only when the last holder closes. That closes the
        # orphan hole: SIGKILL the wrapper and the measured census keeps
        # running -- with the fd non-inheritable it would keep running with the
        # lease already released, and the next heavy job would start on top of
        # it. This is the difference between a lease and a suggestion.
        os.set_inheritable(self.fd, True)

        self._require_machine_wide()

        deadline = self.requested_at + self.timeout_seconds
        announced = False
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
            if not announced:
                announced = True
                _log(
                    f"waiting for the lease; current owner testimony:\n"
                    f"{self._read_owner()}"
                )
            if interrupted is not None and interrupted():
                # Told to stop while still in the queue. Never measured.
                self.released_at = time.time()
                self.set_status(STATUS_CANCELLED_BEFORE)
                raise LeaseCancelled(
                    "stop signal received while waiting for the lease; "
                    "no measurement was taken"
                )
            if time.time() >= deadline:
                self.timed_out = True
                self.stale_owner = self._read_owner()
                self.released_at = time.time()
                self.set_status(STATUS_CANCELLED_BEFORE)
                raise LeaseTimeout(
                    f"TIMEOUT after {self.timeout_seconds}s waiting for "
                    f"{self.lease_path}"
                )
            time.sleep(min(POLL_SECONDS, max(0.0, deadline - time.time())))

        self.acquired = True
        self.acquired_at = time.time()
        self._write_owner()
        _log(
            f"acquired class={self.lease_class} "
            f"run={os.environ.get('GITHUB_RUN_ID', 'local')} "
            f"commit={os.environ.get('GITHUB_SHA', 'unknown')} "
            f"waited={round(self.acquired_at - self.requested_at, 3)}s"
        )

    def _require_machine_wide(self):
        """Inside a container, the lease MUST be on a bind mount from the host.

        The discriminator is cheap and local: if the lease file sits on the same
        device as ``/``, it is on the container's own root filesystem and no
        other container can see it. A bind mount from the host always has a
        different device.

        Only enforced when we can tell we are containerized, because on a plain
        host ``/var/tmp`` sharing a device with ``/`` is normal and correct --
        there, one filesystem really is one machine.
        """
        if not os.path.exists("/.dockerenv"):
            return
        try:
            lease_dev = os.stat(self.lease_path).st_dev
            root_dev = os.stat("/").st_dev
        except OSError as exc:
            _log(f"WARNING could not compare lease device with root device: {exc}")
            return
        if lease_dev == root_dev:
            raise LeaseNotMachineWide(
                f"{self.lease_path} is on this container's own root filesystem "
                f"(device {lease_dev}), so no other runner container can see it. "
                f"A lease nobody else can take is not a lease -- it would report "
                f"`acquired` while a second census ran beside this one. Point "
                f"SUGAR_HEAVY_LEASE_PATH at a directory bind-mounted from the "
                f"host (on battleaxe: /home/runner/.cache/sugar/binaries)."
            )

    def release(self):
        """Drop the lock and the sidecar. Idempotent; safe from a handler."""
        if self.released_at is None:
            self.released_at = time.time()
        if self.acquired:
            try:
                os.unlink(self.owner_path)
            except OSError:
                pass
        if self.fd is not None:
            try:
                # Explicit LOCK_UN before close: close() already releases, but
                # the explicit unlock keeps the release observable in strace
                # and does not depend on refcount subtleties around forks.
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        _log(
            f"released class={self.lease_class} "
            f"run={os.environ.get('GITHUB_RUN_ID', 'local')}"
        )

    # -- owner sidecar (diagnostics only; never authority) -------------------

    def _write_owner(self):
        lines = [
            f"class={self.lease_class}",
            f"pid={os.getpid()}",
            f"bootId={self.boot_id}",
            f"acquiredAtUnix={self.acquired_at!r}",
            f"githubRunId={os.environ.get('GITHUB_RUN_ID', 'local')}",
            f"githubRunAttempt={os.environ.get('GITHUB_RUN_ATTEMPT', '')}",
            f"githubWorkflow={os.environ.get('GITHUB_WORKFLOW', '')}",
            f"githubJob={os.environ.get('GITHUB_JOB', '')}",
            f"measuredCommit={os.environ.get('GITHUB_SHA', 'unknown')}",
        ]
        try:
            with open(self.owner_path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
        except OSError as exc:
            _log(f"WARNING could not write owner sidecar: {exc}")

    def _read_owner(self):
        """Stale-owner diagnostics. Loud -- and still never a licence to run."""
        try:
            with open(self.owner_path, encoding="utf-8") as handle:
                text = handle.read().strip()
        except OSError as exc:
            return (
                f"no readable owner sidecar at {self.owner_path} ({exc}). Either the "
                f"holder died before writing it, or -- the case worth checking -- "
                f"the lease path is not shared with the holder's container, in "
                f"which case the serialization is not happening at all."
            )
        pid_alive = None
        for line in text.splitlines():
            if line.startswith("pid="):
                try:
                    os.kill(int(line[4:]), 0)
                    pid_alive = True
                except (ValueError, ProcessLookupError):
                    pid_alive = False
                except PermissionError:
                    pid_alive = True
                except OSError:
                    pid_alive = None
        age = None
        try:
            age = round(time.time() - os.stat(self.owner_path).st_mtime, 3)
        except OSError:
            pass
        return (
            f"{text}\nownerSidecarAgeSeconds={age}\nownerPidVisibleAndAlive={pid_alive} "
            f"(a False here means the holder is gone from THIS namespace, which "
            f"across containers proves nothing -- the lock, not the pid, is the "
            f"authority)"
        )

    # -- receipt ------------------------------------------------------------

    def record_environment(self, command, command_exit):
        """The ``LEASE_*`` inputs to tools/heavy_measurement_lease_record.py."""
        return {
            "LEASE_CLASS": self.lease_class,
            "LEASE_PATH": self.lease_path,
            "LEASE_BOOT_ID": self.boot_id,
            "LEASE_TIMEOUT_SECONDS": str(int(self.timeout_seconds)),
            "LEASE_REQUESTED_AT": repr(self.requested_at) if self.requested_at else "",
            "LEASE_ACQUIRED_AT": repr(self.acquired_at) if self.acquired_at else "",
            "LEASE_RELEASED_AT": repr(self.released_at) if self.released_at else "",
            "LEASE_ACQUIRED": "true" if self.acquired else "false",
            "LEASE_TIMED_OUT": "true" if self.timed_out else "false",
            "LEASE_COMMAND": " ".join(command),
            "LEASE_COMMAND_EXIT": "" if command_exit is None else str(command_exit),
            "LEASE_HOLDER_PID": str(os.getpid()),
            "LEASE_STALE_OWNER": self.stale_owner or "",
            "LEASE_STATUS": self.status,
            "LEASE_ZERO_CLAIM_STATUS": ZERO_CLAIM_STATUS,
        }


def write_receipt(lease, command, command_exit, record_path, embed_into):
    """Write the receipt on EVERY exit path. A measurement with no receipt is
    a timing claim with no provenance, which the gate refuses anyway."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    recorder = os.path.join(repo_root, "tools", "heavy_measurement_lease_record.py")
    argv = [sys.executable, recorder, "--output", record_path]
    for path in embed_into:
        argv += ["--embed-into", path]
    env = dict(os.environ)
    env.update(lease.record_environment(command, command_exit))
    try:
        subprocess.run(argv, env=env, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        _log(f"WARNING failed to write receipt {record_path}: {exc}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Serialize one heavy measurement behind the machine-wide lease."
    )
    parser.add_argument("--class", dest="lease_class", required=True,
                        help="heavy class name, recorded in the receipt")
    parser.add_argument("--record", required=True,
                        help="where to write the lease receipt (not optional)")
    parser.add_argument("--embed-into", action="append", default=[],
                        help="artifact JSON to splice the receipt into as leaseRecord")
    parser.add_argument("--lease", default=DEFAULT_LEASE_PATH,
                        help=f"lease file (default {DEFAULT_LEASE_PATH})")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS,
                        help="seconds to wait before REFUSING (never proceeding)")
    parser.add_argument("--status-file", default=None,
                        help="path kept current with the measurement status, so a "
                             "killed run still says which phase it died in")
    parser.add_argument("--zero-findings-exit", type=int, default=0,
                        help="command exit status that means 'ran, found nothing'. "
                             "Any other status is completed/findings; only "
                             "completed/zero-findings may support a zero claim.")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("heavy-measurement-lease: no command given after --", file=sys.stderr)
        return EX_USAGE

    os.makedirs(os.path.dirname(os.path.abspath(args.record)) or ".", exist_ok=True)

    lease = HeavyMeasurementLease(args.lease_class, args.lease, args.timeout,
                                  status_file=args.status_file)

    command_exit = None
    state = {"child": None, "pending": None}

    def _forward(signum, _frame):
        # The child is in our process group, so an interactive ^C already
        # reached it; this covers a signal delivered to us alone. Then fall
        # through to the finally: below, which releases and writes the receipt.
        #
        # `pending` closes a race with teeth: a SIGTERM landing between the
        # acquisition and the spawn used to be SWALLOWED, leaving a wrapper
        # holding the lease and running a heavy census that the signal was
        # sent to stop. Remembered here, delivered as soon as there is a child.
        state["pending"] = signum
        child = state["child"]
        if child is not None and child.poll() is None:
            try:
                child.send_signal(signum)
            except OSError:
                pass

    previous = {}
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        try:
            previous[signum] = signal.signal(signum, _forward)
        except (ValueError, OSError):  # pragma: no cover - non-main thread
            pass

    # Handlers are installed BEFORE the acquire, on purpose. A GitHub
    # cancellation arriving while this job sits in the lease queue must be
    # recorded as `cancelled-before-measurement` -- that is the eviction case
    # this whole change exists to make visible, and it happens precisely during
    # the wait.
    try:
        lease.acquire(interrupted=lambda: state["pending"] is not None)
    except (
        LeaseTimeout,
        LeaseCancelled,
        LeaseNotMachineWide,
        LeaseDirectoryUnusable,
    ) as exc:
        _log(str(exc))
        if isinstance(exc, LeaseDirectoryUnusable):
            _log("REFUSING to measure without a lease that serializes.")
            lease.set_status(STATUS_CANCELLED_BEFORE)
            lease.released_at = time.time()
            lease.stale_owner = str(exc)
        if isinstance(exc, LeaseNotMachineWide):
            _log("REFUSING to measure behind a lease that serializes nothing.")
            lease.set_status(STATUS_CANCELLED_BEFORE)
            lease.released_at = time.time()
            lease.stale_owner = str(exc)
        if isinstance(exc, LeaseTimeout):
            _log("current owner testimony:\n" + (lease.stale_owner or "(none)"))
            _log(f"REFUSING to run {command!r} concurrently.")
            _log("a timing number measured beside another census is not a slow "
                 "measurement, it is not a measurement.")
        _log(f"status={lease.status}: this run supports NO claim. Not zero. None.")
        lease.release()
        write_receipt(lease, command, None, args.record, args.embed_into)
        return EX_TEMPFAIL

    try:
        lease.set_status(STATUS_MEASURING)
        # pass_fds keeps the lease descriptor open across the fork/exec, so the
        # measurement itself is a lease holder for as long as it lives.
        child = subprocess.Popen(command, pass_fds=(lease.fd,))
        state["child"] = child
        if state["pending"] is not None and child.poll() is None:
            # A stop signal arrived while we were still spawning. Honour it now
            # rather than measuring for three hours after being told to stop.
            child.send_signal(state["pending"])
        command_exit = child.wait()
    except KeyboardInterrupt:
        command_exit = 130
    except OSError as exc:
        _log(f"could not execute {command!r}: {exc}")
        command_exit = EX_USAGE
    finally:
        for signum, handler in previous.items():
            try:
                signal.signal(signum, handler)
            except (ValueError, OSError):  # pragma: no cover
                pass
        # The verdict on what this run may be used to claim.
        if state["pending"] is not None:
            # Stopped mid-census. Partial numbers are not small numbers.
            lease.set_status(STATUS_INTERRUPTED_DURING)
        elif command_exit == args.zero_findings_exit:
            lease.set_status(STATUS_COMPLETED_ZERO_FINDINGS)
        else:
            lease.set_status(STATUS_COMPLETED_FINDINGS)
        lease.release()
        write_receipt(lease, command, command_exit, args.record, args.embed_into)

    return command_exit if command_exit is not None else 1


if __name__ == "__main__":
    sys.exit(main())
