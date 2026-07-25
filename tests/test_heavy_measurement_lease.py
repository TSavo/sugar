"""A leaked lease is worse than no lease. These are the release-path teeth.

The machine-wide lease (``tools/heavy_measurement_lease.py``) is the ONE thing
standing between two heavy censuses and a pair of uninterpretable timing
numbers. Two failure modes matter and both are exercised here on both faces:

    LEAKED  -- the lease is held after the measurement is over, and every
               subsequent heavy job on the box deadlocks. Tested on success,
               on non-zero exit, on SIGTERM, and on SIGKILL (the one no
               handler can catch, where only the kernel's fd-close saves us).

    ABSENT  -- the lease was never taken and two measurements ran side by side
               anyway. Tested by holding the lock and watching the wrapper
               REFUSE rather than proceed, and by the gate rejecting the
               receipt that refusal produces.

Bounded by construction: every case is sub-second and touches a temporary
lease file, never the real one.
"""

from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "tools" / "heavy_measurement_lease.py"
GATE = ROOT / "tools" / "heavy_measurement_lease_gate.py"


def run_wrapper(lease, record, command, timeout=5, extra=(), env=None, wait=True):
    argv = [
        sys.executable, str(WRAPPER),
        "--class", "test-class",
        "--lease", str(lease),
        "--record", str(record),
        "--timeout", str(timeout),
        *extra,
        "--", *command,
    ]
    merged = dict(os.environ)
    merged.setdefault("GITHUB_RUN_ID", "424242")
    merged.setdefault("GITHUB_SHA", "421ef4157000000000000000000000000000dead")
    merged.update(env or {})
    if not wait:
        return subprocess.Popen(argv, env=merged, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
    return subprocess.run(argv, env=merged, capture_output=True, text=True, timeout=60)


def lease_is_free(lease_path):
    """True iff nobody holds the lease -- i.e. it was released."""
    fd = os.open(str(lease_path), os.O_RDWR | os.O_CREAT, 0o666)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


@pytest.fixture()
def lease(tmp_path):
    return tmp_path / "heavy.lease"


@pytest.fixture()
def record(tmp_path):
    return tmp_path / "lease-record.json"


# -- the measured section runs, and the receipt describes it ----------------


def test_success_runs_command_writes_receipt_and_releases(lease, record):
    result = run_wrapper(lease, record, [sys.executable, "-c", "print('measured')"])
    assert result.returncode == 0
    assert "measured" in result.stdout

    payload = json.loads(record.read_text())
    assert payload["acquired"] is True
    assert payload["timedOut"] is False
    assert payload["leaseClass"] == "test-class"
    assert payload["measuredCommit"].startswith("421ef4157")
    assert payload["owner"]["githubRunId"] == "424242"
    assert payload["commandExitStatus"] == 0
    # request -> acquisition -> release, all present and ordered.
    assert payload["requestedAtUnix"] <= payload["acquiredAtUnix"]
    assert payload["acquiredAtUnix"] <= payload["releasedAtUnix"]
    assert payload["waitSeconds"] >= 0
    assert payload["heldSeconds"] >= 0

    assert lease_is_free(lease), "lease leaked after a SUCCESSFUL measurement"
    assert not Path(str(lease) + ".owner").exists()


def test_failure_still_releases_and_records_the_exit_status(lease, record):
    result = run_wrapper(lease, record, [sys.executable, "-c", "raise SystemExit(3)"])
    assert result.returncode == 3
    payload = json.loads(record.read_text())
    assert payload["acquired"] is True
    assert payload["commandExitStatus"] == 3
    assert lease_is_free(lease), "lease leaked after a FAILED measurement"


def test_signal_releases_the_lease(lease, record):
    proc = run_wrapper(lease, record, [sys.executable, "-c", "import time; time.sleep(30)"],
                       wait=False)
    _wait_until(lambda: not lease_is_free(lease), "wrapper never took the lease")
    proc.send_signal(signal.SIGTERM)
    proc.communicate(timeout=30)
    assert lease_is_free(lease), "lease leaked after SIGTERM"
    payload = json.loads(record.read_text())
    assert payload["acquired"] is True
    assert payload["releasedAtUnix"] is not None


def test_sigkill_leaves_the_lease_with_the_orphan_then_frees_it(lease, record):
    """The case no handler can catch, and the orphan hole underneath it.

    SIGKILL the wrapper and the measured census keeps running. The lease must
    stay HELD for as long as that orphan lives -- otherwise the next heavy job
    starts on top of a census still burning the box, which is exactly the
    overlap the lease exists to forbid. Then, when the orphan exits, the kernel
    frees the lock with no handler of ours ever running: no leak either.
    """
    proc = run_wrapper(lease, record, [sys.executable, "-c", "import time; time.sleep(2)"],
                       wait=False)
    _wait_until(lambda: not lease_is_free(lease), "wrapper never took the lease")
    proc.kill()
    proc.wait(timeout=30)
    assert not lease_is_free(lease), (
        "lease was released while the orphaned measurement was still running"
    )
    _wait_until(lambda: lease_is_free(lease), "lease leaked after the orphan exited")


# -- the refusal face -------------------------------------------------------


def test_contended_lease_refuses_and_does_not_run_the_command(lease, record, tmp_path):
    """Only one enters the measured section. The other REFUSES -- it does not
    wait forever, and it does not 'recover' by running alongside."""
    canary = tmp_path / "canary"
    fd = os.open(str(lease), os.O_RDWR | os.O_CREAT, 0o666)
    fcntl.flock(fd, fcntl.LOCK_EX)
    Path(str(lease) + ".owner").write_text(
        "class=other\npid=1\nbootId=test\ngithubRunId=999\n"
    )
    try:
        result = run_wrapper(
            lease, record,
            [sys.executable, "-c", f"open({str(canary)!r}, 'w').write('ran')"],
            timeout=1,
        )
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    assert result.returncode == 75, result.stderr
    assert not canary.exists(), "the measured command RAN while another held the lease"
    assert "REFUSING" in result.stderr
    payload = json.loads(record.read_text())
    assert payload["acquired"] is False
    assert payload["timedOut"] is True
    assert payload["commandExitStatus"] is None
    assert "githubRunId=999" in payload["staleOwnerDiagnostics"]


def test_second_wrapper_waits_then_proceeds_after_release(lease, record, tmp_path):
    """Serialized, not dropped: the waiter's own interval starts after the
    holder's ends, which is the property the whole design exists to buy."""
    first_record = tmp_path / "first.json"
    holder = run_wrapper(
        lease, first_record,
        [sys.executable, "-c", "import time; time.sleep(1.5)"],
        wait=False,
    )
    _wait_until(lambda: not lease_is_free(lease), "holder never took the lease")
    waiter = run_wrapper(lease, record, [sys.executable, "-c", "print('second')"],
                         timeout=30, wait=False)
    holder.communicate(timeout=60)
    out, err = waiter.communicate(timeout=60)
    assert waiter.returncode == 0, err
    assert "second" in out

    first = json.loads(first_record.read_text())
    second = json.loads(record.read_text())
    assert second["acquired"] is True
    assert second["waitSeconds"] > 0, "the waiter did not actually wait"
    assert second["acquiredAtUnix"] >= first["releasedAtUnix"], (
        "the two measured sections OVERLAPPED"
    )


# -- the receipt joins the measurement's own artifact -----------------------


def test_receipt_embeds_into_the_measurement_artifact(lease, record, tmp_path):
    artifact = tmp_path / "suite-report.json"
    program = (
        f"import json; json.dump({{'schemaVersion': 1, 'counts': {{'collected': 7}}}}, "
        f"open({str(artifact)!r}, 'w'))"
    )
    result = run_wrapper(lease, record, [sys.executable, "-c", program],
                         extra=("--embed-into", str(artifact)))
    assert result.returncode == 0
    payload = json.loads(artifact.read_text())
    assert payload["counts"]["collected"] == 7, "embedding clobbered the measurement"
    assert payload["leaseRecord"]["acquired"] is True
    assert payload["leaseRecord"]["measuredCommit"].startswith("421ef4157")


# -- a lease nobody else can see is not a lease -------------------------------


def _lease_module():
    from importlib import util
    spec = util.spec_from_file_location("heavy_measurement_lease", WRAPPER)
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_container_private_lease_is_refused(monkeypatch, tmp_path):
    """The defect the first live run exposed.

    Two heavy jobs took /var/tmp leases on the same kernel, waited 0.0007s
    each, and OVERLAPPED -- because battleaxe runners are containers and
    /var/tmp is per-container. A lock nobody else can see reports `acquired`
    while a second census runs beside it, which is worse than no lock at all.
    """
    module = _lease_module()
    lease_path = tmp_path / "private.lease"
    lease_path.touch()
    lease = module.HeavyMeasurementLease("t", str(lease_path), 1)

    monkeypatch.setattr(module.os.path, "exists", lambda p: p == "/.dockerenv")
    same = os.stat(str(lease_path))
    monkeypatch.setattr(module.os, "stat", lambda p: same)
    with pytest.raises(module.LeaseNotMachineWide):
        lease._require_machine_wide()


def test_bind_mounted_lease_is_accepted(monkeypatch, tmp_path):
    """The other face: a lease on a host bind mount has a different device
    from `/`, and must pass -- or the check is a wall nobody can get through."""
    module = _lease_module()
    lease_path = tmp_path / "shared.lease"
    lease_path.touch()
    lease = module.HeavyMeasurementLease("t", str(lease_path), 1)

    monkeypatch.setattr(module.os.path, "exists", lambda p: p == "/.dockerenv")

    class _Stat:
        def __init__(self, dev):
            self.st_dev = dev

    monkeypatch.setattr(module.os, "stat",
                        lambda p: _Stat(1 if p == "/" else 2))
    lease._require_machine_wide()  # must not raise


def test_outside_a_container_one_filesystem_really_is_one_machine(monkeypatch, tmp_path):
    """On a plain host, /var/tmp sharing a device with / is normal. Enforcing
    the container rule there would refuse every honest local measurement."""
    module = _lease_module()
    lease_path = tmp_path / "host.lease"
    lease_path.touch()
    lease = module.HeavyMeasurementLease("t", str(lease_path), 1)
    monkeypatch.setattr(module.os.path, "exists", lambda p: False)
    lease._require_machine_wide()  # must not raise


# -- the status vocabulary: silence is never a clean floor ------------------
#
#   queued -> lease-waiting -> measuring -> completed/{findings,zero-findings}
#   queued / lease-waiting -> cancelled-before-measurement
#   measuring              -> interrupted-during-measurement
#
# Only completed/zero-findings may support a zero claim. Every other terminal
# status is "no measurement", and these tests run BOTH faces of that: the one
# status that licenses a zero claim, and each status that must not.


def test_zero_findings_is_the_only_status_that_licenses_a_zero_claim(lease, record):
    run_wrapper(lease, record, [sys.executable, "-c", "pass"])
    payload = json.loads(record.read_text())
    assert payload["measurementStatus"] == "completed/zero-findings"
    assert payload["supportsZeroClaim"] is True
    assert _gate("--record", str(record), "--require-zero-claim").returncode == 0


def test_findings_do_not_license_a_zero_claim(lease, record):
    run_wrapper(lease, record, [sys.executable, "-c", "raise SystemExit(1)"])
    payload = json.loads(record.read_text())
    assert payload["measurementStatus"] == "completed/findings"
    assert payload["supportsZeroClaim"] is False
    result = _gate("--record", str(record), "--require-zero-claim")
    assert result.returncode == 1
    assert "does NOT support a zero claim" in result.stdout


def test_cancelled_before_measurement_is_distinct_from_zero_findings(lease, record):
    """THE distinction the five suite cancellations and three floor
    cancellations needed somebody to draw."""
    fd = os.open(str(lease), os.O_RDWR | os.O_CREAT, 0o666)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        run_wrapper(lease, record, [sys.executable, "-c", "pass"], timeout=1)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    payload = json.loads(record.read_text())
    assert payload["measurementStatus"] == "cancelled-before-measurement"
    assert payload["supportsZeroClaim"] is False
    assert _gate("--record", str(record), "--require-zero-claim").returncode == 1


def test_signal_while_waiting_records_cancelled_before_measurement(lease, record, tmp_path):
    """A GitHub cancellation lands while the job sits in the lease queue. That
    run measured NOTHING, and its artifact has to say so -- not go silent."""
    canary = tmp_path / "canary"
    fd = os.open(str(lease), os.O_RDWR | os.O_CREAT, 0o666)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        proc = run_wrapper(
            lease, record,
            [sys.executable, "-c", f"open({str(canary)!r}, 'w').write('ran')"],
            timeout=120, wait=False,
        )
        # Let it settle into the wait, then cancel it there.
        time.sleep(1.0)
        proc.send_signal(signal.SIGTERM)
        proc.communicate(timeout=30)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    assert proc.returncode == 75
    assert not canary.exists(), "the command ran despite never holding the lease"
    payload = json.loads(record.read_text())
    assert payload["measurementStatus"] == "cancelled-before-measurement"
    assert payload["acquired"] is False
    assert payload["supportsZeroClaim"] is False


def test_interrupted_during_measurement_is_its_own_status(lease, record):
    """Stopped mid-census. Partial numbers are not small numbers."""
    proc = run_wrapper(lease, record, [sys.executable, "-c", "import time; time.sleep(30)"],
                       wait=False)
    _wait_until(lambda: not lease_is_free(lease), "wrapper never took the lease")
    time.sleep(0.3)
    proc.send_signal(signal.SIGTERM)
    proc.communicate(timeout=30)
    payload = json.loads(record.read_text())
    assert payload["measurementStatus"] == "interrupted-during-measurement"
    assert payload["acquired"] is True, "it did measure, briefly"
    assert payload["supportsZeroClaim"] is False


def test_status_file_tracks_the_live_phase(lease, record, tmp_path):
    """The phase a killed process never got to update is itself testimony."""
    status = tmp_path / "status"
    proc = run_wrapper(lease, record, [sys.executable, "-c", "import time; time.sleep(30)"],
                       extra=("--status-file", str(status)), wait=False)
    _wait_until(lambda: status.exists() and status.read_text().strip() == "measuring",
                "status file never reached `measuring`")
    proc.kill()
    proc.wait(timeout=30)
    # SIGKILL: no handler ran, so the file still says what it was doing.
    assert status.read_text().strip() == "measuring"


# -- attendance: an absent instrument is not a clean floor ------------------


def test_attendance_counts_a_missing_receipt_as_unmeasured(lease, record, tmp_path):
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    run_wrapper(lease, receipts / "python-package-suite.json", [sys.executable, "-c", "pass"])
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "heavy_measurement_attendance.py"),
         "--commit", "421ef4157", "--receipts-dir", str(receipts)],
        capture_output=True, text=True, timeout=60,
    )
    # A real receipt is present, but it belongs to no roster class -- so NOT
    # ONE roster instrument spoke, and the roll call must say five, not zero.
    # An artifact directory that merely contains files is not attendance.
    assert result.returncode == 1
    assert "R_attendance = 5" in result.stdout
    assert "NOT a clean floor" in result.stdout
    assert "python-sole-construction-floors" in result.stdout


def test_attendance_is_green_when_every_instrument_reported(lease, record, tmp_path):
    """The other face: a full roll call must be able to pass, or the check is
    a red light nobody can turn green."""
    from importlib import util
    spec = util.spec_from_file_location(
        "attendance", ROOT / "tools" / "heavy_measurement_attendance.py")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)

    receipts = tmp_path / "receipts"
    receipts.mkdir()
    for lease_class in module.HEAVY_ROSTER:
        (receipts / f"{lease_class}.json").write_text(json.dumps({
            "schemaVersion": 1, "leaseClass": lease_class, "acquired": True,
            "measurementStatus": "completed/zero-findings", "supportsZeroClaim": True,
        }))
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "heavy_measurement_attendance.py"),
         "--commit", "421ef4157", "--receipts-dir", str(receipts)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout
    assert "R_attendance = 0" in result.stdout


# -- the gate: no timing claim without an acquired lease --------------------


def _gate(*argv):
    return subprocess.run([sys.executable, str(GATE), *argv],
                          capture_output=True, text=True, timeout=60)


def test_gate_accepts_an_acquired_lease(lease, record):
    run_wrapper(lease, record, [sys.executable, "-c", "pass"])
    result = _gate("--record", str(record))
    assert result.returncode == 0, result.stdout
    assert "R_lease = 0" in result.stdout


def test_gate_refuses_a_lease_that_was_never_acquired(lease, record, tmp_path):
    fd = os.open(str(lease), os.O_RDWR | os.O_CREAT, 0o666)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        run_wrapper(lease, record, [sys.executable, "-c", "pass"], timeout=1)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    result = _gate("--record", str(record))
    assert result.returncode == 1
    assert "lease NOT acquired" in result.stdout


def test_gate_refuses_a_commit_mismatch(lease, record):
    run_wrapper(lease, record, [sys.executable, "-c", "pass"])
    assert _gate("--record", str(record), "--require-commit", "deadbeef").returncode == 1


def test_gate_refuses_a_missing_receipt(tmp_path):
    result = _gate("--record", str(tmp_path / "absent.json"))
    assert result.returncode == 1
    assert "unreadable lease receipt" in result.stdout


def test_gate_scope_check_catches_a_per_container_lease(tmp_path):
    """Same kernel, different inode: the lease file was never shared between
    runner containers, so the serialization never happened. This is the check
    that stops the mechanism from being theatre."""
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    base = {
        "schemaVersion": 1, "acquired": True, "measuredCommit": "abc",
        "acquiredAtUnix": 100.0, "releasedAtUnix": 200.0,
    }
    a.write_text(json.dumps(dict(base, leaseIdentity={"bootId": "K", "device": 1, "inode": 11})))
    b.write_text(json.dumps(dict(base, leaseIdentity={"bootId": "K", "device": 1, "inode": 22})))
    result = _gate("--scope-check", str(a), "--scope-check", str(b))
    assert result.returncode == 1
    assert "DIFFERENT inodes" in result.stdout


def test_gate_scope_check_catches_overlapping_intervals(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    identity = {"bootId": "K", "device": 1, "inode": 11}
    a.write_text(json.dumps({"schemaVersion": 1, "acquired": True, "leaseIdentity": identity,
                             "acquiredAtUnix": 100.0, "releasedAtUnix": 200.0}))
    b.write_text(json.dumps({"schemaVersion": 1, "acquired": True, "leaseIdentity": identity,
                             "acquiredAtUnix": 150.0, "releasedAtUnix": 250.0}))
    result = _gate("--scope-check", str(a), "--scope-check", str(b))
    assert result.returncode == 1
    assert "OVERLAP" in result.stdout


def test_gate_scope_check_accepts_disjoint_intervals_on_one_inode(tmp_path):
    """The other face: correctly serialized receipts must pass, or the check
    above is just a red light nobody can turn green."""
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    identity = {"bootId": "K", "device": 1, "inode": 11}
    a.write_text(json.dumps({"schemaVersion": 1, "acquired": True, "leaseIdentity": identity,
                             "acquiredAtUnix": 100.0, "releasedAtUnix": 200.0}))
    b.write_text(json.dumps({"schemaVersion": 1, "acquired": True, "leaseIdentity": identity,
                             "acquiredAtUnix": 200.5, "releasedAtUnix": 250.0}))
    assert _gate("--scope-check", str(a), "--scope-check", str(b)).returncode == 0


def _wait_until(predicate, message, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(message)
