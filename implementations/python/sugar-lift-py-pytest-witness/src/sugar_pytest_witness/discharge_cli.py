# SPDX-License-Identifier: Apache-2.0
"""Witness discharge command — the verifier<->kit contract.

The Rust verifier stays language-blind: when it meets a contract carrying a
``custom`` witness EvidenceTerm it cannot recompute (it can't run Python), so it
SPAWNS this command (the same way it spawns z3/coq), and the kit — which owns the
runtime — settles the obligation BY RECOMPUTE.

Usage:
    sugar-pytest-witness-discharge <witness.proof> <project_dir>

The witness is self-describing about its code (project-relative paths), so only
the project root is needed.  Output (stdout): one JSON line
``{"verdict": "...", "reason": "..."}``.  Exit code: 0 iff DISCHARGED, 1
otherwise (fail-closed).
"""

from __future__ import annotations

import json
import sys
from typing import List

from .witness import discharge_from_proof


def main(argv: List[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        sys.stdout.write(
            json.dumps(
                {
                    "verdict": "REFUSED",
                    "reason": "usage: <witness.proof> <project_dir>",
                }
            )
            + "\n"
        )
        return 1
    proof_path, project_dir = argv[0], argv[1]
    try:
        verdict, reason = discharge_from_proof(proof_path, project_dir)
    except Exception as e:  # fail-closed: any error is a refusal, never a discharge
        sys.stdout.write(
            json.dumps({"verdict": "REFUSED", "reason": f"discharge error: {e}"}) + "\n"
        )
        return 1
    sys.stdout.write(json.dumps({"verdict": verdict, "reason": reason}) + "\n")
    return 0 if verdict == "DISCHARGED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
