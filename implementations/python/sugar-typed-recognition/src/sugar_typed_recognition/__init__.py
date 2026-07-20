"""sugar-typed-recognition: the typed recognition layer (#5940).

``accepts`` narrows the node shape, by type. ``owns`` interrogates the
operand types, which arrive already ``Typed`` from their own construction.
The catalog resolves the two together — registry-based multiple dispatch —
to exactly one claim, or it panics. Two arms, never three.

Built against ``sugar-node-membrane`` and nothing else in the tree;
greenfield beside the legacy ``claim/sugar_catalog.py`` +
``factory/build.py``, which are untouched.
"""

from .catalog import TypedCatalog
from .claim import TypedClaim, operand_types
from .claims import PORTED_CLAIMS
from .panic import RecognitionArm, RecognitionPanic
from .role import Role

__all__ = [
    "PORTED_CLAIMS",
    "RecognitionArm",
    "RecognitionPanic",
    "Role",
    "TypedCatalog",
    "TypedClaim",
    "operand_types",
    "default_catalog",
]


def default_catalog() -> TypedCatalog:
    """The ported demonstration set. Not the full ~80 — proof of mechanism."""
    return TypedCatalog(PORTED_CLAIMS)
