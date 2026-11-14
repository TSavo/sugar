"""Plan Cut 2 wiring: an authenticated ``re.search`` import-member call decides.

The matcher core and the BuiltinSemanticCallable arm are proven elsewhere.
Here the recognition seam in ImportMemberValue is exercised through a REAL
authenticated value-use receipt (target ``python:re.search``): a concrete
call decides to a truthy ReMatchValue / None; a subject known only to be a
``str`` completes on its predicate's two faces; a subject of undecided type
is the one unanswered call owed under ``python:re.search`` -- never a guess,
never keyed on spelling.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.floor.import_member_value import (
    ImportMemberValue,
    _IMPORT_MEMBER_AUTHORITY,
)
from sugar_lift_py_tests.floor.none_value import NoneValue
from sugar_lift_py_tests.floor.re_match_value import ReMatchValue
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.import_binding import (
    authenticated_import_value_use_receipts,
)
from sugar_lift_py_tests.ir import make_var
from sugar_source_tree.nodes import Call
from sugar_source_tree.tree import SourceFile


_SOURCE = 'import re\ndef f():\n    return re.search("nee", "a needle")\n'


def _re_search_member(tmp_path: Path):
    consumer = tmp_path / "use.py"
    consumer.write_text(_SOURCE)
    receipts, _ = authenticated_import_value_use_receipts(
        tmp_path, consumer, _SOURCE, blake3_512_of(_SOURCE.encode()), module_identities={}
    )
    receipt = next(r for r in receipts if r.target_symbol == "python:re.search")
    member = ImportMemberValue(
        qualified_name="re.search",
        source_cid=receipt.source_cid,
        import_binding_cid=receipt.import_binding.cid,
        use_cid=receipt.use["cid"],
        exported_member_path=tuple(receipt.use["exportedMemberPath"]),
        receipt=receipt,
        _authority=_IMPORT_MEMBER_AUTHORITY,
    )
    call = next(n for n in SourceFile((_SOURCE, "use.py", blake3_512_of(_SOURCE.encode()))).nodes() if isinstance(n, Call))
    return member, call.fragment


class _Op:
    def __init__(self, args, site):
        self.arguments = tuple(args)
        self.keyword_names = ()
        self.site = site


def test_concrete_re_search_decides_truthful_and_lying(tmp_path) -> None:
    member, site = _re_search_member(tmp_path)
    hit = member.callable_application_with(
        _Op([StringValue("nee"), StringValue("a needle")], site), None
    )
    assert isinstance(hit.value, ReMatchValue)
    truth = hit.value.truth(site=site)
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    assert isinstance(truth.value, TrueBoolLiteralSugar)
    miss = member.callable_application_with(
        _Op([StringValue("zzz"), StringValue("a needle")], site), None
    )
    assert isinstance(miss.value, NoneValue)


def test_symbolic_subject_is_the_one_unanswered_call(tmp_path) -> None:
    """A subject whose type is undecided: the one two-faced unanswered call,
    owing one debt under the import table's target symbol -- NOT a decided
    match, NOT a panic, NOT a halt-only boundary (#7757)."""
    member, site = _re_search_member(tmp_path)
    out = member.callable_application_with(
        _Op([StringValue("nee"), SymbolicValue(make_var("s"))], site), None
    )
    owed = out.owed_items()
    assert len(owed) == 1 and owed[0].symbol == "python:re.search"
    assert len(out.halts()) == 1
    completed = [e for e in out.exits if e not in out.halts()]
    assert len(completed) == 1
    assert not isinstance(completed[0].value, (ReMatchValue, NoneValue))


def test_str_subject_completes_on_its_predicate(tmp_path) -> None:
    """A subject known only to be a ``str`` completes on the two faces of
    ``py.re_search(pattern, subject)``, owing nothing."""
    member, site = _re_search_member(tmp_path)
    subject = (
        SymbolicValue(make_var("t"))
        .attribute("__name__", "name-attr", None)
        .completed_value()
    )
    out = member.callable_application_with(
        _Op([StringValue("nee"), subject], site), None
    )
    assert out.halts() == ()
    assert out.owed_items() == ()
    assert {type(e.value) for e in out.exits} == {ReMatchValue, NoneValue}
    assert all("py.re_search" in str(e.guard) for e in out.exits)


def test_recognition_is_keyed_on_the_authenticated_target_not_spelling(tmp_path) -> None:
    """A member whose authenticated qualified_name is not a C-floor semantic
    stays the ordinary boundary even if it is spelled ``search``."""
    member, site = _re_search_member(tmp_path)
    from sugar_source_tree.nodes import LanguageCallee

    # A different module's ``search`` binds no LanguageCallee member, so
    # recognition cannot fire on the bare attribute spelling.
    assert LanguageCallee.of("python:thirdparty.search") is None
    assert member.c_floor_semantic_operation(None) is None
    assert member.language_callee() is LanguageCallee.RE_SEARCH
    assert (
        member.c_floor_semantic_operation(LanguageCallee.RE_SEARCH)
        == "python.re.search"
    )
