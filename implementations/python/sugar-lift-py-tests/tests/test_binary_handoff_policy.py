from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import threading
import time
import tokenize
from pathlib import Path

import pytest


from sugar_lift_py_tests.repo_root import resolve_repo_root

ROOT = resolve_repo_root()
SUGARBIN = ROOT / "bin" / "sugarbin"
PY_KIT_ROOTS = (
    ROOT / "implementations" / "python" / "sugar-lift-py-tests",
    ROOT / "implementations" / "python" / "sugar-lift-python-source",
)
THIS_TEST = Path(__file__).resolve()
SOURCE_STAMP_TOOL = ROOT / "tools" / "sugar_source_stamp.py"
# The path-coordinate form tools/sugar_source_stamp.py prints: underscore, no colon.
STAMP_RE = re.compile(r"^blake3-512_[0-9a-f]{128}$")


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in PY_KIT_ROOTS:
        files.extend(path for path in root.rglob("*.py") if path != THIS_TEST)
    return sorted(files)


def _runtime_python_files() -> list[Path]:
    files: list[Path] = []
    for root in PY_KIT_ROOTS:
        src = root / "src"
        files.extend(path for path in src.rglob("*.py"))
    return sorted(files)


def _literal_text(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_cargo_build_call(node: ast.Call) -> bool:
    if not (
        isinstance(node.func, ast.Attribute)
        and node.func.attr in {"run", "check_call", "check_output", "Popen"}
    ):
        return False
    if not node.args:
        return False
    argv = node.args[0]
    if isinstance(argv, ast.List):
        values = [_literal_text(elt) for elt in argv.elts]
        return len(values) >= 2 and values[0] == "cargo" and values[1] == "build"
    return False


def _is_bare_sugar_subprocess_call(node: ast.Call) -> bool:
    if not (
        isinstance(node.func, ast.Attribute)
        and node.func.attr in {"run", "check_call", "check_output", "Popen"}
    ):
        return False
    if not node.args:
        return False
    argv = node.args[0]
    if not isinstance(argv, ast.List) or not argv.elts:
        return False
    return _literal_text(argv.elts[0]) == "sugar"


def _is_sugar_path_lookup(node: ast.Call) -> bool:
    if not (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "which"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "shutil"
    ):
        return False
    if not node.args:
        return False
    return _literal_text(node.args[0]) == "sugar"


def test_python_kit_has_no_ad_hoc_cargo_build_shells() -> None:
    offenders: list[str] = []
    for path in _python_files():
        with tokenize.open(path) as source:
            tree = ast.parse(source.read(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_cargo_build_call(node):
                rel = path.relative_to(ROOT)
                offenders.append(f"{rel}:{node.lineno}: subprocess cargo build")
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and "cargo build" in node.value
            ):
                rel = path.relative_to(ROOT)
                offenders.append(f"{rel}:{node.lineno}: cargo build prose")
    assert offenders == []


def test_python_runtime_has_no_bare_sugar_binary_acquisition() -> None:
    offenders: list[str] = []
    for path in _runtime_python_files():
        with tokenize.open(path) as source:
            tree = ast.parse(source.read(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_bare_sugar_subprocess_call(node):
                rel = path.relative_to(ROOT)
                offenders.append(f"{rel}:{node.lineno}: subprocess bare sugar")
            if isinstance(node, ast.Call) and _is_sugar_path_lookup(node):
                rel = path.relative_to(ROOT)
                offenders.append(f"{rel}:{node.lineno}: shutil.which sugar")
    assert offenders == []


def _write_fake_sugar(path: Path, build_stamp: str) -> None:
    path.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "version" ] && [ "$2" = "--json" ]; then\n'
        "  printf '%s\\n' "
        '\'{"name":"sugar","version":"0.1.0",'
        f'"buildGitHead":"{build_stamp}","buildStamp":"{build_stamp}"}}\'\n'
        "  exit 0\n"
        "fi\n"
        "echo unexpected fake sugar invocation >&2\n"
        "exit 2\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _link_required_tool(bin_dir: Path, name: str) -> None:
    tool = shutil.which(name)
    assert tool is not None
    (bin_dir / name).symlink_to(tool)


def _run_sugarbin(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    merged_env = {**os.environ}
    for key in (
        "SUGAR_BIN",
        "SUGAR_BINARY_ALLOW_BUILD",
        "SUGAR_BINARY_CACHE_DIR",
        "SUGAR_BINARY_DIR",
        "SUGAR_BINARY_NO_SELF_HEAL",
        "SUGAR_BINARY_NO_SHELF",
        "SUGAR_BINARY_REPO",
        "SUGAR_BINARY_SOURCE_STAMP",
        "SUGAR_BINARY_TARGET_ROOT",
    ):
        if key not in env:
            merged_env.pop(key, None)
    merged_env.update(env)
    return subprocess.run(
        [os.fspath(SUGARBIN), *args],
        cwd=ROOT,
        env=merged_env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def _write_stamp_fixture(root: Path) -> Path:
    script = root / "bin" / "sugarbin"
    script.parent.mkdir(parents=True)
    shutil.copy2(SUGARBIN, script)
    script.chmod(0o755)
    # sugarbin sources bin/lib/sugar-exec.sh (execution broker split); the
    # fixture copy must carry the library or the copied script dies at source.
    shutil.copytree(SUGARBIN.parent / "lib", root / "bin" / "lib")
    # sugarbin does not compute the stamp itself: it asks the one stamp tool,
    # at <repo>/tools/sugar_source_stamp.py. The fixture repo carries it.
    (root / "tools").mkdir()
    shutil.copy2(SOURCE_STAMP_TOOL, root / "tools" / SOURCE_STAMP_TOOL.name)

    rust_src = root / "implementations" / "rust" / "sugar-cli" / "src"
    rust_src.mkdir(parents=True)
    (root / "implementations" / "rust" / "Cargo.toml").write_text(
        '[workspace]\nmembers = ["sugar-cli"]\n',
        encoding="utf-8",
    )
    # The stamp tool reads the package's dependency closure through
    # ``cargo metadata --locked``, so the lock states the one package exactly.
    (root / "implementations" / "rust" / "Cargo.lock").write_text(
        "# This file is automatically @generated by Cargo.\n"
        "# It is not intended for manual editing.\n"
        "version = 3\n"
        "\n"
        "[[package]]\n"
        'name = "sugar-cli"\n'
        'version = "0.0.0"\n',
        encoding="utf-8",
    )
    (root / "implementations" / "rust" / "sugar-cli" / "Cargo.toml").write_text(
        '[package]\nname = "sugar-cli"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    (rust_src / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    py_src = root / "implementations" / "python" / "sugar-lift-py-tests"
    py_src.mkdir(parents=True)
    (py_src / "ignored_by_sugarbin.py").write_text("VALUE = 1\n", encoding="utf-8")
    return script


def _run_fixture_sugarbin(
    script: Path, env: dict[str, str] | None = None, *args: str
) -> subprocess.CompletedProcess[str]:
    merged_env = {**os.environ, **(env or {})}
    for key in (
        "SUGAR_BIN",
        "SUGAR_BINARY_ALLOW_BUILD",
        "SUGAR_BINARY_CACHE_DIR",
        "SUGAR_BINARY_NO_SHELF",
        "SUGAR_BINARY_REPO",
        "SUGAR_BINARY_SOURCE_STAMP",
        "SUGAR_BINARY_TARGET_ROOT",
        "SUGAR_BUILD_GIT_HEAD",
    ):
        if env is None or key not in env:
            merged_env.pop(key, None)
    return subprocess.run(
        [os.fspath(script), *args],
        cwd=script.parent.parent,
        env=merged_env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def _fixture_stamp(script: Path) -> str:
    completed = _run_fixture_sugarbin(script, {}, "--print-source-stamp")
    assert completed.returncode == 0, completed.stderr
    stamp = completed.stdout.strip()
    assert STAMP_RE.fullmatch(stamp)
    return stamp


def test_sugarbin_prints_explicit_sugar_bin_without_resolving(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit-sugar"
    _write_fake_sugar(explicit, "not-the-workspace")
    completed = _run_sugarbin(
        {
            "SUGAR_BIN": os.fspath(explicit),
            "SUGAR_BINARY_ALLOW_BUILD": "0",
            "SUGAR_BINARY_NO_SHELF": "1",
        },
        "--profile",
        "release",
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == os.fspath(explicit)


def _write_profiled_fake_sugar(tmp_path: Path, profile: str) -> Path:
    binary = tmp_path / "target" / profile / "sugar"
    binary.parent.mkdir(parents=True)
    _write_fake_sugar(binary, "not-the-workspace")
    return binary


def test_sugarbin_refuses_sugar_bin_whose_path_contradicts_the_profile(
    tmp_path: Path,
) -> None:
    release_binary = _write_profiled_fake_sugar(tmp_path, "release")
    completed = _run_sugarbin(
        {
            "SUGAR_BIN": os.fspath(release_binary),
            "SUGAR_BINARY_ALLOW_BUILD": "0",
            "SUGAR_BINARY_NO_SHELF": "1",
        },
        "--profile",
        "debug",
    )
    assert completed.returncode != 0
    assert completed.stdout.strip() == ""
    assert "crime=profile-blind-override" in completed.stderr
    assert "requested=debug" in completed.stderr
    assert "evidence=release" in completed.stderr


def test_sugarbin_serves_sugar_bin_whose_path_agrees_with_the_profile(
    tmp_path: Path,
) -> None:
    debug_binary = _write_profiled_fake_sugar(tmp_path, "debug")
    completed = _run_sugarbin(
        {
            "SUGAR_BIN": os.fspath(debug_binary),
            "SUGAR_BINARY_ALLOW_BUILD": "0",
            "SUGAR_BINARY_NO_SHELF": "1",
        },
        "--profile",
        "debug",
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == os.fspath(debug_binary)


def test_sugarbin_refuses_shelf_named_override_that_contradicts_the_profile(
    tmp_path: Path,
) -> None:
    shelved = tmp_path / "sugar-darwin-x86_64-release-abcdef"
    _write_fake_sugar(shelved, "not-the-workspace")
    completed = _run_sugarbin(
        {
            "SUGAR_BIN": os.fspath(shelved),
            "SUGAR_BINARY_ALLOW_BUILD": "0",
            "SUGAR_BINARY_NO_SHELF": "1",
        },
        "--profile",
        "debug",
        "--bin",
        "sugar",
    )
    assert completed.returncode != 0
    assert "crime=profile-blind-override" in completed.stderr


def test_sugarbin_refuses_binary_dir_override_that_contradicts_the_profile(
    tmp_path: Path,
) -> None:
    release_binary = _write_profiled_fake_sugar(tmp_path, "release")
    release_binary.chmod(0o755)
    completed = _run_sugarbin(
        {
            "SUGAR_BINARY_DIR": os.fspath(release_binary.parent),
            "SUGAR_BINARY_ALLOW_BUILD": "0",
            "SUGAR_BINARY_NO_SHELF": "1",
        },
        "--profile",
        "debug",
    )
    assert completed.returncode != 0
    assert completed.stdout.strip() == ""
    assert "source=SUGAR_BINARY_DIR" in completed.stderr


def test_sugarbin_refuses_when_every_rung_is_exhausted(tmp_path: Path) -> None:
    """A local binary with no manifest is not served, and a miss with every
    other rung closed is a refusal -- never a build.

    The local rung authenticates by the ``.sugarbin.json`` manifest beside the
    binary, so an executable that states none is skipped by name. With the
    shelf off and both the build and the self-heal rebuild refused, nothing is
    left: the resolve prints no path and exits non-zero. (The shelf rung itself
    is the filesystem CAS, twinned in ``tests/sugarbin_shelf_*.sh``.)
    """
    target = tmp_path / "target"
    unauthenticated = target / "release" / "sugar"
    unauthenticated.parent.mkdir(parents=True)
    _write_fake_sugar(unauthenticated, "oldbadcafe")
    completed = _run_sugarbin(
        {
            "SUGAR_BINARY_TARGET_ROOT": os.fspath(target),
            "SUGAR_BINARY_CACHE_DIR": os.fspath(tmp_path / "cache"),
            "SUGAR_BINARY_SOURCE_STAMP": "newfeedface",
            "SUGAR_BINARY_ALLOW_BUILD": "0",
            "SUGAR_BINARY_NO_SELF_HEAL": "1",
            "SUGAR_BINARY_NO_SHELF": "1",
        },
        "--profile",
        "release",
    )
    assert completed.returncode != 0
    assert completed.stdout.strip() == ""
    assert "local target skipped: no executable manifest" in completed.stderr
    assert "shelf pull disabled by SUGAR_BINARY_NO_SHELF=1" in completed.stderr
    assert "note=no-self-heal" in completed.stderr
    assert "phase=resolve-build-start" not in completed.stderr


def test_sugarbin_can_print_source_stamp_without_resolving_binary() -> None:
    completed = _run_sugarbin(
        {
            "SUGAR_BINARY_SOURCE_STAMP": "stamp-for-delegators",
            "SUGAR_BINARY_ALLOW_BUILD": "0",
            "SUGAR_BINARY_NO_SHELF": "1",
        },
        "--print-source-stamp",
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "stamp-for-delegators"
    assert completed.stderr == ""


def test_sugarbin_source_stamp_is_rust_tree_content_hash(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "nested" / "second"
    first_script = _write_stamp_fixture(first)
    second_script = _write_stamp_fixture(second)

    first_stamp = _fixture_stamp(first_script)
    assert _fixture_stamp(second_script) == first_stamp

    (
        first
        / "implementations"
        / "python"
        / "sugar-lift-py-tests"
        / "ignored_by_sugarbin.py"
    ).write_text(
        "VALUE = 2\n",
        encoding="utf-8",
    )
    assert _fixture_stamp(first_script) == first_stamp

    (first / "implementations" / "rust" / "sugar-cli" / "src" / "main.rs").write_text(
        'fn main() { println!("changed"); }\n',
        encoding="utf-8",
    )
    assert _fixture_stamp(first_script) != first_stamp


def test_sugarbin_source_stamp_ignores_git_history_for_identical_bytes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    script = _write_stamp_fixture(root)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Sugar Test",
            "-c",
            "user.email=sugar@example.invalid",
            "commit",
            "-qm",
            "initial",
        ],
        cwd=root,
        check=True,
    )
    before = _fixture_stamp(script)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Sugar Test",
            "-c",
            "user.email=sugar@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "synthetic rebase commit",
        ],
        cwd=root,
        check=True,
    )
    assert _fixture_stamp(script) == before


def test_sugarbin_source_stamp_requires_blake3_tool(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    script = _write_stamp_fixture(root)
    fake_bin = tmp_path / "bin-no-b3sum"
    fake_bin.mkdir()
    # Everything the stamp needs except b3sum, so the refusal names b3sum alone.
    for tool in ("bash", "dirname", "git", "python3", "cargo"):
        _link_required_tool(fake_bin, tool)

    completed = _run_fixture_sugarbin(
        script,
        {"PATH": os.fspath(fake_bin)},
        "--print-source-stamp",
    )

    assert completed.returncode != 0
    assert completed.stdout.strip() == ""
    assert (
        "source stamping refused: missing required tool: b3sum" in completed.stderr
    )
    assert "b3sum is required for source stamping" in completed.stderr


def test_python_wrapper_delegates_to_sugarbin(tmp_path: Path, monkeypatch) -> None:
    from sugar_lift_py_tests import sugar_binary

    fake = tmp_path / "sugarbin"
    resolved = tmp_path / "sugar"
    fake.write_text(
        f"#!/bin/sh\nprintf '%s\\n' {os.fspath(resolved)!r}\n", encoding="utf-8"
    )
    fake.chmod(0o755)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, f"{resolved}\n", "")

    monkeypatch.setattr(sugar_binary, "sugarbin_path", lambda: fake)
    monkeypatch.setattr(sugar_binary, "current_os_name", lambda: "posix")
    monkeypatch.setattr(sugar_binary.platform, "node", lambda: "MapLaptop")
    monkeypatch.setattr(sugar_binary, "subprocess_run", fake_run)
    assert sugar_binary.resolve_sugar_binary() == resolved
    assert calls[0][0] == [str(fake), "--profile", "release"]


def test_python_wrapper_uses_native_windows_sugarbin(monkeypatch) -> None:
    from sugar_lift_py_tests import sugar_binary

    resolved = Path(r"C:\sugar\target\release\sugar.exe")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, f"{resolved}\n", "")

    monkeypatch.setattr(sugar_binary, "current_os_name", lambda: "nt")
    monkeypatch.setattr(sugar_binary.platform, "node", lambda: "Battleaxe")
    monkeypatch.setattr(sugar_binary, "subprocess_run", fake_run)

    assert sugar_binary.resolve_sugar_binary() == resolved
    assert calls[0][0] == [
        "powershell.exe",
        "-NoProfile",
        "-File",
        str(sugar_binary.sugarbin_windows_path()),
        "-Profile",
        "release",
    ]


def test_python_wrapper_keeps_non_battleaxe_windows_on_broker(monkeypatch) -> None:
    from sugar_lift_py_tests import sugar_binary

    resolved = Path("/remote/cache/sugar")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, f"{resolved}\n", "")

    monkeypatch.setattr(sugar_binary, "current_os_name", lambda: "nt")
    monkeypatch.setattr(sugar_binary.platform, "node", lambda: "MapLaptop")
    monkeypatch.setattr(sugar_binary, "subprocess_run", fake_run)

    assert sugar_binary.resolve_sugar_binary() == resolved
    assert calls[0][0] == [
        "bash.exe",
        "-lc",
        'script="$(cygpath -u "$SUGAR_WINDOWS_SCRIPT" 2>/dev/null || '
        'wslpath -u "$SUGAR_WINDOWS_SCRIPT")"; '
        'exec "$script" --profile "$1"',
        "sugarbin",
        "release",
    ]
    assert calls[0][1]["env"]["SUGAR_WINDOWS_SCRIPT"] == str(
        sugar_binary.sugarbin_path()
    )


def test_mac_laptop_routes_to_posix_offload_broker() -> None:
    from sugar_lift_py_tests.sugar_binary import sugarbin_route

    assert (
        sugarbin_route(os_name="posix", hostname="Tsavo-MacBook-Pro") == "posix-broker"
    )


def test_battleaxe_routes_to_native_local_build() -> None:
    from sugar_lift_py_tests.sugar_binary import sugarbin_route

    assert sugarbin_route(os_name="nt", hostname="Battleaxe") == "battleaxe-native"


def test_witness_harness_resolves_sugar_once_for_parallel_callers(
    tmp_path: Path, monkeypatch
) -> None:
    from sugar_lift_py_tests import witness_harness

    resolved = tmp_path / "sugar"
    calls = 0
    lock = threading.Lock()
    start = threading.Event()
    monkeypatch.setattr(witness_harness, "_RESOLVED_SUGAR_BIN", None)

    def fake_resolve_sugar_binary(**named):
        nonlocal calls
        # The harness names no profile of its own: the suite has one.
        assert named == {}
        with lock:
            calls += 1
        time.sleep(0.05)
        return resolved

    monkeypatch.setattr(
        witness_harness,
        "resolve_sugar_binary",
        fake_resolve_sugar_binary,
    )

    results: list[Path] = []
    errors: list[BaseException] = []

    def call_ensure_sugar_bin() -> None:
        start.wait(timeout=5)
        try:
            results.append(witness_harness.ensure_sugar_bin())
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=call_ensure_sugar_bin) for _ in range(4)]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join(timeout=5)

    assert errors == []
    assert results == [resolved, resolved, resolved, resolved]
    assert calls == 1


def test_the_solver_harness_runs_the_binary_the_conftest_handed_over(
    sugar_binary_handoff: str, tmp_path: Path, monkeypatch
) -> None:
    """One profile, named in one place. Through the real ``bin/sugarbin``.

    Truthful: the harness resolves with no profile of its own, so it gets the
    binary the session handoff exported as ``SUGAR_BIN``. Lying: the same door
    asked for a second profile against a handoff of the suite's profile is
    refused by ``sugarbin`` (#6282), which is what stopped every solver twin
    while the harness asked for ``debug``.
    """
    from sugar_lift_py_tests import sugar_binary, witness_harness

    monkeypatch.setattr(witness_harness, "_RESOLVED_SUGAR_BIN", None)
    assert witness_harness.ensure_sugar_bin() == Path(sugar_binary_handoff)

    handed = tmp_path / "target" / sugar_binary.SUITE_PROFILE / "sugar"
    with pytest.raises(sugar_binary.SugarBinaryResolutionError) as refusal:
        sugar_binary.resolve_sugar_binary(
            env={**os.environ, "SUGAR_BIN": str(handed)}, profile="debug"
        )
    assert "crime=profile-blind-override" in str(refusal.value)


def test_resolution_timeout_is_a_resolution_error_not_a_bare_timeout(
    monkeypatch,
) -> None:
    """A stalled sugarbin must not error every collected test with one traceback.

    `resolve_sugar_binary` runs inside a session-scoped autouse fixture that
    only catches `SugarBinaryResolutionError`. Any other exception type escapes
    the fixture and is attributed to every test in the run.
    """
    from sugar_lift_py_tests import sugar_binary

    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(sugar_binary.platform, "node", lambda: "MapLaptop")
    monkeypatch.setattr(sugar_binary, "subprocess_run", fake_run)

    with pytest.raises(sugar_binary.SugarBinaryResolutionError) as excinfo:
        sugar_binary.resolve_sugar_binary(env={}, profile="debug")

    message = str(excinfo.value)
    assert "did not resolve a debug sugar binary within 600s" in message
    assert "SUGAR_BINARY_ALLOW_BUILD=0" in message
    assert isinstance(excinfo.value.__cause__, subprocess.TimeoutExpired)


def test_resolution_timeout_budget_is_overridable(monkeypatch) -> None:
    from sugar_lift_py_tests import sugar_binary

    seen: list[float] = []

    def fake_run(command, **kwargs):
        seen.append(kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0, "/tmp/sugar\n", "")

    monkeypatch.setattr(sugar_binary.platform, "node", lambda: "MapLaptop")
    monkeypatch.setattr(sugar_binary, "subprocess_run", fake_run)

    sugar_binary.resolve_sugar_binary(
        env={"SUGAR_BINARY_RESOLVE_TIMEOUT_SECONDS": "45"}
    )

    assert seen == [45.0]


def test_resolution_timeout_budget_refuses_nonsense(monkeypatch) -> None:
    from sugar_lift_py_tests import sugar_binary

    for raw in ("0", "-1", "soon"):
        with pytest.raises(sugar_binary.SugarBinaryResolutionError):
            sugar_binary.resolve_timeout_seconds(
                {"SUGAR_BINARY_RESOLVE_TIMEOUT_SECONDS": raw}
            )

    assert (
        sugar_binary.resolve_timeout_seconds({})
        == sugar_binary.DEFAULT_RESOLVE_TIMEOUT_SECONDS
    )
