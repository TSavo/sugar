"""Immutable environment identity for the authoritative Python package suite.

One environment, one identity. Two runs that print the same
`environmentIdentityHash` ran the same interpreter, on the same platform,
against the same package sources, with the same declared test extras. Two runs
that print different hashes are not comparable measurements, and any claim that
compares them is a stale-measurement claim.

Fields (all load-bearing, all hashed into `environmentIdentityHash`):

  pythonImplementation / pythonVersion / pythonAbi   the interpreter
  platform                                            the machine + libc/OS
  sourceStamp                                         the Rust+Python build
                                                      inputs, from the same
                                                      preimage `bin/sugarbin`
                                                      hashes (tools/sugar_source_stamp.py)
  testExtraInputHash                                  hash of the [test] table
                                                      and `dependencies` of the
                                                      package's pyproject.toml
                                                      -- the SOLE dependency
                                                      authority (#6275)
  packageBuildInputHash                               hash of every packaged
                                                      source file of the
                                                      packages installed

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

    with open(pyproject_path, "rb") as handle:
        data = tomllib.load(handle)
    project = data.get("project", {})
    authority = {
        "dependencies": project.get("dependencies", []),
        "optional-dependencies": project.get("optional-dependencies", {}),
        "requires-python": project.get("requires-python"),
        "build-system": data.get("build-system", {}),
    }
    payload = json.dumps(authority, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest(), authority


def _source_stamp(repo_root):
    """The same sourceStamp `bin/sugarbin` resolves binaries by.

    Failure is recorded, never swallowed: a missing stamp makes the identity
    say so out loud rather than quietly hashing a hole.
    """
    script = os.path.join(repo_root, "tools", "sugar_source_stamp.py")
    if not os.path.isfile(script):
        return {"unavailable": f"missing {script}"}
    try:
        stream = subprocess.run(
            [sys.executable, script, "--repo-root", repo_root, "--stream"],
            check=True,
            capture_output=True,
        ).stdout
    except (subprocess.CalledProcessError, OSError) as exc:
        detail = getattr(exc, "stderr", b"") or b""
        return {
            "unavailable": f"{type(exc).__name__}: {exc}",
            "stderr": detail.decode("utf-8", "replace")[-2000:],
        }
    return {
        "algorithm": "sha256-of-sugar_source_stamp-preimage",
        "value": hashlib.sha256(stream).hexdigest(),
        "preimageBytes": len(stream),
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

    authority_pyproject = os.path.join(python_root, AUTHORITY_PACKAGE, "pyproject.toml")
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
    parser.add_argument(
        "--require-resolved",
        action="store_true",
        help=(
            "exit non-zero if sourceStamp is unavailable or testExtraInputHash "
            "is missing. Authoritative suite preparation must set this: an "
            'identity that embeds {"unavailable": ...} is not an identity.'
        ),
    )
    args = parser.parse_args(argv)

    identity = build_identity(args.repo_root)
    text = json.dumps(identity, indent=2) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)

    if args.require_resolved:
        errors = []
        stamp = identity.get("sourceStamp")
        if not isinstance(stamp, dict) or "unavailable" in stamp:
            detail = (
                stamp.get("unavailable")
                if isinstance(stamp, dict)
                else "sourceStamp missing"
            )
            errors.append(f"sourceStamp unresolved: {detail}")
        elif not stamp.get("value"):
            errors.append("sourceStamp has no value")
        dep = identity.get("dependencyAuthority") or {}
        if not dep.get("testExtraInputHash"):
            errors.append("testExtraInputHash is null or missing")
        if not identity.get("environmentIdentityHash"):
            errors.append("environmentIdentityHash is null or missing")
        if errors:
            for err in errors:
                print(f"python-test-environment-identity: {err}", file=sys.stderr)
            return 1

    print(identity["environmentIdentityHash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
