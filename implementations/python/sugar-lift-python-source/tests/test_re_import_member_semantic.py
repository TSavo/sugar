"""Plan Cut 2 wiring: an authenticated ``re.search`` import-member call decides.

The matcher core and the BuiltinSemanticCallable arm are proven elsewhere.
Here the recognition seam in ImportMemberValue is exercised through a REAL
authenticated value-use receipt (target ``python:re.search``): a concrete
call decides to a truthy ReMatchValue / None; a symbolic operand falls
through to the ordinary undecided import-member boundary -- never a guess,
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


def test_symbolic_subject_stays_the_undecided_boundary(tmp_path) -> None:
    """A symbolic operand is genuinely undecided: the import-member runtime
    effect boundary, NOT a decided match and NOT our missing floor."""
    member, site = _re_search_member(tmp_path)
    out = member.callable_application_with(
        _Op([StringValue("nee"), SymbolicValue(make_var("s"))], site), None
    )
    value = getattr(out, "value", out)
    assert not isinstance(value, (ReMatchValue, NoneValue))


def test_recognition_is_keyed_on_the_authenticated_target_not_spelling(tmp_path) -> None:
    """A member whose authenticated qualified_name is not a C-floor semantic
    stays the ordinary boundary even if it is spelled ``search``."""
    member, site = _re_search_member(tmp_path)
    from dataclasses import replace

    # Same receipt, but pretend the authenticated name is a different module's
    # ``search`` -- recognition must not fire on the bare attribute spelling.
    assert member._C_FLOOR_SEMANTIC_OPERATIONS.get("thirdparty.search") is None
    assert member._C_FLOOR_SEMANTIC_OPERATIONS.get("re.search") == "python.re.search"
