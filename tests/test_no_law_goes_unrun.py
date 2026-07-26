"""A skipped law is an unrun law, and an unrun law reported as green is a lie.

``bpytest`` runs as root on battleaxe. Root bypasses the DAC mode checks that
uid-sensitive laws are about, so a test guarding on ``os.getuid() == 0`` and
skipping is unfalsifiable there: it can never fail, no matter how broken the
code under it becomes. Two permission laws in ``test_heavy_measurement_lease``
skipped on the box while passing locally, and nobody noticed, because the suite
did not go red -- it went *smaller*.

That is the same defect class as a collection error that shrinks the
denominator. The colour is not the instrument; the executed count is.

These are the teeth against that class:

    1. No uid-guarded test may degrade to a skip. Structural, over the whole
       corpus, so the class cannot regrow one test at a time.

    2. The privilege-drop mechanism must actually deny something HERE. A
       mechanism that quietly no-ops under root would restore the exact
       unfalsifiability it was written to remove -- so it is tested by
       provoking a real EACCES, not by inspection.

    5. A package's SIBLINGS must be derived and proven too. A hand-written
       sibling list is a declaration that drifts with nothing to notice:
       ``siblings=()`` sat beside two real sibling imports while the
       structural guard stayed green and 30 test modules resolved a stale
       worktree. Derived, or it rots.

    4. Every package under test must PIN this checkout, and prove it. A
       package resolving to an editable install elsewhere does not fail -- it
       passes, reports coverage, and describes a tree nobody is editing. That
       is worse than the other two: they omit work, this fabricates
       attribution. So the assertion is a POSITIVE (this module resolved
       under this root), because absence of an error proves nothing when the
       defect IS success about the wrong thing.

    3. No law may be left unrun by an unnamed skip, anywhere in the Python
       corpus. This is the same predicate one level more general, and it
       covers the worse case: a missing corpus is a ROUTINE condition, so
       ``pytest.skip(f"{package}: not installed")`` means those laws are unrun
       on every machine lacking the package, permanently, with nobody ever
       seeing a red. Absence of a DECLARED corpus must fail; a genuinely
       conditional law must skip under a NAMED, COUNTED category.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from unprivileged_identity import (
    UnprivilegedIdentityUnavailable,
    reachable_by_unprivileged,
    run_unprivileged,
    unprivileged_identity,
)

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
SELF = Path(__file__).name

# Every Python test tree in the repo, not just this one. The uid pair lived
# here; the far larger presence-guard population lives under the per-package
# trees, and a guard that cannot see them is a guard in name only.
CORPUS_ROOTS = (TESTS, ROOT / "implementations" / "python")

# The single sanctioned home for raw skip machinery. Every legitimate skip
# routes through its named categories, so a raw pytest.skip anywhere else is a
# law somebody left unrun without deciding to.
SANCTIONED_SKIP_MODULE = "declared_corpus.py"

# A package that ships sources AND tests must pin those sources to this
# checkout. sugar-lift-python-source lacked the conftest its sibling had and
# silently measured /Users/tsavo/provekit-wt/fresh-main-20260701 instead.
PACKAGES_DIR = ROOT / "implementations" / "python"
PIN_CALL = "pin_checkout("


def _uid_guarded_skips():
    """Every test function that both consults the uid and calls ``pytest.skip``."""
    offenders = []
    for path in _corpus_files():
        if path.name == SELF:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            consults_uid = False
            skips = False
            for inner in ast.walk(node):
                if isinstance(inner, ast.Attribute) and inner.attr in {
                    "getuid",
                    "geteuid",
                }:
                    consults_uid = True
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "skip"
                ):
                    skips = True
            if consults_uid and skips:
                offenders.append(f"{_rel(path)}:{node.lineno}: {node.name}")
    return offenders


def test_no_uid_sensitive_law_degrades_to_a_skip():
    """A uid guard that skips makes the law unfalsifiable wherever it matters.

    The suite runs as root under ``bpytest``, which is precisely the identity
    such a guard excludes -- so the law would be skipped in the one environment
    that is supposed to run it. Run it under a dropped identity instead
    (``tests/unprivileged_identity.py``); never skip it.
    """
    offenders = _uid_guarded_skips()
    assert not offenders, (
        f"R={len(offenders)} uid-sensitive laws degrade to a skip and are "
        "therefore unfalsifiable under the root identity bpytest runs as:\n"
        + "\n".join(offenders)
        + "\nreplacement: run the law under a non-root identity with "
        "unprivileged_identity.run_unprivileged / unprivileged_preexec, or "
        "fail by name -- a skip reports an unrun law as green"
    )


def test_the_privilege_drop_actually_denies_something_here(tmp_path):
    """The positive control: without this, the mechanism could silently no-op.

    A privilege drop that failed to take effect would leave every law using it
    passing vacuously under root -- exactly the unfalsifiability being removed,
    now hidden one layer deeper. So provoke a real EACCES and require it.
    """
    reachable_by_unprivileged(tmp_path)
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    target = locked / "denied.txt"

    def write():
        target.write_text("x")
        return "wrote"

    with pytest.raises(PermissionError):
        run_unprivileged(write)

    assert not target.exists(), "the write must not have landed"
    locked.chmod(0o700)


def test_the_dropped_identity_is_not_root():
    """Whatever identity the law runs under, the kernel must be checking it."""
    assert run_unprivileged(os.getuid) != 0
    assert run_unprivileged(os.geteuid) != 0


def test_an_unavailable_identity_refuses_by_name_rather_than_skipping():
    """The refusal is named and is an error, never a silently smaller suite."""
    assert issubclass(UnprivilegedIdentityUnavailable, Exception)
    assert not issubclass(UnprivilegedIdentityUnavailable, pytest.skip.Exception), (
        "an unavailable identity must fail, never register as a skip"
    )

    identity = unprivileged_identity()
    if identity is not None:
        uid, _ = identity
        assert uid != 0, "a 'dropped' identity of uid 0 would prove nothing"


def _corpus_files():
    """Every Python test-tree file in the repo, deduplicated and ordered."""
    seen = {}
    for root in CORPUS_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if any(part in {".venv", "venv", "build", "__pycache__", "node_modules"}
                   for part in path.parts):
                continue
            if root is not TESTS and "tests" not in path.parts:
                continue
            seen[path.resolve()] = path
    return [seen[key] for key in sorted(seen)]


def _rel(path):
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _unnamed_skips():
    """Every raw skip outside the one module that owns skip machinery.

    A raw ``pytest.skip`` / ``skipif`` is an anonymous absence: the law simply
    stops running, and no bucket in the report says so. Legitimate conditional
    laws go through ``optional_law_skip`` / ``optional_law_skipif``, which
    stamp a named category; declared corpora that are missing raise
    ``DeclaredCorpusMissing`` and fail.
    """
    offenders = []
    for path in _corpus_files():
        if path.name in {SELF, SANCTIONED_SKIP_MODULE}:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            # pytest.skip(...) and pytest.mark.skipif(...); bare `skip`
            # attribute access (pytest.skip.Exception) is not a call.
            #
            # importorskip is the same defect wearing an import: it answers
            # "is the module present" when the suite is asking "did this law
            # run", and leaves no bucket saying it did not. It hid a 441-line
            # first-party pydantic lifter whose three laws never ran in CI for
            # the repo's whole history -- and once they were made visible, the
            # module turned out to have zero reverse-deps and was burned
            # (#6373). Making the unrun visible is what allowed it to be
            # judged; deleting it while it was invisible was never an option.
            if func.attr in {"skip", "skipif", "importorskip"}:
                offenders.append(f"{_rel(path)}:{node.lineno}: {func.attr}(...)")
    return offenders


def test_no_law_is_left_unrun_by_an_unnamed_skip():
    """A missing corpus is routine, so a skip on absence is permanent silence.

    ``pytest.skip(f"{package}: not installed at {path}")`` answers *"is it
    present"* when the suite is asking *"did this law run"* -- the same shape
    as ``dpkg-query`` answering "did apt install b3sum" when the build asked
    "is b3sum usable". numpy and pandas are PINNED in ``sugar-build.toml`` and
    declared by the ``[test]`` extra that calls itself the sole dependency
    authority; the stdlib vendors ship with CPython; the showcase targets are
    directories in this checkout. Every one of those absences is a broken
    environment, and the honest report is a failure.
    """
    offenders = _unnamed_skips()
    assert not offenders, (
        f"R={len(offenders)} laws can be left unrun by an unnamed skip:\n"
        + "\n".join(offenders)
        + "\nreplacement: if the corpus is DECLARED (pinned vendor, stdlib, "
        "in-repo path) its absence is a broken environment -- raise "
        "DeclaredCorpusMissing via require_declared_corpus. If the law is "
        "genuinely conditional, skip through optional_law_skip / "
        "optional_law_skipif / optional_law_import so the skip carries a "
        "named, counted category. "
        "An anonymous skip reports an unrun law as green on every machine "
        "that lacks the corpus."
    )


def test_the_sanctioned_skip_module_is_identical_in_every_package():
    """Two packages, no dependency edge between them, one contract.

    The helper is duplicated by necessity; drift between the copies would let
    one package sanction a category the other rejects, which is a hole in the
    guard rather than a cosmetic difference.
    """
    copies = sorted(
        path for path in _corpus_files() if path.name == SANCTIONED_SKIP_MODULE
    )
    assert len(copies) >= 2, f"expected the helper in each package, found {copies}"
    bodies = {path.read_text(encoding="utf-8") for path in copies}
    assert len(bodies) == 1, (
        "the sanctioned skip module has drifted between packages:\n"
        + "\n".join(_rel(path) for path in copies)
        + "\nreplacement: keep the copies byte-identical; a category "
        "sanctioned in one package and rejected in the other is a hole"
    )


def _packages_under_test():
    """Every package that ships both sources and tests of its own."""
    if not PACKAGES_DIR.is_dir():
        return []
    return [
        path
        for path in sorted(PACKAGES_DIR.iterdir())
        if (path / "src").is_dir() and (path / "tests").is_dir()
    ]


def test_every_package_pins_its_own_checkout():
    """An unpinned package measures whatever install the machine happens to have.

    This is the defect that fabricates attribution rather than omitting work:
    it does not fail, it succeeds about the wrong code. The tell was an
    asymmetry -- one package had a conftest pinning its src and its sibling did
    not -- so the guard is structural over every package, not a spot check.
    """
    packages = _packages_under_test()
    assert packages, "found no packages under test; the guard would be vacuous"

    offenders = []
    for package in packages:
        conftest = package / "tests" / "conftest.py"
        if not conftest.is_file():
            offenders.append(f"{_rel(package)}: no tests/conftest.py to pin src")
            continue
        if PIN_CALL not in conftest.read_text(encoding="utf-8"):
            offenders.append(
                f"{_rel(conftest)}: does not call {PIN_CALL}...) to pin this checkout"
            )

    assert not offenders, (
        f"R={len(offenders)} packages do not pin their sources to this "
        f"checkout (of {len(packages)} under test):\n"
        + "\n".join(offenders)
        + "\nreplacement: call checkout_resolution.pin_checkout(__file__) from "
        "the package's tests/conftest.py. An unpinned package resolves "
        "whatever editable install exists on the machine -- it passes, "
        "reports coverage, and describes a tree nobody is editing"
    )


def test_the_resolution_guard_can_actually_fail():
    """The positive control. Absence of an error proves nothing here.

    The defect is a SUCCESSFUL import of the wrong tree, so a guard that only
    caught ImportError would pass on every instance of it. This proves the
    guard rejects a module resolving outside the root, and accepts one inside.
    """
    from checkout_resolution import CheckoutResolutionEscaped, require_local_resolution

    # Positive: a module that genuinely lives under this root is accepted.
    resolved = require_local_resolution("unprivileged_identity", str(ROOT))
    assert resolved.startswith(str(ROOT))

    # The refusal must BE a failure. pytest.raises cannot establish this:
    # if the mechanism regressed to pytest.skip, the Skipped propagates
    # straight through the raises block and this control SKIPS -- green, and
    # proving nothing. Exactly the hole found in #6362's control, so the skip
    # is caught explicitly and converted.
    assert issubclass(CheckoutResolutionEscaped, AssertionError), (
        "the refusal must be an AssertionError so it lands as a failure"
    )
    assert not issubclass(CheckoutResolutionEscaped, pytest.skip.Exception), (
        "escaping the checkout must FAIL, never skip"
    )

    # Negative: a stdlib module lives outside the checkout and must be refused.
    try:
        require_local_resolution("json", str(ROOT))
    except pytest.skip.Exception as skipped:
        raise AssertionError(
            f"require_local_resolution degraded into a SKIP ({skipped!r}); a "
            "package measuring the wrong checkout would then report green"
        ) from None
    except CheckoutResolutionEscaped as refusal:
        message = str(refusal)
    else:
        raise AssertionError(
            "a module outside the checkout was ACCEPTED; the guard cannot "
            "catch the defect it exists for"
        )

    assert "resolved OUTSIDE this checkout" in message
    assert "fabricates" in message


def test_sibling_requirements_are_derived_not_declared():
    """A package that declares NO siblings must still have them derived.

    This is the exact case that hid the defect: `pin_checkout(__file__,
    siblings=())` satisfied the structural guard while two sibling packages
    resolved ambiently, one of them to another worktree entirely. If derivation
    ever stops seeing them, an empty declaration hides them again.
    """
    from checkout_resolution import derive_required_siblings

    packages_dir = ROOT / "implementations" / "python"
    package = packages_dir / "sugar-lift-py-tests"
    conftest = (package / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "siblings=()" in conftest, (
        "this control is pinned to the package that declares NO siblings; if "
        "that changed, point it at another empty-declaration package or the "
        "regression it guards becomes invisible again"
    )

    derived = derive_required_siblings(str(package), str(packages_dir))
    assert set(derived) >= {"sugar-lift-python-source", "sugar-source-tree"}, (
        "derivation stopped seeing siblings this package imports; an empty "
        f"`siblings=()` would hide them again. derived={derived}"
    )


def test_a_sibling_resolving_outside_the_checkout_FAILS(tmp_path):
    """The positive assertion extended to siblings, and it must FAIL.

    Absence of an ImportError proves nothing when the defect is a SUCCESSFUL
    import of the wrong tree -- which is what those 30 errors were: one of them
    named a source_oracle.py in another worktree. So the refusal is provoked,
    and a degraded skip is caught explicitly rather than trusted.
    """
    from checkout_resolution import CheckoutResolutionEscaped, require_local_resolution

    assert issubclass(CheckoutResolutionEscaped, AssertionError)
    assert not issubclass(CheckoutResolutionEscaped, pytest.skip.Exception)

    try:
        # `json` stands for any sibling resolving outside the checkout root.
        require_local_resolution("json", str(tmp_path))
    except pytest.skip.Exception as skipped:
        raise AssertionError(
            f"sibling resolution degraded into a SKIP ({skipped!r}); a package "
            "measuring another checkout would then report green"
        ) from None
    except CheckoutResolutionEscaped as refusal:
        message = str(refusal)
    else:
        raise AssertionError(
            "a module resolving OUTSIDE the root was accepted; the guard "
            "cannot catch the defect it exists for"
        )

    assert "resolved OUTSIDE this checkout" in message


def test_every_package_proves_its_derived_siblings_resolve_locally():
    """Derivation must be wired into the pin, not merely available beside it."""
    from checkout_resolution import derive_required_siblings

    packages_dir = ROOT / "implementations" / "python"
    packages = _packages_under_test()
    assert packages, "no packages under test; this guard would be vacuous"

    # BEHAVIOURAL, not a text match. An earlier version of this control
    # asserted the source contained "derive_required_siblings(package_dir,
    # packages_dir)" -- which also matches the function DEFINITION, so deleting
    # the CALL left it green. Mutation caught it. Text presence is not evidence
    # that a thing runs; run it.
    package = packages_dir / "sugar-lift-py-tests"
    sibling_src = str((packages_dir / "sugar-source-tree" / "src").resolve())
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, runpy;"
            f"runpy.run_path({str(package / 'tests' / 'conftest.py')!r});"
            "print(chr(10).join(sys.path))",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "PYTHONPATH": ""},
    )
    assert probe.returncode == 0, f"conftest failed to load:\n{probe.stderr}"
    assert sibling_src in probe.stdout.splitlines(), (
        "loading a conftest that declares `siblings=()` did NOT put its derived "
        f"sibling {sibling_src} on sys.path, so those imports resolve whatever "
        f"install the machine has.\nsys.path was:\n{probe.stdout}"
    )

    covered = 0
    for package in packages:
        derived = derive_required_siblings(str(package), str(packages_dir))
        for sibling in derived:
            assert (packages_dir / sibling / "src").is_dir(), (
                f"{_rel(package)} derives sibling {sibling!r}, which has no "
                "src/ in this checkout -- it could only resolve from elsewhere"
            )
            covered += 1
    assert covered, (
        "no package derived any sibling; either the repo genuinely has none "
        "or derivation is broken, and this guard cannot tell the difference"
    )
