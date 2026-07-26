# SPDX-License-Identifier: MIT OR Apache-2.0
"""Put this tests directory on the path, as the sibling package already does.

Helpers that live next to test modules (``declared_corpus``) are only
importable if the directory holding them is importable. ``sugar-lift-py-tests``
does exactly this in its own conftest; without it here, a shared helper in this
package resolves as a collection error -- which shrinks the denominator instead
of turning anything red, the very failure mode the helper exists to close.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# This checkout's own sources, ahead of any editable install pointing at
# another worktree. Without it these tests measure a tree nobody is editing.
_SRC = os.path.normpath(os.path.join(_HERE, "..", "src"))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
