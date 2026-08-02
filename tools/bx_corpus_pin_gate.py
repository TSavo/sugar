#!/usr/bin/env python3
"""Corpus pin gate for battleaxe timing measurements.

Exit codes:
  0  — observed corpus matches the declared pin (identity at minimum)
  78 — corpus pin mismatch or pin could not be established (not a measurement)

A wall-clock number against the wrong pandas is not a slow measurement — it is
not a measurement. System python on battleaxe has carried pandas 2.3.3
(1415 files) while the authenticated pin is 3.0.3 (1421). Five agents almost
reported numbers against the wrong corpus; this gate refuses before the walk.

Identity mode (default, cheap): distribution + version + file count.
Full mode (``--full``): also require aggregate hash via pin_corpus/require_pin.

Prints ``bx-corpus-pin phase=…`` lines on stderr so the receipt can carry the
pin next to the load/lease lines from the quiet brun wrapper.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

EXIT_PIN = 78

# Banked authenticated pin (docs/ledgers/pins/pandas-3.0.3.pin.json).
DEFAULT_PIN_REL = "docs/ledgers/pins/pandas-3.0.3.pin.json"
DEFAULT_DISTRIBUTION = "pandas"
DEFAULT_VERSION = "3.0.3"
DEFAULT_FILE_COUNT = 1421


def _eprint(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _venv_python_path(python: Path) -> Path:
    """Absolute path of the measurement interpreter WITHOUT following symlinks.

    ``.venv-py312/bin/python`` is a symlink onto the uv/Homebrew CPython
    binary. ``Path.resolve()`` follows that link and lands on the bare
    interpreter, which has no venv ``site-packages`` and therefore cannot
    import the pinned pandas (or worse: imports the wrong system one).
    Venv activation is keyed by the path used to *launch* the process, so
    we must pass the shim itself — only make it absolute via abspath.
    """
    return Path(os.path.abspath(python))


def _resolve_corpus_via_python(python: Path, distribution: str) -> Path:
    """Import distribution with *python* and return its package root."""
    # Do not resolve() the venv shim — see _venv_python_path.
    python = _venv_python_path(python)
    code = (
        "import importlib, pathlib, sys\n"
        f"m = importlib.import_module({distribution!r})\n"
        "print(pathlib.Path(m.__file__).resolve().parent)\n"
    )
    try:
        out = subprocess.check_output(
            [str(python), "-c", code],
            text=True,
            stderr=subprocess.STDOUT,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        _eprint(
            f"sugarbin: crime=corpus-pin-import-failed python={python} "
            f"distribution={distribution} detail={exc} "
            f"replacement=use .venv-py312/bin/python after "
            f"`bin/brun -- bash scripts/bootstrap-venv-py312.sh` "
            f"(system python often has the wrong pandas; never Path.resolve the "
            f"venv shim — that drops site-packages onto the bare uv interpreter)"
        )
        raise SystemExit(EXIT_PIN) from exc
    root = Path(out.strip())
    if not root.is_dir():
        _eprint(
            f"sugarbin: crime=corpus-pin-root-missing path={root} "
            f"replacement=install {distribution} into the measurement venv"
        )
        raise SystemExit(EXIT_PIN)
    return root


def _observe_identity(root: Path, distribution: str) -> tuple[str, int]:
    """Version from dist-info + file count from SourceTree (no content hash)."""
    # Prefer in-process if packages importable; else shell out is caller's job.
    try:
        from sugar_lift_py_tests.corpus_pin import (  # type: ignore
            CorpusPinDefect,
            distribution_version,
        )
        from sugar_source_tree.tree import SourceTree  # type: ignore
    except ImportError as exc:
        _eprint(
            f"sugarbin: crime=corpus-pin-imports-missing detail={exc} "
            f"replacement=set PYTHONPATH to sugar-lift-py-tests/src + "
            f"sugar-source-tree/src before the gate"
        )
        raise SystemExit(EXIT_PIN) from exc
    try:
        version = distribution_version(root, distribution)
        count = sum(1 for _ in SourceTree(root).paths())
    except CorpusPinDefect as defect:
        _eprint(str(defect))
        raise SystemExit(EXIT_PIN) from defect
    return version, count


def _observe_full(root: Path, distribution: str):
    from sugar_lift_py_tests.corpus_pin import CorpusPinDefect, pin_corpus  # type: ignore

    try:
        return pin_corpus(root, distribution=distribution)
    except CorpusPinDefect as defect:
        _eprint(str(defect))
        raise SystemExit(EXIT_PIN) from defect


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expected-pin",
        type=Path,
        default=None,
        help=f"banked sugar-corpus-pin/v1 JSON (default: {DEFAULT_PIN_REL})",
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=None,
        help="package root; default: import via --python",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=None,
        help="interpreter that must see the pinned corpus (prefer .venv-py312/bin/python)",
    )
    parser.add_argument(
        "--distribution",
        default=None,
        help="override distribution name (default: from pin or pandas)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="require aggregate hash match (slow: hashes every enrolled file)",
    )
    parser.add_argument(
        "--expected-version",
        default=None,
        help="override expected version when no pin file (tests)",
    )
    parser.add_argument(
        "--expected-file-count",
        type=int,
        default=None,
        help="override expected file count when no pin file (tests)",
    )
    parser.add_argument(
        "--observed-version",
        default=None,
        help="test double: skip live observe, use this version",
    )
    parser.add_argument(
        "--observed-file-count",
        type=int,
        default=None,
        help="test double: skip live observe, use this file count",
    )
    args = parser.parse_args(argv)

    expected_version = args.expected_version
    expected_count = args.expected_file_count
    expected_aggregate = ""
    distribution = args.distribution or DEFAULT_DISTRIBUTION
    pin_path = args.expected_pin

    if pin_path is None and expected_version is None:
        # Default banked pin relative to cwd (repo root on battleaxe).
        candidate = Path(DEFAULT_PIN_REL)
        if candidate.is_file():
            pin_path = candidate

    if pin_path is not None:
        if not pin_path.is_file():
            _eprint(
                f"sugarbin: crime=corpus-pin-file-missing path={pin_path} "
                f"replacement=use docs/ledgers/pins/pandas-3.0.3.pin.json from the repo"
            )
            return EXIT_PIN
        try:
            from sugar_lift_py_tests.corpus_pin import (  # type: ignore
                CorpusPinDefect,
                load_pin,
            )
        except ImportError as exc:
            _eprint(
                f"sugarbin: crime=corpus-pin-imports-missing detail={exc} "
                f"replacement=set PYTHONPATH before the gate"
            )
            return EXIT_PIN
        try:
            expected = load_pin(pin_path)
        except (OSError, ValueError, CorpusPinDefect, KeyError, TypeError) as exc:
            _eprint(
                f"sugarbin: crime=corpus-pin-unreadable path={pin_path} detail={exc}"
            )
            return EXIT_PIN
        distribution = args.distribution or expected.distribution
        expected_version = expected.version
        expected_count = expected.file_count
        expected_aggregate = expected.aggregate_hash
    else:
        expected_version = expected_version or DEFAULT_VERSION
        expected_count = (
            expected_count if expected_count is not None else DEFAULT_FILE_COUNT
        )

    if expected_version is None or expected_count is None:
        _eprint(
            "sugarbin: crime=corpus-pin-undeclared "
            "replacement=pass --expected-pin or --expected-version/--expected-file-count"
        )
        return EXIT_PIN

    # Test doubles: pure comparison without opening a corpus on the Mac.
    if args.observed_version is not None or args.observed_file_count is not None:
        if args.observed_version is None or args.observed_file_count is None:
            _eprint(
                "sugarbin: crime=corpus-pin-test-double-incomplete "
                "replacement=pass both --observed-version and --observed-file-count"
            )
            return EXIT_PIN
        root = args.corpus_root or Path("<test-double>")
        observed_version = args.observed_version
        observed_count = args.observed_file_count
        _eprint(
            f"sugarbin: bx-corpus-pin phase=check mode=identity-test-double "
            f"distribution={distribution} expected_version={expected_version} "
            f"expected_file_count={expected_count} "
            f"observed_version={observed_version} "
            f"observed_file_count={observed_count}"
        )
        failures: list[str] = []
        if observed_version != expected_version:
            failures.append(
                f"version: observed {observed_version!r} expected {expected_version!r}"
            )
        if observed_count != expected_count:
            failures.append(
                f"file_count: observed {observed_count} expected {expected_count}"
            )
        if failures:
            _eprint(
                "sugarbin: crime=corpus-pin-mismatch mode=identity "
                + "; ".join(failures)
                + f" replacement=use .venv-py312 with {distribution}=={expected_version} "
                f"(fileCount {expected_count}); system python on battleaxe has been "
                f"2.3.3/1415 — that is a different corpus, not a different speed"
            )
            return EXIT_PIN
        _eprint(
            f"sugarbin: bx-corpus-pin phase=ok mode=identity-test-double "
            f"distribution={distribution} version={observed_version} "
            f"file_count={observed_count}"
        )
        print(
            json.dumps(
                {
                    "kind": "bx-corpus-pin-ok",
                    "mode": "identity-test-double",
                    "distribution": distribution,
                    "version": observed_version,
                    "fileCount": observed_count,
                    "expectedAggregateHash": expected_aggregate or None,
                },
                sort_keys=True,
            )
        )
        return 0

    root = args.corpus_root
    if root is None:
        if args.python is None:
            _eprint(
                "sugarbin: crime=corpus-pin-no-root "
                "replacement=pass --corpus-root or --python (.venv-py312/bin/python)"
            )
            return EXIT_PIN
        # abspath only — never Path.resolve() on the venv python shim
        # (uv/Homebrew symlink follows into a bare interpreter with no
        # site-packages; that is crime=corpus-pin-import-failed against a
        # live 3.0.3 venv that would otherwise import cleanly).
        root = _resolve_corpus_via_python(args.python, distribution)
    root = root.resolve()

    _eprint(
        f"sugarbin: bx-corpus-pin phase=check "
        f"distribution={distribution} expected_version={expected_version} "
        f"expected_file_count={expected_count} "
        f"expected_aggregate={expected_aggregate or 'unset'} "
        f"root={root} full={int(bool(args.full))}"
    )

    if args.full and pin_path is not None:
        from sugar_lift_py_tests.corpus_pin import (  # type: ignore
            CorpusPinDefect,
            load_pin,
            require_pin,
        )

        observed = _observe_full(root, distribution)
        try:
            require_pin(load_pin(pin_path), observed)
        except CorpusPinDefect as defect:
            _eprint(str(defect))
            _eprint(
                f"sugarbin: crime=corpus-pin-mismatch mode=full "
                f"observed_version={observed.version} "
                f"observed_file_count={observed.file_count} "
                f"observed_aggregate={observed.aggregate_hash} "
                f"expected_version={expected_version} "
                f"expected_file_count={expected_count} "
                f"expected_aggregate={expected_aggregate} "
                f"replacement=use .venv-py312 with pandas=={expected_version} "
                f"(fileCount {expected_count}); never system python 2.3.3/1415"
            )
            return EXIT_PIN
        _eprint(
            f"sugarbin: bx-corpus-pin phase=ok mode=full "
            f"distribution={observed.distribution} version={observed.version} "
            f"file_count={observed.file_count} aggregate={observed.aggregate_hash} "
            f"root={observed.root}"
        )
        # Machine-readable one-liner for receipts.
        print(
            json.dumps(
                {
                    "kind": "bx-corpus-pin-ok",
                    "mode": "full",
                    "distribution": observed.distribution,
                    "version": observed.version,
                    "fileCount": observed.file_count,
                    "aggregateHash": observed.aggregate_hash,
                    "root": observed.root,
                },
                sort_keys=True,
            )
        )
        return 0

    # Identity mode: version + file count (catches 2.3.3/1415 vs 3.0.3/1421).
    observed_version, observed_count = _observe_identity(root, distribution)
    failures: list[str] = []
    if observed_version != expected_version:
        failures.append(
            f"version: observed {observed_version!r} expected {expected_version!r}"
        )
    if observed_count != expected_count:
        failures.append(
            f"file_count: observed {observed_count} expected {expected_count}"
        )
    if failures:
        _eprint(
            "sugarbin: crime=corpus-pin-mismatch mode=identity "
            + "; ".join(failures)
            + f" root={root} "
            f"replacement=use .venv-py312 with {distribution}=={expected_version} "
            f"(fileCount {expected_count}); system python on battleaxe has been "
            f"2.3.3/1415 — that is a different corpus, not a different speed"
        )
        return EXIT_PIN

    _eprint(
        f"sugarbin: bx-corpus-pin phase=ok mode=identity "
        f"distribution={distribution} version={observed_version} "
        f"file_count={observed_count} "
        f"expected_aggregate={expected_aggregate or 'unset'} "
        f"root={root}"
    )
    print(
        json.dumps(
            {
                "kind": "bx-corpus-pin-ok",
                "mode": "identity",
                "distribution": distribution,
                "version": observed_version,
                "fileCount": observed_count,
                "expectedAggregateHash": expected_aggregate or None,
                "root": str(root),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    # Allow focused unit tests to exercise without full package tree via env.
    if os.environ.get("BX_CORPUS_PIN_GATE_SELFTEST") == "1":
        raise SystemExit(0)
    raise SystemExit(main())
