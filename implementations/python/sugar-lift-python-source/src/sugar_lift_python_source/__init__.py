"""Python source package for Sugar.

The source tree depends on the package's SourceOracle.  Keep public exports
lazy so importing that lower-layer oracle cannot initialize a consumer and
form a cycle back through ``sugar_source_tree``.

There is no lifter here: a Python file becomes a proof one way, through the
node tree (``sugar_lift_py_tests``, ``sugar.enumerate``). The old whole-file
lifter (``lifter.py``) is deleted (#7767).
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .compiler import compile_ir_document

__all__ = ["compile_ir_document"]


def __getattr__(name: str):
    if name == "compile_ir_document":
        from .compiler import compile_ir_document

        return compile_ir_document
    raise AttributeError(name)
