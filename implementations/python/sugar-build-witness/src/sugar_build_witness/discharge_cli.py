# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import sys
from typing import List

from .witness import discharge_from_proof


def main(argv: List[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        print(
            json.dumps(
                {"verdict": "REFUSED", "reason": "usage: <witness.proof> <project_dir>"}
            )
        )
        return 1
    try:
        verdict, reason = discharge_from_proof(args[0], args[1])
    except Exception as e:
        print(json.dumps({"verdict": "REFUSED", "reason": f"discharge error: {e}"}))
        return 1
    print(json.dumps({"verdict": verdict, "reason": reason}))
    return 0 if verdict == "DISCHARGED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
