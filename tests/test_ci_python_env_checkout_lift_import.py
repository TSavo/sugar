"""CI python-test-environment: first-party lift resolves from the checkout.

Both S0.1 recensus and S0.2 floors died with the same
``ExecutionEnvironmentMismatch``: ``sugar_lift_py_tests`` was loaded from the
immutable venv's site-packages, not the synced checkout. The authority
(``authenticate_lift``) is correct — measuring with a different build than the
tree you claim about is false provenance. The fix is the environment shape:

1. Do NOT wheel-install first-party packages into the venv.
2. Export managed checkout PYTHONPATH before any process imports the package.
3. ``activate_checkout_import_roots`` after first import cannot unseat
   ``sys.modules`` — so a test that only imports from a dev editable checkout
   cannot fail on this defect.

These twins rebuild CI's install contract in a mini checkout + venv. They do
not require numpy/pandas; they prove import provenance under the same path
rules the action uses.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github/actions/python-test-environment/action.yml"
MANAGED_TOOL = ROOT / "tools/managed_checkout_pythonpath.py"
DOCKERFILE = ROOT / "tools/sugar-build/Dockerfile"


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")


def _mini_checkout(tmp_path: Path) -> Path:
    """Synthetic monorepo whose lift package lives only under checkout src."""
    repo = tmp_path / "sugar"
    # Marker for resolve_repo_root / identity of a real checkout.
    (repo / "sugar-build.toml").parent.mkdir(parents=True, exist_ok=True)
    (repo / "sugar-build.toml").write_text("# mini\n", encoding="utf-8")

    # Managed PYTHONPATH declaration — same shape as production Dockerfile.
    dockerfile = repo / "tools/sugar-build/Dockerfile"
    _write(
        dockerfile,
        """
        FROM scratch
        ENV PYTHONPATH=/workspace/sugar/implementations/python/sugar-lift-py-tests/src:/workspace/sugar/implementations/python/sugar-source-tree/src
        """,
    )

    lift_root = (
        repo / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests"
    )
    _write(
        lift_root / "__init__.py",
        '''
        """Checkout-resident first-party package (truthful face)."""
        CHECKOUT_MARKER = "from-synced-checkout"
        ''',
    )
    # Minimal authenticated_pytest surface for authenticate_lift import path.
    _write(
        lift_root / "authenticated_pytest.py",
        '''
        from pathlib import Path
        from types import ModuleType

        class ExecutionEnvironmentMismatch(RuntimeError):
            pass

        def authenticate_lift(module: ModuleType, repo_root: Path):
            expected = (
                repo_root / "implementations/python/sugar-lift-py-tests/src"
            ).resolve()
            loaded = Path(str(getattr(module, "__file__", ""))).resolve()
            if not (loaded == expected or expected in loaded.parents):
                raise ExecutionEnvironmentMismatch(
                    f"lift import escaped the synced checkout: loaded "
                    f"sugar_lift_py_tests from {loaded}; required {expected}"
                )
            return loaded
        ''',
    )
    source_tree = (
        repo / "implementations/python/sugar-source-tree/src/sugar_source_tree"
    )
    _write(source_tree / "__init__.py", 'MARKER = "source-tree-checkout"\n')

    # Stdlib-only managed PYTHONPATH tool (copy production tool into mini repo
    # so the twin exercises the same file the action runs).
    tool_src = MANAGED_TOOL.read_text(encoding="utf-8")
    _write(repo / "tools/managed_checkout_pythonpath.py", tool_src)
    return repo


def _make_venv(path: Path) -> Path:
    venv.create(path, with_pip=False, clear=True)
    python = path / ("Scripts" if os.name == "nt" else "bin") / "python"
    assert python.is_file(), python
    return python


def _site_packages(venv_python: Path) -> Path:
    completed = subprocess.run(
        [
            str(venv_python),
            "-c",
            "import sysconfig; print(sysconfig.get_paths()['purelib'])",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(completed.stdout.strip())


def _install_foreign_lift_into_site_packages(purelib: Path) -> Path:
    """Simulate the broken CI shape: first-party wheel-installed into venv."""
    pkg = purelib / "sugar_lift_py_tests"
    _write(
        pkg / "__init__.py",
        '''
        """Foreign site-packages copy (lying face)."""
        CHECKOUT_MARKER = "from-site-packages"
        ''',
    )
    return pkg / "__init__.py"


PROBE = textwrap.dedent(
    """
    import importlib
    import sys
    from pathlib import Path

    repo = Path(sys.argv[1]).resolve()
    # Optional: activate roots AFTER import (the ordering bug).
    activate_after = sys.argv[2] == "activate-after"

    if activate_after:
        # Import first (as -m sugar_lift_py_tests.* does), then rebind path.
        import sugar_lift_py_tests  # noqa: F401
        tool = repo / "tools/managed_checkout_pythonpath.py"
        import importlib.util
        spec = importlib.util.spec_from_file_location("mcp", tool)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for root in reversed(mod.managed_checkout_import_roots(repo)):
            sys.path.insert(0, str(root))
        # Rebinding path does not replace sys.modules — the defect.
        lift = sys.modules["sugar_lift_py_tests"]
    else:
        lift = importlib.import_module("sugar_lift_py_tests")

    loaded = Path(lift.__file__).resolve()
    marker = getattr(lift, "CHECKOUT_MARKER", "<missing>")
    print(f"loaded_from={loaded}")
    print(f"marker={marker}")

    # authenticate_lift law (same predicate CI uses)
    expected = (repo / "implementations/python/sugar-lift-py-tests/src").resolve()
    inside = loaded == expected or expected in loaded.parents
    print(f"inside_checkout={inside}")
    if not inside:
        raise SystemExit(2)
    if marker != "from-synced-checkout":
        raise SystemExit(3)
    """
).lstrip()


def test_action_strips_first_party_and_binds_checkout_pythonpath() -> None:
    """Static teeth on the shared action both S0.1 and S0.2 consume."""
    text = ACTION.read_text(encoding="utf-8")
    assert ACTION.is_file()
    assert "managed_checkout_pythonpath" in text
    assert "SUGAR_CHECKOUT_PYTHONPATH" in text
    # First-party must be stripped from the wheelhouse / not installed.
    assert "sugar_lift_*.whl" in text or "sugar_lift_" in text
    assert "first-party" in text.lower()
    # Must not pip-install the authority package by name into the venv.
    install_lines = [
        line
        for line in text.splitlines()
        if "pip install" in line and "sugar-lift-py-tests" in line
    ]
    assert not install_lines, (
        "action must not pip-install sugar-lift-py-tests into the venv; "
        f"found: {install_lines}"
    )
    # Wheel build still names the authority so the third-party table resolves.
    assert "pip wheel" in text and "sugar-lift-py-tests[test]" in text


def test_managed_checkout_pythonpath_tool_matches_production_dockerfile() -> None:
    """The CI binder and the live Dockerfile agree on the root list."""
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        from managed_checkout_pythonpath import managed_checkout_import_roots
    finally:
        if str(ROOT / "tools") in sys.path:
            sys.path.remove(str(ROOT / "tools"))

    roots = managed_checkout_import_roots(ROOT)
    assert roots, "managed PYTHONPATH produced no roots"
    lift_src = (
        ROOT / "implementations/python/sugar-lift-py-tests/src"
    ).resolve()
    assert lift_src in roots
    assert all(root.is_dir() for root in roots)
    assert DOCKERFILE.is_file()


def test_truthful_ci_shape_import_resolves_inside_checkout(tmp_path: Path) -> None:
    """No first-party in site-packages + process-start PYTHONPATH → checkout.

    This is the python-test-environment contract after the fix. A subprocess
    with only the managed PYTHONPATH (not a developer editable install) must
    load sugar_lift_py_tests from the checkout src tree.
    """
    repo = _mini_checkout(tmp_path)
    venv_python = _make_venv(tmp_path / "venv")
    purelib = _site_packages(venv_python)
    # Truthful: site-packages has NO sugar_lift_py_tests.
    assert not (purelib / "sugar_lift_py_tests").exists()

    checkout_pp = subprocess.run(
        [
            sys.executable,
            str(repo / "tools/managed_checkout_pythonpath.py"),
            "--repo-root",
            str(repo),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert checkout_pp
    assert str(repo) in checkout_pp

    probe = tmp_path / "probe.py"
    probe.write_text(PROBE, encoding="utf-8")
    completed = subprocess.run(
        [str(venv_python), str(probe), str(repo), "no-activate"],
        env={**os.environ, "PYTHONPATH": checkout_pp},
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "inside_checkout=True" in completed.stdout
    assert "marker=from-synced-checkout" in completed.stdout
    assert "site-packages" not in completed.stdout


def test_lying_site_packages_install_is_outside_checkout_even_if_activated_after(
    tmp_path: Path,
) -> None:
    """First-party in site-packages + activate-after-import = the S0 defect.

    Rebinding sys.path after the package is already in sys.modules leaves the
    foreign copy loaded. authenticate_lift's predicate (inside_checkout) is
    false — the twin must go red, not pass because a later path mutation
    looked correct.
    """
    repo = _mini_checkout(tmp_path)
    venv_python = _make_venv(tmp_path / "venv")
    purelib = _site_packages(venv_python)
    foreign = _install_foreign_lift_into_site_packages(purelib)

    checkout_pp = subprocess.run(
        [
            sys.executable,
            str(repo / "tools/managed_checkout_pythonpath.py"),
            "--repo-root",
            str(repo),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    probe = tmp_path / "probe.py"
    probe.write_text(PROBE, encoding="utf-8")

    # Process starts WITHOUT checkout PYTHONPATH so the first import hits
    # site-packages (the broken CI wheel-install shape). Then the probe
    # activates roots after import — which must not green the lie.
    completed = subprocess.run(
        [str(venv_python), str(probe), str(repo), "activate-after"],
        env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0, (
        "activate-after-import must not accept a site-packages first-party "
        f"load:\n{completed.stdout}\n{completed.stderr}"
    )
    assert "inside_checkout=False" in completed.stdout or completed.returncode == 2
    assert "from-site-packages" in completed.stdout or str(foreign.parent) in (
        completed.stdout + completed.stderr
    )


def test_lying_site_packages_with_checkout_pythonpath_prefers_checkout(
    tmp_path: Path,
) -> None:
    """If both exist, process-start PYTHONPATH must win (checkout first).

    Belt: even a leftover site-packages copy must lose to managed PYTHONPATH
    when the action exports it correctly before import.
    """
    repo = _mini_checkout(tmp_path)
    venv_python = _make_venv(tmp_path / "venv")
    purelib = _site_packages(venv_python)
    _install_foreign_lift_into_site_packages(purelib)

    checkout_pp = subprocess.run(
        [
            sys.executable,
            str(repo / "tools/managed_checkout_pythonpath.py"),
            "--repo-root",
            str(repo),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    probe = tmp_path / "probe.py"
    probe.write_text(PROBE, encoding="utf-8")
    completed = subprocess.run(
        [str(venv_python), str(probe), str(repo), "no-activate"],
        env={**os.environ, "PYTHONPATH": checkout_pp},
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "marker=from-synced-checkout" in completed.stdout
    assert "inside_checkout=True" in completed.stdout
