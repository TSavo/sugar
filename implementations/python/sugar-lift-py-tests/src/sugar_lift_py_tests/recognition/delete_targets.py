from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

from sugar_lift_py_tests.factory.node_kind import NodeKind

if TYPE_CHECKING:
    from sugar_lift_py_tests.source_fragment import SourceFragment


_DELETE = NodeKind("Delete")
_NAME = NodeKind("Name")
_ATTRIBUTE = NodeKind("Attribute")
_SUBSCRIPT = NodeKind("Subscript")
_TUPLE = NodeKind("Tuple")
_LIST = NodeKind("List")


class DeleteTargetKind(Enum):
    NAME = auto()
    ATTRIBUTE = auto()
    SUBSCRIPT = auto()


@dataclass(frozen=True)
class RecognizedDeleteTarget:
    kind: DeleteTargetKind
    target: SourceFragment


class DeleteTargetRecognition:
    """Factory-owned structural recognition for Python ``del`` targets."""

    @classmethod
    def statement_targets(cls, site) -> tuple[RecognizedDeleteTarget, ...] | None:
        if site.observed is not _DELETE:
            return None
        recognized: list[RecognizedDeleteTarget] = []
        for target in site.delete_targets():
            if not cls._append_target(target, recognized):
                return None
        return tuple(recognized) if recognized else None

    @classmethod
    def _append_target(cls, target, recognized) -> bool:
        kind = target.observed
        if kind is _NAME:
            recognized.append(RecognizedDeleteTarget(DeleteTargetKind.NAME, target))
            return True
        if kind is _ATTRIBUTE:
            recognized.append(
                RecognizedDeleteTarget(DeleteTargetKind.ATTRIBUTE, target)
            )
            return True
        if kind is _SUBSCRIPT:
            recognized.append(
                RecognizedDeleteTarget(DeleteTargetKind.SUBSCRIPT, target)
            )
            return True
        if kind is _TUPLE:
            children = target.tuple_elts()
        elif kind is _LIST:
            children = target.list_elts()
        else:
            return False
        return bool(children) and all(
            cls._append_target(child, recognized) for child in children
        )
