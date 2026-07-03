#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _first_diagnostic_line(text: str) -> str:
    for line in text.splitlines():
        clean = ANSI.sub("", line).strip()
        if clean:
            return clean[:240]
    return "<empty output>"


def load_receipt(path: Path | str) -> Any:
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"{path}: missing JSON receipt")
    text = path.read_text(encoding="utf-8", errors="replace")
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return value
    raise SystemExit(
        f"{path}: expected JSON receipt, got non-JSON output: "
        f"{_first_diagnostic_line(text)}"
    )


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "usage: json_get.py <receipt-path> <python-expression-over-d>",
            file=sys.stderr,
        )
        return 2
    path = Path(sys.argv[1])
    d = load_receipt(path)
    value = eval(
        sys.argv[2],
        {
            "__builtins__": {
                "all": all,
                "any": any,
                "bool": bool,
                "int": int,
                "len": len,
                "str": str,
                "sum": sum,
            }
        },
        {"d": d},
    )
    print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
