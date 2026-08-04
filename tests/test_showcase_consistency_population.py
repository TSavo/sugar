"""Population teeth for substantive showcase consistency rows."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "showcase"))

from json_get import is_substantive_consistency_row  # noqa: E402


def _row(prop: str) -> dict[str, str]:
    return {"property": prop, "status": "refused"}


def test_panic_callsite_support_is_not_a_substantive_claim() -> None:
    assert not is_substantive_consistency_row(
        _row("consistency:method:contains#panic_callsite#euf#support::assertion")
    )
    assert is_substantive_consistency_row(
        _row("consistency:method:contains#euf#claim::assertion")
    )


def test_non_test_consistency_rows_stay_outside_the_population() -> None:
    assert not is_substantive_consistency_row(
        _row("consistency:rust-source::core::str")
    )
    assert not is_substantive_consistency_row(
        _row("consistency:witness-package:blake3-512:abc")
    )
    assert not is_substantive_consistency_row(_row("not-consistency:anything"))
