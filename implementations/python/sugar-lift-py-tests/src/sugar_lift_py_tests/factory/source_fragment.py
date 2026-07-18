"""Compatibility import for the source grammar gateway.

`SourceFragment` is structural source vocabulary, not a factory behavior
constructor. New code should import it from `sugar_lift_py_tests.source_fragment`.
"""

from sugar_lift_py_tests.source_fragment import InitializerCallSite, SourceFragment

__all__ = ["InitializerCallSite", "SourceFragment"]
