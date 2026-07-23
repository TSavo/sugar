"""Python source lifter for Sugar.

The source tree depends on the package's SourceOracle.  Keep public lifter
exports lazy so importing that lower-layer oracle cannot initialize the
consumer lifter and form a cycle back through ``sugar_source_tree``.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .compiler import compile_ir_document
    from .lifter import LiftResult, lift_paths, lift_source

__all__ = ["LiftResult", "compile_ir_document", "lift_paths", "lift_source"]


def __getattr__(name: str):
    if name == "compile_ir_document":
        from .compiler import compile_ir_document

        return compile_ir_document
    if name in {"LiftResult", "lift_paths", "lift_source"}:
        from . import lifter

        return getattr(lifter, name)
    raise AttributeError(name)
