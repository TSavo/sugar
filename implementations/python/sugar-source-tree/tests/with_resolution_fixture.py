"""Test-only driver: one source file opened under a construction context.

The context holds no table (#7757): a ``with`` constructs from its head
alone, so there is nothing to seat before construction.

The file is opened through the one door production opens every file by
(``open_source_file_for_construction``), rooted at its own isolated
directory, so every locus the tree states is workspace-relative, as a ground
exit's citation requires (``floor.ground_exit``): an ``assert``'s
``AssertionError``, a loop's bound, a ``raise``'s occurrence.  An absolute
``path_source`` seat is an address no checkout can re-read, and the ground
exits refuse it by name.
"""

from pathlib import Path
import shutil
import tempfile

from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_source_tree.reporter import CollectingReporter


def source_file_with_preconstruction(path):
    root = Path(tempfile.mkdtemp(prefix="sugar-with-resolution-"))
    isolated = root / Path(path).name
    shutil.copyfile(path, isolated)
    return open_source_file_for_construction(
        isolated, root=root, reporter=CollectingReporter()
    )
