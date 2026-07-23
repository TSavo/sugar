# Golden quirk-shape corpus source. Every construct where providers
# actually differ on spans (spans.py spec) appears here at least once.
# This file is DATA: it is parsed by the membrane, never imported.
"""module docstring, and an implicit "concat" 'piece'."""

import os
import sys as system
from collections import OrderedDict as OD, defaultdict
from . import nothing  # noqa

é_unicode = "cols before this are two-byte in utf-8: é é é"
after_unicode = é_unicode.strip()

CONST: int = 3
a = b = 1, 2
c = (3, 4)
d = ()
a += 2
del c, d

s_implicit = "one " "two " "three"
s_f = f"pre {after_unicode!r:>10} post {CONST:{a}} end"
s_nested = f"outer {f'inner {CONST}'} done"
s_bytes = b"\x00" b"more"
s_u = "legacy"

numbers = [1, 2.5, 3j, 0x10, 0o7, 0b11, 1_000, ...]
mapping = {"k": 1, **{"j": 2}}
a_set = {1, 2, 3}

result = system.maxsize + (CONST * 2) - (-CONST)
shifted = (CONST << 2) | (CONST & 1) ^ (CONST >> 1)
divided = CONST / 2 // 1 % 2
powed = CONST**2
inverted = ~CONST
truthy = not CONST
chained = 0 < CONST <= 10 != 11
identity = CONST is not None and CONST in numbers or CONST not in numbers

comp_list = [x * 2 for x in numbers[:3] if x if x > 0]
comp_set = {x for x in range(3)}
comp_dict = {k: v for k, v in mapping.items() if k}
comp_gen = (x async for x in aiter) if False else (x for x in range(2))
nested_comp = [[y for y in range(x)] for x in range(3)]

fn = lambda p, q=1, *rest, kw_only=2, **extra: p + q
walrus_result = [(n := len(numbers)), n**2]

multi_call = OD(
    first=1,
    second=2,
)
star_call = print(*numbers[:2], **{"sep": ", "})
subscripted = numbers[0], numbers[1:2], numbers[::2], mapping["k"]
sliced = numbers[CONST : CONST + 1 : 1]


def plain(
    pos_only,
    /,
    normal,
    with_ann: int,
    with_def="d",
    *args,
    kw1,
    kw2: float = 2.0,
    **kwargs,
) -> str:
    """doc"""
    global CONST
    x: list = []
    for item in args:
        if item:
            continue
        elif not item:
            break
    else:
        pass
    while False:
        pass
    try:
        raise ValueError("boom") from None
    except (TypeError, ValueError) as err:
        return str(err)
    except Exception:
        raise
    else:
        pass
    finally:
        del x
    with open("f") as fh, open("g"):
        fh.read()
    if walrus_result:
        nonlocal_probe = 1

        def inner():
            nonlocal nonlocal_probe
            nonlocal_probe = 2

        inner()
    assert CONST, "message"
    return "done"


@system.intern
@plain(1, normal=2, with_ann=3)
def decorated():
    yield 1
    yield from range(2)


async def coro():
    async with open("f") as fh:
        await fh.read()
    async for row in fh:
        pass
    return [x async for x in fh]


class Base:
    attr: int = 0


class Derived(Base, OD, metaclass=type, **{}):
    """doc"""

    def method(self) -> "Derived":
        return self


def matcher(value):
    match value:
        case 0 | 1:
            return "small"
        case [first, *rest] if rest:
            return first
        case {"key": v, **others}:
            return v
        case Derived(attr=x):
            return x
        case (a_, b_):
            return a_, b_
        case str() as s:
            return s
        case None:
            return None
        case _:
            return value


try:
    pass
except* ValueError as eg:
    pass

type AliasSimple = int
type AliasGeneric[T, *Ts, **P] = list[T]


def generic_fn[T: int](x: T) -> T:
    return x


class GenericCls[T]:
    pass
