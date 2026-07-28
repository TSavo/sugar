"""Immutable environment identity for the authoritative Python package suite.

One environment, one identity. Two runs that print the same
`environmentIdentityHash` ran the same interpreter, on the same platform,
against the same package sources, with the same declared test extras. Two runs
that print different hashes are not comparable measurements, and any claim that
compares them is a stale-measurement claim.

Fields (all load-bearing, all hashed into `environmentIdentityHash`):

  pythonImplementation / pythonVersion / pythonAbi   the interpreter
  platform                                            the machine + libc/OS
  sourceStamp                                         the Rust build inputs,
                                                      from the same
                                                      preimage `bin/sugarbin`
                                                      hashes (tools/sugar_source_stamp.py)
  testExtraInputHash                                  hash of the [test] table
                                                      and `dependencies` of the
                                                      package's pyproject.toml
                                                      -- the SOLE dependency
                                                      authority (#6275)
  packageBuildInputHash                               hash of every packaged
                                                      Python source file of
                                                      the packages installed

Usage:
    python tools/python_test_environment_identity.py \
        --repo-root . --output environment-identity.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import sysconfig

# The packages that make up the Python test environment. These are PATH
# installs of first-party packages, not a dependency list: every third-party
# requirement still comes from `sugar-lift-py-tests[test]`, which remains the
# sole dependency authority (#6275). Adding a third-party name here would be
# the regression that table exists to prevent.
ENVIRONMENT_PACKAGES = (
    "sugar-lift-py-tests",
    "sugar-lift-python-source",
    "sugar-source-tree",
)

AUTHORITY_PACKAGE = "sugar-lift-py-tests"

# Directories that never change what the suite means.
_SKIP_DIRS = {"__pycache__", ".git", ".venv", ".pytest_cache", "build", "dist"}

# The one shape a sourceStamp may take. Shared with
# tools/python_suite_identity_gate.py, which re-checks it on the ARTIFACT.
STAMP_PATTERN = re.compile(r"blake3-512_[0-9a-f]{128}")

# The extra whose contents the suite is allowed to import (#6275).
TEST_EXTRA = "test"


def _hash_tree(root, digest):
    """Fold every file under `root` into `digest`, path-sorted and labelled."""
    if not os.path.isdir(root):
        return 0
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith((".pyc", ".pyo")):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            digest.update(b"path\x00")
            digest.update(rel.encode("utf-8"))
            digest.update(b"\x00")
            with open(full, "rb") as handle:
                digest.update(hashlib.sha256(handle.read()).digest())
            count += 1
    return count


def _test_extra_input_hash(pyproject_path):
    """Hash the declared dependency authority: `dependencies` + `[test]`.

    Hashed from the parsed tables rather than the raw file so that a comment
    edit does not invalidate a measurement, while any change to what the suite
    is allowed to import does.
    """
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
        import tomli as tomllib

    if not os.path.isfile(pyproject_path):
        raise IdentityUnresolved(
            f"testExtraInputHash: missing dependency authority {pyproject_path}"
        )
    with open(pyproject_path, "rb") as handle:
        data = tomllib.load(handle)
    project = data.get("project", {})
    # A hash of nothing is a hash. It is also a claim that the suite declared
    # no test dependencies, which has never been true -- so an empty or absent
    # `[test]` extra is an unresolved identity, not a valid digest of {}.
    extras = project.get("optional-dependencies", {})
    if not extras.get(TEST_EXTRA):
        raise IdentityUnresolved(
            f"testExtraInputHash: {pyproject_path} declares no non-empty "
            f"[project.optional-dependencies].{TEST_EXTRA} -- the sole "
            f"dependency authority (#6275) is empty or missing"
        )
    authority = {
        "dependencies": project.get("dependencies", []),
        "optional-dependencies": project.get("optional-dependencies", {}),
        "requires-python": project.get("requires-python"),
        "build-system": data.get("build-system", {}),
    }
    payload = json.dumps(authority, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest(), authority


class IdentityUnresolved(Exception):
    """An identity field could not be resolved. There is no other outcome.

    THE DEFECT THIS TYPE EXISTS TO KILL. This function used to return
    `{"unavailable": "<exception text>"}` on failure. That object is TRUTHY.
    Every downstream reader -- `(identity.get('sourceStamp') or {}).get('value')`
    in the summary, the artifact consumers, a human reading a green check --
    treated a non-empty dict as a present field and read `None` out of it. A
    null would have been caught; a populated excuse was not. Run 30175741263
    concluded `success` with `sourceStamp: {"unavailable": ...}` and
    `testExtraInputHash: None` for exactly that reason.

    A marker that downstream code can mistake for a value is the bug. Identity
    resolves or the process dies here, before anything can call the result a
    measurement.
    """


def _source_stamp(repo_root):
    """The sourceStamp `bin/sugarbin` keys the measured binary by.

    Not a hash of our own choosing: the value here is the SAME
    `blake3-512_<hex>` string `tools/sugar_source_stamp.py` prints and
    `bin/sugarbin` resolves artifacts by, so a report's sourceStamp can be
    compared field-for-field with the resolved binary's `.sugarbin.json`
    manifest. A different algorithm over the same preimage would be a number
    that looks authoritative and matches nothing.

    Requires `cargo` on PATH: the preimage is the cargo local-dependency
    closure. That requirement is why run 30175741263 failed here -- identity
    was minted before the Rust toolchain was on PATH -- and it is a real
    requirement, so the fix is to put cargo on PATH, never to hash a hole.
    """
    script = os.path.join(repo_root, "tools", "sugar_source_stamp.py")
    if not os.path.isfile(script):
        raise IdentityUnresolved(f"sourceStamp: missing {script}")

    def _run(args):
        try:
            return subprocess.run(
                [sys.executable, script, "--repo-root", repo_root, *args],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode("utf-8", "replace")[-2000:]
            raise IdentityUnresolved(
                f"sourceStamp: {' '.join(args)} exited {exc.returncode}. "
                f"Is `cargo` on PATH? stderr:\n{stderr}"
            ) from exc
        except OSError as exc:
            raise IdentityUnresolved(f"sourceStamp: {type(exc).__name__}: {exc}") from exc

    stamp = _run([]).stdout.decode("utf-8", "replace").strip()
    if not STAMP_PATTERN.fullmatch(stamp):
        raise IdentityUnresolved(
            f"sourceStamp: {stamp!r} is not a blake3-512_<128 hex> stamp"
        )
    stream = _run(["--stream"]).stdout
    if not stream:
        raise IdentityUnresolved("sourceStamp: empty stamp preimage")
    return {
        "algorithm": "blake3-512-of-sugar_source_stamp-preimage",
        "value": stamp,
        "preimageBytes": len(stream),
        "preimageSha256": hashlib.sha256(stream).hexdigest(),
    }


def build_identity(repo_root):
    repo_root = os.path.abspath(repo_root)
    python_root = os.path.join(repo_root, "implementations", "python")

    package_inputs = {}
    build_digest = hashlib.sha256()
    for package in ENVIRONMENT_PACKAGES:
        package_dir = os.path.join(python_root, package)
        digest = hashlib.sha256()
        files = _hash_tree(os.path.join(package_dir, "src"), digest)
        pyproject = os.path.join(package_dir, "pyproject.toml")
        if os.path.isfile(pyproject):
            with open(pyproject, "rb") as handle:
                digest.update(hashlib.sha256(handle.read()).digest())
            files += 1
        package_inputs[package] = {"fileCount": files, "hash": digest.hexdigest()}
        build_digest.update(package.encode("utf-8"))
        build_digest.update(b"\x00")
        build_digest.update(digest.digest())

    authority_pyproject = os.path.join(
        python_root, AUTHORITY_PACKAGE, "pyproject.toml"
    )
    extra_hash, authority = _test_extra_input_hash(authority_pyproject)

    identity = {
        "schemaVersion": 1,
        "pythonImplementation": platform.python_implementation(),
        "pythonVersion": platform.python_version(),
        "pythonAbi": {
            "soabi": sysconfig.get_config_var("SOABI"),
            "apiVersion": sysconfig.get_config_var("VERSION"),
            "maxUnicode": sys.maxunicode,
            "hexVersion": sys.hexversion,
            "platformTag": sysconfig.get_platform(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "platform": platform.platform(),
            "libc": list(platform.libc_ver()),
        },
        "sourceStamp": _source_stamp(repo_root),
        "dependencyAuthority": {
            "package": AUTHORITY_PACKAGE,
            "pyprojectPath": os.path.relpath(authority_pyproject, repo_root),
            "testExtraInputHash": extra_hash,
            "declared": authority,
        },
        "packageBuildInputs": {
            "packages": package_inputs,
            "hash": build_digest.hexdigest(),
        },
    }

    # The identity hash covers everything above except itself.
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    identity["environmentIdentityHash"] = hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()
    return identity


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default=None, help="write JSON here")
    args = parser.parse_args(argv)

    try:
        identity = build_identity(args.repo_root)
    except IdentityUnresolved as exc:
        # No file is written. A half-minted identity on disk is exactly the
        # thing a later step would read, find truthy, and publish.
        print(
            "crime=identity-unresolved owner=tools/python_test_environment_identity.py "
            f"illegal shape={exc} "
            "replacement=resolve the field (put `cargo` on PATH before minting "
            "identity; declare the [test] extra) -- never record a marker in "
            "its place",
            file=sys.stderr,
        )
        return 1
    text = json.dumps(identity, indent=2) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
    print(identity["environmentIdentityHash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
