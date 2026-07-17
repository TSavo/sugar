#!/usr/bin/env python3
"""Re-measure #4013 live isolation residual: R_live_factory_panic_files.

Runs the production per-file isolation path over assert-bearing files of an
installed package (default: numpy), ranks FactoryPanic fronts with the shared
fingerprint axes, and optionally writes a JSON receipt.

Examples (from sugar-lift-py-tests, with src on PYTHONPATH)::

  python scripts/live_factory_panic_isolation.py --package numpy \\
    --out /tmp/numpy-live-isolation.json

  SUGAR_4013_LIMIT=5 python scripts/live_factory_panic_isolation.py  # smoke

This does not convert panics to RuntimeEffect. TemporalContext / RuntimeEffect
construction belongs to dedicated floor lanes; this script only measures.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_PKG_ROOT = _SCRIPTS.parent
_SRC = _PKG_ROOT / "src"
_SOURCE_SRC = _PKG_ROOT.parent / "sugar-lift-python-source" / "src"
for _path in (_SRC, _SOURCE_SRC):
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from sugar_lift_py_tests.idd.collect_panic_audit import (  # noqa: E402
    _resolve_installed_package_path,
)
from sugar_lift_py_tests.idd.live_factory_panic_isolation import (  # noqa: E402
    assert_bearing_py_files,
    live_per_file_isolation_conservation,
    write_isolation_receipt,
)


def _git_head(cwd: Path) -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=cwd,
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure R_live_factory_panic_files via per-file isolation"
    )
    parser.add_argument(
        "--package",
        default=os.environ.get("SUGAR_4013_PACKAGE", "numpy"),
        help="Installed package name (default: numpy)",
    )
    parser.add_argument(
        "--out",
        default=os.environ.get("SUGAR_4013_ISOLATION_OUT")
        or os.environ.get("SUGAR_4013_OUT"),
        help="Write ranked JSON receipt to this path",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.environ["SUGAR_4013_LIMIT"])
        if os.environ.get("SUGAR_4013_LIMIT")
        else None,
        help="Optional cap on assert-bearing files (smoke)",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=10,
        help="Progress print interval (0 disables)",
    )
    args = parser.parse_args(argv)

    path = _resolve_installed_package_path(args.package)
    if not path.exists():
        print(f"error: package not installed at {path}", file=sys.stderr)
        return 2
    if path.is_file():
        files = [path]
        root = path.parent
    else:
        root = path
        files = assert_bearing_py_files(root)
    if args.limit is not None:
        files = files[: args.limit]
    if not files:
        print(f"error: no assert-bearing files under {path}", file=sys.stderr)
        return 2

    print(
        f"package={args.package} root={root} assert_files={len(files)}",
        flush=True,
    )
    meta = {
        "git_head": os.environ.get("SUGAR_GIT_HEAD") or _git_head(_PKG_ROOT),
        "instrument": "live_factory_panic_isolation",
        "package_path": str(path),
    }
    result = live_per_file_isolation_conservation(
        files,
        root=root,
        package=args.package,
        progress_every=args.progress_every,
        meta=meta,
    )
    if args.out:
        written = write_isolation_receipt(result, args.out)
        print(f"wrote {written}", flush=True)

    print("top exact_fronts:", flush=True)
    for row in result["exact_fronts"][:15]:
        print(f"  {row['count']}× {row['label']}", flush=True)

    if int(result["delta"]) != 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
