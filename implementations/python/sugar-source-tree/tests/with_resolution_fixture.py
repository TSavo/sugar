"""Test-only driver: one source file opened under a construction context.

The context holds no table (#7757): a ``with`` constructs from its head
alone, so there is nothing to seat before construction.
"""

from pathlib import Path
import shutil
import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile


def source_file_with_preconstruction(path):
    isolated = Path(tempfile.mkdtemp(prefix="sugar-with-resolution-")) / path.name
    shutil.copyfile(path, isolated)
    path = isolated
    return SourceFile(
        path_source(str(path)),
        construction_context=TreeConstructionContextV1(),
    )
