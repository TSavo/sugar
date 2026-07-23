from __future__ import annotations

from dataclasses import dataclass, field
from sugar_lift_python_source.canonical import cid_of_json
from sugar_source_tree.binding_provenance import BindingCoordinateV1

from .context_manager_resolution import SourceFragmentCoordinateV1


@dataclass(frozen=True)
class SourceVisibleCallFrameV1:
    """A body constructed by FunctionDef through the ordinary tree door."""

    source_identity_cid: str
    definition_site: SourceFragmentCoordinateV1
    definition_fragment_cid: str
    parameters: tuple[str, ...]
    formal_coordinates: tuple[BindingCoordinateV1, ...]
    parameter_kinds: tuple[str, ...]
    default_sugars: tuple[object | None, ...] = field(compare=False)
    default_fragments: tuple[object | None, ...] = field(compare=False)
    default_fragment_cids: tuple[str | None, ...]
    body: object = field(compare=False)
    frame_cid: str = field(init=False)

    def __post_init__(self) -> None:
        preimage = {
            "kind": "source-visible-call-frame",
            "schemaVersion": "1",
            "sourceIdentityCid": self.source_identity_cid,
            "definitionSite": self.definition_site.wire(),
            "definitionFragmentCid": self.definition_fragment_cid,
            "parameters": list(self.parameters),
            "formalCoordinates": [item.wire() for item in self.formal_coordinates],
            "parameterKinds": list(self.parameter_kinds),
            "defaultFragmentCids": list(self.default_fragment_cids),
        }
        object.__setattr__(self, "frame_cid", cid_of_json(preimage))

    def bind_actuals(self, positional: tuple, keywords: tuple, ctx=None) -> tuple:
        from sugar_lift_py_tests.floor import DictValue, StringValue, TupleValue

        remaining = list(positional)
        named = dict(keywords)
        if len(named) != len(keywords):
            raise SourceCallBindingGap("duplicate keyword actual")
        bound = []
        for index, (name, kind, default) in enumerate(
            zip(
                self.parameters,
                self.parameter_kinds,
                self.default_sugars,
                strict=True,
            )
        ):
            if kind == "vararg":
                bound.append(TupleValue(tuple(remaining)))
                remaining.clear()
                continue
            if kind == "kwarg":
                bound.append(
                    DictValue(
                        tuple((StringValue(key), value) for key, value in named.items())
                    )
                )
                named.clear()
                continue
            value = None
            present = False
            if kind in {"positional_only", "positional_or_keyword"} and remaining:
                value = remaining.pop(0)
                present = True
                if name in named:
                    raise SourceCallBindingGap("formal received positional and keyword")
            elif kind != "positional_only" and name in named:
                value = named.pop(name)
                present = True
            if not present and default is not None:
                from sugar_lift_py_tests.outcome import Complete

                outcome = default.desugar(ctx)
                if not isinstance(outcome, Complete):
                    raise SourceCallBindingGap("default did not construct completely")
                value = outcome.value
                present = True
            if not present:
                raise SourceCallBindingGap(f"missing required formal {index}")
            bound.append(value)
        if remaining or named:
            raise SourceCallBindingGap("unconsumed call actual")
        return tuple(bound)


class SourceCallBindingGap(ValueError):
    pass


SourceCallFrameV1 = SourceVisibleCallFrameV1
