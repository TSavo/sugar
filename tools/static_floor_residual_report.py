#!/usr/bin/env python3
"""Seal the static-floor outcome partition behind the universal witness door."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
from sugar_repo_root import resolve_repo_root  # noqa: E402

ROOT = resolve_repo_root()
PACKAGE_SRC = ROOT / "implementations/python/sugar-lift-py-tests/src"
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from sugar_lift_py_tests.conservation_mint import (  # noqa: E402
    ConservationFailure,
    seal_after_validation,
)


def mint_static_residual(
    *,
    input_axes: list[str],
    green_axes: list[str],
    red_axes: list[str],
) -> tuple[dict, int]:
    input_manifest = [{"axis": axis} for axis in input_axes]
    output_manifest = [{"axis": axis} for axis in [*green_axes, *red_axes]]
    payload = {
        "kind": "floor-residual-v1",
        "residualKey": "R_static_sole_construction",
        "residualCount": len(red_axes),
        "greenAxes": len(green_axes),
        "redAxes": len(red_axes),
        "inputKeyManifest": input_manifest,
        "outputKeyManifest": output_manifest,
    }

    def validate() -> None:
        if not input_axes:
            raise ValueError("static floor input axis roster is empty")
        if len(input_axes) != len(set(input_axes)):
            raise ValueError("static floor input axis roster contains duplicates")
        if Counter(input_axes) != Counter([*green_axes, *red_axes]):
            raise ValueError("static floor outcomes do not conserve the axis roster")

    outcome = seal_after_validation(
        measured_payload=payload,
        input_key_manifest=input_manifest,
        output_key_manifest=output_manifest,
        validator_stage_id="static-sole-construction.axis-outcome-partition/v1",
        validator_source_path=Path(__file__).resolve(),
        validate=validate,
    )
    if isinstance(outcome, ConservationFailure):
        body = outcome.to_wire()
        body.update(
            {
                "kind": "floor-unmeasured-v1",
                "residualKey": "R_static_sole_construction",
                "residualCount": None,
                "unmeasurableReasons": [outcome.reason],
            }
        )
        return body, 1
    return outcome.to_wire(), 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--input-axis", action="append", default=[])
    parser.add_argument("--green-axis", action="append", default=[])
    parser.add_argument("--red-axis", action="append", default=[])
    args = parser.parse_args(argv)
    body, code = mint_static_residual(
        input_axes=args.input_axis,
        green_axes=args.green_axis,
        red_axes=args.red_axis,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"static_floors residual_written path={args.out} "
        f"measurement={body.get('measurement')} "
        f"residualCount={body.get('residualCount')}",
        flush=True,
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
