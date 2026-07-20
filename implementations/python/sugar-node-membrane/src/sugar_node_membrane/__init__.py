"""sugar-node-membrane: the node membrane, standalone (#5940).

Source text in, constructed graph out. A pure function. The class
hierarchy is the grammar; spans are ours; providers plug in behind a
read-only adapter; every node is Typed at construction; every site is
interned once. Nothing here imports from, or is imported by, the existing
tree — greenfield by design.
"""

from .backend import ProviderRefused
from .construct import Membrane, NodePool
from .nodes import KIND_REGISTRY, SourceFragment, SourceUnit, Typeable, Typed
from .panic import MembraneMissing, MembranePanic, MembraneProviderDefect
from .spans import LineColSpan, LineTable, Span

__all__ = [
    "KIND_REGISTRY",
    "LineColSpan",
    "LineTable",
    "Membrane",
    "MembraneMissing",
    "MembranePanic",
    "MembraneProviderDefect",
    "NodePool",
    "ProviderRefused",
    "SourceFragment",
    "SourceUnit",
    "Span",
    "Typeable",
    "Typed",
]
