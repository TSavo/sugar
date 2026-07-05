from __future__ import annotations

import ast
import os
import subprocess
import threading
import time
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SUGARBIN = ROOT / "bin" / "sugarbin"
PY_KIT_ROOTS = (
    ROOT / "implementations" / "python" / "sugar-lift-py-tests",
    ROOT / "implementations" / "python" / "sugar-lift-python-source",
)
THIS_TEST = Path(__file__).resolve()


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in PY_KIT_ROOTS:
        files.extend(path for path in root.rglob("*.py") if path != THIS_TEST)
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


def test_sugarbin_publish_uploads_stamp_named_assets(tmp_path: Path) -> None:
    target = tmp_path / "target"
    binary = target / "release" / "sugar"
    binary.parent.mkdir(parents=True)
    _write_fake_sugar(binary, "publishstamp")

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
            "SUGAR_BINARY_SOURCE_STAMP": "publishstamp",
        },
        "--profile",
        "release",
    )

    assert completed.returncode == 0, completed.stderr
    upload_args = upload_log.read_text(encoding="utf-8").splitlines()
    uploaded_paths = [
        arg
        for arg in upload_args
        if Path(arg).name.startswith("sugar-darwin-x86_64-release-publishstamp")
    ]
    assert [Path(arg).name for arg in uploaded_paths] == [
        "sugar-darwin-x86_64-release-publishstamp",
        "sugar-darwin-x86_64-release-publishstamp.metadata.json",
    ]
    assert all("#" not in arg for arg in uploaded_paths)


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
