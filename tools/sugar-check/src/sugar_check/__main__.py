"""sugar-check: behavioral semver for Python packages (the pip wedge).

`sugar-check check` lifts the current package and a baseline (a git revision)
into pytest-derived behavior contracts via the sugar pytest lifter, diffs them
with `sugar diff`, and fails if the version bump is dishonest about what the
code does.

The fingerprint is the harvested pytest assertion set, which is reformat-stable:
refactor the implementation and the assertion is unchanged, so the behavior CID
holds. Only a changed promise (a changed assertion) or an added/removed test
moves it. That is the whole thesis -- the test is the contract you pin on --
and it is what makes the diff quiet on refactors and loud only on real change.

Delivered as a pre-commit hook: one stanza in .pre-commit-config.yaml, the most
frictionlessly adopted artifact in Python tooling. The content-addressed
machinery stays entirely under the hood.

Requires the `sugar` binary (set SUGAR_BIN or have it on PATH) and the
`sugar_lift_py_tests` kit importable in this interpreter.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT_MODULE = "sugar_lift_py_tests.lift_rpc"

CONFIG_TOML = """[[plugins]]
name = "python-tests-lift"
kind = "lift"
surface = "python-tests"
[solvers]
default = "z3"
[solvers.dispatch]
default = "z3"
[solvers.z3]
binary = "z3"
flags = ["-smt2", "-in"]
"""

SKIP = {".git", ".sugar", "__pycache__", ".venv", "venv", "build", "dist", ".tox", ".pytest_cache"}


def sugar_bin() -> str:
    return os.environ.get("SUGAR_BIN", "sugar")


def treeish(rev: str, path: str) -> str:
    """The git tree-ish for `git archive`: `rev` for the whole tree, `rev:path`
    for a subtree."""
    return rev if path in ("", ".") else f"{rev}:{path}"


def manifest_toml() -> str:
    return (
        'name = "python-tests-lift"\n'
        'kind = "lift"\n'
        f'command = ["{sys.executable}", "-m", "{KIT_MODULE}", "--rpc"]\n'
        'working_dir = "."\n'
        "[capabilities]\n"
        'authoring_surfaces = ["python-tests"]\n'
    )


def bootstrap_python(project: Path) -> None:
    """Stamp the pytest-contract lift config into `project` (idempotent)."""
    s = project / ".sugar"
    if (s / "config.toml").exists():
        return
    (s / "lift" / "python-tests").mkdir(parents=True, exist_ok=True)
    (s / "config.toml").write_text(CONFIG_TOML)
    (s / "lift" / "python-tests" / "manifest.toml").write_text(manifest_toml())


def mint(project: Path, out: Path) -> None:
    bootstrap_python(project)
    r = subprocess.run([sugar_bin(), "mint", "--project", str(project), "--out", str(out)])
    if r.returncode != 0:
        raise SystemExit(f"sugar mint failed for {project}")


def copy_current(dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in os.listdir("."):
        if item in SKIP:
            continue
        src = Path(item)
        if src.is_dir():
            shutil.copytree(src, dst / item, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, dst / item)


def extract_git(rev: str, path: str, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    archive = subprocess.run(
        ["git", "archive", "--format=tar", treeish(rev, path)], stdout=subprocess.PIPE
    )
    if archive.returncode != 0:
        raise SystemExit(f"git archive {treeish(rev, path)} failed")
    tar = subprocess.run(["tar", "-x", "-C", str(dst)], input=archive.stdout)
    if tar.returncode != 0:
        raise SystemExit("tar extract failed")


def cmd_check(a: argparse.Namespace) -> int:
    if not a.rev:
        raise SystemExit(
            "baseline required: pass --rev <git-rev> "
            "(the PyPI-release baseline is the next increment)"
        )
    scratch = Path(tempfile.mkdtemp(prefix="sugar-check-"))
    try:
        cur_src, cur_out = scratch / "cur", scratch / "cur-proofs"
        base_src, base_out = scratch / "base", scratch / "base-proofs"
        copy_current(cur_src)
        extract_git(a.rev, a.path, base_src)
        print(f"sugar-check: current tree vs git {a.rev}", file=sys.stderr)
        mint(cur_src, cur_out)
        mint(base_src, base_out)
        cmd = [sugar_bin(), "diff", str(base_out), str(cur_out)]
        if a.require:
            cmd += ["--require", a.require]
        return subprocess.run(cmd).returncode
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def cmd_diff(a: argparse.Namespace) -> int:
    return subprocess.run([sugar_bin(), "diff", *a.args]).returncode


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sugar-check", description="Behavioral semver for Python packages.")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="diff current package behavior against a baseline; enforce the bump")
    c.add_argument("--rev", help="baseline git revision (e.g. HEAD, the last release tag)")
    c.add_argument("--path", default=".", help="project subdirectory within the revision tree")
    c.add_argument("--require", help="fail unless the behavior delta fits this bump (none|minor|major)")
    c.set_defaults(fn=cmd_check)
    d = sub.add_parser("diff", help="passthrough to `sugar diff`")
    d.add_argument("args", nargs=argparse.REMAINDER)
    d.set_defaults(fn=cmd_diff)
    return p


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
