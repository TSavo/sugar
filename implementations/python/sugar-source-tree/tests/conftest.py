# SPDX-License-Identifier: MIT OR Apache-2.0
"""Pin this package's sources to THIS checkout before anything imports them.

Without the pin these tests resolve whatever editable install happens to be on
the machine -- which in practice pointed at another worktree entirely. That
does not fail; it passes about the wrong code. See tests/checkout_resolution.py.
"""

import os
import sys
import tempfile

import pytest

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


@pytest.fixture(autouse=True)
def _isolate_process_resident_files():
    """One test, one residency (#7364). Cross-test sharing is unrepresentable.

    The process-resident file cache is keyed by (content CID, workspace-RELATIVE
    filename). Byte-identical fixture source written under the same relative
    name therefore collides across tests, and distinct ``tmp_path`` gives ZERO
    isolation. ``_prepare_uncached`` -- which runs MaterializeModule and builds
    the unit's relation tables -- is reached only on a residency MISS, so a
    second test inherits whatever unit state the first left behind.

    Both polarities of false signal follow, and the worse one is silent:

      false red   -- a neighbour is blamed for state an earlier test mutated;
      false GREEN -- a test that expects a refusal is handed a unit some earlier
                     test already put into the refusing state, and passes
                     without ever exercising its own mechanism. That green is
                     indistinguishable from a real one.

    The reset is autouse and unconditional: an opt-out marker would restore
    exactly the silent default this closes. Residency is a WITHIN-test property
    (prepare-count tests measure it inside one test body and already clear at
    entry), so nothing legitimately needs it to span the test boundary.

    Production behaviour is untouched. This is a test-boundary reset only; the
    protocol §4 cache remains the amortisation door for census/demand.
    """
    from sugar_source_tree.process_resident_file import clear_process_resident_files

    clear_process_resident_files()
    yield
    clear_process_resident_files()


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
