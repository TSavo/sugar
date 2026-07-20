"""sugar-source-tree: a parser and a source tree (#5940).

Strongly typed objects that enumerate strongly typed children, delegating
to a swappable backend:

    SourceTree   enumerates ->  SourceFile
    SourceFile   enumerates ->  its nodes
    Node         enumerates ->  its children

The class hierarchy is the grammar; spans are ours; backends plug in
behind a read-only adapter; every node is Typed at construction. Nothing
above an adapter names a backend library or receives a backend-native
object. No caching anywhere: a ``SourceFile`` holding its parsed tree IS
the file.
"""

from .backend import Backend, BackendRefused
from .nodes import KIND_REGISTRY, Node, SourceUnit, Typeable, Typed
from .panic import BackendDefect, SourceTreePanic, VocabularyMissing
from .spans import LineColSpan, LineTable, Span
from .tree import SourceFile, SourceTree

__all__ = [
    "Backend",
    "BackendDefect",
    "BackendRefused",
    "KIND_REGISTRY",
    "LineColSpan",
    "LineTable",
    "Node",
    "SourceFile",
    "SourceTree",
    "SourceTreePanic",
    "SourceUnit",
    "Span",
    "Typeable",
    "Typed",
    "VocabularyMissing",
]
