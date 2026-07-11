"""The mint projection: the record entries mint their own UniverseMint rows.
An InvValue mints slot="inv" with Stated provenance (the vendor spoke it; the
locus is its site) and its sealed source warrant; the post mints slot="post"
with Derived provenance (the lift composed it). Formulas enter the proof
language through the one named door (formula_from_ir); formals scope with
UnknownSort -- the lift stays sort-silent, the compiler decides. Nothing is
assembled from outside: carried, projected."""

from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import UniverseValue
from sugar_lift_py_tests.canonicalizer import blake3_512_of
from sugar_lift_py_tests.outcome import complete_value

_SOURCE = "def A(z):\n    y = f(3)\n    assert y == 7\n    return z\n"


def _universe() -> UniverseValue:
    ctx = FactoryBuildContext(filename="vendor.py", catalog=default_catalog())
    site = (
        SourceFragment.from_source(_SOURCE, "vendor.py").statements()[0].statements()[0]
    )
    result = build_node(site, filename="vendor.py", role=SugarRole.STATEMENT, ctx=ctx)
    return complete_value(result.sugar.desugar(ctx), owner="test")


def test_the_inv_mints_a_stated_row_with_its_warrant() -> None:
    mints = _universe().mints()
    inv_rows = [m for m in mints if m.slot == "inv"]
    assert len(inv_rows) == 1
    row = inv_rows[0]
    assert row.name == "A"
    provenance = row.formula.provenanced.provenance
    assert provenance.warrants[0].to_rpc()["kind"] == "Stated"
    assert provenance.warrants[0].locus.line == 3
    warrant = row.source_warrants[0]
    assert warrant.file == "vendor.py"
    assert warrant.source_cid == blake3_512_of(b"assert y == 7")


def test_the_post_mints_a_derived_row() -> None:
    mints = _universe().mints()
    post_rows = [m for m in mints if m.slot == "post"]
    assert len(post_rows) == 1
    provenance = post_rows[0].formula.provenanced.provenance
    assert provenance.warrants[0].to_rpc()["kind"] == "Derived"
