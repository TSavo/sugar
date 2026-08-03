# SPDX-License-Identifier: MIT OR Apache-2.0
"""Pin this package's sources to THIS checkout before anything imports them.

Without the pin these tests resolve whatever editable install happens to be on
the machine -- which in practice pointed at another worktree entirely. That
does not fail; it passes about the wrong code. See tests/checkout_resolution.py.
"""

import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = _HERE
while _ROOT != os.path.dirname(_ROOT) and not (
    os.path.isdir(os.path.join(_ROOT, "implementations"))
    and os.path.isdir(os.path.join(_ROOT, "tests"))
):
    _ROOT = os.path.dirname(_ROOT)
if os.path.join(_ROOT, "tests") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "tests"))

from checkout_resolution import pin_checkout  # noqa: E402

pin_checkout(__file__, siblings=("sugar-lift-python-source",))


def oracle_source_file(source: str, backend=None, suffix: str = ".py"):
    """Test door that honors the law: text enters only through the oracle.

    Writes the literal to a real file and constructs the SourceFile through
    the oracle's path-addressed identity — there is no raw-string door to
    bypass, in tests or anywhere else.
    """
    from sugar_source_tree.tree import SourceFile

    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=suffix, delete=False
    ) as handle:
        handle.write(source)
        path = handle.name
    return SourceFile.from_path(path, backend=backend)
