#!/usr/bin/env python3
"""Sample N pandas files for the first construction panic per file.

Production open door only: ``open_source_file_for_construction`` with the
install root the distribution recorded seats against (``install_root_for``).

A prior walk rooted at the package directory (``.../site-packages/pandas``)
minted loci like ``_config/display.py``. RECORD seats are
``pandas/_config/display.py``. That is SourceUnavailable at the membrane —
instrument defect, not a construct residual ranking.

Schema: sample-construct-panic-walk/v2
  v2 = install_root_for open root (seat-authenticated).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
import traceback
from collections import Counter
from pathlib import Path
from typing import Any


def _pandas_root() -> Path:
    spec = importlib.util.find_spec("pandas")
    if spec is None or not spec.submodule_search_locations:
        raise SystemExit("pandas not importable — cannot sample")
    return Path(list(spec.submodule_search_locations)[0]).resolve()


def _workspace_root(package_root: Path) -> Path:
    from sugar_lift_python_source.source_oracle import install_root_for

    installed = install_root_for(str(package_root))
    return package_root if installed is None else Path(installed)


def _panic_fields(exc: BaseException) -> dict[str, Any]:
    """Project any loud construction failure into a stable row half."""
    if hasattr(exc, "info") and exc.info is not None:
        info = exc.info
        return {
            "panicType": type(exc).__name__,
            "panicOwner": getattr(info, "owner", None) or "?",
            "panicObserved": getattr(info, "observed", None),
            "panicRequested": getattr(info, "requested", None),
            "panicFix": getattr(info, "fix", None),
            "panicMessage": getattr(info, "message", None) or str(exc)[:500],
        }
    return {
        "panicType": type(exc).__name__,
        "panicOwner": getattr(exc, "owner", None) or "?",
        "panicObserved": getattr(exc, "observed", None),
        "panicRequested": getattr(exc, "requested", None),
        "panicFix": getattr(exc, "fix", None),
        "panicMessage": str(exc)[:500],
    }


def _origin() -> list[str]:
    frames: list[str] = []
    for fr in traceback.extract_stack(limit=12)[:-1]:
        frames.append(f"{fr.filename}:{fr.lineno} {fr.name}")
    return frames[-6:]


def _first_panic(
    path: Path,
    *,
    workspace_root: Path,
    contract_refs,
) -> dict[str, Any]:
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_lift_python_source.source_oracle import SourceUnavailable
    from sugar_source_tree.panic import SourceTreePanic
    from sugar_source_tree.reporter import CollectingReporter

    rel_pkg = path.name  # filled below if relative known
    try:
        rel_pkg = str(path.resolve().relative_to(workspace_root.resolve()))
    except ValueError:
        rel_pkg = path.name

    reporter = CollectingReporter()
    try:
        sf = open_source_file_for_construction(
            path,
            root=workspace_root,
            reporter=reporter,
            contract_refs=contract_refs,
            populate_derived=True,
        )
    except SourceUnavailable as exc:
        return {
            "file": rel_pkg,
            "functions": 0,
            "status": "open_panic",
            "origin": _origin(),
            **_panic_fields(exc),
        }
    except ConstructionPanic as exc:
        return {
            "file": rel_pkg,
            "functions": 0,
            "status": "open_panic",
            "origin": _origin(),
            **_panic_fields(exc),
        }
    except SourceTreePanic as exc:
        return {
            "file": rel_pkg,
            "functions": 0,
            "status": "open_panic",
            "origin": _origin(),
            **_panic_fields(exc),
        }
    except Exception as exc:  # noqa: BLE001 — sample membrane
        return {
            "file": rel_pkg,
            "functions": 0,
            "status": "open_panic",
            "origin": _origin(),
            **_panic_fields(exc),
        }

    functions = list(sf.functions())
    n = len(functions)
    for fn in functions:
        try:
            fn.sugar()
        except ConstructionPanic as exc:
            return {
                "file": rel_pkg,
                "functions": n,
                "status": "construct_panic",
                "origin": _origin(),
                **_panic_fields(exc),
            }
        except SourceTreePanic as exc:
            return {
                "file": rel_pkg,
                "functions": n,
                "status": "construct_panic",
                "origin": _origin(),
                **_panic_fields(exc),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "file": rel_pkg,
                "functions": n,
                "status": "construct_panic",
                "origin": _origin(),
                **_panic_fields(exc),
            }
    return {
        "file": rel_pkg,
        "functions": n,
        "status": "clean",
        "origin": None,
        "panicType": None,
        "panicOwner": None,
        "panicObserved": None,
        "panicRequested": None,
        "panicFix": None,
        "panicMessage": None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=80)
    parser.add_argument("--seed", type=int, default=7135)
    parser.add_argument("--out", type=Path, default=Path("/tmp/orange_sample_report_v2.json"))
    parser.add_argument(
        "--pandas-root",
        type=Path,
        default=None,
        help="Override pandas package root (default: importlib find)",
    )
    args = parser.parse_args(argv)

    package_root = (args.pandas_root or _pandas_root()).resolve()
    workspace_root = _workspace_root(package_root)
    files = sorted(
        p
        for p in package_root.rglob("*.py")
        if "__pycache__" not in p.parts and p.is_file()
    )
    if not files:
        raise SystemExit(f"no .py under {package_root}")

    rng = random.Random(args.seed)
    n = min(args.n, len(files))
    sample = rng.sample(files, n)

    from sugar_lift_py_tests.lift_rpc import provisional_contract_refs_from_demands

    # Demand table over the package tree (same tree the files live in).
    contract_refs = provisional_contract_refs_from_demands(package_root)

    rows: list[dict[str, Any]] = []
    for i, path in enumerate(sample, 1):
        row = _first_panic(
            path, workspace_root=workspace_root, contract_refs=contract_refs
        )
        rows.append(row)
        print(
            f"[{i}/{n}] {row['file']} {row['status']} fn={row['functions']} "
            f"type={row.get('panicType')} owner={row.get('panicOwner')}",
            flush=True,
        )

    report = {
        "schema": "sample-construct-panic-walk/v2",
        "seed": args.seed,
        "nRequested": args.n,
        "nSampled": n,
        "pandasRoot": str(package_root),
        "workspaceRoot": str(workspace_root),
        "rows": rows,
    }
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"wrote {args.out}", flush=True)

    status_c = Counter(r["status"] for r in rows)
    type_c = Counter(r["panicType"] for r in rows if r.get("panicType"))
    owner_c = Counter(r["panicOwner"] for r in rows if r.get("panicOwner"))
    summary = {
        "n": n,
        "status": dict(status_c),
        "clean": status_c.get("clean", 0),
        "panic": n - status_c.get("clean", 0),
        "functionsSum": sum(r["functions"] for r in rows),
        "panicType": type_c.most_common(30),
        "panicOwner": owner_c.most_common(40),
        "workspaceRoot": str(workspace_root),
        "pandasRoot": str(package_root),
    }
    summary_path = args.out.with_name(args.out.stem + "_summary.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)
    print(f"wrote {summary_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
