"""``import a.b`` in a function is a binding the trace never mints an entry for.

The one import table rows nothing for the package ``a`` that ``import a.b``
binds (``SourceUnit.import_binding_reference``), so the import binds the name
to ``UNDECIDED_MODULE_BINDING``: every read keeps its own name and resolves
through the table at its own coordinate (``Name.substitute``).  A function
frame holds every local unbound until its body binds it
(``FunctionDef._body_scope``), so every function-local dotted import makes
that binding, and a function frame is the one frame with a substitution trace
(``SubstitutionTraceBuilderV1``).  ``_binding_entries`` wrapped the sentinel
as a runtime entry and its sealer raised ``BindingStateWireGap: unknown
runtime binding state object`` out of the whole file's discharge: five pandas
board files at 49413757d were ``instrument failure during residual``
(``io/common.py:275 urlopen``, ``io/parquet.py:163 __init__``,
``io/feather_format.py:81 read_feather``,
``core/arrays/sparse/scipy_sparse.py:143 sparse_series_to_coo``,
``tests/dtypes/test_common.py:213``).

The sentinel stays unwrapped in a function frame as the module threading
leaves it, so the file discharges.
"""

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def _report(tmp_path, source: str):
    path = tmp_path / "function_local_dotted_import.py"
    path.write_text(source)
    return discharge(
        SourceFile(
            path_source(str(path)),
            reporter=CollectingReporter(),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )


def _import_rows(entries):
    return [e for e in entries if e.kind == "ImportBindingRef"]


# ``pandas/io/common.py:275`` (pandas 3.0.3).
URLOPEN_SHAPE = (
    "def urlopen(*args, **kwargs):\n"
    "    import urllib.request\n"
    "\n"
    "    return urllib.request.urlopen(*args, **kwargs)\n"
)


def test_a_function_local_dotted_import_discharges(tmp_path):
    report = _report(tmp_path, URLOPEN_SHAPE)
    assert not _import_rows(report.minority), report.minority


# ``pandas/io/parquet.py:163`` (``PyArrowImpl.__init__``): the package read
# bare after two dotted imports of it.
PARQUET_SHAPE = (
    "def import_optional_dependency(name, extra=''):\n"
    "    return None\n"
    "\n"
    "class PyArrowImpl:\n"
    "    def __init__(self):\n"
    "        import_optional_dependency(\n"
    "            'pyarrow', extra='pyarrow is required for parquet support.'\n"
    "        )\n"
    "        import pyarrow.parquet\n"
    "\n"
    "        import pandas.core.arrays.arrow.extension_types\n"
    "\n"
    "        self.api = pyarrow\n"
)


def test_the_package_a_dotted_import_binds_is_read_bare(tmp_path):
    report = _report(tmp_path, PARQUET_SHAPE)
    assert not _import_rows(report.minority), report.minority


# ``pandas/tests/dtypes/test_common.py:206`` (``test_is_sparse``): the dotted
# import in an ``if`` arm.
IN_ONE_ARM_SHAPE = (
    "def test_is_sparse(check_scipy):\n"
    "    if check_scipy:\n"
    "        import scipy.sparse\n"
    "\n"
    "        assert scipy.sparse.bsr_matrix([1, 2, 3]) is not None\n"
)


def test_a_dotted_import_in_one_arm_discharges(tmp_path):
    report = _report(tmp_path, IN_ONE_ARM_SHAPE)
    assert not _import_rows(report.minority), report.minority
