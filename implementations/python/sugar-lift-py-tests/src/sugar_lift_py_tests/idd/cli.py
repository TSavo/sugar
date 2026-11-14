from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from .collect_dunder_frontier import collect_dunder_frontier
from .proofir_vocab_instruments import (
    collect_proofir_vocabulary_frontier,
    render_text as render_proofir_vocab_text,
)
from .render_dunder_frontier import render_text as render_dunder_text


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dunder-frontier",
        action="store_true",
        help="audit tracked Python data-model dunder slots",
    )
    mode.add_argument(
        "--proofir-vocab-frontier",
        action="store_true",
        help="audit raw ProofIR emission vocabulary sites",
    )
    args = parser.parse_args(argv)

    if args.proofir_vocab_frontier:
        report = collect_proofir_vocabulary_frontier(Path(args.root))
        if args.json:
            print(json.dumps(report.to_json(), sort_keys=True, indent=2))
        else:
            print(render_proofir_vocab_text(report), end="")
        return 0 if report.is_zero else 1

    report = collect_dunder_frontier(Path(args.root))
    if args.json:
        print(json.dumps(report.to_json(), sort_keys=True, indent=2))
    else:
        print(render_dunder_text(report), end="")
    return 0 if report.is_zero else 1
