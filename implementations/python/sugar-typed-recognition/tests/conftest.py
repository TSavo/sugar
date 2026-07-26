# SPDX-License-Identifier: MIT OR Apache-2.0
"""Pin this package's sources to THIS checkout before anything imports them.

NOTE: this package's tests import ``sugar_node_membrane``, which was REMOVED in
#5940/#5953 when the node membrane was replaced by sugar-source-tree. The
sibling path pinned here no longer exists, so these 26 test functions have been
uncollectable ever since -- the suite went smaller, not red. Pinning fixes
which checkout is measured; it does not resurrect a deleted package. Tracked
separately.
"""

import os
import sys

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

# Pin this package's sources to THIS checkout before anything imports them.
# Without the pin these tests resolve whatever editable install the machine
# happens to have -- which does not fail, it passes about the wrong code.
pin_checkout(__file__, siblings=())
