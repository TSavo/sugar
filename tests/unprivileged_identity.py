"""Run a uid-sensitive law under an identity that the kernel actually checks.

``bpytest`` runs as root on battleaxe. Root bypasses DAC mode checks, so every
test guarding on ``os.getuid() == 0`` skipped there while passing locally --
and a skip is not a pass. The suite did not go red, it went *smaller*, which is
the same defect class as a collection error that shrinks the denominator:
nobody notices, because a skipped test reports green.

The honest fix is not a louder skip. It is to stop needing one: fork, drop to
an unprivileged identity, and run the law there, so the permission bits the
law is about are enforced by the kernel exactly as they are for an ordinary
caller. The law then executes under root and non-root alike.

When no unprivileged identity can be reached, this refuses BY NAME with
``UnprivilegedIdentityUnavailable``. It never degrades to a skip. An
environment that is supposed to run these laws and cannot must say so out
loud, as a failure.
"""

from __future__ import annotations

import os
import pickle
import stat
from pathlib import Path

# nobody(65534) is the conventional unprivileged identity on Linux and macOS
# alike. The candidates are tried in order and the first that resolves wins.
_CANDIDATE_USERS = ("nobody", "nfsnobody", "daemon")


class UnprivilegedIdentityUnavailable(RuntimeError):
    """No identity was available under which a uid-sensitive law could run.

    Raised, never skipped. A uid-sensitive law that cannot be executed is an
    unrun law, and an unrun law reported as green is the defect this module
    exists to close.
    """


def unprivileged_identity():
    """Return ``(uid, gid)`` of an identity with no special privileges.

    Returns ``None`` when the caller is already unprivileged: there is nothing
    to drop to, because the kernel already enforces mode bits against it.
    """
    if os.getuid() != 0:
        return None

    import pwd

    for name in _CANDIDATE_USERS:
        try:
            entry = pwd.getpwnam(name)
        except KeyError:
            continue
        if entry.pw_uid != 0:
            return (entry.pw_uid, entry.pw_gid)

    raise UnprivilegedIdentityUnavailable(
        "running as root and no unprivileged identity "
        f"({', '.join(_CANDIDATE_USERS)}) exists on this host, so a "
        "uid-sensitive law cannot be executed here. This is reported as a "
        "failure and never as a skip: root bypasses the DAC mode checks the "
        "law is about, so skipping would report an unrun law as green. "
        "replacement: provide an unprivileged account in the image that runs "
        "the suite (bpytest runs as root), or run the suite as a non-root uid."
    )


def reachable_by_unprivileged(path):
    """Open the ancestor chain of ``path`` so a dropped identity can reach it.

    ``tmp_path`` lives under ``/tmp/pytest-of-root/...`` at mode 700 when the
    suite runs as root. Traversal, not the law under test, would otherwise
    decide the outcome -- and a law that fails for the wrong reason is no
    better than one that never ran.
    """
    path = Path(path).resolve()
    for ancestor in [path, *path.parents]:
        try:
            mode = ancestor.stat().st_mode
        except OSError:
            continue
        if mode & stat.S_IXOTH and mode & stat.S_IROTH:
            # Already world-traversable; every ancestor above it is too.
            break
        try:
            ancestor.chmod(mode | stat.S_IROTH | stat.S_IXOTH)
        except OSError:
            continue
    return path


def writable_by_unprivileged(directory):
    """Let a dropped identity WRITE into ``directory``, not merely reach it.

    A law whose subject writes a receipt needs somewhere to write it. Without
    this the receipt is missing and the test fails on the wrong thing, which
    proves nothing about the law.
    """
    directory = reachable_by_unprivileged(directory)
    try:
        mode = directory.stat().st_mode
        directory.chmod(mode | stat.S_IRWXO)
    except OSError:
        pass
    return directory


def run_unprivileged(law, expected=()):
    """Run ``law()`` under an unprivileged identity and return its result.

    When the caller is already unprivileged the law runs inline. Otherwise it
    runs in a forked child that has irrevocably dropped to a non-root uid, so
    the kernel enforces mode bits against it.

    An exception raised inside the child is transported back and re-raised, so
    ``pytest.raises`` around this call behaves as it does for an ordinary
    caller. Exception *classes* do not always survive a fork boundary: a module
    loaded by file location (as the lease wrapper is, freshly per call) defines
    classes that are unpicklable and whose identity differs between parent and
    child. So the caller names the classes it expects in ``expected`` and they
    are matched by name and re-raised as the parent's own class. Anything
    unexpected is still raised, never swallowed.
    """
    identity = unprivileged_identity()
    if identity is None:
        return law()

    uid, gid = identity
    read_fd, write_fd = os.pipe()
    pid = os.fork()

    if pid == 0:  # child
        try:
            os.close(read_fd)
            os.setgroups([])
            os.setgid(gid)
            os.setuid(uid)
            if os.getuid() == 0 or os.geteuid() == 0:
                raise UnprivilegedIdentityUnavailable(
                    "privilege drop did not take effect; the law would have "
                    "run as root and proved nothing"
                )
            value = law()
            try:
                payload = pickle.dumps(("value", None, None, pickle.dumps(value)))
            except Exception:
                payload = pickle.dumps(("value", None, repr(value), None))
        except BaseException as error:  # transported to the parent, not swallowed
            try:
                blob = pickle.dumps(error)
            except Exception:
                blob = None
            payload = pickle.dumps(
                ("error", type(error).__name__, str(error), blob)
            )
        try:
            os.write(write_fd, payload)
        finally:
            os.close(write_fd)
            os._exit(0)

    # parent
    os.close(write_fd)
    chunks = []
    while True:
        chunk = os.read(read_fd, 65536)
        if not chunk:
            break
        chunks.append(chunk)
    os.close(read_fd)
    _, wait_status = os.waitpid(pid, 0)

    if not chunks:
        raise UnprivilegedIdentityUnavailable(
            f"the unprivileged child (uid {uid}) died without reporting a "
            f"result (wait status {wait_status}); the law did not execute"
        )

    kind, name, text, blob = pickle.loads(b"".join(chunks))

    if kind == "value":
        return pickle.loads(blob) if blob is not None else text

    if isinstance(expected, type):
        expected = (expected,)
    for candidate in expected:
        if candidate.__name__ == name:
            raise candidate(text)
    if blob is not None:
        raise pickle.loads(blob)
    raise RuntimeError(f"{name}: {text}")


def unprivileged_preexec():
    """A ``subprocess`` ``preexec_fn`` that drops to an unprivileged identity.

    Returns ``None`` when the caller is already unprivileged, which is exactly
    what ``subprocess`` expects for "do nothing extra".
    """
    identity = unprivileged_identity()
    if identity is None:
        return None

    uid, gid = identity

    def drop():
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)

    return drop
