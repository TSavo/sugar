"""An authenticated ``typing.final`` applied to one operand returns that operand.

``typing.final(f)`` tries ``f.__final__ = True``, swallows the failure and
returns ``f``; a class under ``@final`` is that class.  The answer is the one
decorator application's (``builtin_decorator_application``, #7757), keyed on
the authenticated import target, so ``abc.abstractmethod(f)`` is answered the
same way and any other import member -- and any other call shape -- stays the
undecided import-member runtime boundary.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.floor.import_member_value import (
    ImportMemberValue,
    _IMPORT_MEMBER_AUTHORITY,
)
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.import_binding import (
    authenticated_import_value_use_receipts,
)
from sugar_lift_py_tests.outcome import ExitSet
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile


_SOURCE = (
    "from abc import abstractmethod\n"
    "from typing import final, runtime_checkable\n"
    "@final\n"
    "class Sealed:\n"
    "    pass\n"
    "@runtime_checkable\n"
    "class Checked:\n"
    "    pass\n"
    "@abstractmethod\n"
    "def g():\n"
    "    pass\n"
)


def _member(tmp_path: Path, target: str):
    consumer = tmp_path / "use.py"
    consumer.write_text(_SOURCE)
    source_cid = blake3_512_of(_SOURCE.encode())
    receipts, _ = authenticated_import_value_use_receipts(
        tmp_path, consumer, _SOURCE, source_cid, module_identities={}
    )
    receipt = next(r for r in receipts if r.target_symbol == f"python:{target}")
    member = ImportMemberValue(
        qualified_name=target,
        source_cid=receipt.source_cid,
        import_binding_cid=receipt.import_binding.cid,
        use_cid=receipt.use["cid"],
        exported_member_path=(target.rsplit(".", 1)[1],),
        receipt=receipt,
        _authority=_IMPORT_MEMBER_AUTHORITY,
    )
    decorated = next(
        node
        for node in SourceFile((_SOURCE, "use.py", source_cid)).nodes()
        if isinstance(node, ClassDef)
    )
    return member, decorated.decorators[0].fragment


class _Op:
    def __init__(self, args, site, keyword_names=()):
        self.arguments = tuple(args)
        self.keyword_names = tuple(keyword_names)
        self.site = site


def test_typing_final_returns_its_one_operand(tmp_path) -> None:
    member, site = _member(tmp_path, "typing.final")
    operand = StringValue("the decorated floor")
    out = member.callable_application_with(_Op([operand], site), None)
    assert type(out) is ExitSet
    assert out.completed_value() is operand


def test_abc_abstractmethod_is_answered_by_the_same_one_application(
    tmp_path,
) -> None:
    """``abstractmethod(f)`` marks ``f`` and returns it: the one decorator
    application answers it exactly as it answers ``@abstractmethod``."""
    member, site = _member(tmp_path, "abc.abstractmethod")
    operand = StringValue("the decorated floor")
    out = member.callable_application_with(_Op([operand], site), None)
    assert type(out) is ExitSet
    assert out.completed_value() is operand


def test_another_typing_member_stays_the_undecided_boundary(tmp_path) -> None:
    """Lying twin: the same shape through a different authenticated member is
    not answered with the operand."""
    member, site = _member(tmp_path, "typing.runtime_checkable")
    operand = StringValue("the decorated floor")
    out = member.callable_application_with(_Op([operand], site), None)
    assert type(out) is ExitSet
    assert out.exits and out.halts() == out.exits


def test_typing_final_in_any_other_call_shape_stays_the_boundary(tmp_path) -> None:
    """Lying twin: ``final`` takes exactly one positional operand; two
    operands or a keyword are not that call."""
    member, site = _member(tmp_path, "typing.final")
    operand = StringValue("the decorated floor")
    two = member.callable_application_with(_Op([operand, operand], site), None)
    assert type(two) is ExitSet
    assert two.exits and two.halts() == two.exits
    keyword = member.callable_application_with(
        _Op([operand], site, keyword_names=("f",)), None
    )
    assert type(keyword) is ExitSet
    assert keyword.exits and keyword.halts() == keyword.exits
