"""The one speller of a call coordinate: ``call:<target_symbol>``.

Every call term, call edge and call bridge symbol is spelled here, and every
reader that asks which target a call symbol names reads it back here. No other
site formats or slices the ``call:`` prefix.
"""

from __future__ import annotations

_CALL = "call:"


def call_symbol(target_symbol: str) -> str:
    """The call coordinate of ``target_symbol``: ``call:<target_symbol>``."""
    return _CALL + target_symbol


def call_target(symbol: str) -> str | None:
    """The target symbol a call coordinate names, or ``None`` if ``symbol``
    is not a call coordinate."""
    if symbol.startswith(_CALL):
        return symbol[len(_CALL) :]
    return None
