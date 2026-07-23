from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_python_source.canonical import cid_of_json


@dataclass(frozen=True)
class AttributePlaceSelectorV1:
    name: str
    cid: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "cid", cid_of_json(self.preimage))

    @property
    def preimage(self):
        return {
            "kind": "attribute-place-selector",
            "schemaVersion": "1",
            "name": self.name,
        }

    def wire(self):
        return {**self.preimage, "cid": self.cid}


@dataclass(frozen=True)
class SubscriptPlaceSelectorV1:
    index_term_cid: str
    cid: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "cid", cid_of_json(self.preimage))

    @property
    def preimage(self):
        return {
            "kind": "subscript-place-selector",
            "schemaVersion": "1",
            "indexTermCid": self.index_term_cid,
        }

    def wire(self):
        return {**self.preimage, "cid": self.cid}


PlaceSelectorV1 = AttributePlaceSelectorV1 | SubscriptPlaceSelectorV1


def validate_place_selector(selector: PlaceSelectorV1) -> None:
    if not isinstance(selector, (AttributePlaceSelectorV1, SubscriptPlaceSelectorV1)):
        raise TypeError(f"unknown place selector {type(selector).__name__}")
    if cid_of_json(selector.preimage) != selector.cid:
        raise ValueError("place selector CID mismatch")
