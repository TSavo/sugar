from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from .collect_dunder_frontier import collect_dunder_frontier
from .collect_panic_audit import collect_panic_audit
from .collect_temporal_dispatch_frontier import collect_temporal_dispatch_frontier
from .render_dunder_frontier import render_text as render_dunder_text
from .render_panic_audit import render_text
from .render_temporal_dispatch_frontier import (
    render_text as render_temporal_dispatch_text,
)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--installed-package",
        action="append",
        default=[],
        help="also audit an installed Python package by import name, e.g. numpy",
    )
    parser.add_argument(
        "--no-showcases",
        action="store_true",
        help="only run explicitly requested audit targets",
    )
    parser.add_argument(
        "--dunder-frontier",
        action="store_true",
        help="audit tracked Python data-model dunder slots instead of panic targets",
    )
    parser.add_argument(
        "--temporal-dispatch-frontier",
        action="store_true",
        help="audit temporal curry/rewrite side doors instead of panic targets",
    )
    args = parser.parse_args(argv)

    if args.temporal_dispatch_frontier:
        report = collect_temporal_dispatch_frontier(Path(args.root))
        if args.json:
            print(json.dumps(report.to_json(), sort_keys=True, indent=2))
        else:
            print(render_temporal_dispatch_text(report), end="")
        return 0 if report.is_zero else 1

    if args.dunder_frontier:
        report = collect_dunder_frontier(Path(args.root))
        if args.json:
            print(json.dumps(report.to_json(), sort_keys=True, indent=2))
        else:
            print(render_dunder_text(report), end="")
        return 0 if report.is_zero else 1

    report = collect_panic_audit(
        Path(args.root),
        installed_packages=tuple(args.installed_package),
        include_showcases=not args.no_showcases,
    )
    if args.json:
        print(json.dumps(report.to_json(), sort_keys=True, indent=2))
    else:
        print(render_text(report), end="")
    return 0 if report.is_zero else 1


if __name__ == "__main__":
    raise SystemExit(main())
