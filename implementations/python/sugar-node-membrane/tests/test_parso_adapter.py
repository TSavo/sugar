"""parso adapter smoke tests (#5940, #5932).

No cross-provider CID comparison here (out of scope — see differential.py
and the #5940/#5932 ruling that different parsers are not expected to
agree on addresses). These tests only establish: the adapter constructs a
representative sample without crashing, and the one hard, load-bearing
finding — parso 0.8's shipped grammar has NO match/case support at all — is
pinned as an explicit, named result rather than an unexplained failure.
"""

import pytest

parso = pytest.importorskip("parso")

from pathlib import Path

from sugar_node_membrane import Membrane
from sugar_node_membrane.panic import MembranePanic
from sugar_node_membrane.parso_adapter import ParsoProvider

GOLDENS = Path(__file__).resolve().parents[1] / "goldens"


def _membrane() -> Membrane:
    return Membrane(ParsoProvider())


def test_constructs_a_representative_sample():
    source = '''
import os
from typing import Optional, List


class Point:
    """A point."""

    def __init__(self, x: int, y: int = 0, *args, z: float = 1.0, **kwargs) -> None:
        self.x = x
        self.y = y

    def norm(self) -> float:
        return (self.x ** 2 + self.y ** 2) ** 0.5

    @property
    def as_tuple(self):
        return (self.x, self.y)


async def fetch(urls: List[str]) -> Optional[dict]:
    out = {}
    async with open_session() as session:
        for i, u in enumerate(urls):
            try:
                out[u] = await session.get(u)
            except (ValueError, KeyError) as e:
                raise RuntimeError("bad") from e
            finally:
                pass
    return out if out else None


def gen():
    yield from range(10)
    x = [i * 2 for i in range(5) if i % 2 == 0]
    y = {k: v for k, v in zip(x, x)}
    z = (a for a in x)
    return x, y, z


result = f"{gen()!r}"
'''
    root = _membrane().parse(source, filename="sample.py")
    assert len(list(root.walk())) > 20


def test_match_statement_is_not_supported_by_parso_080_grammar():
    """The load-bearing finding: parso's shipped grammar311/312/etc. has no
    match_stmt/case_block productions at all (verified by grepping the
    grammar text files directly). This is not an adapter gap — there is no
    tree to translate. A source using `match` refuses to parse."""
    source = "match x:\n    case 0:\n        pass\n"
    with pytest.raises(SyntaxError):
        _membrane().parse(source, filename="match.py")


def test_quirks_golden_fails_on_the_known_match_gap():
    source = (GOLDENS / "quirks.py").read_text(encoding="utf-8")
    with pytest.raises(SyntaxError):
        _membrane().parse(source, filename="quirks.py")


def test_fstring_format_spec_is_a_known_adapter_gap():
    """Documented, not silently worked around: an f-string WITH a format
    spec (``f"{x!r:>10}"``) panics in this adapter today. parso's own
    ``fstring_format_spec`` node mixes literal spec characters in with
    the containing fstring_expr's own children in a shape this adapter's
    ``_fstring_values``/``_describe_fstring_expr`` do not yet parse
    correctly — real coverage gap, tracked here rather than guessed at."""
    with pytest.raises(MembranePanic):
        _membrane().parse('x = f"{y!r:>10}"\n', filename="fspec.py")
