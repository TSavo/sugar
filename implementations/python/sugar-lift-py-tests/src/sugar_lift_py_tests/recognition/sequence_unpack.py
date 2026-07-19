from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecognizedSequenceTarget:
    """A finite, name-rooted sequence assignment target."""

    name: str | None = None
    children: tuple["RecognizedSequenceTarget", ...] = ()


@dataclass(frozen=True)
class SequenceUnpackRecognition:
    targets: tuple[RecognizedSequenceTarget, ...]
    star_index: int | None


class SequenceUnpackRecognizer:
    """Recognize finite nested targets owned by SequenceUnpackAssignSugar."""

    @classmethod
    def assignment(cls, site) -> SequenceUnpackRecognition | None:
        if site.observed != "Assign":
            return None
        assignments = site.assign_targets()
        if len(assignments) != 1 or assignments[0].observed not in {"Tuple", "List"}:
            return None
        target = assignments[0]
        elements = cls._elements(target)
        starred = [
            index
            for index, element in enumerate(elements)
            if element.observed == "Starred"
        ]
        if target.observed == "Tuple" and not starred:
            return None
        if not elements or len(starred) > 1:
            return None

        targets: list[RecognizedSequenceTarget] = []
        for element in elements:
            candidate = (
                element.starred_value() if element.observed == "Starred" else element
            )
            recognized = cls._target(candidate)
            if recognized is None:
                return None
            targets.append(recognized)

        if not cls._literal_arity_can_match(
            site.assign_value(), len(elements), starred
        ):
            return None
        return SequenceUnpackRecognition(
            tuple(targets),
            starred[0] if starred else None,
        )

    @classmethod
    def _target(cls, target) -> RecognizedSequenceTarget | None:
        if target.observed == "Name":
            return RecognizedSequenceTarget(name=target.name_id())
        if target.observed not in {"Tuple", "List"}:
            return None
        elements = cls._elements(target)
        if not elements:
            return None
        children: list[RecognizedSequenceTarget] = []
        for element in elements:
            # Nested starred targets are a distinct, still-unowned shape.
            if element.observed == "Starred":
                return None
            recognized = cls._target(element)
            if recognized is None:
                return None
            children.append(recognized)
        return RecognizedSequenceTarget(children=tuple(children))

    @staticmethod
    def _elements(target):
        return target.tuple_elts() if target.observed == "Tuple" else target.list_elts()

    @classmethod
    def _literal_arity_can_match(
        cls, value, target_count: int, starred: list[int]
    ) -> bool:
        if value.observed not in {"Tuple", "List"}:
            return True
        values = cls._elements(value)
        return (
            len(values) >= target_count - 1 if starred else len(values) == target_count
        )
