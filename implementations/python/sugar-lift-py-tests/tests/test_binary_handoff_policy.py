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

from sugar_lift_py_tests.filename import cid_filename_stem

ROOT = Path(__file__).resolve().parents[4]
SUGARBIN = ROOT / "bin" / "sugarbin"
PY_KIT_ROOTS = (
    ROOT / "implementations" / "python" / "sugar-lift-py-tests",
    ROOT / "implementations" / "python" / "sugar-lift-python-source",
)
THIS_TEST = Path(__file__).resolve()
STAMP_RE = re.compile(r"^blake3-512:[0-9a-f]{128}$")


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

    rust_src = root / "implementations" / "rust" / "sugar-cli" / "src"
    rust_src.mkdir(parents=True)
    (root / "implementations" / "rust" / "Cargo.toml").write_text(
        '[workspace]\nmembers = ["sugar-cli"]\n',
        encoding="utf-8",
    )
    (root / "implementations" / "rust" / "Cargo.lock").write_text(
        "# fixture lock\n",
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


def test_sugarbin_skips_stale_local_and_pulls_matching_shelf(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    stale = target / "release" / "sugar"
    stale.parent.mkdir(parents=True)
    _write_fake_sugar(stale, "oldbadcafe")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/bin/sh\n"
        'if [ "$1 $2" = "release download" ]; then\n'
        "  pattern=''\n"
        "  out=''\n"
        '  while [ "$#" -gt 0 ]; do\n'
        '    case "$1" in\n'
        '      --pattern) pattern="$2"; shift 2 ;;\n'
        '      --dir) out="$2"; shift 2 ;;\n'
        "      *) shift ;;\n"
        "    esac\n"
        "  done\n"
        '  mkdir -p "$out"\n'
        "  cat > \"$out/$pattern\" <<'EOS'\n"
        "#!/bin/sh\n"
        'if [ "$1" = "version" ] && [ "$2" = "--json" ]; then\n'
        '  printf \'%s\\n\' \'{"name":"sugar","version":"0.1.0",'
        '"buildGitHead":"newfeedface","buildStamp":"newfeedface"}\'\n'
        "  exit 0\n"
        "fi\n"
        "exit 2\n"
        "EOS\n"
        '  chmod +x "$out/$pattern"\n'
        "  exit 0\n"
        "fi\n"
        'if [ "$1 $2" = "attestation verify" ]; then exit 1; fi\n'
        'echo unexpected gh "$@" >&2\n'
        "exit 2\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    cache = tmp_path / "cache"
    completed = _run_sugarbin(
        {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "SUGAR_BINARY_TARGET_ROOT": os.fspath(target),
            "SUGAR_BINARY_CACHE_DIR": os.fspath(cache),
            "SUGAR_BINARY_REPO": "TSavo/sugar",
            "SUGAR_BINARY_SOURCE_STAMP": "newfeedface",
            "SUGAR_BINARY_ALLOW_BUILD": "0",
        },
        "--profile",
        "release",
    )
    assert completed.returncode == 0, completed.stderr
    resolved = Path(completed.stdout.strip())
    assert resolved.parent == cache
    assert resolved.name.endswith("-release-newfeedface")
    assert "local target skipped: stale binary" in completed.stderr


def test_sugarbin_refuses_when_every_rung_is_exhausted(tmp_path: Path) -> None:
    target = tmp_path / "target"
    stale = target / "release" / "sugar"
    stale.parent.mkdir(parents=True)
    _write_fake_sugar(stale, "oldbadcafe")
    completed = _run_sugarbin(
        {
            "SUGAR_BINARY_TARGET_ROOT": os.fspath(target),
            "SUGAR_BINARY_SOURCE_STAMP": "newfeedface",
            "SUGAR_BINARY_ALLOW_BUILD": "0",
            "SUGAR_BINARY_NO_SHELF": "1",
        },
        "--profile",
        "release",
    )
    assert completed.returncode != 0
    assert "local target skipped: stale binary" in completed.stderr
    assert "no matching sugar binary for stamp newfeedface" in completed.stderr


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
    for tool in ("bash", "dirname", "git", "python3"):
        _link_required_tool(fake_bin, tool)

    completed = _run_fixture_sugarbin(
        script,
        {"PATH": os.fspath(fake_bin)},
        "--print-source-stamp",
    )

    assert completed.returncode != 0
    assert "crime=missing-blake3-tool" in completed.stderr
    assert "replacement=install b3sum" in completed.stderr


def test_sugarbin_publish_uploads_stamp_named_assets(tmp_path: Path) -> None:
    target = tmp_path / "target"
    binary = target / "release" / "sugar"
    binary.parent.mkdir(parents=True)
    stamp = "blake3-512:" + ("a" * 128)
    artifact_stamp = cid_filename_stem(stamp)
    _write_fake_sugar(binary, stamp)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    upload_log = tmp_path / "upload.log"
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/bin/sh\n"
        'if [ "$1 $2" = "repo view" ]; then echo TSavo/sugar; exit 0; fi\n'
        'if [ "$1 $2" = "api user" ]; then echo fake-publisher; exit 0; fi\n'
        'if [ "$1 $2" = "release view" ]; then\n'
        '  case "$*" in *"--json assets"*) exit 0 ;; esac\n'
        "  exit 0\n"
        "fi\n"
        'if [ "$1 $2" = "release upload" ]; then\n'
        f"  printf '%s\\n' \"$@\" > {os.fspath(upload_log)!r}\n"
        "  exit 0\n"
        "fi\n"
        'echo unexpected gh "$@" >&2\n'
        "exit 2\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    completed = _run_sugarbin(
        {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "SUGAR_BINARY_TARGET_ROOT": os.fspath(target),
            "SUGAR_BINARY_REPO": "TSavo/sugar",
            "SUGAR_BINARY_SOURCE_STAMP": stamp,
            "SUGAR_BINARY_ALLOW_BUILD": "0",
        },
        "--profile",
        "release",
        "--platform",
        "darwin-x86_64",
    )

    assert completed.returncode == 0, completed.stderr
    upload_args = upload_log.read_text(encoding="utf-8").splitlines()
    uploaded_paths = [
        arg
        for arg in upload_args
        if Path(arg).name.startswith(f"sugar-darwin-x86_64-release-{artifact_stamp}")
    ]
    assert [Path(arg).name for arg in uploaded_paths] == [
        f"sugar-darwin-x86_64-release-{artifact_stamp}",
        f"sugar-darwin-x86_64-release-{artifact_stamp}.metadata.json",
    ]
    assert all("#" not in arg and ":" not in Path(arg).name for arg in uploaded_paths)


def test_python_wrapper_delegates_to_sugarbin(tmp_path: Path, monkeypatch) -> None:
    from sugar_lift_py_tests import sugar_binary

    fake = tmp_path / "sugarbin"
    resolved = tmp_path / "sugar"
    fake.write_text(
        f"#!/bin/sh\nprintf '%s\\n' {os.fspath(resolved)!r}\n", encoding="utf-8"
    )
    fake.chmod(0o755)
    monkeypatch.setattr(sugar_binary, "SUGARBIN", fake)
    assert sugar_binary.resolve_sugar_binary() == resolved


def test_witness_harness_resolves_sugar_once_for_parallel_callers(
    tmp_path: Path, monkeypatch
) -> None:
    from sugar_lift_py_tests import witness_harness

    resolved = tmp_path / "sugar"
    calls = 0
    lock = threading.Lock()
    start = threading.Event()
    monkeypatch.setattr(witness_harness, "_RESOLVED_SUGAR_BIN", None)

    def fake_resolve_sugar_binary(*, profile: str = "release"):
        nonlocal calls
        assert profile == "debug"
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
