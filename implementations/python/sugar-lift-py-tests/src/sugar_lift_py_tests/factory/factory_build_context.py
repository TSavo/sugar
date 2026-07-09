from __future__ import annotations

# Leaf import (not package __init__) — avoids the context↔factory cycle
# when factory/__init__ loads build while context is still initializing.
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext

__all__ = ["FactoryBuildContext"]
