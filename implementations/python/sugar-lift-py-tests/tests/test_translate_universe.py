from __future__ import annotations

import sys
import textwrap
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
PY_TESTS_SRC = ROOT / "implementations/python/sugar-lift-py-tests/src"
PKG_SRC = ROOT / "implementations/python/sugar-lift-python-source/src"
for p in (str(PY_TESTS_SRC), str(PKG_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from sugar_lift_py_tests.layer2 import lift_file_layer2
from sugar_lift_py_tests.lsp import _lift_source, _with_package_source_accounting
from sugar_lift_py_tests.translate_universe import translate_universe_for_callee

VENDOR_TRANSLATE = '''
_tab = bytes.maketrans(b"+/", b"-_")


def _enc(s):
    return s


def urlsafe(s):
    """Translate-shaped vendor body, CPython base64.urlsafe_b64encode shape."""
    return _enc(s).translate(_tab)
'''

VENDOR_SWAP = '''
_tab = bytes.maketrans(b"+/", b"/+")


def _enc(s):
    return s


def urlsafe(s):
    return _enc(s).translate(_tab)
'''

VENDOR_UNSTABLE = '''
_tab = bytes.maketrans(b"+/", b"-_")
_tab = bytes.maketrans(b"+/", b"-_")


def _enc(s):
    return s


def urlsafe(s):
    return _enc(s).translate(_tab)
'''

VENDOR_FLIPPED = '''
_tab = bytes.maketrans(b"+!", b"-_")


def _enc(s):
    return s


def urlsafe(s):
    return _enc(s).translate(_tab)
'''

VENDOR_PLAIN = '''
def plain(s):
    return s + "x"
'''


@pytest.fixture()
def vendor_path(tmp_path, monkeypatch):
    def write(module_name: str, source: str) -> None:
        (tmp_path / f"{module_name}.py").write_text(textwrap.dedent(source))

    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()
    return write


def test_walk_derives_forbidden_set(vendor_path):
    vendor_path("venduniv_ok", VENDOR_TRANSLATE)
    universe, refusal = translate_universe_for_callee("venduniv_ok.urlsafe")
    assert refusal is None
    assert universe is not None
    assert universe.forbidden == "+/"
    assert universe.table_name == "_tab"
    assert universe.qualname == "venduniv_ok.urlsafe"


def test_swap_table_refuses_no_universe(vendor_path):
    # maketrans(b"+/", b"/+") maps '+' to '/' and back: every mapped char is
    # reintroduced, so NO complement claim exists. Must refuse by name, never
    # emit an empty/false universe.
    vendor_path("venduniv_swap", VENDOR_SWAP)
    universe, refusal = translate_universe_for_callee("venduniv_swap.urlsafe")
    assert universe is None
    assert refusal is not None
    assert "reintroduces" in refusal.reason


def test_unstable_table_refuses(vendor_path):
    vendor_path("venduniv_unstable", VENDOR_UNSTABLE)
    universe, refusal = translate_universe_for_callee("venduniv_unstable.urlsafe")
    assert universe is None
    assert refusal is not None


def test_non_translate_body_is_not_a_candidate(vendor_path):
    vendor_path("venduniv_plain", VENDOR_PLAIN)
    universe, refusal = translate_universe_for_callee("venduniv_plain.plain")
    assert universe is None
    assert refusal is None  # fog was never a candidate; no refusal owed


def test_partial_swap_keeps_surviving_chars(vendor_path):
    vendor_path(
        "venduniv_partial",
        '''
_tab = bytes.maketrans(b"+/", b"/_")


def _enc(s):
    return s


def urlsafe(s):
    return _enc(s).translate(_tab)
''',
    )
    # '+' -> '/' reintroduces '/'; '/' -> '_' removes it. Forbidden = {+}.
    universe, refusal = translate_universe_for_callee("venduniv_partial.urlsafe")
    assert refusal is None
    assert universe is not None
    assert universe.forbidden == "+"


# --- layer2 integration: the ::universe sibling row ---


def _lift(source: str):
    source = textwrap.dedent(source)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test_mod.py"
        path.write_text(source, encoding="utf-8")
        return lift_file_layer2(source, str(path))


def _lift_source_from_disk(tmp_path: Path, name: str, source: str):
    source = textwrap.dedent(source)
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return _lift_source(str(path), source)


def _universe_atoms(out):
    # The universe is a CONJUNCT inside the base's conjoined ::assertion --
    # never a sibling contract (the verifier conjoins by name; a sibling
    # verifies alone and is vacuously consistent).
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    atoms = []
    for d in out.decls:
        if d.name.endswith("::assertion") and d.inv is not None:
            atoms.extend(
                a
                for a in _iter_conjuncts(d.inv)
                if a.name == "str.chars-not-in-set"
            )
    return atoms


def _universe_decls(out):
    # Distinct universe claims, deduped by content: coalescing may repeat
    # idempotent conjuncts; WHICH universes exist is the property.
    return sorted({(a.args[0], a.args[1]) for a in _universe_atoms(out)}, key=str)


def test_universe_row_emitted_for_translate_callee(vendor_path):
    vendor_path("venduniv_l2", VENDOR_TRANSLATE)
    out = _lift(
        """
        import venduniv_l2

        def test_urlsafe():
            assert venduniv_l2.urlsafe("abc") == "abc"
        """
    )
    atoms = _universe_atoms(out)
    assert len(atoms) == 1
    assert atoms[0].args[1].value == "+/"
    # contact is structural: the atom lives INSIDE the conjoined assertion
    assert any(d.name.endswith("::assertion") and "urlsafe" in d.name for d in out.decls)


def test_universe_assertion_carries_source_warrant(vendor_path):
    vendor_path("venduniv_warrant", VENDOR_TRANSLATE)
    out = _lift(
        """
        import venduniv_warrant

        def test_urlsafe():
            assert venduniv_warrant.urlsafe("abc") == "abc"
        """
    )

    decl = next(
        d
        for d in out.decls
        if d.name.endswith("::assertion") and "venduniv_warrant.urlsafe" in d.name
    )
    roles = {warrant.get("role") for warrant in decl.source_warrants}
    assert {"python.test-fact", "python.translate-universe"} <= roles
    warrant = next(
        warrant
        for warrant in decl.source_warrants
        if warrant.get("role") == "python.translate-universe"
    )
    assert warrant["kind"] == "source-memento"
    assert warrant["role"] == "python.translate-universe"
    assert warrant["source_function_name"] == "urlsafe"
    assert warrant["file"].endswith("venduniv_warrant.py")
    assert warrant["source_cid"].startswith("blake3-512:")
    assert warrant["template_cid"].startswith("blake3-512:")
    assert warrant["span"]["start_line"] > 0
    assert "body_text" not in warrant
    assert "ast_template" not in warrant

    assert out.source_ledger["source_loci"] > 0
    assert out.source_ledger["source_warranted"] > 0
    assert out.source_ledger["source_refused"] >= 0
    assert out.source_ledger["source_inactive"] == 0
    assert out.source_ledger["source_refuted"] == 0
    assert "source_work" not in out.source_ledger
    assert out.source_ledger["unclassified_source"] == 0
    assert out.source_audits
    audit = next(
        audit
        for audit in out.source_audits
        if audit["contract"]["name"] == decl.name
        and audit["role"] == "python.translate-universe"
    )
    assert audit["kind"] == "source-audit"
    assert audit["language"] == "python"
    assert audit["source_memento"]["kind"] == "source-memento"
    assert "body_text" not in audit["source_memento"]
    assert "ast_template" not in audit["source_memento"]
    assert audit["totals"]["source_loci"] == len(audit["loci"])
    assert audit["totals"]["source_inactive"] == 0
    assert audit["totals"]["unclassified_source"] == 0
    assert {locus["status"] for locus in audit["loci"]} <= {"warranted", "support"}
    for locus in audit["loci"]:
        assert locus.get("ast_path", "").startswith("$.body"), locus
        assert locus.get("span", {}).get("start_line", 0) > 0, locus
        assert locus.get("line_range") == [
            locus["span"]["start_line"],
            locus["span"]["end_line"],
        ], locus
    assert any(
        locus["status"] == "warranted" and locus.get("ast_kind") == "Return"
        for locus in audit["loci"]
    ), audit
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Attribute"
        and locus.get("ast_path") == "$.body[1].value.func"
        for locus in audit["loci"]
    ), audit
    assert any(
        locus["status"] == "support" and locus.get("ast_kind") == "Expr"
        for locus in audit["loci"]
    ), audit


def test_lift_source_exposes_source_audit_countdown(vendor_path, tmp_path):
    vendor_path("venduniv_wire", VENDOR_TRANSLATE)
    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import venduniv_wire

        def test_urlsafe():
            assert venduniv_wire.urlsafe("abc") == "abc"
        """,
    )

    source_ledger = lifted["sourceLedger"]
    assert source_ledger["source_loci"] > 0
    assert source_ledger["source_warranted"] > 0
    assert source_ledger["source_support"] > 0
    assert source_ledger["source_refused"] == 0
    assert source_ledger["source_inactive"] == 0
    assert source_ledger["unclassified_source"] == 0
    assert lifted["sourceMementos"]
    rpc_memento = next(
        m
        for m in lifted["sourceMementos"]
        if m.get("role") == "python.translate-universe"
    )
    assert rpc_memento["kind"] == "source-memento"
    assert rpc_memento["claimName"].endswith("::assertion")
    assert rpc_memento["contractName"].endswith("::assertion")
    assert rpc_memento["source_cid"].startswith("blake3-512:")
    assert "body_text" not in rpc_memento
    assert "ast_template" not in rpc_memento
    assert lifted["sourceAudits"]


def test_lift_source_dedupes_shared_fact_source_audits(vendor_path, tmp_path):
    vendor_path("vendrstrip_dedupe", VENDOR_RSTRIP)
    source = textwrap.dedent(
        """
        import vendrstrip_dedupe

        def test_token():
            assert vendrstrip_dedupe.b64e("abc") == "abc"
        """
    )
    source_path = tmp_path / "test_mod.py"
    source_path.write_text(source, encoding="utf-8")
    lifted = _lift_source(str(source_path), source)

    fact_audits = [
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.test-fact"
    ]
    assert len(fact_audits) == 1
    assert fact_audits[0]["totals"]["source_warranted"] == 1


def test_lift_source_emits_package_unclassified_accounting(tmp_path, monkeypatch):
    pkg = tmp_path / "vendpkg_accounting"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            """
            def _inner(s):
                return s


            def b64e(s):
                return _inner(s).rstrip(b"=")
            """
        ),
        encoding="utf-8",
    )
    (pkg / "extra.py").write_text(
        textwrap.dedent(
            """
            def skipped(value):
                return value + noisy(value)
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_accounting.encoding as enc

        def test_token():
            assert enc.b64e("abc") == "abc"
        """,
    )

    package_audits = [
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    ]
    assert len(package_audits) == 1
    audit = package_audits[0]
    assert audit["package"] == "vendpkg_accounting"
    assert audit["totals"]["source_loci"] == len(audit["loci"])
    assert audit["totals"]["source_warranted"] > 0
    assert audit["totals"]["source_support"] > 0
    assert audit["totals"]["source_refused"] == 0
    assert audit["totals"]["unclassified_source"] > 0
    assert audit["totals"]["unclassified_source"] < len(audit["loci"])
    assert lifted["sourceLedger"]["unclassified_source"] >= audit["totals"]["unclassified_source"]
    assert any(
        locus["status"] == "warranted"
        and locus["file"].endswith("vendpkg_accounting/encoding.py")
        and locus.get("ast_kind") == "Return"
        and "delegation" in locus.get("reason", "")
        for locus in audit["loci"]
    ), audit
    assert any(
        locus["status"] == "unclassified"
        and locus["file"].endswith("vendpkg_accounting/extra.py")
        and locus.get("ast_kind") == "Return"
        for locus in audit["loci"]
    ), audit


def test_lift_source_classifies_imports_as_package_support(tmp_path, monkeypatch):
    pkg = tmp_path / "vendpkg_import_support"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            """
            def b64e(s):
                return s.rstrip(b"=")
            """
        ),
        encoding="utf-8",
    )
    (pkg / "extra.py").write_text(
        textwrap.dedent(
            """
            import json
            from .encoding import b64e as imported_b64e

            def skipped(value):
                return imported_b64e(json.dumps(value))
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_import_support.encoding as enc

        def test_token():
            assert enc.b64e("abc") == "abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    import_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_import_support/extra.py")
        and locus.get("ast_kind") in {"Import", "ImportFrom", "alias"}
    ]
    assert import_loci
    assert {locus["status"] for locus in import_loci} == {"support"}
    assert audit["totals"]["source_support"] >= len(import_loci)
    assert lifted["sourceLedger"]["source_support"] >= len(import_loci)


def test_lift_source_warrants_translate_return_in_package_accounting(
    tmp_path, monkeypatch
):
    pkg = tmp_path / "vendpkg_translate_accounting"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            """
            import base64

            def want_bytes(s):
                return s

            def b64e(s):
                s = want_bytes(s)
                return base64.urlsafe_b64encode(s).rstrip(b"=")
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_translate_accounting.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"YWJj"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    return_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_translate_accounting/encoding.py")
        and locus.get("line") == 9
        and locus.get("ast_kind") in {"Return", "Call", "Attribute", "Name", "Constant"}
    ]
    assert return_loci
    assert not [
        locus for locus in return_loci if locus["status"] == "unclassified"
    ], return_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Return"
        and "no-suffix-chars" in locus.get("reason", "")
        for locus in return_loci
    ), return_loci


def test_lift_source_reuses_emitted_audit_statuses_in_package_accounting(
    tmp_path, monkeypatch
):
    pkg = tmp_path / "vendpkg_replayed_accounting"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "serializer.py").write_text(
        textwrap.dedent(
            """
            class Serializer:
                def dumps(self, obj):
                    return "x"

            def is_text_serializer(serializer):
                return isinstance(serializer.dumps({}), str)
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_replayed_accounting.serializer as ser

        def test_text_serializer():
            serializer = ser.Serializer()
            assert ser.is_text_serializer(serializer) == True
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    return_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_replayed_accounting/serializer.py")
        and locus.get("line") == 7
        and locus.get("ast_kind") in {"Return", "Call", "Attribute", "Name", "Dict"}
    ]
    assert return_loci
    assert not [
        locus for locus in return_loci if locus["status"] == "unclassified"
    ], return_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "return-isinstance" in locus.get("reason", "")
        for locus in return_loci
    ), return_loci


def test_package_accounting_reuses_line_level_source_warrants(tmp_path):
    pkg = tmp_path / "vendpkg_line_replay"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    source_file = pkg / "mod.py"
    source_file.write_text("def f(x):\n    return x\n", encoding="utf-8")

    lifted = {
        "sourceAudits": [
            {
                "kind": "source-audit",
                "language": "python",
                "contract": {"name": "vendpkg_line_replay.mod.f::assertion"},
                "role": "python.legacy-line-universe",
                "universe_kind": "legacy-line",
                "source_memento": {
                    "kind": "source-memento",
                    "file": str(source_file),
                    "source_function_name": "f",
                },
                "loci": [
                    {
                        "kind": "source-line",
                        "file": str(source_file),
                        "line": 2,
                        "status": "warranted",
                        "role": "python.legacy-line-universe",
                        "universe_kind": "legacy-line",
                        "reason": "legacy line-level source warrant",
                    }
                ],
                "totals": {
                    "source_loci": 1,
                    "source_warranted": 1,
                    "source_support": 0,
                    "source_refused": 0,
                    "source_inactive": 0,
                    "source_refuted": 0,
                    "unclassified_source": 0,
                },
            }
        ],
        "sourceLedger": {
            "source_loci": 1,
            "source_warranted": 1,
            "source_support": 0,
            "source_refused": 0,
            "source_inactive": 0,
            "source_refuted": 0,
            "unclassified_source": 0,
        },
    }

    out = _with_package_source_accounting(lifted)
    audit = next(
        audit
        for audit in out["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    return_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_line_replay/mod.py")
        and locus.get("line") == 2
    ]
    assert {locus.get("ast_kind") for locus in return_loci} == {"Return", "Name"}
    assert {locus["status"] for locus in return_loci} == {"warranted"}
    assert {
        locus.get("source_audit_role") for locus in return_loci
    } == {"python.legacy-line-universe"}


def test_lift_source_warrants_constructor_field_assignments_in_package_accounting(
    tmp_path, monkeypatch
):
    pkg = tmp_path / "vendpkg_constructor_accounting"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            """
            def b64e(s):
                return s.rstrip(b"=")
            """
        ),
        encoding="utf-8",
    )
    (pkg / "exc.py").write_text(
        textwrap.dedent(
            """
            class BadTimeSignature(Exception):
                def __init__(self, message, payload=None, date_signed=None):
                    super().__init__(message, payload)
                    self.date_signed = date_signed
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_constructor_accounting.encoding as enc

        def test_token():
            assert enc.b64e("abc") == "abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    constructor_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_constructor_accounting/exc.py")
        and locus.get("line") == 5
        and locus.get("ast_kind") in {"Assign", "Attribute", "Name"}
    ]
    assert constructor_loci
    assert {locus["status"] for locus in constructor_loci} == {"warranted"}
    assert all(
        "constructor field assignment" in locus.get("reason", "")
        for locus in constructor_loci
    )


def test_structural_package_accounting_warrants_object_setattr_constructor_fields(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_object_setattr_constructor"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    config_path = pkg / "config.py"
    config_path.write_text(
        textwrap.dedent(
            """
            class DictWrapper:
                def __init__(self, d, prefix=""):
                    object.__setattr__(self, "d", d)
                    object.__setattr__(self, "prefix", prefix)

            def version():
                return "1.0"
            """
        ),
        encoding="utf-8",
    )
    setattr_lines = {
        line_no
        for line_no, line in enumerate(config_path.read_text().splitlines(), 1)
        if "object.__setattr__" in line
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_object_setattr_constructor.config as config

        def test_version():
            assert config.version() == "1.0"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_object_setattr_constructor"
    )
    constructor_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_object_setattr_constructor/config.py")
        and locus["line"] in setattr_lines
    ]
    assert constructor_loci
    assert not [
        locus for locus in constructor_loci if locus["status"] == "unclassified"
    ], constructor_loci
    assert {locus["status"] for locus in constructor_loci} == {"warranted"}
    assert any(
        locus.get("ast_kind") == "Call"
        and "object.__setattr__ constructor field" in locus.get("reason", "")
        for locus in constructor_loci
    ), constructor_loci


def test_structural_package_accounting_supports_public_module_metadata_rebinding(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_public_module_metadata"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def get_option():
                return "ok"

            class Options:
                pass

            get_option.__module__ = "pandas"
            Options.__module__ = "pandas"
            object.__setattr__(get_option, "__module__", "pandas")
            """
        ),
        encoding="utf-8",
    )
    metadata_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if "__module__" in line
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_public_module_metadata.api as api

        def test_get_option():
            assert api.get_option() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_public_module_metadata"
    )
    metadata_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_public_module_metadata/api.py")
        and locus["line"] in metadata_lines
    ]
    assert metadata_loci
    assert {locus["status"] for locus in metadata_loci} == {"support"}
    assert all(
        "public module metadata" in locus.get("reason", "")
        for locus in metadata_loci
    ), metadata_loci


def test_structural_package_accounting_supports_pass_noop_scaffolding(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_pass_noop"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            class Empty:
                pass

            def skipped():
                pass

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    pass_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip() == "pass"
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_pass_noop.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_pass_noop"
    )
    pass_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_pass_noop/api.py")
        and locus["line"] in pass_lines
    ]
    assert pass_loci
    assert {locus["status"] for locus in pass_loci} == {"support"}
    assert all(
        "pass no-op" in locus.get("reason", "")
        for locus in pass_loci
    ), pass_loci


def test_structural_package_accounting_refuses_loop_control_flow(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_loop_control"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def skipped(values):
                for value in values:
                    if value is None:
                        continue
                    break

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    control_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip() in {"break", "continue"}
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_loop_control.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_loop_control"
    )
    control_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_loop_control/api.py")
        and locus["line"] in control_lines
    ]
    assert control_loci
    assert {locus["status"] for locus in control_loci} == {"refused"}
    assert all(
        "loop control flow" in locus.get("reason", "")
        for locus in control_loci
    ), control_loci


def test_structural_package_accounting_refuses_generator_yield_flow(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_generator_flow"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def skipped(values):
                yield "prefix"
                yield from values

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    yield_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith("yield")
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_generator_flow.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_generator_flow"
    )
    yield_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_generator_flow/api.py")
        and locus["line"] in yield_lines
    ]
    assert yield_loci
    assert {locus["status"] for locus in yield_loci} == {"refused"}
    assert all(
        "generator/yield flow" in locus.get("reason", "")
        for locus in yield_loci
    ), yield_loci


def test_structural_package_accounting_warrants_local_compiler_bindings(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_local_bindings"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def skipped(value):
                local = "abc"
                pair = ("x", 1)
                alias = value
                return local

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    binding_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith(("local =", "pair =", "alias ="))
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_local_bindings.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_local_bindings"
    )
    binding_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_local_bindings/api.py")
        and locus["line"] in binding_lines
    ]
    assert binding_loci
    assert {locus["status"] for locus in binding_loci} == {"warranted"}
    assert all(
        "local " in locus.get("reason", "")
        for locus in binding_loci
    ), binding_loci


def test_structural_package_accounting_warrants_pure_branch_predicates(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_pure_branch_predicates"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def skipped(value, allowed):
                if value in ("a", "b") and len(allowed) > 0:
                    return value
                if value is None:
                    return "missing"
                return "ok"

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    predicate_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith("if ")
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_pure_branch_predicates.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_pure_branch_predicates"
    )
    predicate_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_pure_branch_predicates/api.py")
        and locus["line"] in predicate_lines
        and locus.get("ast_kind")
        in {"If", "BoolOp", "Compare", "Call", "Name", "Tuple", "Constant"}
    ]
    assert predicate_loci
    assert not [
        locus for locus in predicate_loci if locus["status"] == "unclassified"
    ], predicate_loci
    assert {locus["status"] for locus in predicate_loci} == {"warranted"}
    assert all(
        "pure branch predicate" in locus.get("reason", "")
        for locus in predicate_loci
    ), predicate_loci


def test_structural_package_accounting_leaves_unknown_branch_calls_unclassified(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_unknown_branch_call"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def expensive(value):
                return value == "x"

            def skipped(value):
                if expensive(value):
                    return value
                return "ok"

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    branch_line = next(
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith("if expensive")
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_unknown_branch_call.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_unknown_branch_call"
    )
    branch_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_unknown_branch_call/api.py")
        and locus["line"] == branch_line
        and locus.get("ast_kind") in {"If", "Call"}
    ]
    assert branch_loci
    assert {
        locus.get("ast_kind")
        for locus in branch_loci
        if locus["status"] == "unclassified"
    } == {"If", "Call"}


def test_structural_package_accounting_warrants_literal_container_terms(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_literal_container_terms"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def skipped(value, other):
                return [value, "x", {"k": other, "pair": (value, None)}]

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    literal_line = next(
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if "return [value" in line
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_literal_container_terms.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_literal_container_terms"
    )
    literal_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_literal_container_terms/api.py")
        and locus["line"] == literal_line
        and locus.get("ast_kind")
        in {"List", "Dict", "Tuple", "Constant", "Name"}
    ]
    assert literal_loci
    assert not [
        locus for locus in literal_loci if locus["status"] == "unclassified"
    ], literal_loci
    assert {locus["status"] for locus in literal_loci} == {"warranted"}
    assert all(
        "literal container value term" in locus.get("reason", "")
        for locus in literal_loci
    ), literal_loci


def test_structural_package_accounting_leaves_computed_literal_container_unclassified(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_computed_literal_container"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def make(value):
                return value

            def skipped(value):
                return [make(value), "x"]

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    literal_line = next(
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if "return [make" in line
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_computed_literal_container.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_computed_literal_container"
    )
    computed_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_computed_literal_container/api.py")
        and locus["line"] == literal_line
        and locus.get("ast_kind") in {"List", "Call"}
    ]
    assert computed_loci
    assert {
        locus.get("ast_kind")
        for locus in computed_loci
        if locus["status"] == "unclassified"
    } == {"List", "Call"}


def test_structural_package_accounting_warrants_known_pure_call_value_terms(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_known_pure_call_terms"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def skipped(value, values):
                return (
                    len(values),
                    tuple(["a", value]),
                    dict(item=value, fallback=getattr(value, "fallback", None)),
                    range(0, 3),
                    isinstance(value, str),
                    type(value),
                    sorted(["b", "a"]),
                )

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    return_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith(
            (
                "len(",
                "tuple(",
                "dict(",
                "range(",
                "isinstance(",
                "type(",
                "sorted(",
            )
        )
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_known_pure_call_terms.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_known_pure_call_terms"
    )
    pure_call_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_known_pure_call_terms/api.py")
        and locus["line"] in return_lines
        and locus.get("ast_kind")
        in {"Call", "Name", "Attribute", "Constant", "List", "Tuple", "Dict", "keyword"}
    ]
    assert pure_call_loci
    assert not [
        locus for locus in pure_call_loci if locus["status"] == "unclassified"
    ], pure_call_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "known pure call value term" in locus.get("reason", "")
        for locus in pure_call_loci
    ), pure_call_loci


def test_structural_package_accounting_warrants_builtin_slice_value_terms(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_builtin_slice_terms"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def skipped(values):
                return (
                    slice(None),
                    slice(1, len(values), 2),
                )

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    slice_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith("slice(")
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_builtin_slice_terms.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_builtin_slice_terms"
    )
    slice_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_builtin_slice_terms/api.py")
        and locus["line"] in slice_lines
        and locus.get("ast_kind") in {"Call", "Name", "Constant"}
    ]
    assert slice_loci
    assert not [
        locus for locus in slice_loci if locus["status"] == "unclassified"
    ], slice_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "known pure call value term" in locus.get("reason", "")
        for locus in slice_loci
    ), slice_loci


def test_structural_package_accounting_refuses_dynamic_getattr_lookup(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_dynamic_getattr_refused"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def skipped(value, attr):
                return getattr(value, attr)

            def skipped_default(value, attr, fallback):
                result = getattr(value, attr, fallback)
                return result

            def safe(value):
                return getattr(value, "name", None)

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    dynamic_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if "getattr(value, attr" in line
    }
    safe_line = next(
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if 'getattr(value, "name"' in line
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_dynamic_getattr_refused.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_dynamic_getattr_refused"
    )
    dynamic_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_dynamic_getattr_refused/api.py")
        and locus["line"] in dynamic_lines
    ]
    assert dynamic_loci
    assert not [
        locus for locus in dynamic_loci if locus["status"] == "unclassified"
    ], dynamic_loci
    assert any(
        locus["status"] == "refused"
        and locus.get("ast_kind") in {"Return", "Assign"}
        and "dynamic getattr" in locus.get("reason", "")
        for locus in dynamic_loci
    ), dynamic_loci
    assert any(
        locus["status"] == "refused"
        and locus.get("ast_kind") == "Call"
        and "dynamic getattr" in locus.get("reason", "")
        for locus in dynamic_loci
    ), dynamic_loci

    safe_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_dynamic_getattr_refused/api.py")
        and locus["line"] == safe_line
        and locus.get("ast_kind") in {"Call", "Name", "Constant"}
    ]
    assert safe_loci
    assert not [
        locus for locus in safe_loci if locus["status"] == "refused"
    ], safe_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "known pure call value term" in locus.get("reason", "")
        for locus in safe_loci
    ), safe_loci


def test_structural_package_accounting_warrants_known_pure_stdlib_bridge_terms(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_known_pure_stdlib_bridge_terms"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            import math
            import os

            def skipped(value, path):
                return (
                    math.floor(value),
                    math.ceil(value),
                    os.fspath(path),
                )

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    return_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith(("math.", "os."))
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_known_pure_stdlib_bridge_terms.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_known_pure_stdlib_bridge_terms"
    )
    bridge_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_known_pure_stdlib_bridge_terms/api.py")
        and locus["line"] in return_lines
        and locus.get("ast_kind") in {"Call", "Attribute", "Name"}
    ]
    assert bridge_loci
    assert not [
        locus for locus in bridge_loci if locus["status"] == "unclassified"
    ], bridge_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "known pure call value term" in locus.get("reason", "")
        for locus in bridge_loci
    ), bridge_loci


def test_structural_package_accounting_warrants_imported_stdlib_constructors(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_stdlib_constructor_terms"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            import datetime as dt
            from datetime import datetime

            START = datetime(2020, 1, 2)
            DELTA = dt.timedelta(days=3)

            def values():
                return [
                    datetime(2020, 1, 2),
                    dt.timedelta(days=3),
                ]

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    shadow_path = pkg / "shadow.py"
    shadow_path.write_text(
        textwrap.dedent(
            '''
            def datetime(value):
                return value

            LOCAL = datetime("not-stdlib")
            '''
        ),
        encoding="utf-8",
    )
    stdlib_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith(("START =", "DELTA =", "datetime(", "dt.timedelta("))
    }
    local_line = next(
        line_no
        for line_no, line in enumerate(shadow_path.read_text().splitlines(), 1)
        if line.strip().startswith("LOCAL =")
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_stdlib_constructor_terms.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_stdlib_constructor_terms"
    )
    stdlib_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_stdlib_constructor_terms/api.py")
        and locus["line"] in stdlib_lines
        and locus.get("ast_kind") in {"Call", "Name", "Attribute", "Constant", "keyword"}
    ]
    assert stdlib_loci
    assert not [
        locus for locus in stdlib_loci if locus["status"] == "unclassified"
    ], stdlib_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "stdlib constructor value term" in locus.get("reason", "")
        for locus in stdlib_loci
    ), stdlib_loci

    local_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_stdlib_constructor_terms/shadow.py")
        and locus["line"] == local_line
        and locus.get("ast_kind") == "Call"
    ]
    assert local_loci
    assert any(locus["status"] == "unclassified" for locus in local_loci), local_loci


def test_structural_package_accounting_warrants_known_pure_method_value_terms(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_known_pure_method_terms"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            '''
            def skipped(value, values, items):
                lowered = value.lower()
                keys = list(values.keys())
                joined = "|".join(items)
                stripped = value.rstrip("=")
                if not value or "ascii" in value.lower():
                    ascii_safe = True
                return joined

            def ok():
                return "ok"
            '''
        ),
        encoding="utf-8",
    )
    method_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith(
            ("lowered =", "keys =", "joined =", "stripped =", "if not value")
        )
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_known_pure_method_terms.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_known_pure_method_terms"
    )
    method_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_known_pure_method_terms/api.py")
        and locus["line"] in method_lines
        and locus.get("ast_kind")
        in {"Assign", "If", "BoolOp", "Compare", "Call", "Attribute", "Name", "Constant"}
    ]
    assert method_loci
    assert not [
        locus
        for locus in method_loci
        if locus["status"] in {"unclassified", "refused"}
    ], method_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "known pure method value term" in locus.get("reason", "")
        for locus in method_loci
    ), method_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "If"
        and "pure branch predicate" in locus.get("reason", "")
        for locus in method_loci
    ), method_loci


def test_structural_package_accounting_warrants_direct_return_value_relations(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_direct_return_value_relations"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def by_arg(value):
                return value

            def by_literal():
                return True

            def by_selector(values, key):
                return values[key]

            def by_compare(value):
                return value == "x"

            def by_none():
                return

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    return_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if (
            line.strip() == "return"
            or (
                line.strip().startswith("return ")
                and not line.strip().startswith('return "ok"')
            )
        )
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_direct_return_value_relations.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_direct_return_value_relations"
    )
    return_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_direct_return_value_relations/api.py")
        and locus["line"] in return_lines
        and locus.get("ast_kind")
        in {"Return", "Name", "Constant", "Subscript", "Compare"}
    ]
    assert return_loci
    assert not [
        locus for locus in return_loci if locus["status"] == "unclassified"
    ], return_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Return"
        and "return value relation" in locus.get("reason", "")
        for locus in return_loci
    ), return_loci


def test_structural_package_accounting_warrants_static_value_references(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_static_value_references"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            DEFAULTS = {"salt": "pepper", "items": ("a", "b")}

            class Options:
                mode = "strict"

            def skipped(index):
                salt = DEFAULTS["salt"]
                mode = Options.mode
                item = DEFAULTS["items"][index]
                return mode

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    value_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith(("salt =", "mode =", "item ="))
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_static_value_references.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_static_value_references"
    )
    static_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_static_value_references/api.py")
        and locus["line"] in value_lines
        and locus.get("ast_kind")
        in {"Assign", "Subscript", "Slice", "Attribute", "Name", "Constant"}
    ]
    assert static_loci
    assert not [
        locus for locus in static_loci if locus["status"] == "unclassified"
    ], static_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Attribute"
        and "static value reference" in locus.get("reason", "")
        for locus in static_loci
    ), static_loci


def test_structural_package_accounting_warrants_static_value_table_construction(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_static_value_table_construction"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            from decimal import Decimal

            NUMPY_DTYPES = ["int8", "int16"]
            EXTENSION_DTYPES = ["Int8", "Int16"]
            ALL_DTYPES: list[object] = [*NUMPY_DTYPES, *EXTENSION_DTYPES]
            NULL_OBJECTS = [None, float("nan"), Decimal("NaN")]

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    table_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith(("ALL_DTYPES", "NULL_OBJECTS"))
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_static_value_table_construction.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_static_value_table_construction"
    )
    table_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_static_value_table_construction/api.py")
        and locus["line"] in table_lines
        and locus.get("ast_kind")
        in {"AnnAssign", "Assign", "List", "Starred", "Name", "Call", "Constant"}
    ]
    assert table_loci
    assert not [
        locus for locus in table_loci if locus["status"] == "unclassified"
    ], table_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Starred"
        and "static binding" in locus.get("reason", "")
        for locus in table_loci
    ), table_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "static binding" in locus.get("reason", "")
        for locus in table_loci
    ), table_loci


def test_structural_package_accounting_warrants_keyword_argument_bindings(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_keyword_argument_bindings"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def skipped(value, obj):
                return factory(
                    alpha=value,
                    beta="literal",
                    gamma=obj.attr,
                    delta=[value, "x"],
                    epsilon=tuple([value]),
                    zeta=len(value),
                )

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    keyword_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith(
            (
                "alpha=",
                "beta=",
                "gamma=",
                "delta=",
                "epsilon=",
                "zeta=",
            )
        )
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_keyword_argument_bindings.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_keyword_argument_bindings"
    )
    keyword_value_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_keyword_argument_bindings/api.py")
        and locus["line"] in keyword_lines
        and locus.get("ast_kind")
        in {"keyword", "Name", "Attribute", "Constant", "List", "Call"}
    ]
    assert keyword_value_loci
    assert not [
        locus for locus in keyword_value_loci if locus["status"] == "unclassified"
    ], keyword_value_loci
    keyword_loci = [
        locus for locus in keyword_value_loci if locus.get("ast_kind") == "keyword"
    ]
    assert keyword_loci
    assert all(
        locus["status"] == "warranted"
        and "keyword argument binding" in locus.get("reason", "")
        for locus in keyword_loci
    ), keyword_loci


def test_structural_package_accounting_leaves_kwargs_splat_unclassified(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_kwargs_splat"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def skipped(value, kwargs):
                return factory(
                    alpha=value,
                    **kwargs,
                )

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    alpha_line = next(
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith("alpha=")
    )
    splat_line = next(
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith("**kwargs")
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_kwargs_splat.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_kwargs_splat"
    )
    keyword_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_kwargs_splat/api.py")
        and locus["line"] in {alpha_line, splat_line}
        and locus.get("ast_kind") == "keyword"
    ]
    assert keyword_loci
    assert any(
        locus["line"] == alpha_line
        and locus["status"] == "warranted"
        and "keyword argument binding" in locus.get("reason", "")
        for locus in keyword_loci
    ), keyword_loci
    assert any(
        locus["line"] == splat_line and locus["status"] == "unclassified"
        for locus in keyword_loci
    ), keyword_loci


def test_structural_package_accounting_keeps_unknown_calls_unclassified_next_to_pure_calls(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_mixed_known_unknown_calls"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def expensive(value):
                return value

            def skipped(value):
                return (
                    expensive(value),
                    len(value),
                )

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    return_line = next(
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith("expensive(value)")
    )
    pure_line = next(
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if "len(value)" in line
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_mixed_known_unknown_calls.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_mixed_known_unknown_calls"
    )
    call_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_mixed_known_unknown_calls/api.py")
        and locus["line"] in {return_line, pure_line}
        and locus.get("ast_kind") == "Call"
    ]
    assert call_loci
    assert any(
        locus["status"] == "warranted"
        and "known pure call value term" in locus.get("reason", "")
        and locus["line"] == pure_line
        for locus in call_loci
    ), call_loci
    assert any(
        locus["status"] == "unclassified" and locus["line"] == return_line
        for locus in call_loci
    ), call_loci


def test_structural_package_accounting_refuses_with_context_flow(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_with_context"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def skipped(path):
                with open(path) as handle:
                    data = handle.read()
                    return data

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_with_context.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_with_context"
    )
    with_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_with_context/api.py")
        and locus.get("ast_path", "").startswith("$.module.body[0].body")
    ]
    assert with_loci
    assert not [
        locus for locus in with_loci if locus["status"] == "unclassified"
    ], with_loci
    assert {locus["status"] for locus in with_loci} == {"refused"}
    assert all(
        "with-context flow" in locus.get("reason", "")
        for locus in with_loci
    ), with_loci


def test_structural_package_accounting_refuses_loop_iteration_flow(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_loop_iteration"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def skipped(values):
                current = None
                for value in values:
                    current = value
                while current is None:
                    current = "fallback"
                return current

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_loop_iteration.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_loop_iteration"
    )
    loop_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_loop_iteration/api.py")
        and (
            locus.get("ast_path", "").startswith("$.module.body[0].body[1]")
            or locus.get("ast_path", "").startswith("$.module.body[0].body[2]")
        )
    ]
    assert loop_loci
    assert not [
        locus for locus in loop_loci if locus["status"] == "unclassified"
    ], loop_loci
    assert {locus["status"] for locus in loop_loci} == {"refused"}
    assert all(
        "loop iteration flow" in locus.get("reason", "")
        for locus in loop_loci
    ), loop_loci


def test_structural_package_accounting_refuses_exception_control_flow(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_exception_control"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def skipped(value):
                try:
                    parsed = int(value)
                except ValueError as err:
                    raise RuntimeError("bad") from err
                finally:
                    marker = "done"
                return parsed

            def skipped_raise(value):
                raise ValueError(value)

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_exception_control.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_exception_control"
    )
    exception_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_exception_control/api.py")
        and (
            locus.get("ast_path", "").startswith("$.module.body[0].body[0]")
            or locus.get("ast_path", "").startswith("$.module.body[1].body[0]")
        )
    ]
    assert exception_loci
    assert not [
        locus for locus in exception_loci if locus["status"] == "unclassified"
    ], exception_loci
    assert {locus["status"] for locus in exception_loci} == {"refused"}
    assert all(
        "exception control flow" in locus.get("reason", "")
        for locus in exception_loci
    ), exception_loci


def test_structural_package_accounting_refuses_assert_guard_flow(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_assert_guard"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def skipped(value):
                assert value > 0, "positive only"
                return value

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    assert_line = next(
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith("assert ")
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_assert_guard.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_assert_guard"
    )
    assert_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_assert_guard/api.py")
        and locus["line"] == assert_line
    ]
    assert assert_loci
    assert not [
        locus for locus in assert_loci if locus["status"] == "unclassified"
    ], assert_loci
    assert {locus["status"] for locus in assert_loci} == {"refused"}
    assert all(
        "assert guard flow" in locus.get("reason", "")
        for locus in assert_loci
    ), assert_loci


def test_structural_package_accounting_refuses_standalone_call_expr_flow(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_expr_call_flow"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def skipped(value):
                record(value)
                helper.check(value, strict=True)
                return value

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    call_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith(("record(", "helper.check("))
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_expr_call_flow.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_expr_call_flow"
    )
    call_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_expr_call_flow/api.py")
        and locus["line"] in call_lines
    ]
    assert call_loci
    assert not [
        locus for locus in call_loci if locus["status"] == "unclassified"
    ], call_loci
    assert {locus["status"] for locus in call_loci} == {"refused"}
    assert all(
        "expression call flow" in locus.get("reason", "")
        for locus in call_loci
    ), call_loci


def test_lift_source_refuses_dynamic_receiver_io_package_accounting(
    tmp_path, monkeypatch
):
    pkg = tmp_path / "vendpkg_dynamic_receiver_refused"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            """
            def b64e(s):
                return s.rstrip(b"=")

            def load(fp):
                return fp.read()

            def dump(fp, value):
                fp.write(value)
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_dynamic_receiver_refused.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    dynamic_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_dynamic_receiver_refused/encoding.py")
        and locus.get("line") in {6, 9}
    ]
    assert dynamic_loci
    assert not [
        locus for locus in dynamic_loci if locus["status"] == "unclassified"
    ], dynamic_loci
    assert any(
        locus["status"] == "refused"
        and locus.get("ast_kind") == "Return"
        and "dynamic receiver" in locus.get("reason", "")
        for locus in dynamic_loci
    ), dynamic_loci
    assert any(
        locus["status"] == "refused"
        and locus.get("ast_kind") == "Expr"
        and "dynamic receiver" in locus.get("reason", "")
        for locus in dynamic_loci
    ), dynamic_loci


def test_lift_source_warrants_function_default_literals_as_compiler_facts(
    tmp_path, monkeypatch
):
    pkg = tmp_path / "vendpkg_default_literals"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            """
            def b64e(s):
                return s.rstrip(b"=")

            def skipped(value=None, flag=False, *, mode="strict"):
                return value
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_default_literals.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    default_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_default_literals/encoding.py")
        and locus.get("line") == 5
        and (
            ".args.defaults[" in locus.get("ast_path", "")
            or ".args.kw_defaults[" in locus.get("ast_path", "")
        )
    ]
    assert default_loci
    assert not [
        locus for locus in default_loci if locus["status"] == "unclassified"
    ], default_loci
    assert {locus["status"] for locus in default_loci} == {"warranted"}
    assert all("default literal" in locus.get("reason", "") for locus in default_loci)


def test_lift_source_refuses_nondeterministic_time_package_accounting(
    tmp_path, monkeypatch
):
    pkg = tmp_path / "vendpkg_nondet_time_refused"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            """
            import time

            def b64e(s):
                return s.rstrip(b"=")

            class Clock:
                def get_timestamp(self):
                    return int(time.time())

                def sign(self, value):
                    ts = self.get_timestamp()
                    return value
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_nondet_time_refused.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    nondet_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_nondet_time_refused/encoding.py")
        and locus.get("line") in {9, 12}
    ]
    assert nondet_loci
    assert not [
        locus for locus in nondet_loci if locus["status"] == "unclassified"
    ], nondet_loci
    assert any(
        locus["status"] == "refused"
        and locus.get("line") == 9
        and locus.get("ast_kind") == "Return"
        and "nondeterminism" in locus.get("reason", "")
        for locus in nondet_loci
    ), nondet_loci
    assert any(
        locus["status"] == "refused"
        and locus.get("line") == 12
        and locus.get("ast_kind") == "Assign"
        and "nondeterminism" in locus.get("reason", "")
        for locus in nondet_loci
    ), nondet_loci


def test_structural_package_accounting_refuses_runtime_environment_probes(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_runtime_environment_probe"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            import os
            import platform

            def skipped():
                if platform.system() in ("Linux", "Darwin"):
                    return True
                return os.environ.get("PANDAS_CI", "0") == "1"

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    refused_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith(("if platform.system", "return os.environ"))
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_runtime_environment_probe.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_runtime_environment_probe"
    )
    probe_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_runtime_environment_probe/api.py")
        and locus["line"] in refused_lines
        and locus.get("ast_kind")
        in {"If", "Return", "Compare", "Call", "Attribute", "Name", "Constant"}
    ]
    assert probe_loci
    assert not [
        locus for locus in probe_loci if locus["status"] == "unclassified"
    ], probe_loci
    assert {locus["status"] for locus in probe_loci} == {"refused"}
    assert all(
        "runtime environment probe" in locus.get("reason", "")
        for locus in probe_loci
    ), probe_loci


def test_lift_source_refuses_self_field_runtime_dispatch_package_accounting(
    tmp_path, monkeypatch
):
    pkg = tmp_path / "vendpkg_self_field_dispatch_refused"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            """
            def b64e(s):
                return s.rstrip(b"=")

            class Base:
                def inherited(self, value):
                    return value

            class C(Base):
                def __init__(self, signer, plugin):
                    self.signer = signer
                    self.plugin = plugin

                def helper(self, value):
                    return value

                def inherited_call(self, value):
                    return self.inherited(value)

                def same_class(self, value):
                    return self.helper(value)

                def dynamic_method(self, value):
                    return self.plugin.run(value)

                def dynamic_callable(self, value):
                    return self.signer(value)
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_self_field_dispatch_refused.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    dynamic_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_self_field_dispatch_refused/encoding.py")
        and locus.get("line") in {24, 27}
    ]
    assert dynamic_loci
    assert not [
        locus for locus in dynamic_loci if locus["status"] == "unclassified"
    ], dynamic_loci
    assert any(
        locus["status"] == "refused"
        and locus.get("line") == 24
        and locus.get("ast_kind") == "Return"
        and "runtime field dispatch" in locus.get("reason", "")
        for locus in dynamic_loci
    ), dynamic_loci
    assert any(
        locus["status"] == "refused"
        and locus.get("line") == 27
        and locus.get("ast_kind") == "Return"
        and "runtime field dispatch" in locus.get("reason", "")
        for locus in dynamic_loci
    ), dynamic_loci
    assert not [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_self_field_dispatch_refused/encoding.py")
        and locus.get("line") in {18, 21}
        and locus.get("status") == "refused"
    ], audit["loci"]


def test_lift_source_refuses_runtime_dispatch_guarded_return_package_accounting(
    tmp_path, monkeypatch
):
    pkg = tmp_path / "vendpkg_runtime_dispatch_guarded_return"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    source = textwrap.dedent(
        """
        def b64e(s):
            return s.rstrip(b"=")

        class Verifier:
            def __init__(self, algorithm):
                self.algorithm = algorithm

            def derive_key(self, value):
                return value

            def verify(self, key, value, sig):
                for secret in [key]:
                    derived = self.derive_key(secret)
                    if self.algorithm.verify_signature(derived, value, sig):
                        return True

                return False
        """
    )
    derived_line = next(
        line_no
        for line_no, line in enumerate(source.splitlines(), start=1)
        if "derived = self.derive_key" in line
    )
    return_true_line = next(
        line_no
        for line_no, line in enumerate(source.splitlines(), start=1)
        if "return True" in line
    )
    (pkg / "encoding.py").write_text(source, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_runtime_dispatch_guarded_return.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    guarded_return_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith(
            "vendpkg_runtime_dispatch_guarded_return/encoding.py"
        )
        and locus.get("line") == return_true_line
        and locus.get("ast_kind") in {"Return", "Constant"}
    ]
    derived_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith(
            "vendpkg_runtime_dispatch_guarded_return/encoding.py"
        )
        and locus.get("line") == derived_line
    ]
    assert derived_loci
    assert not [
        locus for locus in derived_loci if locus["status"] == "refused"
    ], derived_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Assign"
        for locus in derived_loci
    ), derived_loci
    assert guarded_return_loci
    assert {locus["status"] for locus in guarded_return_loci} == {"refused"}
    assert all(
        "runtime field dispatch" in locus.get("reason", "")
        for locus in guarded_return_loci
    )


def test_lift_source_refuses_return_from_runtime_dispatch_binding_package_accounting(
    tmp_path, monkeypatch
):
    pkg = tmp_path / "vendpkg_runtime_dispatch_binding_return"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    source = textwrap.dedent(
        """
        def b64e(s):
            return s.rstrip(b"=")

        class Signer:
            def __init__(self, algorithm):
                self.algorithm = algorithm

            def get_signature(self, value):
                sig = self.algorithm.get_signature(value)
                return b64e(sig)
        """
    )
    sig_line = next(
        line_no
        for line_no, line in enumerate(source.splitlines(), start=1)
        if "sig = self.algorithm.get_signature" in line
    )
    return_line = next(
        line_no
        for line_no, line in enumerate(source.splitlines(), start=1)
        if "return b64e(sig)" in line
    )
    (pkg / "encoding.py").write_text(source, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_runtime_dispatch_binding_return.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    return_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith(
            "vendpkg_runtime_dispatch_binding_return/encoding.py"
        )
        and locus.get("line") == return_line
    ]
    sig_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith(
            "vendpkg_runtime_dispatch_binding_return/encoding.py"
        )
        and locus.get("line") == sig_line
    ]
    assert sig_loci
    assert return_loci
    assert not [
        locus for locus in return_loci if locus["status"] == "unclassified"
    ], return_loci
    assert any(
        locus["status"] == "refused"
        and locus.get("ast_kind") == "Assign"
        and "runtime field dispatch" in locus.get("reason", "")
        for locus in sig_loci
    ), sig_loci
    assert all(
        locus["status"] == "refused"
        and "runtime field dispatch" in locus.get("reason", "")
        for locus in return_loci
    ), return_loci


def test_lift_source_refuses_terminal_return_after_try_flow_package_accounting(
    tmp_path, monkeypatch
):
    pkg = tmp_path / "vendpkg_terminal_return_after_try"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    source = textwrap.dedent(
        """
        def b64e(s):
            return s.rstrip(b"=")

        def parse(value):
            return value

        class Timed:
            def to_dt(self, value):
                return value

            def unsign(self, flag=False):
                try:
                    result = self.load()
                except Exception:
                    result = b""

                value, stamp = result.rsplit(b".", 1)
                stamp_int = None

                try:
                    stamp_int = parse(stamp)
                except Exception:
                    pass

                if flag:
                    return value, self.to_dt(stamp_int)

                return value
        """
    )
    if_line = next(
        line_no
        for line_no, line in enumerate(source.splitlines(), start=1)
        if "if flag" in line
    )
    tuple_return_line = next(
        line_no
        for line_no, line in enumerate(source.splitlines(), start=1)
        if "return value, self.to_dt" in line
    )
    fallback_return_line = next(
        line_no
        for line_no, line in enumerate(source.splitlines(), start=1)
        if line_no > tuple_return_line and line.strip() == "return value"
    )
    (pkg / "encoding.py").write_text(source, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_terminal_return_after_try.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    tail_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_terminal_return_after_try/encoding.py")
        and locus.get("line")
        in {if_line, tuple_return_line, fallback_return_line}
    ]
    assert tail_loci
    assert not [
        locus for locus in tail_loci if locus["status"] == "unclassified"
    ], tail_loci
    assert all(
        locus["status"] == "refused"
        and "terminal return" in locus.get("reason", "")
        for locus in tail_loci
    ), tail_loci


def test_lift_source_refuses_receiver_iteration_header_package_accounting(
    tmp_path, monkeypatch
):
    pkg = tmp_path / "vendpkg_receiver_iteration_refused"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    source = textwrap.dedent(
        """
        def b64e(s):
            return s.rstrip(b"=")

        class Loader:
            def __init__(self, items):
                self.items = items

            def loads(self):
                for signer in reversed(self.items):
                    return signer

                return None
        """
    )
    for_line = next(
        line_no
        for line_no, line in enumerate(source.splitlines(), start=1)
        if "for signer in reversed" in line
    )
    return_line = next(
        line_no
        for line_no, line in enumerate(source.splitlines(), start=1)
        if "return signer" in line
    )
    tail_return_line = next(
        line_no
        for line_no, line in enumerate(source.splitlines(), start=1)
        if "return None" in line
    )
    (pkg / "encoding.py").write_text(source, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_receiver_iteration_refused.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    loop_header_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_receiver_iteration_refused/encoding.py")
        and locus.get("line") == for_line
    ]
    assert loop_header_loci
    assert {locus["status"] for locus in loop_header_loci} == {"refused"}
    assert all(
        "runtime receiver iteration" in locus.get("reason", "")
        for locus in loop_header_loci
    )
    body_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_receiver_iteration_refused/encoding.py")
        and locus.get("line") == return_line
    ]
    assert body_loci
    assert not [locus for locus in body_loci if locus["status"] == "refused"]
    tail_return_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_receiver_iteration_refused/encoding.py")
        and locus.get("line") == tail_return_line
        and locus.get("ast_kind") in {"Return", "Constant"}
    ]
    assert tail_return_loci
    assert {locus["status"] for locus in tail_return_loci} == {"refused"}
    assert all(
        "runtime receiver iteration" in locus.get("reason", "")
        for locus in tail_return_loci
    )


def test_lift_source_refuses_generator_flow_package_accounting(
    tmp_path,
    monkeypatch,
):
    pkg = tmp_path / "vendpkg_generator_flow_refused"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            """
            def iter_values(items, fallback):
                yield fallback(items)

                for item in items:
                    if isinstance(item, dict):
                        kwargs = item
                    else:
                        kwargs = {}

                    yield fallback(item, **kwargs)

            def b64e(s):
                return s.rstrip(b"=")
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_generator_flow_refused.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    generator_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_generator_flow_refused/encoding.py")
        and locus.get("ast_path", "").startswith("$.module.body[0].body")
    ]
    assert generator_loci
    assert not [
        locus for locus in generator_loci if locus["status"] == "unclassified"
    ], generator_loci
    assert any(
        locus["status"] == "refused"
        and locus.get("ast_kind") == "Yield"
        and "generator/yield flow" in locus.get("reason", "")
        for locus in generator_loci
    ), generator_loci
    assert any(
        locus["status"] == "refused"
        and locus.get("ast_kind") == "For"
        and "generator/yield flow" in locus.get("reason", "")
        for locus in generator_loci
    ), generator_loci


def test_lift_source_accounts_stdlib_delegation_static_attribute_keyword(
    tmp_path,
    monkeypatch,
):
    from sugar_lift_py_tests.translate_universe import (
        delegation_universe_for_callee,
    )

    pkg = tmp_path / "vendpkg_stdlib_attr_kw"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            """
            from datetime import datetime
            from datetime import timezone

            def to_datetime(ts):
                return datetime.fromtimestamp(ts, tz=timezone.utc)

            def b64e(s):
                return s.rstrip(b"=")
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    delegation_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_stdlib_attr_kw.encoding as enc

        def test_token():
            assert enc.to_datetime(1) == enc.to_datetime(1)
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.delegation-universe"
        and audit.get("universe_kind") == "delegation-stdlib"
        and audit["source_memento"]["file"].endswith(
            "vendpkg_stdlib_attr_kw/encoding.py"
        )
    )
    assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "delegation" in locus.get("reason", "")
        for locus in audit["loci"]
    ), audit


def test_lift_source_classifies_package_signatures_and_docstrings_as_support(
    tmp_path, monkeypatch
):
    pkg = tmp_path / "vendpkg_decl_support"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            '''
            class Helper:
                """Declaration metadata, not a value constraint."""

                @staticmethod
                def identity(value: str) -> str:
                    return value

            def b64e(s: str | bytes = b"abc") -> bytes:
                """Docstring metadata, not a value constraint."""
                return s.rstrip(b"=")

            def skipped(value: str) -> str:
                return value + "!"

            def typed_only(
                value: str | bytes,
            ) -> bytes:
                return value
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_decl_support.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    support_kinds = {
        locus.get("ast_kind")
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_decl_support/encoding.py")
        and locus["status"] == "support"
    }
    assert {"ClassDef", "FunctionDef", "arg", "Expr", "Constant"} <= support_kinds
    assert not [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_decl_support/encoding.py")
        and locus.get("ast_kind") in {"ClassDef", "FunctionDef", "arg"}
        and locus["status"] == "unclassified"
    ]
    assert not [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_decl_support/encoding.py")
        and (
            ".annotation" in locus.get("ast_path", "")
            or ".returns" in locus.get("ast_path", "")
        )
        and locus["status"] == "unclassified"
    ]
    assert not [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_decl_support/encoding.py")
        and ".decorator_list" in locus.get("ast_path", "")
        and locus["status"] == "unclassified"
    ]


def test_lift_source_classifies_static_assignments_as_warranted_compiler_facts(
    tmp_path, monkeypatch
):
    pkg = tmp_path / "vendpkg_static_warranted"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            '''
            import string
            import struct
            import typing as t

            _alphabet = f"{string.ascii_letters}{string.digits}-_=".encode("ascii")
            _int64_struct = struct.Struct(">Q")
            _int_to_bytes = _int64_struct.pack
            _bytes_to_int = t.cast("t.Callable[[bytes], tuple[int]]", _int64_struct.unpack)

            class Holder:
                default_key_derivation: str = "django-concat"
                typed_only: str

            def b64e(s):
                return s.rstrip(b"=")

            def skipped(value):
                local = value
                return local
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_static_warranted.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    static_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_static_warranted/encoding.py")
        and locus["line"] in {6, 7, 8, 9}
    ]
    assert static_loci
    assert {locus["status"] for locus in static_loci} == {"warranted"}
    assert all("static binding" in locus.get("reason", "") for locus in static_loci)
    class_static_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_static_warranted/encoding.py")
        and locus["line"] == 12
    ]
    assert class_static_loci
    assert not [locus for locus in class_static_loci if locus["status"] == "unclassified"]
    assert any(
        locus["status"] == "warranted" and locus.get("ast_kind") == "AnnAssign"
        for locus in class_static_loci
    ), class_static_loci
    assert any(
        locus["status"] == "support"
        and locus["file"].endswith("vendpkg_static_warranted/encoding.py")
        and locus["line"] == 13
        and locus.get("ast_kind") == "AnnAssign"
        for locus in audit["loci"]
    ), audit
    assert any(
        locus["status"] == "warranted"
        and locus["file"].endswith("vendpkg_static_warranted/encoding.py")
        and locus["line"] == 19
        and locus.get("ast_kind") == "Assign"
        and "SSA alias" in locus.get("reason", "")
        for locus in audit["loci"]
    ), audit


def test_lift_source_warrants_local_name_assignment_accounting(
    tmp_path, monkeypatch
):
    pkg = tmp_path / "vendpkg_local_name_warranted"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            '''
            def b64e(s):
                return s.rstrip(b"=")

            def skipped(value):
                alias = value
                computed = helper(value)
                flag = False
                missing = None
                empty = {}
                return alias
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_local_name_warranted.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    local_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_local_name_warranted/encoding.py")
    ]
    assert any(
        locus["status"] == "warranted"
        and locus["line"] == 6
        and locus.get("ast_kind") == "Assign"
        and "SSA alias" in locus.get("reason", "")
        for locus in local_loci
    ), local_loci
    assert not [
        locus
        for locus in local_loci
        if locus["line"] == 6
        and locus.get("ast_kind") == "Name"
        and locus["status"] == "unclassified"
    ], local_loci
    assert any(
        locus["status"] == "warranted"
        and locus["line"] == 7
        and locus.get("ast_kind") == "Name"
        and locus.get("ast_path", "").endswith(".targets[0]")
        for locus in local_loci
    ), local_loci
    assert any(
        locus["status"] == "unclassified"
        and locus["line"] == 7
        and locus.get("ast_kind") == "Call"
        for locus in local_loci
    ), local_loci
    for line, ast_kind in ((8, "Constant"), (9, "Constant"), (10, "Dict")):
        assert any(
            locus["status"] == "warranted"
            and locus["line"] == line
            and locus.get("ast_kind") == ast_kind
            and "local literal binding" in locus.get("reason", "")
            for locus in local_loci
        ), local_loci
    assert any(
        locus["status"] == "warranted"
        and locus["line"] == 8
        and locus.get("ast_kind") == "Assign"
        and "local literal binding" in locus.get("reason", "")
        for locus in local_loci
        ), local_loci


def test_structural_package_accounting_warrants_local_binding_node_without_hiding_rhs(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_local_binding_node"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            '''
            def b64e(s):
                return s.rstrip(b"=")

            def skipped(value):
                computed = helper(value)
                return computed
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_local_binding_node.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    binding_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_local_binding_node/encoding.py")
        and locus["line"] == 6
    ]
    assert binding_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Assign"
        and "local SSA binding" in locus.get("reason", "")
        for locus in binding_loci
    ), binding_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Name"
        and locus.get("ast_path", "").endswith(".targets[0]")
        and "local SSA binding" in locus.get("reason", "")
        for locus in binding_loci
    ), binding_loci
    assert any(
        locus["status"] == "unclassified"
        and locus.get("ast_kind") == "Call"
        for locus in binding_loci
    ), binding_loci


def test_structural_package_accounting_warrants_chained_local_binding_targets(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_chained_binding"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            '''
            def b64e(s):
                return s.rstrip(b"=")

            def skipped(value):
                first = second = helper(value)
                return first
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_chained_binding.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    binding_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_chained_binding/encoding.py")
        and locus["line"] == 6
    ]
    assert binding_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Assign"
        and "local SSA binding" in locus.get("reason", "")
        for locus in binding_loci
    ), binding_loci
    target_loci = [
        locus
        for locus in binding_loci
        if locus["status"] == "warranted"
        and locus.get("ast_kind") == "Name"
        and ".targets[" in locus.get("ast_path", "")
    ]
    assert len(target_loci) == 2, binding_loci
    assert all(
        "local SSA binding target" in locus.get("reason", "")
        for locus in target_loci
    ), target_loci
    assert any(
        locus["status"] == "unclassified"
        and locus.get("ast_kind") == "Call"
        for locus in binding_loci
    ), binding_loci


def test_structural_package_accounting_refuses_assignment_target_mutation(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_assignment_mutation"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "api.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def skipped(obj, data, idx):
                obj.value = data
                data[idx] = obj.value
                obj.count += 1
                data[idx] += 1
                return data

            def ok():
                return "ok"
            """
        ),
        encoding="utf-8",
    )
    mutation_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if any(
            marker in line
            for marker in ("obj.value =", "data[idx] =", "obj.count +=", "data[idx] +=")
        )
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_assignment_mutation.api as api

        def test_ok():
            assert api.ok() == "ok"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendpkg_assignment_mutation"
    )
    mutation_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_assignment_mutation/api.py")
        and locus["line"] in mutation_lines
    ]
    assert mutation_loci
    assert not [
        locus for locus in mutation_loci if locus["status"] == "unclassified"
    ], mutation_loci
    assert {locus["status"] for locus in mutation_loci} == {"refused"}
    assert all(
        "assignment target mutation" in locus.get("reason", "")
        for locus in mutation_loci
    ), mutation_loci


def test_lift_source_warrants_local_adapter_assignment_accounting(
    tmp_path, monkeypatch
):
    from sugar_lift_py_tests.translate_universe import bytes_identity_universe_for_callee

    pkg = tmp_path / "vendpkg_adapter_assignment_warranted"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            '''
            def want_bytes(s, encoding="utf-8", errors="strict"):
                if isinstance(s, str):
                    s = s.encode(encoding, errors)

                return s

            def skipped(value):
                value = want_bytes(value)
                nested = want_bytes(helper(value))
                return value

            class Holder:
                def __init__(self, sep):
                    self.sep = want_bytes(sep)

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()
    bytes_identity_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_adapter_assignment_warranted.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    local_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_adapter_assignment_warranted/encoding.py")
    ]
    assert not [
        locus
        for locus in local_loci
        if locus["line"] == 9 and locus["status"] == "unclassified"
    ], local_loci
    assert any(
        locus["status"] == "warranted"
        and locus["line"] == 9
        and locus.get("ast_kind") == "Call"
        and "adapter assignment" in locus.get("reason", "")
        for locus in local_loci
    ), local_loci
    assert not [
        locus
        for locus in local_loci
        if locus["line"] == 15 and locus["status"] == "unclassified"
    ], local_loci
    assert any(
        locus["status"] == "warranted"
        and locus["line"] == 15
        and locus.get("ast_kind") == "Call"
        and "adapter assignment" in locus.get("reason", "")
        for locus in local_loci
    ), local_loci
    assert any(
        locus["status"] == "unclassified"
        and locus["line"] == 10
        and locus.get("ast_kind") == "Call"
        for locus in local_loci
    ), local_loci


def test_lift_source_classifies_list_adapter_body_as_package_warranted(
    tmp_path,
    monkeypatch,
):
    from sugar_lift_py_tests.translate_universe import (
        bytes_identity_universe_for_callee,
        list_adapter_universe_for_callee,
    )

    pkg = tmp_path / "vendpkg_list_adapter_body"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            """
            def want_bytes(s, encoding="utf-8", errors="strict"):
                if isinstance(s, str):
                    s = s.encode(encoding, errors)

                return s


            def _make_keys_list(secret_key):
                if isinstance(secret_key, (str, bytes)):
                    return [want_bytes(secret_key)]

                return [want_bytes(s) for s in secret_key]


            def b64e(s):
                return s.rstrip(b"=")
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()
    bytes_identity_universe_for_callee.cache_clear()
    list_adapter_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_list_adapter_body.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    helper_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_list_adapter_body/encoding.py")
        and locus.get("ast_path", "").startswith("$.module.body[1]")
    ]
    assert helper_loci
    assert not [
        locus for locus in helper_loci if locus["status"] == "unclassified"
    ], helper_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "ListComp"
        and "list-adapter" in locus.get("reason", "")
        for locus in helper_loci
    ), helper_loci


def test_lift_source_classifies_delegation_body_as_package_warranted(
    tmp_path,
    monkeypatch,
):
    from sugar_lift_py_tests.translate_universe import (
        delegation_universe_for_callee,
    )

    pkg = tmp_path / "vendpkg_delegation_body"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            """
            import typing as t

            def g(seed):
                return "fixed"


            def f(seed):
                return t.cast(str, g(seed))


            def b64e(s):
                return s.rstrip(b"=")
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()
    delegation_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_delegation_body.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    helper_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_delegation_body/encoding.py")
        and locus.get("ast_path", "").startswith("$.module.body[2]")
    ]
    assert helper_loci
    assert not [
        locus for locus in helper_loci if locus["status"] == "unclassified"
    ], helper_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "delegation" in locus.get("reason", "")
        for locus in helper_loci
    ), helper_loci


def test_lift_source_classifies_receiver_method_delegation_body_as_package_warranted(
    tmp_path,
    monkeypatch,
):
    from sugar_lift_py_tests.translate_universe import (
        delegation_universe_for_callee,
    )

    pkg = tmp_path / "vendpkg_receiver_delegation_body"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            """
            class Base:
                def inherited(self, value):
                    return value

            class C(Base):
                def helper(self, value):
                    return value

                def inherited_call(self, value):
                    return self.inherited(value)

                def same_class_call(self, value):
                    return self.helper(value)

            def b64e(s):
                return s.rstrip(b"=")
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()
    delegation_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_receiver_delegation_body.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    receiver_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_receiver_delegation_body/encoding.py")
        and locus.get("line") in {11, 14}
    ]
    assert receiver_loci
    assert not [
        locus for locus in receiver_loci if locus["status"] == "unclassified"
    ], receiver_loci
    assert all(
        locus["status"] == "warranted"
        and "delegation" in locus.get("reason", "")
        for locus in receiver_loci
        if locus.get("ast_kind") == "Return"
    ), receiver_loci


def test_lift_source_accounts_stdlib_delegation_nested_receiver_arg(
    tmp_path,
    monkeypatch,
):
    from sugar_lift_py_tests.translate_universe import (
        delegation_universe_for_callee,
    )

    pkg = tmp_path / "vendpkg_stdlib_receiver_arg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            """
            import hmac

            class Algo:
                def get_signature(self, key, value):
                    return value

                def verify_signature(self, key, value, sig):
                    return hmac.compare_digest(
                        sig,
                        self.get_signature(key, value),
                    )
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    delegation_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_stdlib_receiver_arg.encoding as enc

        def test_token():
            alg = enc.Algo()
            assert alg.verify_signature(b"k", b"v", b"v") == True
        """,
    )

    audits = {
        audit["source_memento"]["source_function_name"]: audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.delegation-universe"
        and audit["source_memento"]["file"].endswith(
            "vendpkg_stdlib_receiver_arg/encoding.py"
        )
    }
    assert {"Algo.verify_signature", "Algo.get_signature"} <= set(audits), audits
    verify_audit = audits["Algo.verify_signature"]
    assert verify_audit["universe_kind"] == "delegation-stdlib"
    assert verify_audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "delegation" in locus.get("reason", "")
        for locus in verify_audit["loci"]
    ), verify_audit
    helper_audit = audits["Algo.get_signature"]
    assert helper_audit["universe_kind"] == "identity"
    assert helper_audit["totals"]["unclassified_source"] == 0


def test_lift_source_classifies_exception_handler_raise_body_as_package_warranted(
    tmp_path,
    monkeypatch,
):
    from sugar_lift_py_tests.translate_universe import (
        exception_handler_raise_universe_for_callee,
    )

    pkg = tmp_path / "vendpkg_exception_handler_body"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            """
            class BadPayload(Exception):
                pass

            class Serializer:
                def load_payload(self, payload):
                    try:
                        return self.serializer.loads(payload)
                    except Exception as e:
                        raise BadPayload("bad", original_error=e) from e

            def b64e(s):
                return s.rstrip(b"=")
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()
    exception_handler_raise_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_exception_handler_body.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    handler_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_exception_handler_body/encoding.py")
        and locus.get("line") in {7, 8, 9, 10}
    ]
    assert handler_loci
    assert not [
        locus for locus in handler_loci if locus["status"] == "unclassified"
    ], handler_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Try"
        and "exception-handler-raise" in locus.get("reason", "")
        for locus in handler_loci
    ), handler_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Raise"
        and "exception-handler-raise" in locus.get("reason", "")
        for locus in handler_loci
    ), handler_loci


def test_lift_source_refuses_unhandled_try_flow_package_accounting(
    tmp_path,
    monkeypatch,
):
    pkg = tmp_path / "vendpkg_unhandled_try_flow"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            """
            def maybe(value):
                try:
                    return value + 1
                except Exception:
                    return value

            def b64e(s):
                return s.rstrip(b"=")
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_unhandled_try_flow.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    try_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_unhandled_try_flow/encoding.py")
        and locus.get("line") in {3, 4, 5, 6}
    ]
    assert try_loci
    assert not [
        locus for locus in try_loci if locus["status"] == "unclassified"
    ], try_loci
    assert any(
        locus["status"] == "refused"
        and locus.get("ast_kind") == "Try"
        and "path-sensitive try/except" in locus.get("reason", "")
        for locus in try_loci
    ), try_loci


def test_lift_source_refuses_unhandled_raise_path_package_accounting(
    tmp_path,
    monkeypatch,
):
    pkg = tmp_path / "vendpkg_unhandled_raise_path"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    source = textwrap.dedent(
        """
        def maybe(value):
            if value:
                if value == 2:
                    pass
                raise ValueError(value)
            if value == 0:
                return 1
            return value + 1

        def b64e(s):
            return s.rstrip(b"=")
        """
    )
    outer_guard_line = next(
        line_no
        for line_no, line in enumerate(source.splitlines(), start=1)
        if "if value:" in line
    )
    nested_guard_line = next(
        line_no
        for line_no, line in enumerate(source.splitlines(), start=1)
        if "if value == 2" in line
    )
    raise_line = next(
        line_no
        for line_no, line in enumerate(source.splitlines(), start=1)
        if "raise ValueError" in line
    )
    (pkg / "encoding.py").write_text(source, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_unhandled_raise_path.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    raise_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_unhandled_raise_path/encoding.py")
        and locus.get("line") == raise_line
    ]
    assert raise_loci
    assert not [
        locus for locus in raise_loci if locus["status"] == "unclassified"
    ], raise_loci
    assert any(
        locus["status"] == "refused"
        and locus.get("ast_kind") == "Raise"
        and "raise path" in locus.get("reason", "")
        for locus in raise_loci
    ), raise_loci
    guard_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_unhandled_raise_path/encoding.py")
        and locus.get("line") == outer_guard_line
        and locus.get("ast_kind") in {"If", "Name"}
    ]
    assert guard_loci
    assert {locus["status"] for locus in guard_loci} == {"refused"}
    assert all("raise path" in locus.get("reason", "") for locus in guard_loci)
    nested_guard_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_unhandled_raise_path/encoding.py")
        and locus.get("line") == nested_guard_line
        and locus.get("ast_kind") in {"If", "Compare", "Name", "Constant"}
    ]
    assert nested_guard_loci
    assert {locus["status"] for locus in nested_guard_loci} == {"refused"}
    assert all(
        "raise path" in locus.get("reason", "") for locus in nested_guard_loci
    )


def test_lift_source_classifies_typing_cast_wrapper_as_package_warranted(
    tmp_path,
    monkeypatch,
):
    pkg = tmp_path / "vendpkg_cast_wrapper"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            """
            import typing as t

            def dynamic(seed):
                return t.cast(str, seed.transform(noisy()))


            def b64e(s):
                return s.rstrip(b"=")
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_cast_wrapper.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    local_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_cast_wrapper/encoding.py")
    ]
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and locus.get("ast_path") == "$.module.body[1].body[0].value"
        and "transparent typing cast" in locus.get("reason", "")
        for locus in local_loci
    ), local_loci
    assert any(
        locus["status"] == "unclassified"
        and locus.get("ast_kind") == "Call"
        and locus.get("ast_path") == "$.module.body[1].body[0].value.args[1]"
        for locus in local_loci
    ), local_loci


def test_lift_source_classifies_imported_typing_cast_wrapper_as_package_warranted(
    tmp_path,
    monkeypatch,
):
    pkg = tmp_path / "vendpkg_imported_cast_wrapper"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            """
            from typing import cast

            def dynamic(seed):
                return cast(str, seed.transform(noisy()))


            def b64e(s):
                return s.rstrip(b"=")
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_imported_cast_wrapper.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    local_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_imported_cast_wrapper/encoding.py")
    ]
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and locus.get("ast_path") == "$.module.body[1].body[0].value"
        and "transparent typing cast" in locus.get("reason", "")
        for locus in local_loci
    ), local_loci
    assert any(
        locus["status"] == "unclassified"
        and locus.get("ast_kind") == "Call"
        and locus.get("ast_path") == "$.module.body[1].body[0].value.args[1]"
        for locus in local_loci
    ), local_loci


def test_lift_source_warrants_guarded_default_value_flow(tmp_path, monkeypatch):
    pkg = tmp_path / "vendpkg_guarded_default_warranted"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            '''
            class Holder:
                default_value = "fallback"

                def skipped(self, value, callback):
                    if value is None:
                        value = self.default_value
                    if callback is None:
                        callback = build_default()
                    return value

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_guarded_default_warranted.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    local_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_guarded_default_warranted/encoding.py")
    ]
    assert any(
        locus["status"] == "warranted"
        and locus["line"] == 6
        and locus.get("ast_kind") == "If"
        and "guarded default value flow" in locus.get("reason", "")
        for locus in local_loci
    ), local_loci
    assert not [
        locus
        for locus in local_loci
        if locus["line"] in {6, 7}
        and locus["status"] == "unclassified"
    ], local_loci
    assert any(
        locus["status"] == "unclassified"
        and locus["line"] == 9
        and locus.get("ast_kind") == "Call"
        for locus in local_loci
    ), local_loci


def test_lift_source_warrants_assert_guard_universe_in_package_accounting(
    tmp_path, monkeypatch
):
    from sugar_lift_py_tests.translate_universe import guard_universe_for_callee

    pkg = tmp_path / "vendpkg_assert_guard_accounting"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            '''
            def positive(x):
                assert x > 0
                return x
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    guard_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_assert_guard_accounting.encoding as enc

        def test_positive():
            assert enc.positive(3) == 3
        """,
    )

    guard_audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.guard-universe"
    )
    assert guard_audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Assert"
        and locus["line"] == 3
        and "guard" in locus.get("reason", "")
        for locus in guard_audit["loci"]
    ), guard_audit

    package_audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    guard_loci = [
        locus
        for locus in package_audit["loci"]
        if locus["file"].endswith("vendpkg_assert_guard_accounting/encoding.py")
        and locus["line"] == 3
    ]
    assert guard_loci
    assert not [
        locus for locus in guard_loci if locus["status"] == "unclassified"
    ], guard_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Assert"
        and "guard" in locus.get("reason", "")
        for locus in guard_loci
    ), guard_loci


def test_package_accounting_discovers_untriggered_assert_guard_universe(
    tmp_path, monkeypatch
):
    from sugar_lift_py_tests.translate_universe import guard_universe_for_callee

    pkg = tmp_path / "vendpkg_untriggered_assert_guard"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            '''
            def checked(x):
                assert x > 0
                return x

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    guard_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_untriggered_assert_guard.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    package_audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    guard_loci = [
        locus
        for locus in package_audit["loci"]
        if locus["file"].endswith("vendpkg_untriggered_assert_guard/encoding.py")
        and locus["line"] == 3
    ]
    assert guard_loci
    assert not [
        locus for locus in guard_loci if locus["status"] == "unclassified"
    ], guard_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Assert"
        and "guard" in locus.get("reason", "")
        for locus in guard_loci
    ), guard_loci


def test_package_accounting_warrants_none_identity_guard_universe(
    tmp_path, monkeypatch
):
    from sugar_lift_py_tests.translate_universe import guard_universe_for_callee

    pkg = tmp_path / "vendpkg_none_guard_accounting"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            '''
            def require_value(x):
                if x is None:
                    raise ValueError("missing")
                return x

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    guard_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_none_guard_accounting.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    guard_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_none_guard_accounting/encoding.py")
        and locus["line"] in {3, 4}
    ]
    assert guard_loci
    assert not [
        locus for locus in guard_loci if locus["status"] == "unclassified"
    ], guard_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "If"
        and "guard" in locus.get("reason", "")
        for locus in guard_loci
    ), guard_loci


def test_lift_source_classifies_super_init_as_package_support(tmp_path, monkeypatch):
    pkg = tmp_path / "vendpkg_super_init_support"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            '''
            class PayloadError(Exception):
                def __init__(self, message, payload=None):
                    super().__init__(message, payload)
                    self.payload = payload

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_super_init_support.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    super_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_super_init_support/encoding.py")
        and locus["line"] == 4
    ]
    assert super_loci
    assert not [
        locus
        for locus in super_loci
        if locus["status"] == "unclassified"
    ], super_loci
    assert {locus["status"] for locus in super_loci} == {"support"}
    assert {"Expr", "Call", "Attribute", "Name"} <= {
        locus.get("ast_kind") for locus in super_loci
    }
    assert all(
        "base constructor call" in locus.get("reason", "")
        for locus in super_loci
    )


def test_structural_package_accounting_classifies_super_init_as_support(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_structural_super_init_support"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            '''
            class PayloadError(Exception):
                def __init__(self, message, payload=None):
                    super().__init__(message, payload)
                    self.payload = payload

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_structural_super_init_support.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    super_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_structural_super_init_support/encoding.py")
        and locus["line"] == 4
    ]
    assert super_loci
    assert not [
        locus
        for locus in super_loci
        if locus["status"] == "unclassified"
    ], super_loci
    assert {locus["status"] for locus in super_loci} == {"support"}
    assert {"Expr", "Call", "Attribute", "Name"} <= {
        locus.get("ast_kind") for locus in super_loci
    }
    assert all(
        "base constructor call" in locus.get("reason", "")
        for locus in super_loci
    )


def test_lift_source_classifies_type_checking_blocks_as_support_or_inactive(
    tmp_path, monkeypatch
):
    pkg = tmp_path / "vendpkg_type_checking"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            '''
            import typing as t
            from typing import TYPE_CHECKING

            if t.TYPE_CHECKING:
                import typing_extensions as te
                _TSerialized = te.TypeVar("_TSerialized", bound=t.Union[str, bytes])
            else:
                _TSerialized = t.TypeVar("_TSerialized", bound=t.Union[str, bytes])

            if TYPE_CHECKING:
                from vendpkg_type_checking import only_for_types

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_type_checking.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    type_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_type_checking/encoding.py")
        and locus.get("ast_path", "").startswith("$.module.body[2]")
    ]
    assert type_loci
    assert {locus["status"] for locus in type_loci} <= {"support", "inactive"}
    assert not [
        locus
        for locus in type_loci
        if locus["status"] == "unclassified"
    ]
    assert any(locus["status"] == "inactive" for locus in type_loci), type_loci
    direct_type_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_type_checking/encoding.py")
        and locus.get("ast_path", "").startswith("$.module.body[3]")
    ]
    assert direct_type_loci
    assert {locus["status"] for locus in direct_type_loci} <= {
        "support",
        "inactive",
    }
    assert not [
        locus
        for locus in direct_type_loci
        if locus["status"] == "unclassified"
    ], direct_type_loci


def test_lift_source_classifies_overload_declarations_as_type_metadata(
    tmp_path, monkeypatch
):
    pkg = tmp_path / "vendpkg_overload_metadata"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            '''
            import typing as t

            class Codec:
                @t.overload
                def encode(self, value: str, fallback: None = None) -> str: ...

                @t.overload
                def encode(self, value: bytes, fallback: bytes | None = None) -> bytes: ...

                def encode(self, value, fallback=None):
                    return value

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_overload_metadata.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    overload_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_overload_metadata/encoding.py")
        and (
            locus.get("ast_path", "").startswith("$.module.body[1].body[0]")
            or locus.get("ast_path", "").startswith("$.module.body[1].body[1]")
        )
    ]
    assert overload_loci
    assert not [
        locus for locus in overload_loci if locus["status"] == "unclassified"
    ], overload_loci
    assert any(
        locus["status"] == "support"
        and locus.get("ast_kind") == "Attribute"
        and "overload" in locus.get("reason", "")
        for locus in overload_loci
    ), overload_loci
    assert any(
        locus["status"] == "inactive"
        and locus.get("ast_kind") == "Expr"
        and "overload" in locus.get("reason", "")
        for locus in overload_loci
    ), overload_loci
    assert any(
        locus["file"].endswith("vendpkg_overload_metadata/encoding.py")
        and locus.get("ast_path") == "$.module.body[1].body[2].body[0]"
        and locus["status"] == "warranted"
        and "delegation" in locus.get("reason", "")
        for locus in audit["loci"]
    ), audit


def test_lift_source_classifies_imported_overload_declarations_as_type_metadata(
    tmp_path, monkeypatch
):
    pkg = tmp_path / "vendpkg_imported_overload_metadata"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            '''
            from typing import overload as type_overload

            class Codec:
                @type_overload
                def encode(self, value: str, fallback: None = None) -> str: ...

                @type_overload
                def encode(self, value: bytes, fallback: bytes | None = None) -> bytes: ...

                def encode(self, value, fallback=None):
                    return value

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_imported_overload_metadata.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    overload_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_imported_overload_metadata/encoding.py")
        and (
            locus.get("ast_path", "").startswith("$.module.body[1].body[0]")
            or locus.get("ast_path", "").startswith("$.module.body[1].body[1]")
        )
    ]
    assert overload_loci
    assert not [
        locus for locus in overload_loci if locus["status"] == "unclassified"
    ], overload_loci
    assert any(
        locus["status"] == "support"
        and locus.get("ast_kind") == "Name"
        and "overload" in locus.get("reason", "")
        for locus in overload_loci
    ), overload_loci
    assert any(
        locus["status"] == "inactive"
        and locus.get("ast_kind") == "Expr"
        and "overload" in locus.get("reason", "")
        for locus in overload_loci
    ), overload_loci


def test_lift_source_classifies_type_alias_declarations_as_type_metadata(
    tmp_path, monkeypatch
):
    pkg = tmp_path / "vendpkg_type_alias_metadata"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            '''
            from typing import Literal, TypeAlias

            Label: TypeAlias = Literal["left", "right"] | tuple[str, ...]

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    translate_universe_for_callee.cache_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_type_alias_metadata.encoding as enc

        def test_token():
            assert enc.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    alias_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_type_alias_metadata/encoding.py")
        and locus.get("ast_path", "").startswith("$.module.body[1]")
    ]
    assert alias_loci
    assert not [
        locus for locus in alias_loci if locus["status"] == "unclassified"
    ], alias_loci
    assert any(
        locus["status"] == "support"
        and locus.get("ast_kind") == "AnnAssign"
        and "TypeAlias" in locus.get("reason", "")
        for locus in alias_loci
    ), alias_loci


def test_universe_row_emitted_once_per_base_across_tests(vendor_path):
    # Same callee + same concrete args in TWO test functions: the bases
    # collapse cross-location (EUF), and the bundle must carry exactly ONE
    # ::universe decl -- a duplicate name would collide at mint.
    vendor_path("venduniv_once", VENDOR_TRANSLATE)
    out = _lift(
        """
        import venduniv_once

        def test_urlsafe_a():
            assert venduniv_once.urlsafe("abc") == "abc"

        def test_urlsafe_b():
            assert venduniv_once.urlsafe("abc") == "abc"
        """
    )
    assert len(_universe_decls(out)) == 1


def test_refused_walk_surfaces_loud_warning(vendor_path):
    vendor_path("venduniv_warn", VENDOR_SWAP)
    out = _lift(
        """
        import venduniv_warn

        def test_urlsafe():
            assert venduniv_warn.urlsafe("abc") == "abc"
        """
    )
    assert not _universe_decls(out)
    reasons = [w.reason for w in out.warnings if "translate-universe" in w.item_name]
    assert reasons and "reintroduces" in reasons[0]


def test_bad_twin_flip_changes_forbidden_set(vendor_path):
    # Perturb the vendor's maketrans FROM side: the emitted universe must
    # change with it -- proves the row carries the walked table, not
    # decoration.
    vendor_path("venduniv_flip", VENDOR_FLIPPED)
    out = _lift(
        """
        import venduniv_flip

        def test_urlsafe():
            assert venduniv_flip.urlsafe("abc") == "abc"
        """
    )
    atoms = _universe_atoms(out)
    assert len(atoms) == 1
    assert atoms[0].args[1].value == "!+"


def test_non_translate_callee_emits_nothing_and_no_warning(vendor_path):
    vendor_path("venduniv_fog", VENDOR_PLAIN)
    out = _lift(
        """
        import venduniv_fog

        def test_plain():
            assert venduniv_fog.plain("a") == "ax"
        """
    )
    assert not _universe_decls(out)
    assert not [w for w in out.warnings if "translate-universe" in w.item_name]


# --- the rstrip family (no-suffix-chars): the token-padding shape ---

VENDOR_RSTRIP = '''
def _inner(s):
    return s


def b64e(s):
    s = _inner(s)
    return _inner(s).rstrip(b"=")
'''


VENDOR_WANT_BYTES_RSTRIP = '''
def _inner(s):
    return s


def want_bytes(s, encoding="utf-8", errors="strict"):
    if isinstance(s, str):
        s = s.encode(encoding, errors)

    return s


def b64e(s):
    s = want_bytes(s)
    return _inner(s).rstrip(b"=")
'''


VENDOR_LSTRIP = '''
def _pack(n):
    return b"\\x00\\x01"


def int_to_bytes(n):
    return _pack(n).lstrip(b"\\x00")
'''


def test_rstrip_family_walks(vendor_path):
    vendor_path("vendrstrip_ok", VENDOR_RSTRIP)
    universe, refusal = translate_universe_for_callee("vendrstrip_ok.b64e")
    assert refusal is None
    assert universe is not None
    assert universe.kind == "no-suffix-chars"
    assert universe.forbidden == "="


def test_rstrip_emits_negated_suffix_conjunct(vendor_path):
    vendor_path("vendrstrip_l2", VENDOR_RSTRIP)
    out = _lift(
        """
        import vendrstrip_l2

        def test_token():
            assert vendrstrip_l2.b64e("abc") == "abc"
        """
    )
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    suffix_atoms = []
    for d in out.decls:
        if d.name.endswith("::assertion") and d.inv is not None:
            for f in [d.inv] if not hasattr(d.inv, "operands") else list(d.inv.operands):
                if getattr(f, "kind", None) == "not":
                    inner = f.operands[0]
                    if getattr(inner, "name", None) == "suffix-of":
                        suffix_atoms.append(inner)
    assert len(suffix_atoms) == 1
    assert suffix_atoms[0].args[0].value == "="


def test_rstrip_source_audit_warrants_return_shape(vendor_path):
    vendor_path("vendrstrip_audit", VENDOR_RSTRIP)
    out = _lift(
        """
        import vendrstrip_audit

        def test_token():
            assert vendrstrip_audit.b64e("abc") == "abc"
        """
    )

    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.translate-universe"
        and audit["universe_kind"] == "no-suffix-chars"
    )
    assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "support"
        and locus.get("ast_kind") == "Assign"
        and locus.get("ast_path") == "$.body[0]"
        for locus in audit["loci"]
    ), audit
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Return"
        and locus.get("ast_path") == "$.body[1]"
        for locus in audit["loci"]
    ), audit
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Attribute"
        and locus.get("ast_path") == "$.body[1].value.func"
        for locus in audit["loci"]
    ), audit


def test_rstrip_queues_want_bytes_identity_for_bytes_callsite(vendor_path):
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.translate_universe import (
        bytes_identity_universe_for_callee,
        translate_universe_for_callee,
    )

    bytes_identity_universe_for_callee.cache_clear()
    translate_universe_for_callee.cache_clear()
    vendor_path("vendrstrip_want_bytes", VENDOR_WANT_BYTES_RSTRIP)
    out = _lift(
        """
        import vendrstrip_want_bytes

        def test_token():
            assert vendrstrip_want_bytes.b64e(b"abc") == b"abc"
        """
    )

    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    bytes_term = ctor("python:bytes", [str_const("abc")])
    identity_atoms = []
    for d in out.decls:
        if not d.name.endswith("::assertion") or d.inv is None:
            continue
        for atom in _iter_conjuncts(d.inv):
            if getattr(atom, "name", None) != "=":
                continue
            args = getattr(atom, "args", ())
            if bytes_term not in args:
                continue
            if any(
                "callresult_vendrstrip_want_bytes_want_bytes_a1"
                in getattr(side, "name", "")
                for side in args
            ):
                identity_atoms.append(atom)
    assert identity_atoms, [d.name for d in out.decls]

    assertion = next(
        d
        for d in out.decls
        if d.name.endswith("::assertion")
        and "vendrstrip_want_bytes.b64e#euf#" in d.name
    )
    assert any(
        warrant.get("role") == "python.bytes-identity-universe"
        and warrant.get("source_function_name") == "want_bytes"
        for warrant in assertion.source_warrants
    )
    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.bytes-identity-universe"
    )
    assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "inactive" and locus.get("ast_kind") == "If"
        for locus in audit["loci"]
    ), audit
    assert any(
        locus["status"] == "warranted" and locus.get("ast_kind") == "Return"
        for locus in audit["loci"]
    ), audit


def test_lstrip_family_walks_no_prefix_chars(vendor_path):
    vendor_path("vendlstrip_ok", VENDOR_LSTRIP)
    universe, refusal = translate_universe_for_callee("vendlstrip_ok.int_to_bytes")
    assert refusal is None
    assert universe is not None
    assert universe.kind == "no-prefix-chars"
    assert universe.forbidden == "\x00"


def test_lstrip_emits_negated_prefix_conjunct(vendor_path):
    vendor_path("vendlstrip_l2", VENDOR_LSTRIP)
    out = _lift(
        """
        import vendlstrip_l2

        def test_int_to_bytes():
            assert vendlstrip_l2.int_to_bytes(1) == b"\\x01"
        """
    )

    prefix_atoms = []
    for d in out.decls:
        if d.name.endswith("::assertion") and d.inv is not None:
            for f in [d.inv] if not hasattr(d.inv, "operands") else list(d.inv.operands):
                if getattr(f, "kind", None) == "not":
                    inner = f.operands[0]
                    if getattr(inner, "name", None) == "prefix-of":
                        prefix_atoms.append(inner)
    assert len(prefix_atoms) == 1
    assert prefix_atoms[0].args[0].value == "\x00"


def test_lstrip_source_audit_warrants_return_shape(vendor_path):
    vendor_path("vendlstrip_audit", VENDOR_LSTRIP)
    out = _lift(
        """
        import vendlstrip_audit

        def test_int_to_bytes():
            assert vendlstrip_audit.int_to_bytes(1) == b"\\x01"
        """
    )

    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.translate-universe"
        and audit["universe_kind"] == "no-prefix-chars"
    )
    assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Return"
        and locus.get("ast_path") == "$.body[0]"
        for locus in audit["loci"]
    ), audit
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Attribute"
        and locus.get("ast_path") == "$.body[0].value.func"
        for locus in audit["loci"]
    ), audit


def test_rstrip_vendor_vector_endswith_refuses(vendor_path):
    vendor_path("vendrstrip_bad", VENDOR_RSTRIP)
    vendor_path(
        "test_vendrstrip_bad",
        """
        import vendrstrip_bad

        def test_vector():
            assert vendrstrip_bad.b64e("abc") == "abc="
        """,
    )
    universe, refusal = translate_universe_for_callee("vendrstrip_bad.b64e")
    assert universe is None
    assert refusal is not None and "sample-gate" in refusal.reason


# --- from-import callee resolution ---


def test_from_import_module_alias_claims_and_walks(vendor_path, tmp_path):
    # `from vend_pkg import enc` where enc IS a module: alias-bound
    # (find_spec-verified), the callsite claims, the universe attaches.
    pkg = tmp_path / "vendfi_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "enc.py").write_text(textwrap.dedent(VENDOR_TRANSLATE))
    translate_universe_for_callee.cache_clear()
    out = _lift(
        """
        from vendfi_pkg import enc

        def test_urlsafe():
            assert enc.urlsafe("abc") == "abc"
        """
    )
    atoms = _universe_atoms(out)
    assert len(atoms) == 1
    assert atoms[0].args[1].value == "+/"


def test_from_import_function_qualifies_base_and_walks(vendor_path):
    # `from vendmod import urlsafe`: the bare-name callsite keys to the
    # QUALIFIED base (cross-proof conjoin alignment) and the walk resolves.
    vendor_path("vendfi_fn", VENDOR_TRANSLATE)
    out = _lift(
        """
        from vendfi_fn import urlsafe

        def test_urlsafe():
            assert urlsafe("abc") == "abc"
        """
    )
    atoms = _universe_atoms(out)
    assert len(atoms) == 1
    assert any(
        d.name.startswith("vendfi_fn.urlsafe#euf#")
        for d in out.decls
        if d.name.endswith("::assertion")
    )


def test_from_import_class_does_not_alias(vendor_path):
    # A from-imported NON-module that is not walkable must not crash or
    # mis-claim; behavior stays as before (no universe, no error).
    vendor_path("vendfi_cls", "class Thing:\n    @staticmethod\n    def go(x):\n        return x\n")
    out = _lift(
        """
        from vendfi_cls import Thing

        def test_thing():
            assert Thing.go("abc") == "abc"
        """
    )
    assert not _universe_atoms(out)


# --- the member-of-values family: return TABLE[x] (census #1 cheap shape) ---

VENDOR_TABLE = '''
_STATUSES = ("active", "paused", "deleted")


def status_name(i):
    return _STATUSES[i]
'''


def test_table_subscript_family_walks(vendor_path):
    vendor_path("vendtbl_ok", VENDOR_TABLE)
    universe, refusal = translate_universe_for_callee("vendtbl_ok.status_name")
    assert refusal is None
    assert universe is not None
    assert universe.kind == "member-of-values"
    assert universe.values == ("active", "paused", "deleted")


def test_table_subscript_emits_membership_disjunction(vendor_path):
    vendor_path("vendtbl_l2", VENDOR_TABLE)
    out = _lift(
        """
        import vendtbl_l2

        def test_status():
            assert vendtbl_l2.status_name(0) == "active"
        """
    )
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    ors = []
    for d in out.decls:
        if d.name.endswith("::assertion") and d.inv is not None:
            stack = [d.inv]
            while stack:
                f = stack.pop()
                if getattr(f, "kind", None) == "or":
                    ors.append(f)
                elif getattr(f, "kind", None) in ("and", "not"):
                    stack.extend(f.operands)
    assert len(ors) == 1
    assert len(ors[0].operands) == 3


def test_mutable_table_refuses(vendor_path):
    vendor_path(
        "vendtbl_list",
        '''
_STATUSES = ["active", "paused"]


def status_name(i):
    return _STATUSES[i]
''',
    )
    universe, refusal = translate_universe_for_callee("vendtbl_list.status_name")
    assert universe is None
    assert refusal is not None
    assert "tuple-literal" in refusal.reason


def test_mixed_type_table_refuses(vendor_path):
    vendor_path(
        "vendtbl_mixed",
        '''
_STATUSES = ("active", 2)


def status_name(i):
    return _STATUSES[i]
''',
    )
    universe, refusal = translate_universe_for_callee("vendtbl_mixed.status_name")
    assert universe is None
    assert refusal is not None and "all-string" in refusal.reason


def test_rebound_table_refuses(vendor_path):
    vendor_path(
        "vendtbl_rebound",
        '''
_STATUSES = ("active",)
_STATUSES = ("active", "paused")


def status_name(i):
    return _STATUSES[i]
''',
    )
    universe, refusal = translate_universe_for_callee("vendtbl_rebound.status_name")
    assert universe is None
    assert refusal is not None


def test_table_vendor_vector_outside_table_refuses(vendor_path):
    vendor_path("vendtbl_gate", VENDOR_TABLE)
    vendor_path(
        "test_vendtbl_gate",
        """
        import vendtbl_gate

        def test_vector():
            assert vendtbl_gate.status_name(0) == "archived"
        """,
    )
    universe, refusal = translate_universe_for_callee("vendtbl_gate.status_name")
    assert universe is None
    assert refusal is not None and "sample-gate" in refusal.reason


def test_table_flip_changes_values(vendor_path):
    vendor_path(
        "vendtbl_flip",
        VENDOR_TABLE.replace('"deleted"', '"removed"'),
    )
    universe, _ = translate_universe_for_callee("vendtbl_flip.status_name")
    assert universe.values == ("active", "paused", "removed")


# --- the guard-then-raise family: census #1 (23,082 bodies) ---

VENDOR_GUARDED = '''
def scale(x, factor):
    """Guarded vendor fn: x must be non-negative, factor must not be 0."""
    if x < 0:
        raise ValueError("negative")
    if factor == 0:
        raise ValueError("zero factor")
    return x * factor
'''


def test_guard_universe_walks(vendor_path):
    from sugar_lift_py_tests.translate_universe import guard_universe_for_callee

    guard_universe_for_callee.cache_clear()
    vendor_path("vendguard_ok", VENDOR_GUARDED)
    guards, refusal = guard_universe_for_callee("vendguard_ok.scale")
    assert refusal is None
    assert guards is not None
    assert len(guards.clauses) == 2
    assert (guards.clauses[0].param_name, guards.clauses[0].op, guards.clauses[0].literal) == ("x", "<", 0)
    assert (guards.clauses[1].param_name, guards.clauses[1].op, guards.clauses[1].literal) == ("factor", "=", 0)


def test_guard_universe_walks_none_identity_guards(vendor_path):
    from sugar_lift_py_tests.translate_universe import guard_universe_for_callee

    guard_universe_for_callee.cache_clear()
    vendor_path(
        "vendguard_none_identity",
        '''
def require_value(x, fallback):
    if x is None:
        raise ValueError("missing")
    if fallback is not None:
        raise ValueError("unexpected")
    return x
''',
    )
    guards, refusal = guard_universe_for_callee(
        "vendguard_none_identity.require_value"
    )
    assert refusal is None
    assert guards is not None
    assert [
        (clause.param_name, clause.op, clause.literal)
        for clause in guards.clauses
    ] == [("x", "=", None), ("fallback", "≠", None)]


def test_guard_universe_emits_negated_comparisons(vendor_path):
    from sugar_lift_py_tests.translate_universe import guard_universe_for_callee

    guard_universe_for_callee.cache_clear()
    vendor_path("vendguard_l2", VENDOR_GUARDED)
    out = _lift(
        """
        import vendguard_l2

        def test_scale():
            assert vendguard_l2.scale(-3, 2) == -6
        """
    )
    nots = []
    for d in out.decls:
        if d.name.endswith("::assertion") and d.inv is not None:
            stack = [d.inv]
            while stack:
                f = stack.pop()
                if getattr(f, "kind", None) == "not":
                    nots.append(f.operands[0])
                elif getattr(f, "kind", None) == "and":
                    stack.extend(f.operands)
    # both guards instantiate at the concrete args (-3, 2):
    # not(-3 < 0) -- which check will refute -- and not(2 = 0).
    assert len(nots) == 2
    names = sorted(n.name for n in nots)
    assert names == ["<", "="]


def test_guard_universe_emits_negated_none_identity(vendor_path):
    from sugar_lift_py_tests.translate_universe import guard_universe_for_callee

    guard_universe_for_callee.cache_clear()
    vendor_path(
        "vendguard_none_l2",
        '''
def require_value(x):
    if x is None:
        raise ValueError("missing")
    return x
''',
    )
    out = _lift(
        """
        import vendguard_none_l2

        def test_value():
            assert vendguard_none_l2.require_value(None) == "claimed"
        """
    )

    def walk_formula(formula):
        yield formula
        for operand in getattr(formula, "operands", ()):
            yield from walk_formula(operand)

    negated = []
    for d in out.decls:
        if d.name.endswith("::assertion") and d.inv is not None:
            negated.extend(
                f.operands[0]
                for f in walk_formula(d.inv)
                if getattr(f, "kind", None) == "not"
            )
    assert any(
        getattr(atom, "name", None) == "="
        and any(getattr(arg, "name", None) == "None" for arg in atom.args)
        for atom in negated
    ), repr(out.decls)


def test_guard_vendor_vector_firing_guard_refuses(vendor_path):
    from sugar_lift_py_tests.translate_universe import guard_universe_for_callee

    guard_universe_for_callee.cache_clear()
    vendor_path("vendguard_bad", VENDOR_GUARDED)
    vendor_path(
        "test_vendguard_bad",
        """
        import vendguard_bad

        def test_vector():
            assert vendguard_bad.scale(-1, 2) == -2
        """,
    )
    guards, refusal = guard_universe_for_callee("vendguard_bad.scale")
    assert guards is None
    assert refusal is not None and "sample-gate" in refusal.reason


def test_unreadable_guards_skip_without_poisoning(vendor_path):
    from sugar_lift_py_tests.translate_universe import guard_universe_for_callee

    guard_universe_for_callee.cache_clear()
    vendor_path(
        "vendguard_mixed",
        '''
def f(x, y):
    if complicated(x):
        raise ValueError("opaque")
    if y < 0:
        raise ValueError("negative")
    return x + y
''',
    )
    guards, refusal = guard_universe_for_callee("vendguard_mixed.f")
    assert refusal is None
    assert guards is not None
    assert len(guards.clauses) == 1
    assert guards.clauses[0].param_name == "y"


def test_unguarded_body_is_not_a_candidate(vendor_path):
    from sugar_lift_py_tests.translate_universe import guard_universe_for_callee

    guard_universe_for_callee.cache_clear()
    vendor_path("vendguard_none", "def f(x):\n    return x + 1\n")
    guards, refusal = guard_universe_for_callee("vendguard_none.f")
    assert guards is None and refusal is None


# --- the table-loop family: census #2 (17,781 bodies) ---

VENDOR_LOOP = '''
_HEX = "0123456789abcdef"


def hexify(data):
    out = []
    for b in data:
        out.append(_HEX[b >> 4])
        out.append(_HEX[b & 15])
    return ":".join(out)
'''


def test_table_loop_walks_with_union_and_separator(vendor_path):
    vendor_path("vendloop_ok", VENDOR_LOOP)
    universe, refusal = translate_universe_for_callee("vendloop_ok.hexify")
    assert refusal is None
    assert universe is not None
    assert universe.kind == "chars-in-set"
    assert universe.forbidden == "".join(sorted(set("0123456789abcdef:")))


def test_table_loop_emits_positive_membership(vendor_path):
    vendor_path("vendloop_l2", VENDOR_LOOP)
    out = _lift(
        """
        import vendloop_l2

        def test_hexify():
            assert vendloop_l2.hexify("ab") == "36:31:36:32"
        """
    )
    atoms = []
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    for d in out.decls:
        if d.name.endswith("::assertion") and d.inv is not None:
            atoms.extend(
                a for a in _iter_conjuncts(d.inv) if a.name == "str.chars-in-set"
            )
    assert len(atoms) == 1
    assert "f" in atoms[0].args[1].value and ":" in atoms[0].args[1].value


def test_table_loop_str_accumulator(vendor_path):
    vendor_path(
        "vendloop_str",
        '''
_DIG = "01"


def bits(n):
    out = ""
    for b in n:
        out += _DIG[b]
    return out
''',
    )
    universe, refusal = translate_universe_for_callee("vendloop_str.bits")
    assert refusal is None
    assert universe.forbidden == "01"


def test_table_loop_foreign_append_refuses(vendor_path):
    vendor_path(
        "vendloop_foreign",
        '''
_HEX = "0123456789abcdef"


def hexify(data, extra):
    out = []
    for b in data:
        out.append(extra)
    return "".join(out)
''',
    )
    universe, refusal = translate_universe_for_callee("vendloop_foreign.hexify")
    assert universe is None
    assert refusal is not None
    assert "not a pinned-table element" in refusal.reason


def test_table_loop_unstable_table_refuses(vendor_path):
    vendor_path(
        "vendloop_unstable",
        '''
_HEX = "0123456789abcdef"
_HEX = "0123456789ABCDEF"


def hexify(data):
    out = []
    for b in data:
        out.append(_HEX[b])
    return "".join(out)
''',
    )
    universe, refusal = translate_universe_for_callee("vendloop_unstable.hexify")
    assert universe is None
    assert refusal is not None and "bound more than once" in refusal.reason


def test_table_loop_vendor_vector_outside_union_refuses(vendor_path):
    vendor_path("vendloop_gate", VENDOR_LOOP)
    vendor_path(
        "test_vendloop_gate",
        """
        import vendloop_gate

        def test_vector():
            assert vendloop_gate.hexify("a") == "6Z"
        """,
    )
    universe, refusal = translate_universe_for_callee("vendloop_gate.hexify")
    assert universe is None
    assert refusal is not None and "sample-gate" in refusal.reason


# --- the pre-conjoined path: multi-assert bodies carry universes too ---


def test_preconjoined_path_carries_universes(vendor_path):
    # Two asserts in ONE test body route through the characterization
    # (pre-conjoined) classifier, which previously emitted no universes.
    vendor_path("vendpre_l2", VENDOR_TRANSLATE)
    out = _lift(
        """
        import vendpre_l2

        def test_urlsafe_twice():
            assert vendpre_l2.urlsafe("abc") == "abc"
            assert vendpre_l2.urlsafe("xyz") == "xyz"
        """
    )
    atoms = _universe_atoms_anywhere(out)
    assert len(atoms) == 2  # one universe per distinct subject


def _universe_atoms_anywhere(out):
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    atoms = []
    for d in out.decls:
        if d.inv is None:
            continue
        stack = [d.inv]
        while stack:
            f = stack.pop()
            if getattr(f, "kind", None) in ("and", "or", "not"):
                stack.extend(f.operands)
            elif getattr(f, "name", None) in (
                "str.chars-not-in-set",
                "str.chars-in-set",
            ):
                atoms.append(f)
    return atoms


def test_preconjoined_guard_universe_injects(vendor_path):
    from sugar_lift_py_tests.translate_universe import guard_universe_for_callee

    guard_universe_for_callee.cache_clear()
    vendor_path("vendpre_guard", VENDOR_GUARDED)
    out = _lift(
        """
        import vendpre_guard

        def test_scale_twice():
            assert vendpre_guard.scale(-3, 2) == -6
            assert vendpre_guard.scale(4, 2) == 8
        """
    )
    nots = []
    for d in out.decls:
        if d.inv is None:
            continue
        stack = [d.inv]
        while stack:
            f = stack.pop()
            if getattr(f, "kind", None) == "not":
                nots.append(f)
            elif getattr(f, "kind", None) in ("and", "or"):
                stack.extend(f.operands)
    # two callsites x two guard clauses, MINUS the shared-factor dedupe:
    # not(-3 < 0), not(4 < 0), and ONE not(2 = 0) (identical for both
    # callsites; idempotent conjuncts dedupe).
    assert len(nots) == 3


# --- regression: the corpus (Werkzeug) caught a NameError on the
# single-assertion operator-dispatch path. _Connective was referenced but
# never imported into layer2; a boolean-connective assertion over an
# operator-dispatch ctor reaches the unimported name. ---


def test_connective_operator_dispatch_does_not_NameError():
    out = _lift(
        """
        class C:
            def __eq__(self, other):
                return True

        def test_dispatch():
            assert (C() == C()) and (1 < 2)
        """
    )
    # the point is simply that lifting completes without NameError;
    # whatever the classification, no exception escapes.
    assert out is not None


# --- EUF dropout on non-deterministic callees (corpus finding: Werkzeug
# generate_password_hash salted hash made same-args EUF unify two unequal
# values -> false contradiction) ---


def test_nondeterministic_callee_detected(vendor_path):
    from sugar_lift_py_tests.translate_universe import callee_is_nondeterministic

    callee_is_nondeterministic.cache_clear()
    vendor_path(
        "vendnd_salt",
        '''
import secrets


def gen_salt(n):
    return "".join(secrets.choice("abc") for _ in range(n))


def make_hash(pw):
    return pw + gen_salt(8)
''',
    )
    # direct marker (secrets.choice in gen_salt) and transitive (make_hash
    # -> gen_salt -> secrets) both detected.
    assert callee_is_nondeterministic("vendnd_salt.gen_salt")
    assert callee_is_nondeterministic("vendnd_salt.make_hash")


def test_deterministic_callee_not_flagged(vendor_path):
    from sugar_lift_py_tests.translate_universe import callee_is_nondeterministic

    callee_is_nondeterministic.cache_clear()
    vendor_path("vendnd_pure", "def f(x):\n    return x + 1\n")
    assert not callee_is_nondeterministic("vendnd_pure.f")


def test_nondeterministic_callee_drops_euf_unification(vendor_path):
    from sugar_lift_py_tests.translate_universe import callee_is_nondeterministic

    callee_is_nondeterministic.cache_clear()
    vendor_path(
        "vendnd_l2",
        '''
import secrets


def gen_salt(n):
    return secrets.token_hex(n)


def make_hash(pw):
    return pw + gen_salt(8)
''',
    )
    # the Werkzeug shape: same-args twice, asserted UNEQUAL. With EUF
    # dropout the two calls are independent -> NO false contradiction.
    out = _lift(
        """
        import vendnd_l2

        def test_salted():
            h1 = vendnd_l2.make_hash("secret")
            h2 = vendnd_l2.make_hash("secret")
            assert h1 != h2
        """
    )
    # no contract should argument-key make_hash to a shared euf base
    euf_bases = [
        d.name for d in out.decls if "make_hash#euf#" in d.name
    ]
    assert not euf_bases, euf_bases


def test_unresolvable_callee_stays_pure_conservative():
    from sugar_lift_py_tests.translate_universe import callee_is_nondeterministic

    callee_is_nondeterministic.cache_clear()
    # no such module: evidence-based detector returns False (keeps current
    # sound-conservative unification where we have no body to inspect).
    assert not callee_is_nondeterministic("no_such_module_xyz.f")


# --- return-constant family (census #1, 34k bodies): the equality universal ---

VENDOR_CONST = '''
def version():
    return "3.1.4"


def always_true(x):
    return True


def answer(*a, **k):
    return 42
'''


def test_constant_universe_walks(vendor_path):
    from sugar_lift_py_tests.translate_universe import constant_universe_for_callee

    constant_universe_for_callee.cache_clear()
    vendor_path("vendconst_ok", VENDOR_CONST)
    u, r = constant_universe_for_callee("vendconst_ok.version")
    assert r is None and u is not None
    assert (u.value, u.value_kind) == ("3.1.4", "str")
    u2, _ = constant_universe_for_callee("vendconst_ok.always_true")
    assert (u2.value, u2.value_kind) == (True, "bool")
    u3, _ = constant_universe_for_callee("vendconst_ok.answer")
    assert (u3.value, u3.value_kind) == (42, "int")


def test_constant_guard_prefix_still_constant(vendor_path):
    from sugar_lift_py_tests.translate_universe import constant_universe_for_callee

    constant_universe_for_callee.cache_clear()
    vendor_path(
        "vendconst_guard",
        '''
def f(x):
    if x < 0:
        raise ValueError
    return "ok"
''',
    )
    u, r = constant_universe_for_callee("vendconst_guard.f")
    assert r is None and u is not None and u.value == "ok"


def test_multiple_returns_not_constant(vendor_path):
    from sugar_lift_py_tests.translate_universe import constant_universe_for_callee

    constant_universe_for_callee.cache_clear()
    vendor_path(
        "vendconst_multi",
        'def f(x):\n    if x:\n        return "a"\n    return "b"\n',
    )
    u, r = constant_universe_for_callee("vendconst_multi.f")
    assert u is None and r is None  # not a candidate


def test_constant_emits_equality_and_refutes_wrong(vendor_path):
    constant_universe_for_callee_clear()
    vendor_path("vendconst_l2", VENDOR_CONST)
    out = _lift(
        """
        import vendconst_l2

        def test_version():
            assert vendconst_l2.version() == "3.1.4"
        """
    )
    # the universe equality over the SAME subject coexists with the sworn
    # equality; a bad twin asserting a different constant would conjoin to
    # unsat. Here we just confirm an equality atom to the constant is present.
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    eqs = []
    for d in out.decls:
        if d.name.endswith("::assertion") and d.inv is not None:
            stack = [d.inv]
            while stack:
                f = stack.pop()
                if getattr(f, "name", None) == "=" and str_const("3.1.4") in getattr(f, "args", ()):
                    eqs.append(f)
                elif getattr(f, "kind", None) in ("and", "or", "not"):
                    stack.extend(f.operands)
    assert eqs


def test_decorated_class_method_seeds_package_source_accounting(tmp_path, monkeypatch):
    pkg = tmp_path / "vendconst_decorated_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "decorators.py").write_text(
        textwrap.dedent(
            '''
            _registry = []


            def register_extension_dtype(cls):
                _registry.append(cls)
                return cls


            def set_module(module):
                def decorator(cls):
                    cls.__module__ = module
                    return cls

                return decorator
            '''
        ),
        encoding="utf-8",
    )
    (pkg / "boolean.py").write_text(
        textwrap.dedent(
            '''
            from vendconst_decorated_pkg.decorators import (
                register_extension_dtype,
                set_module,
            )


            @register_extension_dtype
            @set_module("pandas")
            class BooleanDtype:
                def __repr__(self):
                    return "BooleanDtype"
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendconst_decorated_pkg.boolean as boolean

        def test_repr():
            dtype = boolean.BooleanDtype()
            assert dtype.__repr__() == "BooleanDtype"
        """,
    )

    constant_audits = [
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.constant-universe"
        and audit.get("source_memento", {}).get("source_function_name")
        == "BooleanDtype.__repr__"
    ]
    assert len(constant_audits) == 1
    assert constant_audits[0]["source_memento"]["file"].endswith(
        "vendconst_decorated_pkg/boolean.py"
    )
    package_audits = [
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendconst_decorated_pkg"
    ]
    assert len(package_audits) == 1
    package_audit = package_audits[0]
    assert package_audit["totals"]["source_warranted"] > 0
    assert package_audit["totals"]["unclassified_source"] > 0
    assert any(
        locus["status"] == "unclassified"
        and locus["file"].endswith("vendconst_decorated_pkg/decorators.py")
        for locus in package_audit["loci"]
    ), package_audit


def test_package_source_summary_mode_elides_loci_and_counts_ast_types(
    tmp_path,
    monkeypatch,
):
    pkg = tmp_path / "vendconst_summary_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(
        textwrap.dedent(
            '''
            def version():
                return "1.0"


            def extra(value):
                unknown = value + 1
                return unknown
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_LOCI", "summary")
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_SAMPLE_LIMIT", "3")
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendconst_summary_pkg.mod as mod

        def test_version():
            assert mod.version() == "1.0"
        """,
    )

    package_audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendconst_summary_pkg"
    )
    assert package_audit["accounting_mode"] == "structural"
    assert package_audit["loci_elided"] is True
    assert "loci" not in package_audit
    assert package_audit["totals"]["source_loci"] > 0
    assert package_audit["totals"]["source_warranted"] > 0
    assert package_audit["totals"]["unclassified_source"] > 0
    assert package_audit["ast_type_counts"]["unclassified"]["BinOp"] >= 1
    assert len(package_audit["sample_loci"]) == 3


def test_structural_package_accounting_refuses_top_level_import_probe(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendconst_import_probe_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        textwrap.dedent(
            '''
            hard_dependencies = ("sys",)

            for _dependency in hard_dependencies:
                try:
                    __import__(_dependency)
                except ImportError as _e:
                    raise ImportError(f"missing {_dependency}") from _e

            del hard_dependencies, _dependency

            try:
                from vendconst_import_probe_pkg import encoding as _encoding
            except ImportError as _err:
                _module = _err.name
                raise ImportError(f"missing {_module}") from _err
            '''
        ),
        encoding="utf-8",
    )
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            '''
            def version():
                return "1.0"
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendconst_import_probe_pkg.encoding as enc

        def test_version():
            assert enc.version() == "1.0"
        """,
    )

    package_audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendconst_import_probe_pkg"
    )
    probe_loci = [
        locus
        for locus in package_audit["loci"]
        if locus["file"].endswith("vendconst_import_probe_pkg/__init__.py")
        and locus["line"] >= 4
    ]
    assert probe_loci
    assert not [
        locus for locus in probe_loci if locus["status"] == "unclassified"
    ], probe_loci
    assert {locus["status"] for locus in probe_loci} == {"refused"}
    assert any(
        locus.get("ast_kind") == "For"
        and "runtime import probe" in locus.get("reason", "")
        for locus in probe_loci
    ), probe_loci
    assert any(
        locus.get("ast_kind") == "Delete"
        and "delete" in locus.get("reason", "")
        for locus in probe_loci
    ), probe_loci


def test_structural_package_accounting_refuses_top_level_version_probe(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendconst_version_probe_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        textwrap.dedent(
            '''
            _built_with_meson = False
            try:
                from vendconst_version_probe_pkg._version_meson import (
                    __version__,
                    __git_version__,
                )
                _built_with_meson = True
            except ImportError:
                from vendconst_version_probe_pkg._version import get_versions
                v = get_versions()
                __version__ = v.get("closest-tag", v["version"])
                __git_version__ = v.get("full-revisionid")
                del get_versions, v
            '''
        ),
        encoding="utf-8",
    )
    (pkg / "_version.py").write_text(
        textwrap.dedent(
            '''
            def get_versions():
                return {"closest-tag": "1.0", "version": "1.0", "full-revisionid": "abc"}
            '''
        ),
        encoding="utf-8",
    )
    (pkg / "encoding.py").write_text(
        textwrap.dedent(
            '''
            def version():
                return "1.0"
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendconst_version_probe_pkg.encoding as enc

        def test_version():
            assert enc.version() == "1.0"
        """,
    )

    package_audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendconst_version_probe_pkg"
    )
    version_loci = [
        locus
        for locus in package_audit["loci"]
        if locus["file"].endswith("vendconst_version_probe_pkg/__init__.py")
        and locus["line"] >= 3
    ]
    assert version_loci
    assert not [
        locus for locus in version_loci if locus["status"] == "unclassified"
    ], version_loci
    assert {locus["status"] for locus in version_loci} == {"refused"}
    assert any(
        locus.get("ast_kind") == "Try"
        and "version metadata" in locus.get("reason", "")
        for locus in version_loci
    ), version_loci


def test_structural_package_accounting_refuses_global_config_reads(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendconst_global_config_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "config.py").write_text(
        textwrap.dedent(
            '''
            _global_config = {"future": {"enabled": True, "disabled": False}}

            def using_feature():
                _mode_options = _global_config["future"]
                return _mode_options["enabled"]

            def not_disabled():
                _mode_options = _global_config["future"]
                return not _mode_options["disabled"]

            def version():
                return "1.0"
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendconst_global_config_pkg.config as config

        def test_version():
            assert config.version() == "1.0"
        """,
    )

    package_audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendconst_global_config_pkg"
    )
    config_loci = [
        locus
        for locus in package_audit["loci"]
        if locus["file"].endswith("vendconst_global_config_pkg/config.py")
        and locus["line"] in {5, 6, 9, 10}
    ]
    assert config_loci
    assert not [
        locus for locus in config_loci if locus["status"] == "unclassified"
    ], config_loci
    assert {locus["status"] for locus in config_loci} == {"refused"}
    assert any(
        locus.get("ast_kind") == "Return"
        and "global config" in locus.get("reason", "")
        for locus in config_loci
    ), config_loci


def test_structural_package_accounting_refuses_option_registry_flow(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendconst_option_registry_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "config.py").write_text(
        textwrap.dedent(
            '''
            class OptionError(Exception):
                pass

            def _get_single_key(pat):
                keys = _select_options(pat)
                if len(keys) == 0:
                    _warn_if_deprecated(pat)
                    raise OptionError(f"No such keys(s): {pat!r}")
                if len(keys) > 1:
                    raise OptionError("Pattern matched multiple keys")
                key = keys[0]
                _warn_if_deprecated(key)
                key = _translate_key(key)
                return key

            def version():
                return "1.0"
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    constant_universe_for_callee_clear()

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendconst_option_registry_pkg.config as config

        def test_version():
            assert config.version() == "1.0"
        """,
    )

    package_audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendconst_option_registry_pkg"
    )
    option_loci = [
        locus
        for locus in package_audit["loci"]
        if locus["file"].endswith("vendconst_option_registry_pkg/config.py")
        and 6 <= locus["line"] <= 15
    ]
    assert option_loci
    assert not [
        locus for locus in option_loci if locus["status"] == "unclassified"
    ], option_loci
    assert {locus["status"] for locus in option_loci} == {"refused"}
    assert any(
        locus.get("ast_kind") == "If"
        and "option registry" in locus.get("reason", "")
        for locus in option_loci
    ), option_loci


def test_constant_universe_walks_constructor_bound_instance_method(vendor_path):
    constant_universe_for_callee_clear()
    vendor_path(
        "vendconst_method",
        '''
class Algo:
    def get_signature(self, key, value):
        return b""
''',
    )
    out = _lift(
        """
        import vendconst_method

        def test_signature():
            alg = vendconst_method.Algo()
            assert alg.get_signature(b"k", b"v") == b""
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendconst_method.Algo.get_signature" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]
    assert any(
        warrant.get("role") == "python.constant-universe"
        and warrant.get("source_function_name") == "Algo.get_signature"
        and warrant.get("file", "").endswith("vendconst_method.py")
        for warrant in assertion.source_warrants
    ), assertion.source_warrants

    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    constant_eqs = [
        atom
        for atom in _iter_conjuncts(assertion.inv)
        if getattr(atom, "name", None) == "="
        and any(
            getattr(side, "name", "") == "callval_get_signature_a3"
            for side in getattr(atom, "args", ())
        )
        and ctor("python:bytes", [str_const("")]) in getattr(atom, "args", ())
    ]
    assert constant_eqs

    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.constant-universe"
        and "vendconst_method.Algo.get_signature" in audit["contract"]["name"]
    )
    assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted" and locus.get("ast_kind") == "Return"
        for locus in audit["loci"]
    ), audit


def test_instance_field_universe_maps_constructor_arg_to_getter(vendor_path):
    vendor_path(
        "vendinst_field",
        '''
class Box(Exception):
    def __init__(self, value):
        super().__init__(value)
        self.value = value

    def get(self):
        return self.value
''',
    )
    out = _lift(
        """
        import vendinst_field

        def test_box():
            box = vendinst_field.Box("raaaa")
            assert box.get() == "wrong"
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendinst_field.Box.get" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    from sugar_lift_py_tests.ir import str_const
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    field_eqs = [
        atom
        for atom in _iter_conjuncts(assertion.inv)
        if getattr(atom, "name", None) == "="
        and any(
            getattr(side, "name", "") == "callval_get_a1"
            for side in getattr(atom, "args", ())
        )
        and str_const("raaaa") in getattr(atom, "args", ())
    ]
    assert field_eqs

    field_warrants = [
        warrant
        for warrant in assertion.source_warrants
        if warrant.get("role") == "python.instance-field-universe"
    ]
    assert {
        warrant.get("source_function_name") for warrant in field_warrants
    } == {"Box.__init__", "Box.get"}

    audits = {
        audit["source_memento"].get("source_function_name"): audit
        for audit in out.source_audits
        if audit["role"] == "python.instance-field-universe"
        and "vendinst_field.Box.get" in audit["contract"]["name"]
    }
    assert set(audits) == {"Box.__init__", "Box.get"}
    for audit in audits.values():
        assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted" and locus.get("ast_kind") == "Assign"
        for locus in audits["Box.__init__"]["loci"]
    ), audits["Box.__init__"]
    assert any(
        locus["status"] == "support" and locus.get("ast_kind") == "Expr"
        for locus in audits["Box.__init__"]["loci"]
    ), audits["Box.__init__"]
    assert any(
        locus["status"] == "warranted" and locus.get("ast_kind") == "Return"
        for locus in audits["Box.get"]["loci"]
    ), audits["Box.get"]


def test_instance_field_universe_maps_constructor_arg_to_attribute(vendor_path):
    vendor_path(
        "vendinst_attr",
        '''
class PayloadError(Exception):
    def __init__(self, message, payload=None):
        super().__init__(message)
        self.payload: object = payload
''',
    )
    out = _lift(
        """
        import vendinst_attr

        def test_payload():
            err = vendinst_attr.PayloadError("bad", payload=b"payload")
            assert err.payload == b"wrong"
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendinst_attr.PayloadError" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    payload_term = ctor("python:bytes", [str_const("payload")])
    field_eqs = [
        atom
        for atom in _iter_conjuncts(assertion.inv)
        if getattr(atom, "name", None) == "="
        and payload_term in getattr(atom, "args", ())
        and any(
            getattr(side, "name", "") == "err$0.payload"
            for side in getattr(atom, "args", ())
        )
    ]
    assert field_eqs

    field_warrants = [
        warrant
        for warrant in assertion.source_warrants
        if warrant.get("role") == "python.instance-field-universe"
    ]
    assert {
        warrant.get("source_function_name") for warrant in field_warrants
    } == {"PayloadError.__init__"}

    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.instance-field-universe"
        and audit["source_memento"].get("source_function_name")
        == "PayloadError.__init__"
    )
    assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted" and locus.get("ast_kind") == "AnnAssign"
        for locus in audit["loci"]
    ), audit
    assert any(
        locus["status"] == "support" and locus.get("ast_kind") == "Expr"
        for locus in audit["loci"]
    ), audit


def test_instance_field_universe_maps_one_of_multiple_constructor_fields(vendor_path):
    vendor_path(
        "vendinst_multi_attr",
        '''
class HeaderError(Exception):
    def __init__(self, message, payload=None, header=None):
        super().__init__(message, payload)
        self.payload = payload
        self.header = header
''',
    )
    out = _lift(
        """
        import vendinst_multi_attr

        def test_header():
            err = vendinst_multi_attr.HeaderError("bad", payload=b"payload", header="h")
            assert err.header == "wrong"
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendinst_multi_attr.HeaderError" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    from sugar_lift_py_tests.ir import str_const
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    field_eqs = [
        atom
        for atom in _iter_conjuncts(assertion.inv)
        if getattr(atom, "name", None) == "="
        and str_const("h") in getattr(atom, "args", ())
        and any(
            getattr(side, "name", "") == "err$0.header"
            for side in getattr(atom, "args", ())
        )
    ]
    assert field_eqs

    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.instance-field-universe"
        and audit["source_memento"].get("source_function_name")
        == "HeaderError.__init__"
    )
    assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Assign"
        and locus.get("line") == 6
        for locus in audit["loci"]
    ), audit


def test_constructor_field_universe_reads_base_constructor_via_super(vendor_path):
    vendor_path(
        "vendinst_super_field",
        '''
class BaseError(Exception):
    def __init__(self, message):
        self.message = message


class PayloadError(BaseError):
    def __init__(self, message, payload=None):
        super().__init__(message)
        self.payload = payload
''',
    )
    out = _lift(
        """
        import vendinst_super_field

        def test_message():
            err = vendinst_super_field.PayloadError("raaaa", payload=b"payload")
            assert err.message == "wrong"
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendinst_super_field.PayloadError" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    from sugar_lift_py_tests.ir import str_const
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    field_eqs = [
        atom
        for atom in _iter_conjuncts(assertion.inv)
        if getattr(atom, "name", None) == "="
        and str_const("raaaa") in getattr(atom, "args", ())
        and any(
            getattr(side, "name", "") == "err$0.message"
            for side in getattr(atom, "args", ())
        )
    ]
    assert field_eqs

    field_warrants = [
        warrant
        for warrant in assertion.source_warrants
        if warrant.get("role") == "python.instance-field-universe"
    ]
    assert {
        warrant.get("source_function_name") for warrant in field_warrants
    } == {"BaseError.__init__", "PayloadError.__init__"}

    audits = {
        audit["source_memento"].get("source_function_name"): audit
        for audit in out.source_audits
        if audit["role"] == "python.instance-field-universe"
        and "vendinst_super_field.PayloadError" in audit["contract"]["name"]
    }
    assert set(audits) == {"BaseError.__init__", "PayloadError.__init__"}
    for audit in audits.values():
        assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Assign"
        for locus in audits["BaseError.__init__"]["loci"]
    ), audits["BaseError.__init__"]
    assert any(
        locus["status"] == "support"
        and locus.get("ast_kind") == "Expr"
        for locus in audits["PayloadError.__init__"]["loci"]
    ), audits["PayloadError.__init__"]


def test_constructor_field_universe_maps_object_setattr_assignment(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        constructor_field_universe_for_callee,
    )

    constructor_field_universe_for_callee.cache_clear()
    vendor_path(
        "vendinst_object_setattr_field",
        '''
class DictWrapper:
    def __init__(self, d, prefix=""):
        object.__setattr__(self, "d", d)
        object.__setattr__(self, "prefix", prefix)
''',
    )

    universe, refusal = constructor_field_universe_for_callee(
        "vendinst_object_setattr_field.DictWrapper",
        "prefix",
    )

    assert refusal is None
    assert universe is not None
    assert universe.field_name == "prefix"
    assert universe.constructor_param_name == "prefix"
    assert universe.constructor_qualname == (
        "vendinst_object_setattr_field.DictWrapper.__init__"
    )
    assert universe.constructor_source_memento is not None
    assert universe.constructor_source_memento.get("source_cid")


def test_constructor_field_universe_maps_adapter_field_assignment(vendor_path):
    from sugar_lift_py_tests.translate_universe import bytes_identity_universe_for_callee

    bytes_identity_universe_for_callee.cache_clear()
    vendor_path(
        "vendinst_adapter_field",
        '''
def want_bytes(s, encoding="utf-8", errors="strict"):
    if isinstance(s, str):
        s = s.encode(encoding, errors)

    return s


class Signer:
    def __init__(self, sep=b"."):
        self.sep: bytes = want_bytes(sep)
''',
    )
    out = _lift(
        """
        import vendinst_adapter_field

        def test_sep():
            signer = vendinst_adapter_field.Signer(sep=b".")
            assert signer.sep == b"wrong"
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendinst_adapter_field.Signer" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    sep_term = ctor("python:bytes", [str_const(".")])
    adapter_terms = []
    field_eqs = []
    identity_eqs = []
    for atom in _iter_conjuncts(assertion.inv):
        if getattr(atom, "name", None) != "=":
            continue
        args = getattr(atom, "args", ())
        adapter_side = next(
            (
                side
                for side in args
                if "callresult_vendinst_adapter_field_want_bytes_a1"
                in getattr(side, "name", "")
            ),
            None,
        )
        if adapter_side is not None:
            adapter_terms.append(adapter_side)
        if adapter_side is not None and any(
            getattr(side, "name", "") == "signer$0.sep" for side in args
        ):
            field_eqs.append(atom)
        if adapter_side is not None and sep_term in args:
            identity_eqs.append(atom)

    assert field_eqs
    assert identity_eqs
    assert adapter_terms

    roles = {
        warrant.get("role")
        for warrant in assertion.source_warrants
    }
    assert {"python.instance-field-universe", "python.bytes-identity-universe"} <= roles

    audits = {
        audit["role"]: audit
        for audit in out.source_audits
        if audit["role"] in {"python.instance-field-universe", "python.bytes-identity-universe"}
        and "vendinst_adapter_field.Signer" in audit["contract"]["name"]
    }
    assert audits["python.instance-field-universe"]["totals"]["unclassified_source"] == 0
    assert audits["python.bytes-identity-universe"]["totals"]["unclassified_source"] == 0


def test_constructor_field_universe_maps_helper_list_adapter(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        bytes_identity_universe_for_callee,
        list_adapter_universe_for_callee,
    )

    bytes_identity_universe_for_callee.cache_clear()
    list_adapter_universe_for_callee.cache_clear()
    vendor_path(
        "vendinst_helper_list",
        '''
def want_bytes(s, encoding="utf-8", errors="strict"):
    if isinstance(s, str):
        s = s.encode(encoding, errors)

    return s


def _make_keys_list(secret_key):
    if isinstance(secret_key, (str, bytes)):
        return [want_bytes(secret_key)]

    return [want_bytes(s) for s in secret_key]


class Signer:
    def __init__(self, secret_key):
        self.secret_keys = _make_keys_list(secret_key)
''',
    )
    out = _lift(
        """
        import vendinst_helper_list

        def test_secret_keys():
            signer = vendinst_helper_list.Signer(b"k")
            assert signer.secret_keys == signer.secret_keys
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendinst_helper_list.Signer" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    secret = ctor("python:bytes", [str_const("k")])
    helper_terms = []
    list_terms = []
    identity_eqs = []
    for atom in _iter_conjuncts(assertion.inv):
        if getattr(atom, "name", None) != "=":
            continue
        args = getattr(atom, "args", ())
        helper_side = next(
            (
                side
                for side in args
                if "callresult_vendinst_helper_list__make_keys_list_a1"
                in getattr(side, "name", "")
            ),
            None,
        )
        if helper_side is not None:
            helper_terms.append(helper_side)
        list_side = next(
            (
                side
                for side in args
                if getattr(side, "name", "") == "python:list"
            ),
            None,
        )
        if list_side is not None:
            list_terms.append(list_side)
        if any(
            "callresult_vendinst_helper_list_want_bytes_a1" in getattr(side, "name", "")
            for side in args
        ) and secret in args:
            identity_eqs.append(atom)

    assert helper_terms
    assert list_terms
    assert identity_eqs

    roles = {warrant.get("role") for warrant in assertion.source_warrants}
    assert {
        "python.instance-field-universe",
        "python.list-adapter-universe",
        "python.bytes-identity-universe",
    } <= roles

    audits = {
        audit["role"]: audit
        for audit in out.source_audits
        if audit["role"]
        in {
            "python.instance-field-universe",
            "python.list-adapter-universe",
            "python.bytes-identity-universe",
        }
        and "vendinst_helper_list" in audit["contract"]["name"]
    }
    assert set(audits) == {
        "python.instance-field-universe",
        "python.list-adapter-universe",
        "python.bytes-identity-universe",
    }
    assert audits["python.instance-field-universe"]["totals"]["unclassified_source"] == 0
    assert audits["python.list-adapter-universe"]["totals"]["unclassified_source"] == 0
    assert audits["python.bytes-identity-universe"]["totals"]["unclassified_source"] == 0


def test_constructor_field_universe_maps_helper_list_adapter_iterable_branch(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        bytes_identity_universe_for_callee,
        list_adapter_universe_for_callee,
    )

    bytes_identity_universe_for_callee.cache_clear()
    list_adapter_universe_for_callee.cache_clear()
    vendor_path(
        "vendinst_helper_listcomp",
        '''
def want_bytes(s, encoding="utf-8", errors="strict"):
    if isinstance(s, str):
        s = s.encode(encoding, errors)

    return s


def _make_keys_list(secret_key):
    if isinstance(secret_key, (str, bytes)):
        return [want_bytes(secret_key)]

    return [want_bytes(s) for s in secret_key]


class Signer:
    def __init__(self, secret_key):
        self.secret_keys = _make_keys_list(secret_key)
''',
    )
    out = _lift(
        """
        import vendinst_helper_listcomp

        def test_secret_keys_iterable():
            signer = vendinst_helper_listcomp.Signer([b"k"])
            assert signer.secret_keys == signer.secret_keys
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendinst_helper_listcomp.Signer" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    secret = ctor("python:bytes", [str_const("k")])
    iterable_arg = ctor("python:list", [secret])
    helper_eqs = []
    output_list_eqs = []
    identity_eqs = []
    for atom in _iter_conjuncts(assertion.inv):
        if getattr(atom, "name", None) != "=":
            continue
        args = getattr(atom, "args", ())
        helper_side = next(
            (
                side
                for side in args
                if "callresult_vendinst_helper_listcomp__make_keys_list_a1"
                in getattr(side, "name", "")
            ),
            None,
        )
        list_side = next(
            (
                side
                for side in args
                if getattr(side, "name", "") == "python:list"
            ),
            None,
        )
        if (
            helper_side is not None
            and getattr(helper_side, "args", ()) == (iterable_arg,)
        ):
            helper_eqs.append(atom)
        if list_side is not None and any(
            "callresult_vendinst_helper_listcomp_want_bytes_a1"
            in getattr(element, "name", "")
            and getattr(element, "args", ()) == (secret,)
            for element in getattr(list_side, "args", ())
        ):
            output_list_eqs.append(atom)
        if any(
            "callresult_vendinst_helper_listcomp_want_bytes_a1"
            in getattr(side, "name", "")
            and getattr(side, "args", ()) == (secret,)
            for side in args
        ) and secret in args:
            identity_eqs.append(atom)

    assert helper_eqs
    assert output_list_eqs
    assert identity_eqs

    assert any(
        warrant.get("role") == "python.list-adapter-universe"
        and warrant.get("list_adapter_branch") == "iterable"
        for warrant in assertion.source_warrants
    )

    list_audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.list-adapter-universe"
        and "vendinst_helper_listcomp" in audit["contract"]["name"]
    )
    assert list_audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") in {"Return", "ListComp"}
        and "iterable branch emitted" in locus.get("reason", "")
        for locus in list_audit["loci"]
    ), list_audit
    assert any(
        locus["status"] == "inactive"
        and locus.get("ast_kind") == "If"
        and "scalar branch inactive" in locus.get("reason", "")
        for locus in list_audit["loci"]
    ), list_audit


def test_instance_field_universe_walks_last_item_property_getter(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        instance_field_universe_for_callee,
        list_adapter_universe_for_callee,
    )

    instance_field_universe_for_callee.cache_clear()
    list_adapter_universe_for_callee.cache_clear()
    vendor_path(
        "vendinst_property_last",
        '''
def want_bytes(s):
    if isinstance(s, str):
        s = s.encode()

    return s


def _make_keys_list(secret_key):
    if isinstance(secret_key, (str, bytes)):
        return [want_bytes(secret_key)]

    return [want_bytes(s) for s in secret_key]


class Signer:
    def __init__(self, secret_key):
        self.secret_keys = _make_keys_list(secret_key)

    @property
    def secret_key(self):
        return self.secret_keys[-1]
''',
    )

    universe, refusal = instance_field_universe_for_callee(
        "vendinst_property_last.Signer.secret_key"
    )
    assert refusal is None
    assert universe is not None
    assert universe.field_name == "secret_keys"
    assert universe.field_projection == ("index", -1)
    assert universe.helper_callee == "vendinst_property_last._make_keys_list"


def test_instance_field_universe_skips_overload_init_stubs(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        instance_field_universe_for_callee,
        list_adapter_universe_for_callee,
    )

    instance_field_universe_for_callee.cache_clear()
    list_adapter_universe_for_callee.cache_clear()
    vendor_path(
        "vendinst_property_overloaded_init",
        '''
import typing as t


def want_bytes(s):
    if isinstance(s, str):
        s = s.encode()

    return s


def _make_keys_list(secret_key):
    if isinstance(secret_key, (str, bytes)):
        return [want_bytes(secret_key)]

    return [want_bytes(s) for s in secret_key]


class Signer:
    @t.overload
    def __init__(self, secret_key): ...

    def __init__(self, secret_key):
        self.secret_keys = _make_keys_list(secret_key)

    @property
    def secret_key(self):
        return self.secret_keys[-1]
''',
    )

    universe, refusal = instance_field_universe_for_callee(
        "vendinst_property_overloaded_init.Signer.secret_key"
    )
    assert refusal is None
    assert universe is not None
    assert universe.field_name == "secret_keys"
    assert universe.field_projection == ("index", -1)
    assert universe.helper_callee == "vendinst_property_overloaded_init._make_keys_list"


def test_instance_field_last_item_property_composes_helper_list_adapter(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        bytes_identity_universe_for_callee,
        instance_field_universe_for_callee,
        list_adapter_universe_for_callee,
    )

    bytes_identity_universe_for_callee.cache_clear()
    instance_field_universe_for_callee.cache_clear()
    list_adapter_universe_for_callee.cache_clear()
    vendor_path(
        "vendinst_property_compose",
        '''
def want_bytes(s):
    if isinstance(s, str):
        s = s.encode()

    return s


def _make_keys_list(secret_key):
    if isinstance(secret_key, (str, bytes)):
        return [want_bytes(secret_key)]

    return [want_bytes(s) for s in secret_key]


class Signer:
    def __init__(self, secret_key):
        self.secret_keys = _make_keys_list(secret_key)

    @property
    def secret_key(self):
        return self.secret_keys[-1]
''',
    )
    out = _lift(
        """
        import vendinst_property_compose

        def test_secret_key_property():
            signer = vendinst_property_compose.Signer(b"k")
            assert signer.secret_key == b"wrong"
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendinst_property_compose.Signer" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    secret = ctor("python:bytes", [str_const("k")])
    adapter = ctor(
        "callresult_vendinst_property_compose_want_bytes_a1",
        [secret],
    )
    property_eqs = []
    identity_eqs = []
    for atom in _iter_conjuncts(assertion.inv):
        if getattr(atom, "name", None) != "=":
            continue
        args = getattr(atom, "args", ())
        if adapter in args and any(
            getattr(side, "name", "") == "signer$0.secret_key"
            for side in args
        ):
            property_eqs.append(atom)
        if adapter in args and secret in args:
            identity_eqs.append(atom)

    assert property_eqs
    assert identity_eqs
    assert {
        "python.instance-field-universe",
        "python.list-adapter-universe",
        "python.bytes-identity-universe",
    } <= {warrant.get("role") for warrant in assertion.source_warrants}


def test_package_accounting_classifies_last_item_property_getter(tmp_path, monkeypatch):
    pkg = tmp_path / "vendpkg_property_last"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "signer.py").write_text(
        textwrap.dedent(
            '''
            def want_bytes(s):
                if isinstance(s, str):
                    s = s.encode()

                return s


            def _make_keys_list(secret_key):
                if isinstance(secret_key, (str, bytes)):
                    return [want_bytes(secret_key)]

                return [want_bytes(s) for s in secret_key]


            class Signer:
                def __init__(self, secret_key):
                    self.secret_keys = _make_keys_list(secret_key)

                @property
                def secret_key(self):
                    return self.secret_keys[-1]
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        from vendpkg_property_last.signer import Signer

        def test_secret_key_property():
            signer = Signer(b"k")
            assert signer.secret_key == b"wrong"
        """,
    )

    property_audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.instance-field-universe"
        and audit.get("source_memento", {}).get("source_function_name")
        == "Signer.secret_key"
    )
    assert property_audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Return"
        for locus in property_audit["loci"]
    ), property_audit

    for audit in lifted["sourceAudits"]:
        if audit.get("role") != "python.package-source":
            continue
        property_loci = [
            locus
            for locus in audit["loci"]
            if locus["file"].endswith("vendpkg_property_last/signer.py")
            and "self.secret_keys[-1]" in Path(locus["file"]).read_text()
            and locus.get("ast_kind") in {"Return", "Subscript"}
        ]
        assert not [
            locus for locus in property_loci if locus["status"] == "unclassified"
        ], property_loci


def test_package_accounting_discovers_untriggered_instance_field_getter(
    tmp_path,
    monkeypatch,
):
    pkg = tmp_path / "vendpkg_property_last_untriggered"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "signer.py").write_text(
        textwrap.dedent(
            '''
            def want_bytes(s):
                if isinstance(s, str):
                    s = s.encode()

                return s


            def _make_keys_list(secret_key):
                if isinstance(secret_key, (str, bytes)):
                    return [want_bytes(secret_key)]

                return [want_bytes(s) for s in secret_key]


            class Signer:
                def __init__(self, secret_key):
                    self.secret_keys = _make_keys_list(secret_key)

                @property
                def secret_key(self):
                    return self.secret_keys[-1]

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_property_last_untriggered.signer as signer

        def test_token():
            assert signer.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    property_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_property_last_untriggered/signer.py")
        and locus.get("ast_path", "").startswith("$.module.body[2].body[1].body")
    ]
    assert property_loci
    assert not [
        locus for locus in property_loci if locus["status"] == "unclassified"
    ], property_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") in {"Return", "Subscript"}
        and "instance-field" in locus.get("reason", "")
        for locus in property_loci
    ), property_loci


def test_package_accounting_warrants_local_call_term_assignment(
    tmp_path,
    monkeypatch,
):
    pkg = tmp_path / "vendpkg_local_call_binding"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "signer.py").write_text(
        textwrap.dedent(
            '''
            class Signer:
                def derive_key(self):
                    return b"k"

                def verify_signature(self, secret_keys):
                    for secret_key in secret_keys:
                        key = self.derive_key(secret_key)
                        if key:
                            return True
                    return False

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_local_call_binding.signer as signer

        def test_token():
            assert signer.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    assignment_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_local_call_binding/signer.py")
        and locus["line"] == 8
    ]
    assert assignment_loci
    assert not [
        locus for locus in assignment_loci if locus["status"] == "unclassified"
    ], assignment_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "call-term SSA" in locus.get("reason", "")
        for locus in assignment_loci
    ), assignment_loci


def test_structural_package_accounting_warrants_local_call_term_assignment(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_structural_local_call_binding"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "signer.py"
    module_path.write_text(
        textwrap.dedent(
            '''
            class Signer:
                def derive_key(self, secret_key):
                    return secret_key

                def verify_signature(self, secret_key):
                    key = self.derive_key(secret_key)
                    if key:
                        return True
                    return False

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    key_line = next(
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith("key = ")
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_structural_local_call_binding.signer as signer

        def test_token():
            assert signer.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    assignment_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_structural_local_call_binding/signer.py")
        and locus["line"] == key_line
    ]
    assert assignment_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Assign"
        and "local SSA binding" in locus.get("reason", "")
        for locus in assignment_loci
    ), assignment_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "call-term SSA" in locus.get("reason", "")
        for locus in assignment_loci
    ), assignment_loci
    assert not [
        locus
        for locus in assignment_loci
        if locus.get("ast_kind") in {"Call", "Attribute", "Name"}
        and locus["status"] == "unclassified"
    ], assignment_loci


def test_structural_package_accounting_warrants_return_call_term(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_structural_return_call"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "signer.py"
    module_path.write_text(
        textwrap.dedent(
            '''
            class Signer:
                def derive_key(self, secret_key):
                    return secret_key

                def current_key(self, secret_key):
                    return self.derive_key(secret_key)

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    return_line = next(
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith("return self.derive_key")
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_structural_return_call.signer as signer

        def test_token():
            assert signer.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    return_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_structural_return_call/signer.py")
        and locus["line"] == return_line
    ]
    assert return_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Return"
        and "return call-term" in locus.get("reason", "")
        for locus in return_loci
    ), return_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "return call-term" in locus.get("reason", "")
        for locus in return_loci
    ), return_loci
    assert not [
        locus
        for locus in return_loci
        if locus.get("ast_kind") in {"Return", "Call", "Attribute", "Name"}
        and locus["status"] == "unclassified"
    ], return_loci


def test_structural_package_accounting_warrants_call_terms_with_pure_value_arguments(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_structural_call_value_args"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "signer.py"
    module_path.write_text(
        textwrap.dedent(
            '''
            def pure_fn(value, key=None, flags=None):
                return value

            class Signer:
                def current_key(self, values):
                    key = pure_fn(
                        values[0],
                        key=self.salt + "-x",
                        flags={"mode": ("strict", len(values))},
                    )
                    return key

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    source_lines = module_path.read_text().splitlines()
    start_line = next(
        line_no
        for line_no, line in enumerate(source_lines, 1)
        if line.strip().startswith("key = pure_fn")
    )
    end_line = next(
        line_no
        for line_no, line in enumerate(source_lines, 1)
        if line_no > start_line and line.strip() == ")"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_structural_call_value_args.signer as signer

        def test_token():
            assert signer.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    assignment_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_structural_call_value_args/signer.py")
        and start_line <= locus["line"] <= end_line
        and locus.get("ast_kind")
        in {
            "Assign",
            "Call",
            "Name",
            "Attribute",
            "Subscript",
            "BinOp",
            "Dict",
            "Tuple",
            "Constant",
            "keyword",
        }
    ]
    assert assignment_loci
    assert not [
        locus for locus in assignment_loci if locus["status"] == "unclassified"
    ], assignment_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "call-term SSA" in locus.get("reason", "")
        for locus in assignment_loci
    ), assignment_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") in {"Subscript", "BinOp", "Dict", "Tuple"}
        and "call-term SSA" in locus.get("reason", "")
        for locus in assignment_loci
    ), assignment_loci


def test_structural_package_accounting_warrants_local_constructor_call_terms(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_structural_constructor_call"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "signer.py"
    module_path.write_text(
        textwrap.dedent(
            '''
            class Payload:
                def __init__(self, value, tag=None):
                    self.value = value
                    self.tag = tag

            def skipped(value):
                payload = Payload(value, tag="x")
                return payload

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    constructor_line = next(
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if "Payload(value" in line
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_structural_constructor_call.signer as signer

        def test_token():
            assert signer.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    constructor_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_structural_constructor_call/signer.py")
        and locus["line"] == constructor_line
        and locus.get("ast_kind") in {"Assign", "Call", "Name", "Constant", "keyword"}
    ]
    assert constructor_loci
    assert not [
        locus for locus in constructor_loci if locus["status"] == "unclassified"
    ], constructor_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "constructor call-term" in locus.get("reason", "")
        for locus in constructor_loci
    ), constructor_loci


def test_structural_package_accounting_warrants_return_through_local_bindings(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_structural_return_local"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "signer.py"
    module_path.write_text(
        textwrap.dedent(
            '''
            def helper(value):
                return value

            def skipped(value, use_default):
                result = helper(value)
                if use_default:
                    return result
                fallback = "fallback"
                return fallback

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    branch_return_line = next(
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip() == "return result"
    )
    fallback_return_line = next(
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip() == "return fallback"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_structural_return_local.signer as signer

        def test_token():
            assert signer.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    return_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_structural_return_local/signer.py")
        and locus["line"] in {branch_return_line, fallback_return_line}
        and locus.get("ast_kind") in {"Return", "Name"}
    ]
    assert return_loci
    assert not [
        locus for locus in return_loci if locus["status"] == "unclassified"
    ], return_loci
    assert any(
        locus["status"] == "warranted"
        and locus["line"] == branch_return_line
        and locus.get("ast_kind") == "Return"
        and "return-through-local" in locus.get("reason", "")
        for locus in return_loci
    ), return_loci
    assert any(
        locus["status"] == "warranted"
        and locus["line"] == fallback_return_line
        and locus.get("ast_kind") == "Return"
        and "return-through-local" in locus.get("reason", "")
        for locus in return_loci
    ), return_loci


def test_structural_package_accounting_warrants_terminal_conditional_returns(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_structural_conditional_returns"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "signer.py"
    module_path.write_text(
        textwrap.dedent(
            '''
            def skipped(value, fallback):
                selected = value
                if selected == fallback:
                    return selected
                return "default"

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    conditional_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith(("if ", "return selected", 'return "default"'))
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_structural_conditional_returns.signer as signer

        def test_token():
            assert signer.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    conditional_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_structural_conditional_returns/signer.py")
        and locus["line"] in conditional_lines
        and locus.get("ast_kind") in {"If", "Compare", "Return", "Name", "Constant"}
    ]
    assert conditional_loci
    assert not [
        locus for locus in conditional_loci if locus["status"] == "unclassified"
    ], conditional_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "If"
        and "terminal conditional return" in locus.get("reason", "")
        for locus in conditional_loci
    ), conditional_loci


def test_structural_package_accounting_refuses_dynamic_receiver_method_dispatch(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_structural_dynamic_receiver"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "signer.py"
    module_path.write_text(
        textwrap.dedent(
            '''
            def skipped(adapter, value):
                result = adapter.transform(value)
                return result

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    dispatch_line = next(
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if "adapter.transform" in line
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_structural_dynamic_receiver.signer as signer

        def test_token():
            assert signer.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    dispatch_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_structural_dynamic_receiver/signer.py")
        and locus["line"] == dispatch_line
        and locus.get("ast_kind") in {"Assign", "Call", "Attribute", "Name"}
    ]
    assert dispatch_loci
    assert not [
        locus for locus in dispatch_loci if locus["status"] == "unclassified"
    ], dispatch_loci
    assert {locus["status"] for locus in dispatch_loci} == {"refused"}
    assert all(
        "dynamic receiver method dispatch" in locus.get("reason", "")
        for locus in dispatch_loci
    ), dispatch_loci


def test_structural_package_accounting_classifies_formatted_strings(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_structural_formatted_strings"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "signer.py"
    module_path.write_text(
        textwrap.dedent(
            '''
            def skipped(value):
                safe = f"token:{value.name}"
                runtime = f"{value!r:>10}"
                return safe

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    safe_line = next(
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if "safe = " in line
    )
    runtime_line = next(
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if "runtime = " in line
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_structural_formatted_strings.signer as signer

        def test_token():
            assert signer.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    formatted_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_structural_formatted_strings/signer.py")
        and locus["line"] in {safe_line, runtime_line}
        and locus.get("ast_kind")
        in {"Assign", "JoinedStr", "FormattedValue", "Constant", "Name", "Attribute"}
    ]
    assert formatted_loci
    assert not [
        locus for locus in formatted_loci if locus["status"] == "unclassified"
    ], formatted_loci
    assert any(
        locus["line"] == safe_line
        and locus["status"] == "warranted"
        and locus.get("ast_kind") == "JoinedStr"
        and "formatted string" in locus.get("reason", "")
        for locus in formatted_loci
    ), formatted_loci
    assert any(
        locus["line"] == runtime_line
        and locus["status"] == "refused"
        and locus.get("ast_kind") == "JoinedStr"
        and "formatted string runtime formatting" in locus.get("reason", "")
        for locus in formatted_loci
    ), formatted_loci


def test_structural_package_accounting_warrants_subscript_and_slice_terms(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_structural_subscript_slice_terms"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "signer.py"
    module_path.write_text(
        textwrap.dedent(
            '''
            def skipped(values, key, start):
                head = values[0]
                window = values[start:start + 2]
                picked = values[key]
                return head

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    selector_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith(("head =", "window =", "picked ="))
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_structural_subscript_slice_terms.signer as signer

        def test_token():
            assert signer.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    selector_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_structural_subscript_slice_terms/signer.py")
        and locus["line"] in selector_lines
        and locus.get("ast_kind")
        in {"Assign", "Subscript", "Slice", "Name", "Constant", "BinOp"}
    ]
    assert selector_loci
    assert not [
        locus for locus in selector_loci if locus["status"] == "unclassified"
    ], selector_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Subscript"
        and "subscript/slice" in locus.get("reason", "")
        for locus in selector_loci
    ), selector_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Slice"
        and "subscript/slice" in locus.get("reason", "")
        for locus in selector_loci
    ), selector_loci


def test_structural_package_accounting_warrants_ifexp_value_terms(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_structural_ifexp_terms"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "signer.py"
    module_path.write_text(
        textwrap.dedent(
            '''
            def skipped(flag, value, fallback):
                selected = value if flag else fallback
                named = value.name if flag else fallback.name
                return selected

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    ifexp_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if line.strip().startswith(("selected =", "named ="))
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_structural_ifexp_terms.signer as signer

        def test_token():
            assert signer.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    ifexp_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_structural_ifexp_terms/signer.py")
        and locus["line"] in ifexp_lines
        and locus.get("ast_kind") in {"Assign", "IfExp", "Name", "Attribute"}
    ]
    assert ifexp_loci
    assert not [
        locus for locus in ifexp_loci if locus["status"] == "unclassified"
    ], ifexp_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "IfExp"
        and "conditional value expression" in locus.get("reason", "")
        for locus in ifexp_loci
    ), ifexp_loci


def test_structural_package_accounting_refuses_comprehensions_and_lambdas(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_structural_comprehensions"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "signer.py"
    module_path.write_text(
        textwrap.dedent(
            '''
            def skipped(values):
                doubled = [value * 2 for value in values]
                lazy = (value for value in values)
                project = lambda value: value.name
                return doubled

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    refused_lines = {
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if any(marker in line for marker in ("[value * 2", "(value for", "lambda "))
    }
    monkeypatch.syspath_prepend(str(tmp_path))
    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_structural_comprehensions.signer as signer

        def test_token():
            assert signer.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    flow_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_structural_comprehensions/signer.py")
        and locus["line"] in refused_lines
        and locus.get("ast_kind")
        in {
            "Assign",
            "ListComp",
            "GeneratorExp",
            "Lambda",
            "Name",
            "BinOp",
            "Constant",
            "Attribute",
        }
    ]
    assert flow_loci
    assert not [
        locus for locus in flow_loci if locus["status"] == "unclassified"
    ], flow_loci
    assert {locus["status"] for locus in flow_loci} == {"refused"}
    assert all(
        "collection/lambda flow" in locus.get("reason", "")
        for locus in flow_loci
    ), flow_loci


def test_structural_package_accounting_warrants_regex_fullmatch(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_structural_regex"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    module_path = pkg / "matcher.py"
    module_path.write_text(
        textwrap.dedent(
            r'''
            import re

            def is_slug(value):
                pattern = re.compile(r"^[a-z]+$")
                return pattern.fullmatch(value) is not None

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    compile_line = next(
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if "re.compile" in line
    )
    fullmatch_line = next(
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if "fullmatch" in line
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_structural_regex.matcher as matcher

        def test_token():
            assert matcher.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    regex_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_structural_regex/matcher.py")
        and locus["line"] in {compile_line, fullmatch_line}
    ]
    assert regex_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "regex" in locus.get("reason", "")
        for locus in regex_loci
    ), regex_loci
    assert not [
        locus
        for locus in regex_loci
        if locus.get("ast_kind") in {"Return", "Compare", "Call", "Attribute", "Name"}
        and locus["status"] == "unclassified"
    ], regex_loci


def test_structural_package_accounting_regex_does_not_resolve_by_import(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_structural_regex_no_import"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "safe.py").write_text(
        textwrap.dedent(
            """
            def b64e(s):
                return s.rstrip(b"=")
            """
        ),
        encoding="utf-8",
    )
    matcher_path = pkg / "matcher.py"
    matcher_path.write_text(
        textwrap.dedent(
            r'''
            import re

            def is_slug(value):
                pattern = re.compile(r"^[a-z]+$")
                return pattern.fullmatch(value) is not None
            '''
        ),
        encoding="utf-8",
    )
    fullmatch_line = next(
        line_no
        for line_no, line in enumerate(matcher_path.read_text().splitlines(), 1)
        if "fullmatch" in line
    )

    import sugar_lift_py_tests.lsp as lsp_mod

    def _fail_if_regex_package_accounting_imports(callee):
        if "vendpkg_structural_regex_no_import.matcher.is_slug" in callee:
            raise AssertionError("structural package accounting must not import")
        return None, None

    monkeypatch.setattr(
        lsp_mod,
        "return_regex_universe_for_callee",
        _fail_if_regex_package_accounting_imports,
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_structural_regex_no_import.safe as safe

        def test_token():
            assert safe.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    fullmatch_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_structural_regex_no_import/matcher.py")
        and locus["line"] == fullmatch_line
    ]
    assert fullmatch_loci
    assert not [
        locus
        for locus in fullmatch_loci
        if locus.get("ast_kind") in {"Return", "Compare", "Call", "Attribute", "Name"}
        and locus["status"] == "unclassified"
    ], fullmatch_loci


def test_structural_package_accounting_warrants_module_regex_match_boolop(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    pkg = tmp_path / "vendpkg_structural_regex_module_match"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "safe.py").write_text(
        textwrap.dedent(
            """
            def b64e(s):
                return s.rstrip(b"=")
            """
        ),
        encoding="utf-8",
    )
    module_path = pkg / "urlcheck.py"
    module_path.write_text(
        textwrap.dedent(
            r'''
            import re

            _URL = re.compile(r"^s3://")

            def is_url(value):
                return isinstance(value, str) and bool(_URL.match(value))
            '''
        ),
        encoding="utf-8",
    )
    match_line = next(
        line_no
        for line_no, line in enumerate(module_path.read_text().splitlines(), 1)
        if "_URL.match" in line
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_structural_regex_module_match.safe as safe

        def test_token():
            assert safe.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    match_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_structural_regex_module_match/urlcheck.py")
        and locus["line"] == match_line
    ]
    assert match_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "regex match" in locus.get("reason", "")
        for locus in match_loci
    ), match_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "known pure call value term" in locus.get("reason", "")
        for locus in match_loci
    ), match_loci
    assert not [
        locus
        for locus in match_loci
        if locus.get("ast_kind") == "Call"
        and locus["status"] == "unclassified"
    ], match_loci


def test_package_accounting_warrants_tuple_unpack_call_projection(
    tmp_path,
    monkeypatch,
):
    pkg = tmp_path / "vendpkg_tuple_unpack_call"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "timed.py").write_text(
        textwrap.dedent(
            '''
            def unsign(result, sep):
                value, ts_bytes = result.rsplit(sep, 1)
                return value

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_tuple_unpack_call.timed as timed

        def test_token():
            assert timed.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    unpack_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_tuple_unpack_call/timed.py")
        and locus["line"] == 3
    ]
    assert unpack_loci
    assert not [
        locus for locus in unpack_loci if locus["status"] == "unclassified"
    ], unpack_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Tuple"
        and "tuple-unpack" in locus.get("reason", "")
        for locus in unpack_loci
    ), unpack_loci


def test_package_accounting_warrants_computed_receiver_call_binding(
    tmp_path,
    monkeypatch,
):
    pkg = tmp_path / "vendpkg_computed_receiver_call"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "serializer.py").write_text(
        textwrap.dedent(
            '''
            class Signer:
                def sign(self, payload):
                    return payload

            class Serializer:
                def make_signer(self, salt):
                    return Signer()

                def dumps(self, payload, salt):
                    rv = self.make_signer(salt).sign(payload)
                    return rv

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_computed_receiver_call.serializer as serializer

        def test_token():
            assert serializer.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    binding_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_computed_receiver_call/serializer.py")
        and locus["line"] == 11
    ]
    assert binding_loci
    assert not [
        locus for locus in binding_loci if locus["status"] == "unclassified"
    ], binding_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "call-term SSA" in locus.get("reason", "")
        for locus in binding_loci
    ), binding_loci


def test_package_accounting_warrants_super_receiver_call_binding(
    tmp_path,
    monkeypatch,
):
    pkg = tmp_path / "vendpkg_super_receiver_call"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "serializer.py").write_text(
        textwrap.dedent(
            '''
            class Base:
                def dump_payload(self, obj):
                    return obj

            class Child(Base):
                def dump_payload(self, obj):
                    payload = super().dump_payload(obj)
                    return payload

            def b64e(s):
                return s.rstrip(b"=")
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    lifted = _lift_source_from_disk(
        tmp_path,
        "test_mod.py",
        """
        import vendpkg_super_receiver_call.serializer as serializer

        def test_token():
            assert serializer.b64e(b"abc") == b"abc"
        """,
    )

    audit = next(
        audit
        for audit in lifted["sourceAudits"]
        if audit.get("role") == "python.package-source"
    )
    binding_loci = [
        locus
        for locus in audit["loci"]
        if locus["file"].endswith("vendpkg_super_receiver_call/serializer.py")
        and locus["line"] == 8
    ]
    assert binding_loci
    assert not [
        locus for locus in binding_loci if locus["status"] == "unclassified"
    ], binding_loci
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "call-term SSA" in locus.get("reason", "")
        for locus in binding_loci
    ), binding_loci


def test_instance_field_universe_maps_default_constructor_field(vendor_path):
    vendor_path(
        "vendinst_default_attr",
        '''
class HeaderError(Exception):
    def __init__(self, message, payload=None, header=None):
        super().__init__(message, payload)
        self.payload = payload
        self.header = header
''',
    )
    out = _lift(
        """
        import vendinst_default_attr

        def test_default_header():
            err = vendinst_default_attr.HeaderError("bad")
            assert err.header == None
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendinst_default_attr.HeaderError" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    none_term = ctor("None", [])
    field_eqs = [
        atom
        for atom in _iter_conjuncts(assertion.inv)
        if getattr(atom, "name", None) == "="
        and none_term in getattr(atom, "args", ())
        and any(
            getattr(side, "name", "") == "err$0.header"
            for side in getattr(atom, "args", ())
        )
    ]
    assert field_eqs

    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.instance-field-universe"
        and audit["source_memento"].get("source_function_name")
        == "HeaderError.__init__"
    )
    assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Constant"
        and locus.get("line") == 3
        and locus.get("ast_path") == "$.args.defaults[1]"
        and "default constructor argument emitted" in locus.get("reason", "")
        for locus in audit["loci"]
    ), audit


def test_instance_field_universe_maps_conditional_default_constructor_field(vendor_path):
    vendor_path(
        "vendinst_conditional_default_attr",
        '''
class HMACAlgorithm:
    default_digest_method = object()

    def __init__(self, digest_method=None):
        if digest_method is None:
            digest_method = self.default_digest_method
        self.digest_method = digest_method
''',
    )
    out = _lift(
        """
        import vendinst_conditional_default_attr

        def test_default_digest_method():
            alg = vendinst_conditional_default_attr.HMACAlgorithm()
            assert alg.digest_method == alg.default_digest_method
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendinst_conditional_default_attr.HMACAlgorithm" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    field_warrants = [
        warrant
        for warrant in assertion.source_warrants
        if warrant.get("role") == "python.instance-field-universe"
    ]
    assert len(field_warrants) == 1
    assert field_warrants[0].get("source_function_name") == "HMACAlgorithm.__init__"
    assert field_warrants[0].get("constructor_default_param_names") == [
        "digest_method"
    ]
    assert (
        field_warrants[0].get("constructor_default_attr_name")
        == "default_digest_method"
    )

    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.instance-field-universe"
        and audit["source_memento"].get("source_function_name")
        == "HMACAlgorithm.__init__"
    )
    assert audit["source_memento"].get("constructor_default_attr_name") == (
        "default_digest_method"
    )
    assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted" and locus.get("ast_kind") == "If"
        for locus in audit["loci"]
    ), audit
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Constant"
        and locus.get("ast_path") == "$.args.defaults[0]"
        and "default constructor argument emitted" in locus.get("reason", "")
        for locus in audit["loci"]
    ), audit
    assert any(
        locus["status"] == "warranted" and locus.get("ast_kind") == "Assign"
        for locus in audit["loci"]
    ), audit


def test_instance_field_universe_scans_later_constructor_defaults(vendor_path):
    vendor_path(
        "vendinst_later_default_attr",
        '''
def want_bytes(s, encoding="utf-8", errors="strict"):
    if isinstance(s, str):
        s = s.encode(encoding, errors)

    return s


class Signer:
    _base64_alphabet = b"abcdefghijklmnopqrstuvwxyz"
    default_key_derivation = "django-concat"

    def __init__(
        self,
        secret_key,
        salt=b"itsdangerous.Signer",
        sep=b".",
        key_derivation=None,
    ):
        self.secret_key = secret_key
        self.sep = want_bytes(sep)

        if self.sep in self._base64_alphabet:
            raise ValueError("bad separator")

        if salt is not None:
            salt = want_bytes(salt)
        else:
            salt = b"itsdangerous.Signer"

        self.salt = salt

        if key_derivation is None:
            key_derivation = self.default_key_derivation

        self.key_derivation = key_derivation
''',
    )
    out = _lift(
        """
        import vendinst_later_default_attr

        def test_default_key_derivation():
            signer = vendinst_later_default_attr.Signer("secret")
            assert signer.key_derivation == signer.default_key_derivation
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendinst_later_default_attr.Signer" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    field_warrants = [
        warrant
        for warrant in assertion.source_warrants
        if warrant.get("role") == "python.instance-field-universe"
    ]
    assert len(field_warrants) == 1
    assert field_warrants[0].get("source_function_name") == "Signer.__init__"
    assert field_warrants[0].get("constructor_default_param_names") == [
        "key_derivation"
    ]
    assert (
        field_warrants[0].get("constructor_default_attr_name")
        == "default_key_derivation"
    )

    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.instance-field-universe"
        and audit["source_memento"].get("source_function_name")
        == "Signer.__init__"
    )
    assert audit["source_memento"].get("constructor_default_attr_name") == (
        "default_key_derivation"
    )
    assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "If"
        for locus in audit["loci"]
    ), audit
    assert any(
        locus["status"] == "support"
        and locus.get("ast_kind") == "If"
        for locus in audit["loci"]
    ), audit
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Assign"
        for locus in audit["loci"]
    ), audit


def test_instance_field_universe_maps_bool_or_default_collection(vendor_path):
    vendor_path(
        "vendinst_bool_or_default",
        '''
class Serializer:
    def __init__(self, signer_kwargs=None):
        self.signer_kwargs = signer_kwargs or {}
''',
    )
    out = _lift(
        """
        import vendinst_bool_or_default

        def test_default_signer_kwargs():
            serializer = vendinst_bool_or_default.Serializer()
            assert serializer.signer_kwargs == {}
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendinst_bool_or_default.Serializer" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]
    field_warrants = [
        warrant
        for warrant in assertion.source_warrants
        if warrant.get("role") == "python.instance-field-universe"
    ]
    assert len(field_warrants) == 1
    assert field_warrants[0].get("source_function_name") == "Serializer.__init__"
    assert field_warrants[0].get("constructor_default_literal_kind") == "collection"
    assert field_warrants[0].get("constructor_default_literal") == "dict:{}"

    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.instance-field-universe"
        and audit["source_memento"].get("source_function_name")
        == "Serializer.__init__"
    )
    assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") in {"Assign", "BoolOp", "Dict"}
        and locus.get("line") == 4
        for locus in audit["loci"]
    ), audit


def test_constructor_field_universe_skips_overload_stubs(vendor_path):
    vendor_path(
        "vendinst_overloaded_init",
        '''
import typing as t


class Serializer:
    default_serializer = object()

    @t.overload
    def __init__(self, serializer=None): ...

    def __init__(self, serializer=None):
        if serializer is None:
            serializer = self.default_serializer

        self.serializer = serializer
''',
    )
    out = _lift(
        """
        import vendinst_overloaded_init

        def test_default_serializer():
            serializer = vendinst_overloaded_init.Serializer()
            assert serializer.serializer == serializer.default_serializer
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendinst_overloaded_init.Serializer" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]
    field_warrants = [
        warrant
        for warrant in assertion.source_warrants
        if warrant.get("role") == "python.instance-field-universe"
    ]
    assert len(field_warrants) == 1
    assert field_warrants[0].get("source_function_name") == "Serializer.__init__"
    assert (
        field_warrants[0].get("constructor_default_attr_name")
        == "default_serializer"
    )
    assert field_warrants[0].get("span", {}).get("start_line") == 11


def test_constructor_field_universe_scans_past_unrelated_call_field(vendor_path):
    vendor_path(
        "vendinst_unrelated_call_field",
        '''
def is_text_serializer(serializer):
    return True


class Serializer:
    def __init__(self, signer_kwargs=None):
        self.signer_kwargs = signer_kwargs or {}
        self.is_text_serializer = is_text_serializer(signer_kwargs)
''',
    )
    out = _lift(
        """
        import vendinst_unrelated_call_field

        def test_default_signer_kwargs():
            serializer = vendinst_unrelated_call_field.Serializer()
            assert serializer.signer_kwargs == {}
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendinst_unrelated_call_field.Serializer" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]
    assert any(
        warrant.get("role") == "python.instance-field-universe"
        and warrant.get("constructor_default_literal") == "dict:{}"
        for warrant in assertion.source_warrants
    ), assertion.source_warrants


def test_constructor_field_universe_contacts_not_equal_attribute_claim(vendor_path):
    vendor_path(
        "vendinst_attr_not_equal",
        '''
class Serializer:
    def __init__(self, signer_kwargs=None):
        self.signer_kwargs = signer_kwargs or {}
''',
    )
    out = _lift(
        """
        import vendinst_attr_not_equal

        def test_default_signer_kwargs_not_equal():
            serializer = vendinst_attr_not_equal.Serializer()
            assert serializer.signer_kwargs != {}
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendinst_attr_not_equal.Serializer" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]
    assert any(
        warrant.get("role") == "python.instance-field-universe"
        and warrant.get("constructor_default_literal") == "dict:{}"
        for warrant in assertion.source_warrants
    ), assertion.source_warrants


def test_branch_selected_self_field_return_maps_method_result(vendor_path):
    vendor_path(
        "vendbranch_self_field",
        '''
class Signer:
    def __init__(self, key_derivation):
        self.key_derivation = key_derivation

    def derive_key(self, secret_key):
        if self.key_derivation == "none":
            return secret_key

        raise TypeError("unknown key derivation")
''',
    )
    out = _lift(
        """
        import vendbranch_self_field

        def test_none_key_derivation():
            signer = vendbranch_self_field.Signer("none")
            assert signer.derive_key("raaaa") == "raaaa"
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendbranch_self_field.Signer.derive_key" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    from sugar_lift_py_tests.ir import str_const

    def walk(formula):
        yield formula
        for child in getattr(formula, "operands", ()):
            yield from walk(child)

    implications = [
        formula
        for formula in walk(assertion.inv)
        if getattr(formula, "kind", None) == "implies"
    ]
    assert any(
        getattr(imp.operands[1], "name", None) == "="
        and str_const("raaaa") in getattr(imp.operands[1], "args", ())
        and any(
            getattr(side, "name", "") == "callval_derive_key_a2"
            for side in getattr(imp.operands[1], "args", ())
        )
        for imp in implications
    ), assertion.inv

    assert any(
        warrant.get("role") == "python.branch-selected-universe"
        and warrant.get("source_function_name") == "Signer.derive_key"
        and warrant.get("branch_field_name") == "key_derivation"
        and warrant.get("branch_field_value") == "none"
        for warrant in assertion.source_warrants
    ), assertion.source_warrants

    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.branch-selected-universe"
        and audit["source_memento"].get("source_function_name")
        == "Signer.derive_key"
    )
    assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted" and locus.get("ast_kind") == "If"
        for locus in audit["loci"]
    ), audit
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Return"
        for locus in audit["loci"]
    ), audit
    assert any(
        locus["status"] == "inactive"
        and locus.get("ast_kind") == "Raise"
        for locus in audit["loci"]
    ), audit


def test_branch_selected_self_field_return_maps_normalized_method_arg(vendor_path):
    vendor_path(
        "vendbranch_normalized_arg",
        '''
def want_bytes(s):
    if isinstance(s, str):
        s = s.encode()

    return s


class Signer:
    def __init__(self, key_derivation):
        self.key_derivation = key_derivation

    def derive_key(self, secret_key=None):
        if secret_key is None:
            secret_key = self.secret_keys[-1]
        else:
            secret_key = want_bytes(secret_key)

        if self.key_derivation == "none":
            return secret_key

        raise TypeError("unknown key derivation")
''',
    )
    out = _lift(
        """
        import vendbranch_normalized_arg

        def test_none_key_derivation_normalizes_key():
            signer = vendbranch_normalized_arg.Signer("none")
            assert signer.derive_key(b"raaaa") == b"raaaa"
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendbranch_normalized_arg.Signer.derive_key" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    from sugar_lift_py_tests.ir import ctor, str_const

    def walk(formula):
        yield formula
        for child in getattr(formula, "operands", ()):
            yield from walk(child)

    adapter_term = ctor(
        "callresult_vendbranch_normalized_arg_want_bytes_a1",
        [ctor("python:bytes", [str_const("raaaa")])],
    )
    implications = [
        formula
        for formula in walk(assertion.inv)
        if getattr(formula, "kind", None) == "implies"
    ]
    assert any(
        getattr(imp.operands[1], "name", None) == "="
        and adapter_term in getattr(imp.operands[1], "args", ())
        and any(
            getattr(side, "name", "") == "callval_derive_key_a2"
            for side in getattr(imp.operands[1], "args", ())
        )
        for imp in implications
    ), assertion.inv

    roles = {warrant.get("role") for warrant in assertion.source_warrants}
    assert {
        "python.branch-selected-universe",
        "python.bytes-identity-universe",
    } <= roles

    audits = {
        audit["role"]: audit
        for audit in out.source_audits
        if audit["role"]
        in {"python.branch-selected-universe", "python.bytes-identity-universe"}
        and "vendbranch_normalized_arg" in audit["contract"]["name"]
    }
    assert audits["python.branch-selected-universe"]["totals"]["unclassified_source"] == 0
    assert audits["python.bytes-identity-universe"]["totals"]["unclassified_source"] == 0


def test_branch_selected_universe_contacts_not_equal_claim(vendor_path):
    vendor_path(
        "vendbranch_not_equal",
        '''
class Signer:
    def __init__(self, key_derivation):
        self.key_derivation = key_derivation

    def derive_key(self, secret_key):
        if self.key_derivation == "none":
            return secret_key

        raise TypeError("unknown key derivation")
''',
    )
    out = _lift(
        """
        import vendbranch_not_equal

        def test_none_key_derivation_not_equal():
            signer = vendbranch_not_equal.Signer("none")
            assert signer.derive_key("raaaa") != "raaaa"
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendbranch_not_equal.Signer.derive_key" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]
    assert any(
        warrant.get("role") == "python.branch-selected-universe"
        for warrant in assertion.source_warrants
    ), assertion.source_warrants

    def walk(formula):
        yield formula
        for child in getattr(formula, "operands", ()):
            yield from walk(child)

    assert any(
        getattr(formula, "kind", None) == "implies"
        for formula in walk(assertion.inv)
    ), assertion.inv


def test_branch_selected_raise_universe_walks_param_guard(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        branch_selected_raise_universe_for_callee,
    )

    branch_selected_raise_universe_for_callee.cache_clear()
    vendor_path(
        "vendbranch_raise_source",
        """
        def __getattr__(name):
            if name == "__version__":
                return "2.2.0"

            raise AttributeError(name)
        """,
    )
    u, r = branch_selected_raise_universe_for_callee(
        "vendbranch_raise_source.__getattr__"
    )
    assert r is None and u is not None
    assert u.exception_name == "AttributeError"
    assert u.param_name == "name"
    assert u.param_index == 0
    assert u.excluded_value == "__version__"
    assert u.excluded_value_kind == "str"
    assert u.source_memento is not None
    assert u.source_memento["source_function_name"] == "__getattr__"
    assert u.source_memento["branch_raise_exception_type"] == "AttributeError"


def test_pytest_raises_conjoins_branch_selected_raise_universe(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        branch_selected_raise_universe_for_callee,
    )
    from sugar_lift_py_tests.ir import _ConstStr, _Ctor
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    branch_selected_raise_universe_for_callee.cache_clear()
    vendor_path(
        "vendbranch_raise_l2",
        """
        def __getattr__(name):
            if name == "__version__":
                return "2.2.0"

            raise AttributeError(name)
        """,
    )
    out = _lift(
        """
        import pytest
        import vendbranch_raise_l2

        def test_missing_attr():
            with pytest.raises(ValueError):
                vendbranch_raise_l2.__getattr__("missing")
        """
    )
    decl = next(d for d in out.decls if d.name == "test_missing_attr")
    raised = []
    for atom in _iter_conjuncts(decl.inv):
        if getattr(atom, "name", None) != "=":
            continue
        lhs, rhs = getattr(atom, "args", ())
        if isinstance(lhs, _Ctor) and lhs.name == "raised_exc_a1":
            raised.append((lhs, rhs))
    assert [rhs.value for _, rhs in raised if isinstance(rhs, _ConstStr)] == [
        "ValueError",
        "AttributeError",
    ]
    assert raised[0][0] == raised[1][0]
    assert any(
        warrant.get("role") == "python.branch-selected-raise-universe"
        and warrant.get("source_function_name") == "__getattr__"
        and warrant.get("branch_raise_exception_type") == "AttributeError"
        for warrant in decl.source_warrants
    ), decl.source_warrants
    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.branch-selected-raise-universe"
    )
    assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted"
        for locus in audit["loci"]
    ), audit


def test_constant_vendor_vector_mismatch_refuses(vendor_path):
    from sugar_lift_py_tests.translate_universe import constant_universe_for_callee

    constant_universe_for_callee.cache_clear()
    vendor_path("vendconst_gate", 'def version():\n    return "3.1.4"\n')
    vendor_path(
        "test_vendconst_gate",
        'import vendconst_gate\n\ndef test_v():\n    assert vendconst_gate.version() == "9.9.9"\n',
    )
    u, r = constant_universe_for_callee("vendconst_gate.version")
    assert u is None and r is not None and "sample-gate" in r.reason


def constant_universe_for_callee_clear():
    from sugar_lift_py_tests.translate_universe import constant_universe_for_callee

    constant_universe_for_callee.cache_clear()


# --- return-predicate family (census #2, 24k bodies): ground eval at args ---

VENDOR_PRED = '''
def is_neg(x):
    return x < 0


def in_range(x):
    return 0 <= x and x < 100


def is_empty(s):
    return s == ""
'''


def test_predicate_universe_walks(vendor_path):
    from sugar_lift_py_tests.translate_universe import predicate_universe_for_callee

    predicate_universe_for_callee.cache_clear()
    vendor_path("vendpred_ok", VENDOR_PRED)
    u, r = predicate_universe_for_callee("vendpred_ok.is_neg")
    assert r is None and u is not None and u.params == ("x",)


def test_predicate_ground_eval(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        predicate_universe_for_callee,
        eval_predicate,
    )

    predicate_universe_for_callee.cache_clear()
    vendor_path("vendpred_eval", VENDOR_PRED)
    u, _ = predicate_universe_for_callee("vendpred_eval.is_neg")
    assert eval_predicate(u.expr, {"x": 5}) is False
    assert eval_predicate(u.expr, {"x": -3}) is True
    rng, _ = predicate_universe_for_callee("vendpred_eval.in_range")
    assert eval_predicate(rng.expr, {"x": 50}) is True
    assert eval_predicate(rng.expr, {"x": 200}) is False


def test_predicate_emits_bool_equality_at_callsite(vendor_path):
    from sugar_lift_py_tests.translate_universe import predicate_universe_for_callee
    from sugar_lift_py_tests.ir import bool_const

    predicate_universe_for_callee.cache_clear()
    vendor_path("vendpred_l2", VENDOR_PRED)
    out = _lift(
        """
        import vendpred_l2

        def test_neg():
            assert vendpred_l2.is_neg(5) == False
        """
    )
    # the universe should compute is_neg(5)==False and conjoin subject==False
    falses = []
    for d in out.decls:
        if d.name.endswith("::assertion") and d.inv is not None:
            stack = [d.inv]
            while stack:
                f = stack.pop()
                if getattr(f, "name", None) == "=" and bool_const(False) in getattr(f, "args", ()):
                    falses.append(f)
                elif getattr(f, "kind", None) in ("and", "or", "not"):
                    stack.extend(f.operands)
    assert falses


def test_predicate_impure_not_candidate(vendor_path):
    from sugar_lift_py_tests.translate_universe import predicate_universe_for_callee

    predicate_universe_for_callee.cache_clear()
    vendor_path(
        "vendpred_impure",
        "def f(x):\n    return helper(x) < 0\n",
    )
    u, r = predicate_universe_for_callee("vendpred_impure.f")
    assert u is None and r is None  # call in predicate -> not purely evaluable


def test_return_regex_universe_walks_static_fullmatch(vendor_path):
    from sugar_lift_py_tests.translate_universe import return_regex_universe_for_callee

    return_regex_universe_for_callee.cache_clear()
    vendor_path(
        "vendregex_walk",
        """
        import re

        def is_slug(value):
            return re.fullmatch(r"^[a-z]+$", value) is not None
        """,
    )

    u, r = return_regex_universe_for_callee("vendregex_walk.is_slug")
    assert r is None
    assert u is not None
    assert u.pattern == r"^[a-z]+$"
    assert u.param_index == 0


def test_return_regex_universe_walks_static_match_and_search(vendor_path):
    from sugar_lift_py_tests.translate_universe import return_regex_universe_for_callee

    return_regex_universe_for_callee.cache_clear()
    vendor_path(
        "vendregex_modes",
        r'''
        import re

        def starts_slug(value):
            return re.match(r"[a-z]+", value) is not None

        def has_slug(value):
            return re.search(r"[a-z]+", value) is not None
        ''',
    )

    match_u, match_r = return_regex_universe_for_callee(
        "vendregex_modes.starts_slug"
    )
    assert match_r is None
    assert match_u is not None
    assert match_u.match_kind == "match"
    assert match_u.membership_pattern == r"(?:[a-z]+)(?:.|\n)*"

    search_u, search_r = return_regex_universe_for_callee(
        "vendregex_modes.has_slug"
    )
    assert search_r is None
    assert search_u is not None
    assert search_u.match_kind == "search"
    assert search_u.membership_pattern == r"(?:.|\n)*(?:[a-z]+)(?:.|\n)*"


def test_return_regex_universe_refuses_anchored_search(vendor_path):
    from sugar_lift_py_tests.translate_universe import return_regex_universe_for_callee

    return_regex_universe_for_callee.cache_clear()
    vendor_path(
        "vendregex_anchor_search",
        r'''
        import re

        def has_prefix(value):
            return re.search(r"^foo", value) is not None
        ''',
    )

    u, r = return_regex_universe_for_callee("vendregex_anchor_search.has_prefix")
    assert u is None
    assert r is not None
    assert "anchor" in r.reason


def test_return_regex_emits_str_in_regex_and_source_accounting(vendor_path):
    from sugar_lift_py_tests.ir import _Atomic
    from sugar_lift_py_tests.translate_universe import return_regex_universe_for_callee

    return_regex_universe_for_callee.cache_clear()
    vendor_path(
        "vendregex_l2",
        """
        import re

        def is_slug(value):
            return re.fullmatch(r"^[a-z]+$", value) is not None
        """,
    )

    out = _lift(
        """
        import vendregex_l2

        def test_slug():
            assert vendregex_l2.is_slug("abc") == True
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendregex_l2.is_slug" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    def _walk_formula(formula):
        stack = [formula]
        while stack:
            current = stack.pop()
            yield current
            stack.extend(getattr(current, "operands", ()))

    regex_atoms = [
        f
        for f in _walk_formula(assertion.inv)
        if isinstance(f, _Atomic) and f.name == "str.in-regex"
    ]
    assert regex_atoms
    assert any(
        warrant.get("role") == "python.regex-universe"
        and warrant.get("source_function_name") == "is_slug"
        and warrant.get("regex_pattern") == r"^[a-z]+$"
        for warrant in assertion.source_warrants
    ), assertion.source_warrants

    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.regex-universe"
    )
    assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "str.in-regex" in locus.get("reason", "")
        for locus in audit["loci"]
    ), audit


def test_return_regex_match_emits_prefix_membership(vendor_path):
    from sugar_lift_py_tests.ir import _Atomic, _ConstStr
    from sugar_lift_py_tests.translate_universe import return_regex_universe_for_callee

    return_regex_universe_for_callee.cache_clear()
    vendor_path(
        "vendregex_match_l2",
        r'''
        import re

        def starts_slug(value):
            return re.match(r"[a-z]+", value) is not None
        ''',
    )

    out = _lift(
        """
        import vendregex_match_l2

        def test_slug():
            assert vendregex_match_l2.starts_slug("abc123") == True
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendregex_match_l2.starts_slug" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    def _walk_formula(formula):
        stack = [formula]
        while stack:
            current = stack.pop()
            yield current
            stack.extend(getattr(current, "operands", ()))

    regex_atoms = [
        f
        for f in _walk_formula(assertion.inv)
        if isinstance(f, _Atomic) and f.name == "str.in-regex"
    ]
    assert regex_atoms
    assert any(
        isinstance(atom.args[1], _ConstStr)
        and atom.args[1].value == r"(?:[a-z]+)(?:.|\n)*"
        for atom in regex_atoms
    ), regex_atoms


def test_return_isinstance_emits_boolean_equivalence_and_source_accounting(
    vendor_path,
):
    from sugar_lift_py_tests.ir import _Ctor
    from sugar_lift_py_tests.translate_universe import (
        return_isinstance_universe_for_callee,
    )

    return_isinstance_universe_for_callee.cache_clear()
    vendor_path(
        "vendisinst_serializer",
        """
        class Serializer:
            def dumps(self, obj):
                return "x"


        def is_text_serializer(serializer):
            return isinstance(serializer.dumps({}), str)
        """,
    )
    out = _lift(
        """
        import vendisinst_serializer

        def test_text_serializer():
            serializer = vendisinst_serializer.Serializer()
            assert vendisinst_serializer.is_text_serializer(serializer) == True
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendisinst_serializer.is_text_serializer" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]
    assert any(
        warrant.get("role") == "python.return-isinstance-universe"
        and warrant.get("source_function_name") == "is_text_serializer"
        for warrant in assertion.source_warrants
    ), assertion.source_warrants

    def _walk_formula(formula):
        stack = [formula]
        while stack:
            current = stack.pop()
            yield current
            stack.extend(getattr(current, "operands", ()))

    isinstance_atoms = [
        atom
        for atom in _walk_formula(assertion.inv)
        if getattr(atom, "name", None) == "isinstance"
    ]
    assert isinstance_atoms, assertion.inv
    assert any(
        isinstance(atom.args[0], _Ctor)
        and atom.args[0].name == "callval_dumps_a2"
        and isinstance(atom.args[1], _Ctor)
        and atom.args[1].name == "pytype_str"
        for atom in isinstance_atoms
    ), isinstance_atoms
    assert any(
        getattr(formula, "kind", None) == "implies"
        for formula in _walk_formula(assertion.inv)
    ), assertion.inv

    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.return-isinstance-universe"
    )
    assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted" and locus.get("ast_kind") == "Return"
        for locus in audit["loci"]
    ), audit
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "isinstance" in locus.get("reason", "")
        for locus in audit["loci"]
    ), audit


# --- return-replace-literals family (single-char replace complement) ---

VENDOR_REPLACE = '''
def slugify(s):
    return s.replace(" ", "-")
'''


def test_replace_family_walks(vendor_path):
    vendor_path("vendrepl_ok", VENDOR_REPLACE)
    u, r = translate_universe_for_callee("vendrepl_ok.slugify")
    assert r is None and u is not None
    assert u.kind == "chars-not-in-set" and u.forbidden == " "


def test_replace_noop_refuses(vendor_path):
    vendor_path("vendrepl_noop", 'def f(s):\n    return s.replace("x", "x")\n')
    u, r = translate_universe_for_callee("vendrepl_noop.f")
    assert u is None and r is not None and "no-op" in r.reason


def test_replace_multichar_not_candidate(vendor_path):
    vendor_path("vendrepl_multi", 'def f(s):\n    return s.replace("ab", "cd")\n')
    u, r = translate_universe_for_callee("vendrepl_multi.f")
    assert u is None and r is None  # multi-char: no clean char guarantee


def test_replace_emits_complement(vendor_path):
    vendor_path("vendrepl_l2", VENDOR_REPLACE)
    out = _lift(
        """
        import vendrepl_l2

        def test_slug():
            assert vendrepl_l2.slugify("a b") == "a-b"
        """
    )
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    atoms = [
        a
        for d in out.decls
        if d.name.endswith("::assertion") and d.inv is not None
        for a in _iter_conjuncts(d.inv)
        if a.name == "str.chars-not-in-set"
    ]
    assert atoms and atoms[0].args[1].value == " "


def test_replace_vendor_vector_with_char_refuses(vendor_path):
    vendor_path("vendrepl_gate", VENDOR_REPLACE)
    vendor_path(
        "test_vendrepl_gate",
        'import vendrepl_gate\n\ndef test_s():\n    assert vendrepl_gate.slugify("x") == "a b"\n',
    )
    u, r = translate_universe_for_callee("vendrepl_gate.slugify")
    assert u is None and r is not None and "sample-gate" in r.reason


# --- return-format family (literal prefix → prefix-of) ---

VENDOR_FORMAT = '''
def err(code):
    return "Error {}".format(code)


def ver(a, b):
    return f"v{a}.{b}"


def leading_placeholder(x):
    return "{}!".format(x)
'''


def test_format_dotformat_prefix(vendor_path):
    vendor_path("vendfmt_a", VENDOR_FORMAT)
    u, r = translate_universe_for_callee("vendfmt_a.err")
    assert r is None and u is not None
    assert u.kind == "prefix" and u.forbidden == "Error "


def test_format_fstring_prefix(vendor_path):
    vendor_path("vendfmt_b", VENDOR_FORMAT)
    u, _ = translate_universe_for_callee("vendfmt_b.ver")
    assert u.kind == "prefix" and u.forbidden == "v"


def test_format_leading_placeholder_not_candidate(vendor_path):
    vendor_path("vendfmt_c", VENDOR_FORMAT)
    u, r = translate_universe_for_callee("vendfmt_c.leading_placeholder")
    assert u is None and r is None  # starts with placeholder, no prefix


def test_format_emits_prefix_of(vendor_path):
    vendor_path("vendfmt_l2", VENDOR_FORMAT)
    out = _lift(
        """
        import vendfmt_l2

        def test_err():
            assert vendfmt_l2.err(404) == "Error 404"
        """
    )
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    atoms = [
        a
        for d in out.decls
        if d.name.endswith("::assertion") and d.inv is not None
        for a in _iter_conjuncts(d.inv)
        if a.name == "prefix-of"
    ]
    assert atoms and atoms[0].args[0].value == "Error "


def test_format_vendor_vector_wrong_prefix_refuses(vendor_path):
    vendor_path("vendfmt_gate", VENDOR_FORMAT)
    vendor_path(
        "test_vendfmt_gate",
        'import vendfmt_gate\n\ndef test_e():\n    assert vendfmt_gate.err(1) == "Oops 1"\n',
    )
    u, r = translate_universe_for_callee("vendfmt_gate.err")
    assert u is None and r is not None and "sample-gate" in r.reason


# ---------------------------------------------------------------------------
# Walrus-in-guard soundness (falsePass closed 2026-06-12). A NamedExpr in a
# stripped guard's test REBINDS a name before the remaining body runs:
# `if (x := x + 10) > 100: raise` then `return x > 5` returns True for
# f(1) at runtime, while ground-evaluating the return expression at the
# callsite's argument computes False — an emitted equality would DISCHARGE
# a wrong claim. Every strip site must refuse; each refusal is confirmed
# against a pure twin that still licenses (the refusal is the walrus, not
# collateral).
# ---------------------------------------------------------------------------

VENDOR_WALRUS_PREDICATE = '''
def f(x):
    if (x := x + 10) > 100:
        raise ValueError(x)
    return x > 5
'''

VENDOR_PURE_PREDICATE = '''
def f(x):
    if x > 100:
        raise ValueError(x)
    return x > 5
'''

VENDOR_WALRUS_CONSTANT = '''
def f(x):
    if (x := x + 10) > 100:
        raise ValueError(x)
    return "v"
'''

VENDOR_PURE_CONSTANT = '''
def f(x):
    if x > 100:
        raise ValueError(x)
    return "v"
'''


def test_walrus_guard_predicate_runtime_divergence_is_real(vendor_path):
    # The evidence, kept executable: the runtime and the naive ground-eval
    # disagree, which is exactly why the walk below must refuse.
    import importlib

    vendor_path("vendwalrus_evidence", VENDOR_WALRUS_PREDICATE)
    mod = importlib.import_module("vendwalrus_evidence")
    assert mod.f(1) is True  # x rebinds to 11; 11 > 5
    # naive evaluation of the return expression at the callsite's arg:
    assert (1 > 5) is False  # what a stripped-guard walk would emit


def test_walrus_guard_predicate_refuses(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        predicate_universe_for_callee,
    )

    predicate_universe_for_callee.cache_clear()
    vendor_path("vendwalrus_pred", VENDOR_WALRUS_PREDICATE)
    universe, refusal = predicate_universe_for_callee("vendwalrus_pred.f")
    assert universe is None
    assert refusal is not None
    assert "walrus" in refusal.reason


def test_pure_guard_predicate_still_licenses(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        predicate_universe_for_callee,
    )

    predicate_universe_for_callee.cache_clear()
    vendor_path("vendpure_pred", VENDOR_PURE_PREDICATE)
    universe, refusal = predicate_universe_for_callee("vendpure_pred.f")
    assert refusal is None
    assert universe is not None
    assert universe.params == ("x",)


def test_walrus_guard_constant_refuses(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
    )

    constant_universe_for_callee.cache_clear()
    vendor_path("vendwalrus_const", VENDOR_WALRUS_CONSTANT)
    universe, refusal = constant_universe_for_callee("vendwalrus_const.f")
    assert universe is None
    assert refusal is not None
    assert "walrus" in refusal.reason


def test_pure_guard_constant_still_licenses(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
    )

    constant_universe_for_callee.cache_clear()
    vendor_path("vendpure_const", VENDOR_PURE_CONSTANT)
    universe, refusal = constant_universe_for_callee("vendpure_const.f")
    assert refusal is None
    assert universe is not None
    assert universe.value == "v"


def test_walrus_guard_guard_family_refuses(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        guard_universe_for_callee,
    )

    guard_universe_for_callee.cache_clear()
    vendor_path("vendwalrus_guard", VENDOR_WALRUS_PREDICATE)
    guards, refusal = guard_universe_for_callee("vendwalrus_guard.f")
    assert guards is None
    assert refusal is not None
    assert "walrus" in refusal.reason


def test_pure_guard_guard_family_still_licenses(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        guard_universe_for_callee,
    )

    guard_universe_for_callee.cache_clear()
    vendor_path("vendpure_guard", VENDOR_PURE_PREDICATE)
    guards, refusal = guard_universe_for_callee("vendpure_guard.f")
    assert refusal is None
    assert guards is not None
    assert len(guards.clauses) == 1


# ---------------------------------------------------------------------------
# pure-delegation + identity family (census: 57k delegation bodies + the
# param arm of return-name's 146k). The body forwards verbatim, so the
# output EQUALS the forwarded term — eq between call terms in EUF, zero
# new atoms. The license is syntactic (the body IS the claim); every
# refusal class is named and each is confirmed against a twin that still
# licenses.
# ---------------------------------------------------------------------------

VENDOR_DELEG = '''
def g(a, b):
    return a + b


def f(a, b):
    return g(b, a)


def ident(x):
    return x


def second(a, b):
    return b


def partial(a):
    return g(a, 5)


def forward_all(*args):
    return g(*args)
'''


def _deleg(callee):
    from sugar_lift_py_tests.translate_universe import (
        delegation_universe_for_callee,
    )

    delegation_universe_for_callee.cache_clear()
    return delegation_universe_for_callee(callee)


def test_identity_walks(vendor_path):
    vendor_path("venddeleg_ok", VENDOR_DELEG)
    u, r = _deleg("venddeleg_ok.ident")
    assert r is None and u is not None
    assert (u.kind, u.param_index) == ("identity", 0)
    u2, r2 = _deleg("venddeleg_ok.second")
    assert r2 is None and (u2.kind, u2.param_index) == ("identity", 1)


def test_delegation_walks_with_reordered_params(vendor_path):
    vendor_path("venddeleg_ok2", VENDOR_DELEG)
    u, r = _deleg("venddeleg_ok2.f")
    assert r is None and u is not None
    assert u.kind == "delegation"
    assert u.delegate == "venddeleg_ok2.g"
    assert u.args == (("param", 1), ("param", 0))


def test_delegation_walks_with_literal_arg(vendor_path):
    vendor_path("venddeleg_ok3", VENDOR_DELEG)
    u, r = _deleg("venddeleg_ok3.partial")
    assert r is None and u is not None
    assert u.args == (("param", 0), ("lit", 5, "int"))


def test_splat_forwarding_walks(vendor_path):
    vendor_path("venddeleg_ok4", VENDOR_DELEG)
    u, r = _deleg("venddeleg_ok4.forward_all")
    assert r is None and u is not None
    assert u.kind == "delegation-splat"
    assert u.delegate == "venddeleg_ok4.g"


def test_free_name_return_is_not_identity(vendor_path):
    vendor_path(
        "venddeleg_free", "Y = 3\n\ndef f(x):\n    return Y\n"
    )
    u, r = _deleg("venddeleg_free.f")
    assert u is None and r is None  # return-name's pinned-local arm, not ours


def test_rebound_param_is_not_identity(vendor_path):
    # `x = x + 1; return x` is chain-SHAPED and computed. It must never be
    # identity, which would forward the caller's x unincremented; it is now
    # admitted as the explicit chain expression the source actually states.
    vendor_path(
        "venddeleg_rebind", "def f(x):\n    x = x + 1\n    return x\n"
    )
    u, r = _deleg("venddeleg_rebind.f")
    assert r is None
    assert u is not None
    assert u.kind == "chain-expr"
    assert u.expr_spec == ("binop", "+", ("param", 0), ("lit", 1, "int"))


def test_walrus_guard_delegation_refuses(vendor_path):
    vendor_path(
        "venddeleg_walrus",
        "def f(x):\n"
        "    if (x := x + 10) > 100:\n"
        "        raise ValueError(x)\n"
        "    return x\n",
    )
    u, r = _deleg("venddeleg_walrus.f")
    assert u is None and r is not None and "walrus" in r.reason


def test_pure_guard_identity_still_licenses(vendor_path):
    vendor_path(
        "venddeleg_guarded",
        "def f(x):\n"
        "    if x > 100:\n"
        "        raise ValueError(x)\n"
        "    return x\n",
    )
    u, r = _deleg("venddeleg_guarded.f")
    assert r is None and u is not None and u.kind == "identity"


def test_keyword_forwarding_walks(vendor_path):
    vendor_path(
        "venddeleg_kw",
        "def g(a, b):\n    return a\n\ndef f(a, b):\n    return g(a, b=b)\n",
    )
    u, r = _deleg("venddeleg_kw.f")
    assert r is None and u is not None
    assert u.kind == "delegation"
    assert u.delegate == "venddeleg_kw.g"
    assert u.args == (("param", 0), ("param", 1))


def test_keyword_forwarding_composes(vendor_path):
    from sugar_lift_py_tests.ir import str_const
    from sugar_lift_py_tests.layer2 import _iter_conjuncts
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
        delegation_universe_for_callee,
    )

    constant_universe_for_callee.cache_clear()
    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "venddeleg_kw_l2",
        """
        def g(a, b):
            return "fixed"

        def f(a, b):
            return g(b=b, a=a)
        """,
    )

    out = _lift(
        """
        import venddeleg_kw_l2

        def test_route():
            assert venddeleg_kw_l2.f("raaaa", 5) == "fixed"
        """
    )

    f_to_g_atoms = _delegation_eq_atoms(out, "callresult_venddeleg_kw_l2_g_a2")
    assert f_to_g_atoms
    assert any(
        any("callval_f_a3" in getattr(side, "name", "") for side in atom.args)
        for atom in f_to_g_atoms
    ), f_to_g_atoms
    fixed_atoms = [
        atom
        for d in out.decls
        if d.name.endswith("::assertion") and d.inv is not None
        for atom in _iter_conjuncts(d.inv)
        if getattr(atom, "name", None) == "="
        and str_const("fixed") in getattr(atom, "args", ())
        and any(
            "callresult_venddeleg_kw_l2_g_a2" in getattr(side, "name", "")
            for side in getattr(atom, "args", ())
        )
    ]
    assert fixed_atoms, [d.name for d in out.decls]


def test_keyword_forwarding_unknown_name_refuses(vendor_path):
    vendor_path(
        "venddeleg_kw_unknown",
        "def g(a, b):\n    return a\n\ndef f(a, b):\n    return g(a, c=b)\n",
    )
    u, r = _deleg("venddeleg_kw_unknown.f")
    assert u is None and r is not None and "keyword" in r.reason


def test_imported_stdlib_delegation_walks_literal_keyword(vendor_path):
    vendor_path(
        "venddeleg_stdlib_kw",
        """
        import json

        def f(obj):
            return json.dumps(obj, separators=(",", ":"))
        """,
    )
    u, r = _deleg("venddeleg_stdlib_kw.f")
    assert r is None and u is not None
    assert u.kind == "delegation-stdlib"
    assert u.delegate == "json.dumps"
    assert u.args == (
        ("param", 0),
        (
            "kw",
            "separators",
            ("lit", "tuple:[',', ':']", "collection"),
        ),
    )


def test_imported_stdlib_delegation_walks_kwargs_setdefault(vendor_path):
    vendor_path(
        "venddeleg_stdlib_kwargs_default",
        """
        import json

        def f(obj, **kwargs):
            kwargs.setdefault("ensure_ascii", False)
            kwargs.setdefault("separators", (",", ":"))
            return json.dumps(obj, **kwargs)
        """,
    )
    u, r = _deleg("venddeleg_stdlib_kwargs_default.f")
    assert r is None and u is not None
    assert u.kind == "delegation-stdlib"
    assert u.delegate == "json.dumps"
    assert u.args == (
        ("param", 0),
        ("kw", "ensure_ascii", ("lit", False, "bool")),
        ("kw", "separators", ("lit", "tuple:[',', ':']", "collection")),
    )


def test_imported_stdlib_delegation_walks_static_attribute_keyword(vendor_path):
    vendor_path(
        "venddeleg_stdlib_attr_kw",
        """
        from datetime import datetime
        from datetime import timezone

        def f(ts):
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        """,
    )
    u, r = _deleg("venddeleg_stdlib_attr_kw.f")
    assert r is None and u is not None
    assert u.kind == "delegation-stdlib"
    assert u.delegate == "datetime.datetime.fromtimestamp"
    assert u.args == (
        ("param", 0),
        ("kw", "tz", ("lit", "attr:datetime.timezone.utc", "collection")),
    )


def test_imported_stdlib_delegation_walks_nested_receiver_call(vendor_path):
    vendor_path(
        "venddeleg_stdlib_receiver_arg",
        """
        import hmac

        class Algo:
            def get_signature(self, key, value):
                return value

            def verify_signature(self, key, value, sig):
                return hmac.compare_digest(sig, self.get_signature(key, value))
        """,
    )
    u, r = _deleg("venddeleg_stdlib_receiver_arg.Algo.verify_signature")
    assert r is None and u is not None
    assert u.kind == "delegation-stdlib"
    assert u.delegate == "hmac.compare_digest"
    assert u.args == (
        ("param", 3),
        (
            "receiver-method-call",
            "venddeleg_stdlib_receiver_arg.Algo.get_signature",
            (("param", 0), ("param", 1)),
        ),
    )


def test_chain_assignment_stdlib_bridge_method_return(vendor_path):
    from sugar_lift_py_tests.layer2 import _iter_conjuncts
    from sugar_lift_py_tests.translate_universe import (
        constructor_field_universe_for_callee,
    )

    constructor_field_universe_for_callee.cache_clear()
    vendor_path(
        "venddeleg_stdlib_chain_method",
        """
        import hmac

        class Algo:
            def __init__(self, digest_method):
                self.digest_method = digest_method

            def get_signature(self, key, value):
                mac = hmac.new(key, msg=value, digestmod=self.digest_method)
                return mac.digest()
        """,
    )
    u, r = _deleg("venddeleg_stdlib_chain_method.Algo.get_signature")
    assert r is None and u is not None
    assert u.kind == "chain-expr"
    assert u.expr_spec[0] == "method-call"
    assert u.expr_spec[1] == "digest"
    assert u.expr_spec[2][0][0] == "function-call"
    assert u.expr_spec[2][0][1] == "hmac.new"

    out = _lift(
        """
        import venddeleg_stdlib_chain_method

        def test_sig():
            alg = venddeleg_stdlib_chain_method.Algo("sha1")
            assert alg.get_signature(b"k", b"v") == b"sig"
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "venddeleg_stdlib_chain_method.Algo.get_signature" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    def contains_ctor(term, name):
        return getattr(term, "name", None) == name or any(
            contains_ctor(arg, name) for arg in getattr(term, "args", ())
        )

    expr_eqs = [
        atom
        for atom in _iter_conjuncts(assertion.inv)
        if getattr(atom, "name", None) == "="
    ]
    assert any(
        contains_ctor(side, "callval_digest_a1")
        for atom in expr_eqs
        for side in getattr(atom, "args", ())
    )
    assert any(
        contains_ctor(side, "callresult_hmac_new_a3")
        for atom in expr_eqs
        for side in getattr(atom, "args", ())
    )
    warranted = {
        (warrant.get("role"), warrant.get("source_function_name"))
        for warrant in assertion.source_warrants
    }
    assert (
        "python.delegation-universe",
        "Algo.get_signature",
    ) in warranted
    assert (
        "python.instance-field-universe",
        "Algo.__init__",
    ) in warranted


def test_chain_assignment_function_call_return_queues_recursive_digs(vendor_path):
    from sugar_lift_py_tests.layer2 import _iter_conjuncts
    from sugar_lift_py_tests.translate_universe import delegation_universe_for_callee

    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "venddeleg_call_queue",
        """
        def h(value):
            return value + "h"

        def g(value):
            return value + "g"

        def f(value):
            z = h(value)
            return g(z)
        """,
    )

    universe, refusal = delegation_universe_for_callee("venddeleg_call_queue.f")
    assert refusal is None
    assert universe is not None
    assert universe.kind == "delegation"
    assert universe.delegate == "venddeleg_call_queue.g"
    assert universe.args == (
        (
            "function-call",
            "venddeleg_call_queue.h",
            (("param", 0),),
        ),
    )

    out = _lift(
        """
        import venddeleg_call_queue

        def test_call_queue():
            assert venddeleg_call_queue.f("a") == "ahg"
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "venddeleg_call_queue.f" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    def contains_ctor(term, name):
        return getattr(term, "name", None) == name or any(
            contains_ctor(arg, name) for arg in getattr(term, "args", ())
        )

    expr_eqs = [
        atom
        for atom in _iter_conjuncts(assertion.inv)
        if getattr(atom, "name", None) == "="
    ]
    assert any(
        contains_ctor(side, "callresult_venddeleg_call_queue_g_a1")
        for atom in expr_eqs
        for side in getattr(atom, "args", ())
    )
    assert any(
        contains_ctor(side, "callresult_venddeleg_call_queue_h_a1")
        for atom in expr_eqs
        for side in getattr(atom, "args", ())
    )
    assert any(
        contains_ctor(side, "str.++")
        for atom in expr_eqs
        for side in getattr(atom, "args", ())
    )

    warranted = {
        (warrant.get("role"), warrant.get("source_function_name"))
        for warrant in assertion.source_warrants
    }
    assert ("python.delegation-universe", "f") in warranted
    assert ("python.delegation-universe", "g") in warranted
    assert ("python.delegation-universe", "h") in warranted

    delegation_audits = [
        audit
        for audit in out.source_audits
        if audit["role"] == "python.delegation-universe"
    ]
    assert delegation_audits
    assert any(
        len(
            [
                locus
                for locus in audit["loci"]
                if locus.get("ast_kind") == "Call" and locus["status"] == "warranted"
            ]
        )
        == 2
        for audit in delegation_audits
    ), delegation_audits


def test_computed_arg_refuses(vendor_path):
    vendor_path(
        "venddeleg_computed",
        "def g(a):\n    return a\n\ndef f(a):\n    return g(a + 1)\n",
    )
    u, r = _deleg("venddeleg_computed.f")
    assert u is None and r is not None
    assert "neither a parameter, literal, collection literal, nor chain name" in r.reason


def test_imported_delegate_refuses(vendor_path):
    vendor_path(
        "venddeleg_import",
        "from os.path import join\n\ndef f(a):\n    return join(a)\n",
    )
    u, r = _deleg("venddeleg_import.f")
    assert u is None and r is not None
    assert "not a module-level function" in r.reason


def test_nondeterministic_delegate_refuses(vendor_path):
    vendor_path(
        "venddeleg_nondet",
        "import random\n\n"
        "def g(a):\n    return a + random.random()\n\n"
        "def f(a):\n    return g(a)\n",
    )
    u, r = _deleg("venddeleg_nondet.f")
    assert u is None and r is not None and "nondeterminism" in r.reason


def test_rebound_delegate_refuses(vendor_path):
    vendor_path(
        "venddeleg_rebound",
        "def g(a):\n    return a\n\ng = len\n\ndef f(a):\n    return g(a)\n",
    )
    u, r = _deleg("venddeleg_rebound.f")
    assert u is None and r is not None and "binding events" in r.reason


def test_global_puncture_delegate_refuses(vendor_path):
    vendor_path(
        "venddeleg_glob",
        "def g(a):\n    return a\n\n"
        "def swap():\n    global g\n    g = len\n\n"
        "def f(a):\n    return g(a)\n",
    )
    u, r = _deleg("venddeleg_glob.f")
    assert u is None and r is not None and "global" in r.reason


def test_self_delegation_refuses(vendor_path):
    vendor_path(
        "venddeleg_self", "def f(a):\n    return f(a)\n"
    )
    u, r = _deleg("venddeleg_self.f")
    assert u is None and r is not None and "self-delegation" in r.reason


def test_async_delegate_refuses(vendor_path):
    vendor_path(
        "venddeleg_async",
        "async def g(a):\n    return a\n\ndef f(a):\n    return g(a)\n",
    )
    u, r = _deleg("venddeleg_async.f")
    assert u is None and r is not None and "async" in r.reason


def test_splat_with_extra_arg_refuses(vendor_path):
    vendor_path(
        "venddeleg_splatx",
        "def g(*a):\n    return a\n\n"
        "def f(*args):\n    return g(*args, 1)\n",
    )
    u, r = _deleg("venddeleg_splatx.f")
    assert u is None and r is not None and "splat" in r.reason


def test_multiple_returns_not_delegation(vendor_path):
    vendor_path(
        "venddeleg_multi",
        "def g(a):\n    return a\n\n"
        "def f(a):\n    if a:\n        return g(a)\n    return g(a)\n",
    )
    u, r = _deleg("venddeleg_multi.f")
    assert u is None and r is None  # not a single-return forwarding body


def _delegation_eq_atoms(out, delegate_head_fragment):
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    found = []
    for d in out.decls:
        if d.name.endswith("::assertion") and d.inv is not None:
            for a in _iter_conjuncts(d.inv):
                if getattr(a, "name", None) != "=":
                    continue
                for side in getattr(a, "args", ()):
                    if delegate_head_fragment in getattr(side, "name", ""):
                        found.append(a)
    return found


def test_delegation_emits_call_term_equality(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        delegation_universe_for_callee,
    )

    delegation_universe_for_callee.cache_clear()
    vendor_path("venddeleg_l2", VENDOR_DELEG)
    out = _lift(
        """
        import venddeleg_l2

        def test_route():
            assert venddeleg_l2.f(1, 2) == 3
        """
    )
    # the universe ties callresult_<f>(1,2) to callresult_<g>(2,1): claims
    # about f and claims about g now meet in one term. A consumer swearing
    # venddeleg_l2.g(2, 1) != 3 elsewhere would conjoin to UNSAT.
    atoms = _delegation_eq_atoms(out, "callresult_venddeleg_l2_g_a2")
    assert atoms, [d.name for d in out.decls]


def test_delegation_queues_delegate_dig_and_carries_source_warrants(vendor_path):
    from sugar_lift_py_tests.ir import str_const
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
        delegation_universe_for_callee,
    )

    constant_universe_for_callee.cache_clear()
    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "venddeleg_queue",
        """
        def g(seed):
            return "fixed"


        def f(seed):
            return g(seed)
        """,
    )
    out = _lift(
        """
        import venddeleg_queue

        def test_route():
            assert venddeleg_queue.f("raaaa") == "fixed"
        """
    )

    atoms = _delegation_eq_atoms(out, "callresult_venddeleg_queue_g_a1")
    assert atoms, [d.name for d in out.decls]

    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    fixed_atoms = [
        a
        for d in out.decls
        if d.name.endswith("::assertion") and d.inv is not None
        for a in _iter_conjuncts(d.inv)
        if getattr(a, "name", None) == "="
        and str_const("fixed") in getattr(a, "args", ())
        and any(
            "callresult_venddeleg_queue_g_a1" in getattr(side, "name", "")
            for side in getattr(a, "args", ())
        )
    ]
    assert fixed_atoms, [d.name for d in out.decls]

    assertion = next(
        d
        for d in out.decls
        if d.name.endswith("::assertion")
        and "venddeleg_queue.f#euf#" in d.name
    )
    roles = {warrant.get("role") for warrant in assertion.source_warrants}
    assert {"python.delegation-universe", "python.constant-universe"} <= roles
    assert any(
        warrant.get("role") == "python.delegation-universe"
        and warrant.get("source_function_name") == "f"
        for warrant in assertion.source_warrants
    )
    assert any(
        warrant.get("role") == "python.constant-universe"
        and warrant.get("source_function_name") == "g"
        for warrant in assertion.source_warrants
    )

    audits = {
        audit["role"]: audit
        for audit in out.source_audits
        if audit["role"] in {"python.delegation-universe", "python.constant-universe"}
    }
    assert set(audits) == {"python.delegation-universe", "python.constant-universe"}
    assert audits["python.constant-universe"]["totals"]["unclassified_source"] == 0
    assert audits["python.delegation-universe"]["totals"]["unclassified_source"] == 0
    assert any(
        locus.get("ast_kind") == "Call" and locus["status"] == "warranted"
        for locus in audits["python.delegation-universe"]["loci"]
    ), audits["python.delegation-universe"]


def test_receiver_method_delegation_composes_with_receiver_context(vendor_path):
    from sugar_lift_py_tests.ir import str_const
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
        delegation_universe_for_callee,
    )

    constant_universe_for_callee.cache_clear()
    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "venddeleg_receiver",
        """
        class Router:
            def g(self, seed):
                return "fixed"

            def f(self, seed):
                return self.g(seed)
        """,
    )

    universe, refusal = delegation_universe_for_callee(
        "venddeleg_receiver.Router.f"
    )
    assert refusal is None
    assert universe is not None
    assert universe.kind == "delegation-receiver-method"
    assert universe.delegate == "venddeleg_receiver.Router.g"
    assert universe.args == (("param", 0),)

    out = _lift(
        """
        import venddeleg_receiver

        def test_route():
            router = venddeleg_receiver.Router()
            assert router.f("raaaa") == "fixed"
        """
    )

    atoms = _delegation_eq_atoms(out, "callval_g_a2")
    assert atoms, [d.name for d in out.decls]
    assert any(
        any("callval_f_a2" in getattr(side, "name", "") for side in atom.args)
        for atom in atoms
    ), atoms

    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    fixed_atoms = [
        atom
        for d in out.decls
        if d.name.endswith("::assertion") and d.inv is not None
        for atom in _iter_conjuncts(d.inv)
        if getattr(atom, "name", None) == "="
        and str_const("fixed") in getattr(atom, "args", ())
        and any(
            "callval_g_a2" in getattr(side, "name", "")
            for side in getattr(atom, "args", ())
        )
    ]
    assert fixed_atoms, [d.name for d in out.decls]

    assertion = next(
        d
        for d in out.decls
        if d.name.endswith("::assertion")
        and "venddeleg_receiver.Router.f" in d.name
    )
    roles = {warrant.get("role") for warrant in assertion.source_warrants}
    assert {"python.delegation-universe", "python.constant-universe"} <= roles
    assert any(
        warrant.get("role") == "python.delegation-universe"
        and warrant.get("source_function_name") == "Router.f"
        for warrant in assertion.source_warrants
    )
    assert any(
        warrant.get("role") == "python.constant-universe"
        and warrant.get("source_function_name") == "Router.g"
        for warrant in assertion.source_warrants
    )

    audits = {
        audit["role"]: audit
        for audit in out.source_audits
        if audit["role"] in {"python.delegation-universe", "python.constant-universe"}
        and "venddeleg_receiver.Router" in audit["contract"]["name"]
    }
    assert set(audits) == {"python.delegation-universe", "python.constant-universe"}
    assert audits["python.delegation-universe"]["totals"]["unclassified_source"] == 0
    assert audits["python.constant-universe"]["totals"]["unclassified_source"] == 0


def test_super_receiver_method_delegation_walks_casted_return(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        delegation_universe_for_callee,
    )

    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "venddeleg_super_receiver",
        """
        import typing as t

        class Base:
            def iter_items(self, salt):
                return salt

        class Child(Base):
            def iter_items(self, salt):
                return t.cast("object", super().iter_items(salt))
        """,
    )

    universe, refusal = delegation_universe_for_callee(
        "venddeleg_super_receiver.Child.iter_items"
    )
    assert refusal is None
    assert universe is not None
    assert universe.kind == "delegation-receiver-method"
    assert universe.delegate == "venddeleg_super_receiver.Base.iter_items"
    assert universe.args == (("param", 0),)

    out = _lift(
        """
        import venddeleg_super_receiver

        def test_route():
            child = venddeleg_super_receiver.Child()
            assert child.iter_items("raaaa") == "raaaa"
        """
    )
    audits = [
        audit
        for audit in out.source_audits
        if audit["role"] == "python.delegation-universe"
        and "venddeleg_super_receiver.Child.iter_items" in audit["contract"]["name"]
    ]
    assert audits
    assert audits[0]["totals"]["unclassified_source"] == 0


def test_receiver_method_delegation_composes_through_local_alias(vendor_path):
    from sugar_lift_py_tests.ir import str_const
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
        delegation_universe_for_callee,
    )

    constant_universe_for_callee.cache_clear()
    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "venddeleg_receiver_alias",
        """
        class Router:
            def g(self, seed):
                return "fixed"

            def f(self, seed):
                value = self.g(seed)
                return value
        """,
    )

    universe, refusal = delegation_universe_for_callee(
        "venddeleg_receiver_alias.Router.f"
    )
    assert refusal is None
    assert universe is not None
    assert universe.kind == "delegation-receiver-method"
    assert universe.delegate == "venddeleg_receiver_alias.Router.g"
    assert universe.args == (("param", 0),)

    out = _lift(
        """
        import venddeleg_receiver_alias

        def test_route():
            router = venddeleg_receiver_alias.Router()
            assert router.f("raaaa") == "fixed"
        """
    )

    atoms = _delegation_eq_atoms(out, "callval_g_a2")
    assert atoms, [d.name for d in out.decls]
    assert any(
        any("callval_f_a2" in getattr(side, "name", "") for side in atom.args)
        for atom in atoms
    ), atoms

    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    fixed_atoms = [
        atom
        for d in out.decls
        if d.name.endswith("::assertion") and d.inv is not None
        for atom in _iter_conjuncts(d.inv)
        if getattr(atom, "name", None) == "="
        and str_const("fixed") in getattr(atom, "args", ())
        and any(
            "callval_g_a2" in getattr(side, "name", "")
            for side in getattr(atom, "args", ())
        )
    ]
    assert fixed_atoms, [d.name for d in out.decls]

    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.delegation-universe"
        and "venddeleg_receiver_alias.Router.f" in audit["contract"]["name"]
    )
    assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted" and locus.get("ast_kind") == "Assign"
        for locus in audit["loci"]
    ), audit


def test_receiver_method_delegation_recurses_nested_receiver_call(vendor_path):
    from sugar_lift_py_tests.ir import str_const
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
        delegation_universe_for_callee,
    )

    constant_universe_for_callee.cache_clear()
    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "venddeleg_receiver_recursive",
        """
        class Router:
            def h(self, seed):
                return "fixed"

            def g(self, value):
                return value

            def f(self, seed):
                return self.g(self.h(seed))
        """,
    )

    universe, refusal = delegation_universe_for_callee(
        "venddeleg_receiver_recursive.Router.f"
    )
    assert refusal is None
    assert universe is not None
    assert universe.kind == "delegation-receiver-method"
    assert universe.delegate == "venddeleg_receiver_recursive.Router.g"
    assert universe.args == (
        (
            "receiver-method-call",
            "venddeleg_receiver_recursive.Router.h",
            (("param", 0),),
        ),
    )

    out = _lift(
        """
        import venddeleg_receiver_recursive

        def test_route():
            router = venddeleg_receiver_recursive.Router()
            assert router.f("raaaa") == "fixed"
        """
    )

    f_to_g_atoms = _delegation_eq_atoms(out, "callval_g_a2")
    assert any(
        any("callval_f_a2" in getattr(side, "name", "") for side in atom.args)
        for atom in f_to_g_atoms
    ), f_to_g_atoms
    assert any(
        any(
            "callval_h_a2" in getattr(arg, "name", "")
            for side in atom.args
            for arg in getattr(side, "args", ())
        )
        for atom in f_to_g_atoms
    ), f_to_g_atoms

    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    h_fixed_atoms = [
        atom
        for d in out.decls
        if d.name.endswith("::assertion") and d.inv is not None
        for atom in _iter_conjuncts(d.inv)
        if getattr(atom, "name", None) == "="
        and str_const("fixed") in getattr(atom, "args", ())
        and any(
            "callval_h_a2" in getattr(side, "name", "")
            for side in getattr(atom, "args", ())
        )
    ]
    assert h_fixed_atoms, [d.name for d in out.decls]

    assertion = next(
        d
        for d in out.decls
        if d.name.endswith("::assertion")
        and "venddeleg_receiver_recursive.Router.f" in d.name
    )
    assert any(
        warrant.get("role") == "python.delegation-universe"
        and warrant.get("source_function_name") == "Router.f"
        for warrant in assertion.source_warrants
    )
    assert any(
        warrant.get("role") == "python.delegation-universe"
        and warrant.get("source_function_name") == "Router.g"
        for warrant in assertion.source_warrants
    )
    assert any(
        warrant.get("role") == "python.constant-universe"
        and warrant.get("source_function_name") == "Router.h"
        for warrant in assertion.source_warrants
    )

    audits = {
        (audit["role"], audit["source_memento"]["source_function_name"]): audit
        for audit in out.source_audits
        if "venddeleg_receiver_recursive.Router" in audit["contract"]["name"]
        and audit["role"] in {"python.delegation-universe", "python.constant-universe"}
    }
    assert ("python.delegation-universe", "Router.f") in audits
    assert ("python.delegation-universe", "Router.g") in audits
    assert ("python.constant-universe", "Router.h") in audits
    assert all(
        audit["totals"]["unclassified_source"] == 0
        for audit in audits.values()
    ), audits


def test_receiver_method_delegation_walks_keyword_dict_forwarding(vendor_path):
    from sugar_lift_py_tests.translate_universe import delegation_universe_for_callee

    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "venddeleg_receiver_kwargs",
        """
        class Router:
            def g(self, seed, load_kwargs=None):
                return "fixed"

            def f(self, seed, max_age=None):
                return self.g(seed, load_kwargs={"max_age": max_age})
        """,
    )

    universe, refusal = delegation_universe_for_callee(
        "venddeleg_receiver_kwargs.Router.f"
    )
    assert refusal is None
    assert universe is not None
    assert universe.kind == "delegation-receiver-method"
    assert universe.delegate == "venddeleg_receiver_kwargs.Router.g"
    assert universe.args == (
        ("param", 0),
        ("kw", "load_kwargs", ("dict", (("max_age", ("param", 1)),))),
    )


def test_receiver_method_delegation_composes_keyword_dict_forwarding(vendor_path):
    from sugar_lift_py_tests.ir import str_const
    from sugar_lift_py_tests.layer2 import _iter_conjuncts
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
        delegation_universe_for_callee,
    )

    constant_universe_for_callee.cache_clear()
    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "venddeleg_receiver_kwargs_l2",
        """
        class Router:
            def g(self, seed, load_kwargs=None):
                return "fixed"

            def f(self, seed, max_age=None):
                return self.g(seed, load_kwargs={"max_age": max_age})
        """,
    )

    out = _lift(
        """
        import venddeleg_receiver_kwargs_l2

        def test_route():
            router = venddeleg_receiver_kwargs_l2.Router()
            assert router.f("raaaa", 5) == "fixed"
        """
    )

    f_to_g_atoms = _delegation_eq_atoms(out, "callval_g_a3")
    assert any(
        any("callval_f_a3" in getattr(side, "name", "") for side in atom.args)
        for atom in f_to_g_atoms
    ), f_to_g_atoms
    fixed_atoms = [
        atom
        for d in out.decls
        if d.name.endswith("::assertion") and d.inv is not None
        for atom in _iter_conjuncts(d.inv)
        if getattr(atom, "name", None) == "="
        and str_const("fixed") in getattr(atom, "args", ())
        and any(
            "callval_g_a3" in getattr(side, "name", "")
            for side in getattr(atom, "args", ())
        )
    ]
    assert fixed_atoms, [d.name for d in out.decls]

    assertion = next(
        d
        for d in out.decls
        if d.name.endswith("::assertion")
        and "venddeleg_receiver_kwargs_l2.Router.f" in d.name
    )
    roles = {warrant.get("role") for warrant in assertion.source_warrants}
    assert {"python.delegation-universe", "python.constant-universe"} <= roles
    audits = {
        (audit["role"], audit["source_memento"]["source_function_name"]): audit
        for audit in out.source_audits
        if "venddeleg_receiver_kwargs_l2.Router" in audit["contract"]["name"]
        and audit["role"] in {"python.delegation-universe", "python.constant-universe"}
    }
    assert ("python.delegation-universe", "Router.f") in audits
    assert ("python.constant-universe", "Router.g") in audits
    assert all(
        audit["totals"]["unclassified_source"] == 0
        for audit in audits.values()
    ), audits


def test_receiver_method_delegation_walks_imported_base_keyword_dict(vendor_path):
    from sugar_lift_py_tests.ir import str_const
    from sugar_lift_py_tests.layer2 import _iter_conjuncts
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
        delegation_universe_for_callee,
    )

    constant_universe_for_callee.cache_clear()
    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "venddeleg_receiver_base",
        """
        from typing import Generic, TypeVar

        T = TypeVar("T")

        class Base(Generic[T]):
            def g(self, seed, load_kwargs=None):
                return "fixed"
        """,
    )
    vendor_path(
        "venddeleg_receiver_child",
        """
        from venddeleg_receiver_base import Base

        class Child(Base[str]):
            def f(self, seed, max_age=None):
                return self.g(seed, load_kwargs={"max_age": max_age})
        """,
    )

    universe, refusal = delegation_universe_for_callee(
        "venddeleg_receiver_child.Child.f"
    )
    assert refusal is None
    assert universe is not None
    assert universe.kind == "delegation-receiver-method"
    assert universe.delegate == "venddeleg_receiver_base.Base.g"
    assert universe.args == (
        ("param", 0),
        ("kw", "load_kwargs", ("dict", (("max_age", ("param", 1)),))),
    )

    out = _lift(
        """
        import venddeleg_receiver_child

        def test_route():
            child = venddeleg_receiver_child.Child()
            assert child.f("raaaa", 5) == "fixed"
        """
    )

    f_to_g_atoms = _delegation_eq_atoms(out, "callval_g_a3")
    assert any(
        any("callval_f_a3" in getattr(side, "name", "") for side in atom.args)
        for atom in f_to_g_atoms
    ), f_to_g_atoms
    fixed_atoms = [
        atom
        for d in out.decls
        if d.name.endswith("::assertion") and d.inv is not None
        for atom in _iter_conjuncts(d.inv)
        if getattr(atom, "name", None) == "="
        and str_const("fixed") in getattr(atom, "args", ())
        and any(
            "callval_g_a3" in getattr(side, "name", "")
            for side in getattr(atom, "args", ())
        )
    ]
    assert fixed_atoms, [d.name for d in out.decls]


def test_receiver_runtime_dispatch_refuses(vendor_path):
    from sugar_lift_py_tests.translate_universe import delegation_universe_for_callee

    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "venddeleg_receiver_dynamic",
        """
        class Router:
            def direct(self, method_name, seed):
                return getattr(self, method_name)(seed)

            def alias(self, method_name, seed):
                value = getattr(self, method_name)(seed)
                return value
        """,
    )

    direct_universe, direct_refusal = delegation_universe_for_callee(
        "venddeleg_receiver_dynamic.Router.direct"
    )
    assert direct_universe is None
    assert direct_refusal is not None
    assert "dynamic receiver dispatch" in direct_refusal.reason

    alias_universe, alias_refusal = delegation_universe_for_callee(
        "venddeleg_receiver_dynamic.Router.alias"
    )
    assert alias_universe is None
    assert alias_refusal is not None
    assert "dynamic receiver dispatch" in alias_refusal.reason


def test_delegation_unwraps_typing_cast_and_carries_source_warrants(vendor_path):
    from sugar_lift_py_tests.ir import str_const
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
        delegation_universe_for_callee,
    )

    constant_universe_for_callee.cache_clear()
    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "venddeleg_cast",
        """
        import typing as t

        def g(seed):
            return "fixed"


        def f(seed):
            return t.cast(str, g(seed))
        """,
    )

    universe, refusal = delegation_universe_for_callee("venddeleg_cast.f")
    assert refusal is None
    assert universe is not None
    assert universe.kind == "delegation"
    assert universe.delegate == "venddeleg_cast.g"
    assert universe.args == (("param", 0),)

    out = _lift(
        """
        import venddeleg_cast

        def test_route():
            assert venddeleg_cast.f("raaaa") == "fixed"
        """
    )

    atoms = _delegation_eq_atoms(out, "callresult_venddeleg_cast_g_a1")
    assert atoms, [d.name for d in out.decls]

    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    fixed_atoms = [
        atom
        for d in out.decls
        if d.name.endswith("::assertion") and d.inv is not None
        for atom in _iter_conjuncts(d.inv)
        if getattr(atom, "name", None) == "="
        and str_const("fixed") in getattr(atom, "args", ())
        and any(
            "callresult_venddeleg_cast_g_a1" in getattr(side, "name", "")
            for side in getattr(atom, "args", ())
        )
    ]
    assert fixed_atoms, [d.name for d in out.decls]

    assertion = next(
        d
        for d in out.decls
        if d.name.endswith("::assertion")
        and "venddeleg_cast.f#euf#" in d.name
    )
    assert any(
        warrant.get("role") == "python.delegation-universe"
        and warrant.get("source_function_name") == "f"
        for warrant in assertion.source_warrants
    )

    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.delegation-universe"
        and "venddeleg_cast.f" in audit["contract"]["name"]
    )
    assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Call"
        and "transparent typing cast" in locus.get("reason", "")
        for locus in audit["loci"]
    ), audit


def test_staticmethod_delegates_to_imported_stdlib_function(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        delegation_universe_for_callee,
    )

    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "vendstdlib_deleg",
        '''
import json as _json


class Compact:
    @staticmethod
    def loads(payload):
        return _json.loads(payload)
''',
    )
    out = _lift(
        """
        import vendstdlib_deleg

        def test_loads():
            assert vendstdlib_deleg.Compact.loads('{"ok": true}') == {"ok": True}
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendstdlib_deleg.Compact.loads" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    imported_delegate_eqs = [
        atom
        for atom in _iter_conjuncts(assertion.inv)
        if getattr(atom, "name", None) == "="
        and any(
            getattr(side, "name", "") == "callresult_json_loads_a1"
            for side in getattr(atom, "args", ())
        )
    ]
    assert imported_delegate_eqs
    assert any(
        warrant.get("role") == "python.delegation-universe"
        and warrant.get("source_function_name") == "Compact.loads"
        and warrant.get("universe_kind") == "delegation-stdlib"
        for warrant in assertion.source_warrants
    ), assertion.source_warrants

    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.delegation-universe"
        and audit["universe_kind"] == "delegation-stdlib"
    )
    assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted" and locus.get("ast_kind") == "Return"
        for locus in audit["loci"]
    ), audit
    assert any(
        locus["status"] == "warranted" and locus.get("ast_kind") == "Call"
        for locus in audit["loci"]
    ), audit


def test_identity_universe_contradicts_wrong_claim(vendor_path):
    # THE BAD TWIN: the consumer swears ident(7) == 8; the identity
    # universe swears the output IS the argument (== 7). Both equalities
    # land in the SAME conjoined ::assertion inv — the conjunction is
    # UNSAT and the wrong claim refutes. (The good twin's universe
    # conjunct is byte-identical to the consumer's own assertion and is
    # correctly deduped — the universe adds information exactly when the
    # claim deviates.)
    from sugar_lift_py_tests.translate_universe import (
        delegation_universe_for_callee,
    )
    from sugar_lift_py_tests.ir import _ConstInt

    delegation_universe_for_callee.cache_clear()
    vendor_path("venddeleg_l2i", VENDOR_DELEG)
    out = _lift(
        """
        import venddeleg_l2i

        def test_ident():
            assert venddeleg_l2i.ident(7) == 8
        """
    )
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    claimed, universe = [], []
    for d in out.decls:
        if d.name.endswith("::assertion") and d.inv is not None:
            for a in _iter_conjuncts(d.inv):
                if getattr(a, "name", None) != "=":
                    continue
                args = getattr(a, "args", ())
                if len(args) == 2 and isinstance(args[1], _ConstInt):
                    (claimed if args[1].value == 8 else universe).append(
                        (a, args[1].value)
                    )
    assert claimed, [d.name for d in out.decls]
    assert [v for _, v in universe] == [7], universe


def test_impure_delegate_emits_no_equality_but_warns(vendor_path):
    # DEFENSE IN DEPTH, the case only the walk catches: a nondeterminism
    # source FOUR hops from f (f->g->h->i->random). callee_is_nondeterministic
    # scans depth 3 from f and clears it, so the assertion still lifts and
    # argument-keys; the walk then scans depth 3 from the DELEGATE g,
    # reaches the source, and refuses to equate — surfaced as a loud
    # warning, never silence. (One hop closer and the callee gate itself
    # de-keys the call before any universe is consulted — also covered:
    # test_nondeterministic_delegate_refuses exercises the walk directly.)
    from sugar_lift_py_tests.translate_universe import (
        callee_is_nondeterministic,
        delegation_universe_for_callee,
    )

    callee_is_nondeterministic.cache_clear()
    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "venddeleg_l2bad",
        "import random\n\n"
        "def i(a):\n    return a + random.random()\n\n"
        "def h(a):\n    return i(a)\n\n"
        "def g(a):\n    return h(a)\n\n"
        "def f(a):\n    return g(a)\n",
    )
    assert not callee_is_nondeterministic("venddeleg_l2bad.f")
    out = _lift(
        """
        import venddeleg_l2bad

        def test_route():
            assert venddeleg_l2bad.f(1) == 2
        """
    )
    atoms = _delegation_eq_atoms(out, "callresult_venddeleg_l2bad_g")
    assert not atoms
    assert any(
        "delegation-universe" in w.item_name and "nondeterminism" in w.reason
        for w in out.warnings
    ), [(w.item_name, w.reason) for w in out.warnings]


# ---------------------------------------------------------------------------
# Decorated defs are not their bodies (falsePass closed 2026-06-12). The
# name binds whatever the decorator returns: @negate over `return True`
# runs False while the body walk swore True — through EVERY family, since
# they all resolve via _resolve_vendor_function. The fix is at that one
# chokepoint: a decorated def is the same non-candidate class as a C
# extension (the source we can read is not the callable that runs).
# ---------------------------------------------------------------------------

VENDOR_DECORATED = '''
def negate(fn):
    def inner(*a, **k):
        return not fn(*a, **k)
    return inner


@negate
def truth():
    return True


def plain_truth():
    return True
'''


def test_decorator_runtime_divergence_is_real(vendor_path):
    # The evidence, kept executable: the decorated callable and the def
    # body disagree, which is why resolution below must refuse.
    import importlib

    vendor_path("venddeco_evidence", VENDOR_DECORATED)
    mod = importlib.import_module("venddeco_evidence")
    assert mod.truth() is False  # the decorator negates the body
    assert mod.plain_truth() is True


def test_decorated_vendor_is_not_walkable_any_family(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
        delegation_universe_for_callee,
        guard_universe_for_callee,
        predicate_universe_for_callee,
    )

    vendor_path("venddeco_all", VENDOR_DECORATED)
    for walk in (
        constant_universe_for_callee,
        predicate_universe_for_callee,
        guard_universe_for_callee,
        delegation_universe_for_callee,
    ):
        walk.cache_clear()
        u, r = walk("venddeco_all.truth")
        assert u is None and r is None, (walk.__name__, u, r)


def test_undecorated_twin_still_walks(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
    )

    constant_universe_for_callee.cache_clear()
    vendor_path("venddeco_twin", VENDOR_DECORATED)
    u, r = constant_universe_for_callee("venddeco_twin.plain_truth")
    assert r is None and u is not None
    assert (u.value, u.value_kind) == (True, "bool")


def test_decorated_delegate_refuses(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        delegation_universe_for_callee,
    )

    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "venddeco_deleg",
        "def wrap(fn):\n    return fn\n\n"
        "@wrap\ndef g(a):\n    return a\n\n"
        "def f(a):\n    return g(a)\n",
    )
    u, r = delegation_universe_for_callee("venddeco_deleg.f")
    assert u is None and r is not None and "decorated" in r.reason


# ---------------------------------------------------------------------------
# assert-as-guard + the None arm (census: non-return:Assert 179k, Pass 17k,
# empty 7k, bare-return 1.7k). An `assert P` is a guard with polarity
# flipped — it raises exactly when P is false — so it contributes P itself
# as the clause (the negated comparison of NOT P). A body that is, after
# the guard prefix, empty / pass / bare return falls off the end, and
# CPython defines falling off the end as None, unconditionally. Effect
# tails stay non-candidates: their contract is the effect, not a vacuous
# value claim.
# ---------------------------------------------------------------------------


def test_assert_prefix_contributes_guard_clause(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        guard_universe_for_callee,
    )

    guard_universe_for_callee.cache_clear()
    vendor_path(
        "vendassert_guard",
        "def f(x):\n    assert x > 0\n    return x\n",
    )
    guards, refusal = guard_universe_for_callee("vendassert_guard.f")
    assert refusal is None and guards is not None
    (clause,) = guards.clauses
    # assert x > 0 raises when x <= 0: the clause is the negation
    assert (clause.param_name, clause.op, clause.literal) == ("x", "≤", 0)


def test_assert_and_if_raise_clauses_compose(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        guard_universe_for_callee,
    )

    guard_universe_for_callee.cache_clear()
    vendor_path(
        "vendassert_both",
        "def f(x, y):\n"
        "    assert x > 0\n"
        "    if y < 2:\n"
        "        raise ValueError(y)\n"
        "    return x\n",
    )
    guards, refusal = guard_universe_for_callee("vendassert_both.f")
    assert refusal is None and guards is not None
    ops = [(c.param_name, c.op, c.literal) for c in guards.clauses]
    assert ops == [("x", "≤", 0), ("y", "<", 2)]


def test_assert_vendor_vector_firing_refuses(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        guard_universe_for_callee,
    )

    guard_universe_for_callee.cache_clear()
    vendor_path(
        "vendassert_fire",
        "def f(x):\n    assert x > 0\n    return x\n",
    )
    vendor_path(
        "test_vendassert_fire",
        "import vendassert_fire\n\n"
        "def test_bad():\n    assert vendassert_fire.f(-3) == -3\n",
    )
    guards, refusal = guard_universe_for_callee("vendassert_fire.f")
    assert guards is None and refusal is not None
    assert "sample-gate" in refusal.reason


def test_assert_only_body_swears_none(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
    )

    constant_universe_for_callee.cache_clear()
    vendor_path(
        "vendnone_assert", "def check(x):\n    assert x > 0\n"
    )
    u, r = constant_universe_for_callee("vendnone_assert.check")
    assert r is None and u is not None
    assert (u.value, u.value_kind) == (None, "none")


def test_pass_body_swears_none(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
    )

    constant_universe_for_callee.cache_clear()
    vendor_path("vendnone_pass", "def noop(x):\n    pass\n")
    u, r = constant_universe_for_callee("vendnone_pass.noop")
    assert r is None and (u.value, u.value_kind) == (None, "none")


def test_docstring_only_body_swears_none(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
    )

    constant_universe_for_callee.cache_clear()
    vendor_path(
        "vendnone_doc", 'def noop(x):\n    """does nothing"""\n'
    )
    u, r = constant_universe_for_callee("vendnone_doc.noop")
    assert r is None and (u.value, u.value_kind) == (None, "none")


def test_bare_return_swears_none(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
    )

    constant_universe_for_callee.cache_clear()
    vendor_path(
        "vendnone_ret",
        "def stop(x):\n    if x < 0:\n        raise ValueError(x)\n    return\n",
    )
    u, r = constant_universe_for_callee("vendnone_ret.stop")
    assert r is None and (u.value, u.value_kind) == (None, "none")


def test_effect_tail_is_not_a_none_candidate(vendor_path):
    # `x.fire()` returns None too — but its contract is the EFFECT; a
    # vacuous value claim would dress a side effect as a proven function.
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
    )

    constant_universe_for_callee.cache_clear()
    vendor_path("vendnone_effect", "def f(x):\n    x.fire()\n")
    u, r = constant_universe_for_callee("vendnone_effect.f")
    assert u is None and r is None


def test_generator_is_not_a_none_candidate(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
    )

    constant_universe_for_callee.cache_clear()
    vendor_path("vendnone_gen", "def f(x):\n    yield x\n")
    u, r = constant_universe_for_callee("vendnone_gen.f")
    assert u is None and r is None


def test_walrus_assert_refuses_everywhere(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
        delegation_universe_for_callee,
        guard_universe_for_callee,
    )

    vendor_path(
        "vendassert_walrus",
        "def f(x):\n    assert (x := x + 1) > 0\n    return x\n",
    )
    guard_universe_for_callee.cache_clear()
    g, gr = guard_universe_for_callee("vendassert_walrus.f")
    assert g is None and gr is not None and "walrus" in gr.reason
    delegation_universe_for_callee.cache_clear()
    d, dr = delegation_universe_for_callee("vendassert_walrus.f")
    assert d is None and dr is not None and "walrus" in dr.reason
    constant_universe_for_callee.cache_clear()
    c, cr = constant_universe_for_callee("vendassert_walrus.f")
    # the tainted strip refuses BEFORE the shape is even considered: a
    # rebound environment poisons every downstream read uniformly
    assert c is None and cr is not None and "walrus" in cr.reason


def test_assert_prefix_identity_composes(vendor_path):
    # assert strips for the delegation family too: the identity universe
    # and the assert clause ride the same body.
    from sugar_lift_py_tests.translate_universe import (
        delegation_universe_for_callee,
    )

    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "vendassert_ident",
        "def f(x):\n    assert x > 0\n    return x\n",
    )
    u, r = delegation_universe_for_callee("vendassert_ident.f")
    assert r is None and u is not None and u.kind == "identity"


def test_assert_guard_and_none_emit_together(vendor_path):
    # e2e through layer2: the consumer swears check(-5) == 3. The body
    # swears TWO universes that each refute it — the None equality (the
    # body falls off the end: the value is None, not 3) and the assert
    # clause instantiated at -5 (not(-5 <= 0) is false: you swore a
    # return from a call the vendor's own source says raises). Both
    # conjuncts must land in the same inv as the claim. (A consumer
    # writing `== None` takes the dedicated None-check encoding, which
    # carries no extractable call subject — universes inject on the
    # standard equality path.)
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
        guard_universe_for_callee,
    )
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    constant_universe_for_callee.cache_clear()
    guard_universe_for_callee.cache_clear()
    vendor_path(
        "vendassert_l2", "def check(x):\n    assert x > 0\n"
    )
    out = _lift(
        """
        import vendassert_l2

        def test_neg():
            assert vendassert_l2.check(-5) == 3
        """
    )
    none_eqs, guard_negs = [], []
    for d in out.decls:
        if d.inv is None:
            continue
        # raw operand walk: _iter_conjuncts yields only ATOMIC leaves, so
        # the guard's not(...) conjunct is invisible to it by design
        for a in getattr(d.inv, "operands", (d.inv,)):
            if getattr(a, "name", None) == "=" and any(
                getattr(s, "name", None) == "None"
                for s in getattr(a, "args", ())
            ):
                none_eqs.append(a)
            if getattr(a, "kind", None) == "not":
                guard_negs.append(a)
    assert none_eqs, [d.name for d in out.decls]
    assert guard_negs, [d.name for d in out.decls]


# ---------------------------------------------------------------------------
# method delegation (census return-method-call, 113k bodies):
# `return <param|literal>.method(<params|literals>)` swears
# eq(subject, callval_<method>(recv, args...)). No body backs a method
# delegate — the receiver's type is not static — so the license is
# narrower than function delegation: nondeterminism-marker methods refuse
# by name, and the EMITTER bridges only GROUND instantiations (every
# mapped term concrete at the callsite).
# ---------------------------------------------------------------------------


def test_method_delegation_walks(vendor_path):
    vendor_path(
        "vendmdeleg_ok", "def up(s):\n    return s.upper()\n"
    )
    u, r = _deleg("vendmdeleg_ok.up")
    assert r is None and u is not None
    assert u.kind == "delegation-method"
    assert u.delegate == "upper"
    assert u.args == (("param", 0),)


def test_method_delegation_literal_receiver(vendor_path):
    vendor_path(
        "vendmdeleg_join", "def j(xs):\n    return ','.join(xs)\n"
    )
    u, r = _deleg("vendmdeleg_join.j")
    assert r is None and u is not None
    assert u.delegate == "join"
    assert u.args == (("lit", ",", "str"), ("param", 0))


def test_nondet_method_refuses(vendor_path):
    vendor_path(
        "vendmdeleg_nd", "def f(x):\n    return x.random()\n"
    )
    u, r = _deleg("vendmdeleg_nd.f")
    assert u is None and r is not None and "nondeterminism marker" in r.reason


def test_method_keyword_refuses(vendor_path):
    vendor_path(
        "vendmdeleg_kw", "def f(x):\n    return x.get('a', default=1)\n"
    )
    u, r = _deleg("vendmdeleg_kw.f")
    assert u is None and r is not None and "keyword" in r.reason


def test_computed_receiver_is_not_a_candidate(vendor_path):
    vendor_path(
        "vendmdeleg_deep", "def f(x):\n    return x.attr.m()\n"
    )
    u, r = _deleg("vendmdeleg_deep.f")
    assert u is None and r is None  # other families' shape


def test_method_arg_not_param_refuses(vendor_path):
    vendor_path(
        "vendmdeleg_comp", "def f(x):\n    return x.count(x + 1)\n"
    )
    u, r = _deleg("vendmdeleg_comp.f")
    assert u is None and r is not None
    assert "receiver/argument" in r.reason


def test_method_delegation_emits_ground_equality(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        delegation_universe_for_callee,
    )

    delegation_universe_for_callee.cache_clear()
    vendor_path("vendmdeleg_l2", "def up(s):\n    return s.upper()\n")
    out = _lift(
        """
        import vendmdeleg_l2

        def test_up():
            assert vendmdeleg_l2.up("abc") == "x"
        """
    )
    atoms = _delegation_eq_atoms(out, "callval_upper_a1")
    assert atoms, [d.name for d in out.decls]


def test_method_delegation_skips_symbolic_instantiation():
    # the ground-only gate, exercised at the emission seam directly: a
    # symbolic receiver term (a _Var) must produce NO delegate equality.
    import sugar_lift_py_tests.layer2 as l2
    from sugar_lift_py_tests.ir import ctor as mk_ctor, make_var
    from sugar_lift_py_tests.translate_universe import (
        delegation_universe_for_callee,
        DelegationUniverse,
    )

    u = DelegationUniverse(
        kind="delegation-method",
        module="m",
        qualname="m.up",
        source_path="m.py",
        lineno=1,
        delegate="upper",
        args=(("param", 0),),
    )
    call_args = [make_var("symbolic_receiver")]
    mapped = l2._mapped_delegate_args(u.args, call_args)
    term = mk_ctor(l2._callval_head("upper", len(mapped)), mapped)
    assert not l2._euf_args_all_concrete(term)


# ---------------------------------------------------------------------------
# branch-literal disjunction (census non-return:If, 75k bodies): every
# Return returns a same-kind literal and the body cannot fall off the end
# (terminality: Return | Raise | If with both arms terminal, recursively),
# so output ∈ {walked literals} — sound with NO condition evaluation: any
# execution that returns at all returns SOME Return node's value. Mixed
# kinds refuse by name (the #2103 cross-sort hazard: one subject, two
# theories).
# ---------------------------------------------------------------------------


def _branch(callee):
    from sugar_lift_py_tests.translate_universe import (
        branch_literal_universe_for_callee,
    )

    branch_literal_universe_for_callee.cache_clear()
    return branch_literal_universe_for_callee(callee)


def test_branch_literal_if_else_walks(vendor_path):
    vendor_path(
        "vendbranch_ok",
        'def pick(x):\n'
        '    if x:\n'
        '        return "a"\n'
        '    else:\n'
        '        return "b"\n',
    )
    u, r = _branch("vendbranch_ok.pick")
    assert r is None and u is not None
    assert u.values == ("a", "b") and u.value_kind == "str"


def test_branch_literal_elif_chain_walks(vendor_path):
    vendor_path(
        "vendbranch_chain",
        "def grade(x):\n"
        "    if x > 90:\n"
        "        return 1\n"
        "    elif x > 50:\n"
        "        return 2\n"
        "    else:\n"
        "        return 3\n",
    )
    u, r = _branch("vendbranch_chain.grade")
    assert r is None and u is not None
    assert u.values == (1, 2, 3) and u.value_kind == "int"


def test_branch_literal_tail_return_walks(vendor_path):
    # if-without-else followed by a tail return: terminal via the LAST
    # statement, the if's returns still join the disjunction
    vendor_path(
        "vendbranch_tail",
        'def flag(x):\n'
        '    if x:\n'
        '        return "yes"\n'
        '    return "no"\n',
    )
    u, r = _branch("vendbranch_tail.flag")
    assert r is None and u is not None
    assert u.values == ("yes", "no")


def test_branch_literal_dedupes_repeated_values(vendor_path):
    vendor_path(
        "vendbranch_dup",
        'def same(x):\n'
        '    if x:\n'
        '        return "a"\n'
        '    return "a"\n',
    )
    u, r = _branch("vendbranch_dup.same")
    assert r is None and u is not None and u.values == ("a",)


def test_branch_literal_mixed_kinds_refuse(vendor_path):
    vendor_path(
        "vendbranch_mixed",
        'def odd(x):\n'
        '    if x:\n'
        '        return "a"\n'
        '    return 1\n',
    )
    u, r = _branch("vendbranch_mixed.odd")
    assert u is None and r is not None and "cross-sort" in r.reason


def test_branch_literal_bare_return_refuses(vendor_path):
    vendor_path(
        "vendbranch_bare",
        'def odd(x):\n'
        '    if x:\n'
        '        return "a"\n'
        '    return\n',
    )
    u, r = _branch("vendbranch_bare.odd")
    assert u is None and r is not None and "bare" in r.reason


def test_branch_literal_computed_branch_not_candidate(vendor_path):
    vendor_path(
        "vendbranch_comp",
        'def f(x):\n'
        '    if x:\n'
        '        return "a"\n'
        '    return x\n',
    )
    u, r = _branch("vendbranch_comp.f")
    assert u is None and r is None


def test_branch_literal_loop_tail_not_terminal(vendor_path):
    # a while-tail can fall off the end -> implicit None would join the
    # set; the terminality check excludes it (named residual)
    vendor_path(
        "vendbranch_loop",
        'def f(x):\n'
        '    while x:\n'
        '        return "a"\n',
    )
    u, r = _branch("vendbranch_loop.f")
    assert u is None and r is None


def test_branch_literal_single_return_is_constant_territory(vendor_path):
    vendor_path(
        "vendbranch_single", 'def f(x):\n    return "a"\n'
    )
    u, r = _branch("vendbranch_single.f")
    assert u is None and r is None


def test_branch_literal_generator_excluded(vendor_path):
    vendor_path(
        "vendbranch_gen",
        'def f(x):\n'
        '    if x:\n'
        '        return "a"\n'
        '    yield "b"\n',
    )
    u, r = _branch("vendbranch_gen.f")
    assert u is None and r is None


def test_branch_literal_walrus_guard_refuses(vendor_path):
    vendor_path(
        "vendbranch_walrus",
        'def f(x):\n'
        '    if (x := x + 1) > 99:\n'
        '        raise ValueError(x)\n'
        '    if x:\n'
        '        return "a"\n'
        '    return "b"\n',
    )
    u, r = _branch("vendbranch_walrus.f")
    assert u is None and r is not None and "walrus" in r.reason


def test_branch_literal_sample_gate_refuses_outside_value(vendor_path):
    vendor_path(
        "vendbranch_gate",
        'def pick(x):\n'
        '    if x:\n'
        '        return "a"\n'
        '    return "b"\n',
    )
    vendor_path(
        "test_vendbranch_gate",
        'import vendbranch_gate\n\n'
        'def test_p():\n'
        '    assert vendbranch_gate.pick(1) == "z"\n',
    )
    u, r = _branch("vendbranch_gate.pick")
    assert u is None and r is not None and "sample-gate" in r.reason


def test_branch_literal_sample_gate_licenses_inside_value(vendor_path):
    vendor_path(
        "vendbranch_gate2",
        'def pick(x):\n'
        '    if x:\n'
        '        return "a"\n'
        '    return "b"\n',
    )
    vendor_path(
        "test_vendbranch_gate2",
        'import vendbranch_gate2\n\n'
        'def test_p():\n'
        '    assert vendbranch_gate2.pick(1) == "a"\n',
    )
    u, r = _branch("vendbranch_gate2.pick")
    assert r is None and u is not None
    assert u.vendor_vectors_checked >= 1


def test_branch_literal_emits_disjunction(vendor_path):
    # e2e: the consumer swears pick(1) == "c" — outside the walked set.
    # The inv must carry the or_ disjunction; conjoined with the claim it
    # is UNSAT and the wrong value refutes.
    from sugar_lift_py_tests.translate_universe import (
        branch_literal_universe_for_callee,
    )

    branch_literal_universe_for_callee.cache_clear()
    vendor_path(
        "vendbranch_l2",
        'def pick(x):\n'
        '    if x:\n'
        '        return "a"\n'
        '    return "b"\n',
    )
    out = _lift(
        """
        import vendbranch_l2

        def test_pick():
            assert vendbranch_l2.pick(1) == "c"
        """
    )
    ors = []
    for d in out.decls:
        if d.inv is None:
            continue
        for a in getattr(d.inv, "operands", (d.inv,)):
            if getattr(a, "kind", None) == "or":
                ors.append(a)
    assert ors, [d.name for d in out.decls]
    # both walked literals appear as equality disjuncts
    texts = repr(ors)
    assert "'a'" in texts or '"a"' in texts or "value='a'" in texts


def test_ifexp_return_walks_as_branch_literal(vendor_path):
    # the expression form of the branch shape: one return, two leaves
    vendor_path(
        "vendbranch_ifexp",
        'def pick(x):\n    return "a" if x else "b"\n',
    )
    u, r = _branch("vendbranch_ifexp.pick")
    assert r is None and u is not None
    assert u.values == ("a", "b") and u.value_kind == "str"


def test_nested_ifexp_collects_all_leaves(vendor_path):
    vendor_path(
        "vendbranch_ifexp2",
        'def pick(x):\n    return 1 if x > 9 else (2 if x > 5 else 3)\n',
    )
    u, r = _branch("vendbranch_ifexp2.pick")
    assert r is None and u is not None
    assert u.values == (1, 2, 3)


def test_ifexp_and_statement_returns_compose(vendor_path):
    vendor_path(
        "vendbranch_ifexp3",
        'def pick(x):\n'
        '    if x < 0:\n'
        '        return "neg"\n'
        '    return "big" if x > 9 else "small"\n',
    )
    u, r = _branch("vendbranch_ifexp3.pick")
    assert r is None and u is not None
    assert u.values == ("neg", "big", "small")


def test_ifexp_computed_leaf_not_candidate(vendor_path):
    vendor_path(
        "vendbranch_ifexp4",
        'def pick(x):\n    return "a" if x else x\n',
    )
    u, r = _branch("vendbranch_ifexp4.pick")
    assert u is None and r is None


def test_ifexp_mixed_kinds_refuse(vendor_path):
    vendor_path(
        "vendbranch_ifexp5",
        'def pick(x):\n    return "a" if x else 1\n',
    )
    u, r = _branch("vendbranch_ifexp5.pick")
    assert u is None and r is not None and "cross-sort" in r.reason


def test_walrus_in_ifexp_condition_is_harmless(vendor_path):
    # a rebinding in the CONDITION has nothing downstream of itself to
    # poison: the value is one of the literal leaves either way
    vendor_path(
        "vendbranch_ifexp6",
        'def pick(x):\n    return "a" if (x := x + 1) > 5 else "b"\n',
    )
    u, r = _branch("vendbranch_ifexp6.pick")
    assert r is None and u is not None and u.values == ("a", "b")


# ---------------------------------------------------------------------------
# collection-literal constant arm (census return-collection, 54k bodies):
# a literal tuple/list/dict/set of literal leaves is ONE fixed value; the
# canonical content string is built in exactly one place
# (collection_literal_canonical) and shared with the consumer-side term
# translator, so the universe equality and consumer claims are
# byte-identical by construction. repr-based leaves make 1 and True
# distinct (false-refusal direction only, never a wrong discharge).
# ---------------------------------------------------------------------------


def _const(callee):
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
    )

    constant_universe_for_callee.cache_clear()
    return constant_universe_for_callee(callee)


def test_tuple_return_pins_canonical(vendor_path):
    vendor_path("vendcoll_t", "def pair():\n    return (1, 2)\n")
    u, r = _const("vendcoll_t.pair")
    assert r is None and u is not None
    assert (u.value, u.value_kind) == ("tuple:[1, 2]", "collection")


def test_list_and_tuple_canonicals_are_distinct(vendor_path):
    vendor_path(
        "vendcoll_lt",
        "def t():\n    return (1, 2)\n\ndef l():\n    return [1, 2]\n",
    )
    ut, _ = _const("vendcoll_lt.t")
    ul, _ = _const("vendcoll_lt.l")
    assert ut.value != ul.value
    assert ul.value == "list:[1, 2]"


def test_dict_return_pins_canonical(vendor_path):
    vendor_path(
        "vendcoll_d", "def conf():\n    return {'b': 2, 'a': 1}\n"
    )
    u, r = _const("vendcoll_d.conf")
    assert r is None and u is not None
    # sorted by key repr: insertion order does not leak into the canonical
    assert u.value == "dict:" + repr({"a": 1, "b": 2})


def test_set_return_dedupes_and_sorts(vendor_path):
    vendor_path(
        "vendcoll_s", "def tags():\n    return {'b', 'a', 'b'}\n"
    )
    u, r = _const("vendcoll_s.tags")
    assert r is None and u is not None
    assert u.value == "set:['a', 'b']"


def test_computed_element_not_a_candidate(vendor_path):
    vendor_path(
        "vendcoll_comp", "def f(x):\n    return (1, x)\n"
    )
    u, r = _const("vendcoll_comp.f")
    assert u is None and r is None


def test_nested_collection_not_a_candidate(vendor_path):
    vendor_path(
        "vendcoll_nest", "def f():\n    return ((1, 2), 3)\n"
    )
    u, r = _const("vendcoll_nest.f")
    assert u is None and r is None


def test_collection_universe_contradicts_wrong_tuple(vendor_path):
    # bad twin e2e: vendor returns (1, 2); the consumer swears (1, 3).
    # Both equalities land in one inv over DISTINCT opaque constants —
    # UNSAT, the wrong tuple refutes. This also proves the consumer side
    # now LIFTS tuple-literal equality claims (it loud-refused before).
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
    )
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    constant_universe_for_callee.cache_clear()
    vendor_path("vendcoll_l2", "def pair():\n    return (1, 2)\n")
    out = _lift(
        """
        import vendcoll_l2

        def test_pair():
            assert vendcoll_l2.pair() == (1, 3)
        """
    )
    consts = []
    for d in out.decls:
        if d.inv is None:
            continue
        for a in _iter_conjuncts(d.inv):
            if getattr(a, "name", None) != "=":
                continue
            for side in getattr(a, "args", ()):
                v = getattr(side, "value", None)
                if isinstance(v, str) and v.startswith("tuple:"):
                    consts.append(v)
    assert "tuple:[1, 2]" in consts, consts  # the vendor's universe
    assert "tuple:[1, 3]" in consts, consts  # the consumer's claim


# ---------------------------------------------------------------------------
# SSA-chain delegation (census return-fn-call, 53k bodies): leading simple
# assigns are a substitution environment — `x = a; return g(x)` forwards
# `a` exactly as `return g(a)` does. Linear and control-flow-free, so
# left-to-right resolution IS the SSA; rebound names shadow correctly.
# ---------------------------------------------------------------------------

VENDOR_CHAIN = '''
def g(a, b):
    return a


def f(a):
    x = a
    return g(x, 5)


def hop(a):
    x = a
    y = x
    return g(y, 5)


def shadow(a):
    a = 7
    return g(a, a)


def ident_chain(a):
    x = a
    return x


def const_chain(a):
    x = 5
    return x


def method_chain(s):
    x = s
    return x.upper()
'''


def test_chain_assign_feeds_delegation(vendor_path):
    vendor_path("vendchain_ok", VENDOR_CHAIN)
    u, r = _deleg("vendchain_ok.f")
    assert r is None and u is not None
    assert u.kind == "delegation"
    assert u.args == (("param", 0), ("lit", 5, "int"))


def test_chain_assign_source_audit_warrants_ssa_feed(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        delegation_universe_for_callee,
    )

    delegation_universe_for_callee.cache_clear()
    vendor_path("vendchain_audit", VENDOR_CHAIN)
    out = _lift(
        """
        import vendchain_audit

        def test_chain():
            assert vendchain_audit.f(7) == 7
        """
    )

    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.delegation-universe"
        and audit["universe_kind"] == "delegation"
    )
    assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Assign"
        and locus.get("ast_path") == "$.body[0]"
        for locus in audit["loci"]
    ), audit
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Return"
        and locus.get("ast_path") == "$.body[1]"
        for locus in audit["loci"]
    ), audit


def test_chain_resolves_through_hops(vendor_path):
    vendor_path("vendchain_hop", VENDOR_CHAIN)
    u, r = _deleg("vendchain_hop.hop")
    assert r is None and u.args == (("param", 0), ("lit", 5, "int"))


def test_chain_shadowing_param_rebinds(vendor_path):
    # `a = 7; return g(a, a)`: the runtime forwards 7 regardless of the
    # caller's a — the spec must be the literal, never the param
    vendor_path("vendchain_shadow", VENDOR_CHAIN)
    u, r = _deleg("vendchain_shadow.shadow")
    assert r is None and u.args == (("lit", 7, "int"), ("lit", 7, "int"))


def test_chain_identity(vendor_path):
    vendor_path("vendchain_id", VENDOR_CHAIN)
    u, r = _deleg("vendchain_id.ident_chain")
    assert r is None and u.kind == "identity" and u.param_index == 0


def test_chain_constant(vendor_path):
    vendor_path("vendchain_const", VENDOR_CHAIN)
    u, r = _deleg("vendchain_const.const_chain")
    assert r is None and u.kind == "chain-constant"
    assert u.args == (("lit", 5, "int"),)


def test_chain_method_delegation(vendor_path):
    vendor_path("vendchain_m", VENDOR_CHAIN)
    u, r = _deleg("vendchain_m.method_chain")
    assert r is None and u.kind == "delegation-method"
    assert u.delegate == "upper" and u.args == (("param", 0),)


def test_chain_computed_value_refuses(vendor_path):
    vendor_path(
        "vendchain_comp",
        "def g(a):\n    return a\n\n"
        "def f(a):\n    x = h(a)\n    return g(x)\n",
    )
    u, r = _deleg("vendchain_comp.f")
    assert u is None and r is not None and "chain value is computed" in r.reason


def test_chain_walrus_refuses(vendor_path):
    vendor_path(
        "vendchain_walrus",
        "def g(a):\n    return a\n\n"
        "def f(a):\n    x = (y := a)\n    return g(x)\n",
    )
    u, r = _deleg("vendchain_walrus.f")
    assert u is None and r is not None and "walrus" in r.reason


def test_chain_unpack_not_candidate(vendor_path):
    vendor_path(
        "vendchain_unpack",
        "def g(a):\n    return a\n\n"
        "def f(a, b):\n    x, y = a, b\n    return g(x)\n",
    )
    u, r = _deleg("vendchain_unpack.f")
    assert u is None and r is None


def test_chain_constant_emits_equality(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        delegation_universe_for_callee,
    )
    from sugar_lift_py_tests.ir import _ConstInt

    delegation_universe_for_callee.cache_clear()
    vendor_path("vendchain_l2", VENDOR_CHAIN)
    out = _lift(
        """
        import vendchain_l2

        def test_c():
            assert vendchain_l2.const_chain(1) == 9
        """
    )
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    fives = []
    for d in out.decls:
        if d.inv is None:
            continue
        for a in _iter_conjuncts(d.inv):
            if getattr(a, "name", None) == "=":
                args = getattr(a, "args", ())
                if len(args) == 2 and isinstance(args[1], _ConstInt) and args[1].value == 5:
                    fives.append(a)
    # the universe swears == 5; the claim swears == 9: UNSAT shape present
    assert fives, [d.name for d in out.decls]


# ---------------------------------------------------------------------------
# raise locus (census non-return:Raise, 30k bodies): zero Return/Yield +
# a terminal tail means every path raises — no value exists, so any
# sworn value equality carries the canonical contradiction (0 = 1). The
# guard family's complement, total instead of clause-wise.
# ---------------------------------------------------------------------------


def _raise_locus(callee):
    from sugar_lift_py_tests.translate_universe import (
        raise_locus_universe_for_callee,
    )

    raise_locus_universe_for_callee.cache_clear()
    return raise_locus_universe_for_callee(callee)


def test_bare_raise_body_walks(vendor_path):
    vendor_path(
        "vendraise_ok",
        "def boom(x):\n    raise ValueError(x)\n",
    )
    u, r = _raise_locus("vendraise_ok.boom")
    assert r is None and u is not None


def test_if_else_both_raise_walks(vendor_path):
    vendor_path(
        "vendraise_both",
        "def boom(x):\n"
        "    if x:\n"
        "        raise ValueError(x)\n"
        "    else:\n"
        "        raise TypeError(x)\n",
    )
    u, r = _raise_locus("vendraise_both.boom")
    assert r is None and u is not None


def test_prefix_then_tail_raise_walks(vendor_path):
    vendor_path(
        "vendraise_prefix",
        "def boom(x):\n"
        "    msg = format(x)\n"
        "    raise ValueError(msg)\n",
    )
    u, r = _raise_locus("vendraise_prefix.boom")
    assert r is None and u is not None


def test_fall_off_path_not_candidate(vendor_path):
    # the guarded raise without an else can fall off the end -> None
    vendor_path(
        "vendraise_fall",
        "def maybe(x):\n    if x:\n        raise ValueError(x)\n",
    )
    u, r = _raise_locus("vendraise_fall.maybe")
    assert u is None and r is None


def test_try_wrapped_raise_not_candidate(vendor_path):
    # a handler may swallow the raise and fall off -> None can exist
    vendor_path(
        "vendraise_try",
        "def maybe(x):\n"
        "    try:\n"
        "        raise ValueError(x)\n"
        "    except ValueError:\n"
        "        pass\n",
    )
    u, r = _raise_locus("vendraise_try.maybe")
    assert u is None and r is None


def test_any_return_not_candidate(vendor_path):
    vendor_path(
        "vendraise_ret",
        "def maybe(x):\n"
        "    if x:\n"
        "        return 1\n"
        "    raise ValueError(x)\n",
    )
    u, r = _raise_locus("vendraise_ret.maybe")
    assert u is None and r is None


def test_generator_raise_not_candidate(vendor_path):
    # calling a generator function returns a generator object: a value
    vendor_path(
        "vendraise_gen",
        "def gen(x):\n    yield x\n    raise ValueError(x)\n",
    )
    u, r = _raise_locus("vendraise_gen.gen")
    assert u is None and r is None


def test_raise_locus_contradicts_any_value_claim(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        raise_locus_universe_for_callee,
    )
    from sugar_lift_py_tests.ir import _ConstInt

    raise_locus_universe_for_callee.cache_clear()
    vendor_path(
        "vendraise_l2", "def boom(x):\n    raise ValueError(x)\n"
    )
    out = _lift(
        """
        import vendraise_l2

        def test_boom():
            assert vendraise_l2.boom(1) == 3
        """
    )
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    contradictions = []
    for d in out.decls:
        if d.inv is None:
            continue
        for a in _iter_conjuncts(d.inv):
            if getattr(a, "name", None) != "=":
                continue
            args = getattr(a, "args", ())
            if (
                len(args) == 2
                and isinstance(args[0], _ConstInt)
                and isinstance(args[1], _ConstInt)
                and args[0].value == 0
                and args[1].value == 1
            ):
                contradictions.append(a)
    assert contradictions, [d.name for d in out.decls]


def test_pytest_raises_carries_raise_locus_source_warrant(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        raise_locus_universe_for_callee,
    )

    raise_locus_universe_for_callee.cache_clear()
    vendor_path(
        "vendraise_source",
        """
        class Abstract:
            def boom(self, value):
                raise NotImplementedError()
        """,
    )
    out = _lift(
        """
        import pytest
        import vendraise_source

        def test_boom():
            with pytest.raises(NotImplementedError):
                vendraise_source.Abstract.boom(None, 1)
        """
    )

    assertion = next(
        (
            d for d in out.decls
            if d.name == "test_boom"
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]
    assert any(
        warrant.get("role") == "python.raise-locus-universe"
        and warrant.get("source_function_name") == "Abstract.boom"
        for warrant in assertion.source_warrants
    ), assertion.source_warrants

    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.raise-locus-universe"
    )
    assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Raise"
        for locus in audit["loci"]
    ), audit


def test_exception_handler_raise_universe_walks_try_return_except_raise(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        exception_handler_raise_universe_for_callee,
    )

    exception_handler_raise_universe_for_callee.cache_clear()
    vendor_path(
        "vendtry_raise_source",
        """
        class BadPayload(Exception):
            pass

        class Serializer:
            def load_payload(self, payload):
                try:
                    return payload.decode("utf-8")
                except Exception as e:
                    raise BadPayload("bad", original_error=e) from e
        """,
    )
    u, r = exception_handler_raise_universe_for_callee(
        "vendtry_raise_source.Serializer.load_payload"
    )
    assert r is None and u is not None
    assert u.exception_name == "BadPayload"
    assert u.source_memento is not None
    assert u.source_memento["source_function_name"] == "Serializer.load_payload"
    assert u.source_memento["exception_handler_raise_type"] == "BadPayload"


def test_pytest_raises_conjoins_exception_handler_raise_universe(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        exception_handler_raise_universe_for_callee,
    )
    from sugar_lift_py_tests.ir import _ConstStr, _Ctor
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    exception_handler_raise_universe_for_callee.cache_clear()
    vendor_path(
        "vendtry_raise_l2",
        """
        class BadPayload(Exception):
            pass

        class Serializer:
            def load_payload(self, payload):
                try:
                    return payload.decode("utf-8")
                except Exception as e:
                    raise BadPayload("bad", original_error=e) from e
        """,
    )
    out = _lift(
        """
        import pytest
        import vendtry_raise_l2

        def test_bad_payload():
            with pytest.raises(ValueError):
                vendtry_raise_l2.Serializer.load_payload(None, b"bad")
        """
    )
    decl = next(d for d in out.decls if d.name == "test_bad_payload")
    raised = []
    for atom in _iter_conjuncts(decl.inv):
        if getattr(atom, "name", None) != "=":
            continue
        lhs, rhs = getattr(atom, "args", ())
        if isinstance(lhs, _Ctor) and lhs.name == "raised_exc_a1":
            raised.append((lhs, rhs))
    assert [rhs.value for _, rhs in raised if isinstance(rhs, _ConstStr)] == [
        "ValueError",
        "BadPayload",
    ]
    assert raised[0][0] == raised[1][0]
    assert any(
        warrant.get("role") == "python.exception-handler-raise-universe"
        and warrant.get("source_function_name") == "Serializer.load_payload"
        and warrant.get("exception_handler_raise_type") == "BadPayload"
        for warrant in decl.source_warrants
    ), decl.source_warrants
    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.exception-handler-raise-universe"
    )
    assert audit["totals"]["unclassified_source"] == 0
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Try"
        for locus in audit["loci"]
    ), audit
    assert any(
        locus["status"] == "warranted"
        and locus.get("ast_kind") == "Raise"
        for locus in audit["loci"]
    ), audit


def test_exception_bool_return_universe_walks_validate_wrapper(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        exception_bool_return_universe_for_callee,
    )

    exception_bool_return_universe_for_callee.cache_clear()
    vendor_path(
        "vendtry_bool_source",
        """
        class BadSignature(Exception):
            pass

        class Signer:
            def unsign(self, value):
                raise BadSignature("bad")

            def validate(self, value):
                try:
                    self.unsign(value)
                    return True
                except BadSignature:
                    return False
        """,
    )
    u, r = exception_bool_return_universe_for_callee(
        "vendtry_bool_source.Signer.validate"
    )
    assert r is None and u is not None
    assert u.exception_name == "BadSignature"
    assert u.success_value is True
    assert u.exception_value is False
    assert u.delegate == "vendtry_bool_source.Signer.unsign"
    assert u.args == (("param", 1),)
    assert u.source_memento is not None
    assert u.source_memento["source_function_name"] == "Signer.validate"
    assert u.source_memento["exception_bool_return_exception_type"] == "BadSignature"


def test_exception_bool_return_conjoins_raised_exception_relation(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        exception_bool_return_universe_for_callee,
    )
    from sugar_lift_py_tests.ir import _Atomic, _Connective, _ConstBool, _ConstStr, _Ctor

    exception_bool_return_universe_for_callee.cache_clear()
    vendor_path(
        "vendtry_bool_l2",
        """
        class BadSignature(Exception):
            pass

        class Signer:
            def unsign(self, value):
                raise BadSignature("bad")

            def validate(self, value):
                try:
                    self.unsign(value)
                    return True
                except BadSignature:
                    return False
        """,
    )
    out = _lift(
        """
        import vendtry_bool_l2

        def test_validate():
            signer = vendtry_bool_l2.Signer()
            assert signer.validate(b"bad") == False
        """
    )
    decl = next(
        d
        for d in out.decls
        if d.name.endswith("::assertion")
        and "vendtry_bool_l2.Signer.validate" in d.name
    )
    false_links = []
    raised_terms = []
    atoms = []

    def walk_formula(formula):
        if isinstance(formula, _Atomic):
            atoms.append(formula)
            return
        if isinstance(formula, _Connective):
            for operand in formula.operands:
                walk_formula(operand)

    walk_formula(decl.inv)
    for atom in atoms:
        if getattr(atom, "name", None) != "=":
            continue
        lhs, rhs = getattr(atom, "args", ())
        if isinstance(lhs, _Ctor) and lhs.name == "raised_exc_a1":
            raised_terms.append((lhs, rhs))
        if isinstance(rhs, _ConstBool) and rhs.value is False:
            false_links.append(atom)

    assert any(
        isinstance(rhs, _ConstStr) and rhs.value == "BadSignature"
        for _, rhs in raised_terms
    )
    assert false_links
    assert any(
        warrant.get("role") == "python.exception-bool-return-universe"
        and warrant.get("source_function_name") == "Signer.validate"
        and warrant.get("exception_bool_return_exception_type") == "BadSignature"
        for warrant in decl.source_warrants
    ), decl.source_warrants


def test_exception_bool_return_source_accounting(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        exception_bool_return_universe_for_callee,
        raise_locus_universe_for_callee,
    )

    exception_bool_return_universe_for_callee.cache_clear()
    raise_locus_universe_for_callee.cache_clear()
    vendor_path(
        "vendtry_bool_audit",
        """
        class BadSignature(Exception):
            pass

        class Signer:
            def unsign(self, value):
                raise BadSignature("bad")

            def validate(self, value):
                try:
                    self.unsign(value)
                    return True
                except BadSignature:
                    return False
        """,
    )
    out = _lift(
        """
        import vendtry_bool_audit

        def test_validate():
            signer = vendtry_bool_audit.Signer()
            assert signer.validate(b"bad") == False
        """
    )
    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.exception-bool-return-universe"
    )
    assert audit["totals"]["unclassified_source"] == 0
    warranted_lines = {
        locus["line"]
        for locus in audit["loci"]
        if locus["status"] == "warranted"
    }
    assert warranted_lines == set(range(9, 15)), audit


def test_separator_guard_raise_universe_walks_membership_guard(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        separator_guard_raise_universe_for_callee,
    )

    separator_guard_raise_universe_for_callee.cache_clear()
    vendor_path(
        "vendsep_guard_source",
        '''
def want_bytes(s, encoding="utf-8", errors="strict"):
    if isinstance(s, str):
        s = s.encode(encoding, errors)

    return s


class BadSignature(Exception):
    pass


class Signer:
    def __init__(self, sep=b"."):
        self.sep: bytes = want_bytes(sep)

    def unsign(self, signed_value):
        signed_value = want_bytes(signed_value)
        if self.sep not in signed_value:
            raise BadSignature("No sep found")
        return signed_value
''',
    )
    u, r = separator_guard_raise_universe_for_callee(
        "vendsep_guard_source.Signer.unsign"
    )
    assert r is None and u is not None
    assert u.exception_name == "BadSignature"
    assert u.field_name == "sep"
    assert u.param_name == "signed_value"
    assert u.param_index == 1
    assert u.adapter_callee == "vendsep_guard_source.want_bytes"
    assert u.source_memento is not None
    assert u.source_memento["source_function_name"] == "Signer.unsign"
    assert u.source_memento["separator_guard_exception_type"] == "BadSignature"
    assert u.source_memento["separator_guard_field_name"] == "sep"
    assert u.source_memento["separator_guard_param_name"] == "signed_value"


def test_separator_guard_raise_conjoins_validate_inner_unsign(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        exception_bool_return_universe_for_callee,
        separator_guard_raise_universe_for_callee,
    )
    from sugar_lift_py_tests.ir import _Atomic, _Connective, _ConstStr, _Ctor

    exception_bool_return_universe_for_callee.cache_clear()
    separator_guard_raise_universe_for_callee.cache_clear()
    vendor_path(
        "vendsep_guard_l2",
        '''
def want_bytes(s, encoding="utf-8", errors="strict"):
    if isinstance(s, str):
        s = s.encode(encoding, errors)

    return s


class BadSignature(Exception):
    pass


class Signer:
    def __init__(self, sep=b"."):
        self.sep: bytes = want_bytes(sep)

    def unsign(self, signed_value):
        signed_value = want_bytes(signed_value)
        if self.sep not in signed_value:
            raise BadSignature("No sep found")
        return signed_value

    def validate(self, value):
        try:
            self.unsign(value)
            return True
        except BadSignature:
            return False
''',
    )
    out = _lift(
        """
        import vendsep_guard_l2

        def test_validate():
            signer = vendsep_guard_l2.Signer(sep=b".")
            assert signer.validate(b"bad") == True
        """
    )
    decl = next(
        d
        for d in out.decls
        if d.name.endswith("::assertion")
        and "vendsep_guard_l2.Signer.validate" in d.name
    )
    atoms = []

    def walk_formula(formula):
        if isinstance(formula, _Atomic):
            atoms.append(formula)
            return
        if isinstance(formula, _Connective):
            for operand in formula.operands:
                walk_formula(operand)

    walk_formula(decl.inv)
    assert any(
        atom.name == "contains"
        and any(
            isinstance(arg, _Ctor)
            and "callresult_vendsep_guard_l2_want_bytes_a1" in arg.name
            for arg in atom.args
        )
        and any(
            isinstance(arg, _Ctor)
            and "callresult_vendsep_guard_l2_want_bytes_a1" in arg.name
            and arg.args
            and isinstance(arg.args[0], _Ctor)
            and arg.args[0].name == "python:bytes"
            and arg.args[0].args
            and isinstance(arg.args[0].args[0], _ConstStr)
            and arg.args[0].args[0].value == "."
            for arg in atom.args
        )
        for atom in atoms
    )
    assert any(
        atom.name == "="
        and any(
            isinstance(arg, _Ctor)
            and "callresult_vendsep_guard_l2_want_bytes_a1" in arg.name
            and arg.args
            and isinstance(arg.args[0], _Ctor)
            and arg.args[0].name == "python:bytes"
            and arg.args[0].args
            and isinstance(arg.args[0].args[0], _ConstStr)
            and arg.args[0].args[0].value == "."
            for arg in atom.args
        )
        and any(
            isinstance(arg, _Ctor)
            and arg.name == "python:bytes"
            and arg.args
            and isinstance(arg.args[0], _ConstStr)
            and arg.args[0].value == "."
            for arg in atom.args
        )
        for atom in atoms
    )
    assert any(
        atom.name == "="
        and any(
            isinstance(arg, _Ctor)
            and arg.name == "raised_exc_a1"
            and arg.args
            and isinstance(arg.args[0], _Ctor)
            and arg.args[0].name.startswith("callval_unsign")
            for arg in atom.args
        )
        and any(
            isinstance(arg, _ConstStr) and arg.value == "BadSignature"
            for arg in atom.args
        )
        for atom in atoms
    )
    roles = {warrant.get("role") for warrant in decl.source_warrants}
    assert "python.separator-guard-raise-universe" in roles
    assert "python.bytes-identity-universe" in roles
    audit = next(
        audit
        for audit in out.source_audits
        if audit["role"] == "python.separator-guard-raise-universe"
    )
    assert audit["totals"]["unclassified_source"] == 0
    warranted_lines = {
        locus["line"]
        for locus in audit["loci"]
        if locus["status"] == "warranted"
    }
    assert {19, 20}.issubset(warranted_lines), audit


# ---------------------------------------------------------------------------
# chain-expr (census return-binop, 17k bodies): the returned arithmetic
# expression as STRUCTURE — eq(subject, ctor("+", ...)) over the same
# operator ctors the consumer side builds. + - * lower to real Int math
# substrate-side; / % stay EUF. The emitter bridges only all-Int-const
# instantiations: '+' on strings is CONCAT by dispatch, and a string
# leaf under an arithmetic-lowered ctor is the cross-sort mislower.
# ---------------------------------------------------------------------------


def test_binop_return_walks(vendor_path):
    vendor_path("vendbinop_ok", "def add(a, b):\n    return a + b\n")
    u, r = _deleg("vendbinop_ok.add")
    assert r is None and u is not None
    assert u.kind == "chain-expr"
    assert u.expr_spec == ("binop", "+", ("param", 0), ("param", 1))


def test_nested_binop_with_chain(vendor_path):
    vendor_path(
        "vendbinop_nest",
        "def scale(a, b):\n    x = b\n    return (a + x) * 2\n",
    )
    u, r = _deleg("vendbinop_nest.scale")
    assert r is None and u.expr_spec == (
        "binop", "*",
        ("binop", "+", ("param", 0), ("param", 1)),
        ("lit", 2, "int"),
    )


def test_unsupported_binop_refuses(vendor_path):
    vendor_path("vendbinop_pow", "def p(a, b):\n    return a ** b\n")
    u, r = _deleg("vendbinop_pow.p")
    assert u is None and r is not None and "lowered set" in r.reason


def test_computed_binop_leaf_refuses(vendor_path):
    vendor_path(
        "vendbinop_comp", "def f(a):\n    return a + g(a)\n"
    )
    u, r = _deleg("vendbinop_comp.f")
    assert u is None and r is not None and "binop leaf" in r.reason


def test_binop_emits_arithmetic_equality(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        delegation_universe_for_callee,
    )

    delegation_universe_for_callee.cache_clear()
    vendor_path("vendbinop_l2", "def add(a, b):\n    return a + b\n")
    out = _lift(
        """
        import vendbinop_l2

        def test_add():
            assert vendbinop_l2.add(2, 3) == 9
        """
    )
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    plus_eqs = []
    for d in out.decls:
        if d.inv is None:
            continue
        for a in _iter_conjuncts(d.inv):
            if getattr(a, "name", None) != "=":
                continue
            for side in getattr(a, "args", ()):
                if getattr(side, "name", None) == "+":
                    plus_eqs.append(a)
    # eq(subject, +(2, 3)) conjoined with the claim == 9: Int theory
    # makes it UNSAT (2 + 3 = 5)
    assert plus_eqs, [d.name for d in out.decls]


def test_binop_skips_string_instantiation():
    # the ground gate at the emission seam: a string leaf must emit
    # nothing — '+' over strings is concat by dispatch, not arithmetic
    import sugar_lift_py_tests.layer2 as l2
    from sugar_lift_py_tests.ir import str_const, num

    term = l2._expr_spec_term(
        ("binop", "+", ("param", 0), ("lit", 1, "int")),
        [str_const("a")],
    )
    assert term is not None
    assert not l2._term_leaves_all_const_int(term)
    ok = l2._expr_spec_term(
        ("binop", "+", ("param", 0), ("lit", 1, "int")),
        [num(4)],
    )
    assert l2._term_leaves_all_const_int(ok)


def test_binop_emits_bytes_concat_with_receiver_field_and_method(vendor_path):
    from sugar_lift_py_tests.ir import _ConstStr
    from sugar_lift_py_tests.layer2 import _iter_conjuncts
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
        delegation_universe_for_callee,
    )

    constant_universe_for_callee.cache_clear()
    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "vendbinop_receiver_concat",
        '''
class Signer:
    def __init__(self, sep=b"."):
        self.sep = sep

    def get_signature(self, value):
        return b"sig"

    def sign(self, value):
        return value + self.sep + self.get_signature(value)
''',
    )

    out = _lift(
        """
        import vendbinop_receiver_concat

        def test_sign():
            signer = vendbinop_receiver_concat.Signer()
            assert signer.sign(b"raaaa") == b"wrong"
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendbinop_receiver_concat.Signer.sign" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    def contains_ctor(term, name):
        return getattr(term, "name", None) == name or any(
            contains_ctor(arg, name) for arg in getattr(term, "args", ())
        )

    def contains_str(term, value):
        return (
            isinstance(term, _ConstStr)
            and term.value == value
        ) or any(contains_str(arg, value) for arg in getattr(term, "args", ()))

    concat_eqs = []
    signature_eqs = []
    for atom in _iter_conjuncts(assertion.inv):
        if getattr(atom, "name", None) != "=":
            continue
        args = getattr(atom, "args", ())
        if any(getattr(side, "name", "") == "callval_sign_a2" for side in args):
            if any(contains_ctor(side, "str.++") for side in args):
                concat_eqs.append(atom)
        if any(
            getattr(side, "name", "") == "callval_get_signature_a2"
            for side in args
        ) and any(contains_str(side, "sig") for side in args):
            signature_eqs.append(atom)

    assert concat_eqs
    assert signature_eqs
    assert any(
        contains_ctor(side, "callval_get_signature_a2")
        for atom in concat_eqs
        for side in atom.args
    )
    assert any(
        contains_str(side, ".")
        for atom in concat_eqs
        for side in atom.args
    )

    warranted = {
        (warrant.get("role"), warrant.get("source_function_name"))
        for warrant in assertion.source_warrants
    }
    assert ("python.delegation-universe", "Signer.sign") in warranted
    assert ("python.instance-field-universe", "Signer.__init__") in warranted
    assert ("python.constant-universe", "Signer.get_signature") in warranted


def test_binop_emits_bytes_concat_after_adapter_assignment(vendor_path):
    from sugar_lift_py_tests.ir import _ConstStr
    from sugar_lift_py_tests.layer2 import _iter_conjuncts
    from sugar_lift_py_tests.translate_universe import (
        bytes_identity_universe_for_callee,
        constant_universe_for_callee,
        delegation_universe_for_callee,
    )

    bytes_identity_universe_for_callee.cache_clear()
    constant_universe_for_callee.cache_clear()
    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "vendbinop_adapter_concat",
        '''
def want_bytes(value):
    return value


class Signer:
    def __init__(self, sep=b"."):
        self.sep = sep

    def get_signature(self, value):
        return b"sig"

    def sign(self, value):
        value = want_bytes(value)
        return value + self.sep + self.get_signature(value)
''',
    )

    out = _lift(
        """
        import vendbinop_adapter_concat

        def test_sign():
            signer = vendbinop_adapter_concat.Signer()
            assert signer.sign(b"raaaa") == b"wrong"
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendbinop_adapter_concat.Signer.sign" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    def contains_ctor(term, name):
        return getattr(term, "name", None) == name or any(
            contains_ctor(arg, name) for arg in getattr(term, "args", ())
        )

    def contains_str(term, value):
        return (
            isinstance(term, _ConstStr)
            and term.value == value
        ) or any(contains_str(arg, value) for arg in getattr(term, "args", ()))

    concat_eqs = []
    adapter_eqs = []
    for atom in _iter_conjuncts(assertion.inv):
        if getattr(atom, "name", None) != "=":
            continue
        args = getattr(atom, "args", ())
        if any(getattr(side, "name", "") == "callval_sign_a2" for side in args):
            if any(contains_ctor(side, "str.++") for side in args):
                concat_eqs.append(atom)
        if any(
            getattr(side, "name", "")
            == "callresult_vendbinop_adapter_concat_want_bytes_a1"
            for side in args
        ) and any(contains_str(side, "raaaa") for side in args):
            adapter_eqs.append(atom)

    assert concat_eqs
    assert adapter_eqs
    assert any(
        contains_ctor(
            side,
            "callresult_vendbinop_adapter_concat_want_bytes_a1",
        )
        for atom in concat_eqs
        for side in atom.args
    )

    warranted = {
        (warrant.get("role"), warrant.get("source_function_name"))
        for warrant in assertion.source_warrants
    }
    assert ("python.delegation-universe", "Signer.sign") in warranted
    assert ("python.delegation-universe", "want_bytes") in warranted
    assert ("python.instance-field-universe", "Signer.__init__") in warranted
    assert ("python.constant-universe", "Signer.get_signature") in warranted


def test_binop_emits_nested_adapter_concat_with_receiver_timestamp(vendor_path):
    from sugar_lift_py_tests.layer2 import _iter_conjuncts
    from sugar_lift_py_tests.translate_universe import (
        constant_universe_for_callee,
        delegation_universe_for_callee,
    )

    constant_universe_for_callee.cache_clear()
    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "vendbinop_timestamp_concat",
        '''
def want_bytes(value):
    return value


def int_to_bytes(value):
    return value


def base64_encode(value):
    return value


class TimestampSigner:
    def __init__(self, sep=b"."):
        self.sep = sep

    def get_timestamp(self):
        return b"ts"

    def get_signature(self, value):
        return b"sig"

    def sign(self, value):
        value = want_bytes(value)
        timestamp = base64_encode(int_to_bytes(self.get_timestamp()))
        sep = want_bytes(self.sep)
        value = value + sep + timestamp
        return value + sep + self.get_signature(value)
''',
    )

    universe, refusal = delegation_universe_for_callee(
        "vendbinop_timestamp_concat.TimestampSigner.sign"
    )
    assert refusal is None
    assert universe is not None
    assert universe.kind == "chain-expr"

    out = _lift(
        """
        import vendbinop_timestamp_concat

        def test_sign():
            signer = vendbinop_timestamp_concat.TimestampSigner()
            assert signer.sign(b"raaaa") == b"wrong"
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendbinop_timestamp_concat.TimestampSigner.sign" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    def contains_ctor(term, name):
        return getattr(term, "name", None) == name or any(
            contains_ctor(arg, name) for arg in getattr(term, "args", ())
        )

    concat_eqs = []
    timestamp_eqs = []
    for atom in _iter_conjuncts(assertion.inv):
        if getattr(atom, "name", None) != "=":
            continue
        args = getattr(atom, "args", ())
        if any(getattr(side, "name", "") == "callval_sign_a2" for side in args):
            if any(contains_ctor(side, "str.++") for side in args):
                concat_eqs.append(atom)
        if any(
            getattr(side, "name", "")
            == "callresult_vendbinop_timestamp_concat_base64_encode_a1"
            for side in args
        ):
            timestamp_eqs.append(atom)

    assert concat_eqs
    assert timestamp_eqs
    assert any(
        contains_ctor(side, "callval_get_timestamp_a1")
        for atom in concat_eqs
        for side in atom.args
    )

    warranted = {
        (warrant.get("role"), warrant.get("source_function_name"))
        for warrant in assertion.source_warrants
    }
    assert ("python.delegation-universe", "TimestampSigner.sign") in warranted
    assert ("python.delegation-universe", "base64_encode") in warranted
    assert ("python.delegation-universe", "int_to_bytes") in warranted
    assert ("python.delegation-universe", "want_bytes") in warranted
    assert ("python.constant-universe", "TimestampSigner.get_timestamp") in warranted


def test_chain_expr_emits_subscripted_static_call(vendor_path):
    from sugar_lift_py_tests.layer2 import _iter_conjuncts
    from sugar_lift_py_tests.translate_universe import delegation_universe_for_callee

    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "vendexpr_subscript_call",
        '''
_bytes_to_int = object()


def bytes_to_int(bytestr):
    return _bytes_to_int(bytestr.rjust(8, b"\\x00"))[0]
''',
    )

    universe, refusal = delegation_universe_for_callee(
        "vendexpr_subscript_call.bytes_to_int"
    )
    assert refusal is None
    assert universe is not None
    assert universe.kind == "chain-expr"

    out = _lift(
        """
        import vendexpr_subscript_call

        def test_bytes_to_int():
            assert vendexpr_subscript_call.bytes_to_int(b"\\x01") == 1
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendexpr_subscript_call.bytes_to_int" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    def contains_ctor(term, name):
        return getattr(term, "name", None) == name or any(
            contains_ctor(arg, name) for arg in getattr(term, "args", ())
        )

    subject_head = None
    for atom in _iter_conjuncts(assertion.inv):
        if getattr(atom, "name", None) != "=":
            continue
        args = getattr(atom, "args", ())
        for side in args:
            name = getattr(side, "name", "")
            if name in {
                "callresult_vendexpr_subscript_call_bytes_to_int_a1",
                "callval_bytes_to_int_a2",
            }:
                subject_head = name
                break
        if subject_head is not None:
            break

    assert subject_head is not None

    expr_eqs = []
    for atom in _iter_conjuncts(assertion.inv):
        if getattr(atom, "name", None) != "=":
            continue
        args = getattr(atom, "args", ())
        if any(
            getattr(side, "name", "") == subject_head
            for side in args
        ) and any(contains_ctor(side, "subscript") for side in args):
            expr_eqs.append(atom)

    assert expr_eqs
    assert any(
        contains_ctor(side, "callresult_vendexpr_subscript_call__bytes_to_int_a1")
        for atom in expr_eqs
        for side in atom.args
    )
    assert any(
        contains_ctor(side, "callval_rjust_a3")
        for atom in expr_eqs
        for side in atom.args
    )


def test_static_container_subscript_projection_rewrites_call_args(vendor_path):
    from sugar_lift_py_tests.layer2 import _iter_conjuncts

    vendor_path(
        "vendcontainer_projection",
        """
        def ident(value):
            return value
        """,
    )

    out = _lift(
        """
        import vendcontainer_projection

        def test_projected_container_values():
            pair = ("a", "b")
            table = {"k": "v", "other": "w"}

            assert vendcontainer_projection.ident(("x", "y")[1]) == "y"
            assert vendcontainer_projection.ident(pair[1]) == "b"
            assert vendcontainer_projection.ident(table["k"]) == "v"
        """
    )

    def walk_terms(term):
        yield term
        for arg in getattr(term, "args", ()):
            yield from walk_terms(arg)

    call_args = []
    for decl in out.decls:
        if decl.inv is None:
            continue
        for atom in _iter_conjuncts(decl.inv):
            for side in getattr(atom, "args", ()):
                for term in walk_terms(side):
                    if getattr(
                        term,
                        "name",
                        "",
                    ).startswith("callresult_vendcontainer_projection_ident_a1"):
                        call_args.extend(getattr(term, "args", ()))

    assert {getattr(arg, "value", None) for arg in call_args} == {"y", "b", "v"}
    assert not any(
        getattr(term, "name", None) == "subscript"
        for decl in out.decls
        if decl.inv is not None
        for atom in _iter_conjuncts(decl.inv)
        for side in getattr(atom, "args", ())
        for term in walk_terms(side)
    )


def test_branch_chain_expr_emits_compression_prefix_universe(vendor_path):
    from sugar_lift_py_tests.layer2 import _iter_conjuncts
    from sugar_lift_py_tests.translate_universe import (
        bytes_identity_universe_for_callee,
        conditional_chain_universe_for_callee,
        delegation_universe_for_callee,
    )

    bytes_identity_universe_for_callee.cache_clear()
    conditional_chain_universe_for_callee.cache_clear()
    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "vendbranch_compress_prefix",
        '''
import zlib


def render(obj):
    return obj


def base64_encode(value):
    return value


def dump_payload(obj):
    json = render(obj)
    is_compressed = False
    compressed = zlib.compress(json)

    if len(compressed) < (len(json) - 1):
        json = compressed
        is_compressed = True

    base64d = base64_encode(json)

    if is_compressed:
        base64d = b"." + base64d

    return base64d
''',
    )

    universe, refusal = conditional_chain_universe_for_callee(
        "vendbranch_compress_prefix.dump_payload"
    )
    assert refusal is None
    assert universe is not None
    assert universe.kind == "conditional-chain-expr"

    out = _lift(
        """
        import vendbranch_compress_prefix

        def test_dump_payload():
            assert vendbranch_compress_prefix.dump_payload(b"aaaaaaaa") == b"bad"
        """
    )

    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendbranch_compress_prefix.dump_payload" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    def contains_ctor(term, name):
        return getattr(term, "name", None) == name or any(
            contains_ctor(arg, name) for arg in getattr(term, "args", ())
        )

    def walk_formula(formula):
        yield formula
        for operand in getattr(formula, "operands", ()):
            yield from walk_formula(operand)

    implies_atoms = [
        formula
        for formula in walk_formula(assertion.inv)
        if getattr(formula, "kind", None) == "implies"
    ]
    assert implies_atoms
    assert any(
        contains_ctor(arg, "str.len")
        for atom in implies_atoms
        for arg in getattr(atom, "operands", ())
    )
    assert any(
        contains_ctor(arg, "callresult_zlib_compress_a1")
        for atom in implies_atoms
        for arg in getattr(atom, "operands", ())
    )
    assert any(
        contains_ctor(arg, "str.++")
        for atom in implies_atoms
        for arg in getattr(atom, "operands", ())
    )
    assert any(
        contains_ctor(arg, "callresult_vendbranch_compress_prefix_base64_encode_a1")
        for atom in implies_atoms
        for arg in getattr(atom, "operands", ())
    )

    warranted = {
        (warrant.get("role"), warrant.get("source_function_name"))
        for warrant in assertion.source_warrants
    }
    assert (
        "python.conditional-chain-universe",
        "dump_payload",
    ) in warranted
    assert (
        "python.delegation-universe",
        "base64_encode",
    ) in warranted


def test_terminal_if_return_emits_receiver_field_branch_universe(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        conditional_chain_universe_for_callee,
        constructor_field_universe_for_callee,
        delegation_universe_for_callee,
    )

    conditional_chain_universe_for_callee.cache_clear()
    constructor_field_universe_for_callee.cache_clear()
    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "vendterminal_return",
        '''
def want_bytes(value):
    return value


class Signer:
    def sign(self, value):
        return value


class Serializer:
    def __init__(self, is_text):
        self.is_text_serializer = is_text

    def make_signer(self, salt):
        return Signer()

    def dump_payload(self, obj):
        return obj

    def dumps(self, obj, salt=None):
        payload = want_bytes(self.dump_payload(obj))
        rv = self.make_signer(salt).sign(payload)

        if self.is_text_serializer:
            return rv.decode("utf-8")

        return rv
''',
    )

    universe, refusal = conditional_chain_universe_for_callee(
        "vendterminal_return.Serializer.dumps"
    )
    assert refusal is None
    assert universe is not None
    assert universe.kind == "conditional-chain-expr"
    assert len(universe.branches) == 2

    out = _lift(
        """
        import vendterminal_return

        def test_dumps():
            serializer = vendterminal_return.Serializer(True)
            assert serializer.dumps(b"payload", None) == "payload"
        """
    )
    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendterminal_return.Serializer.dumps" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    def contains_ctor(term, name):
        return getattr(term, "name", None) == name or any(
            contains_ctor(arg, name) for arg in getattr(term, "args", ())
        )

    def walk_formula(formula):
        yield formula
        for operand in getattr(formula, "operands", ()):
            yield from walk_formula(operand)

    implies_atoms = [
        atom
        for atom in walk_formula(assertion.inv)
        if getattr(atom, "kind", None) == "implies"
    ]
    assert implies_atoms
    assert any(
        contains_ctor(arg, "callval_decode_a2")
        for atom in implies_atoms
        for arg in getattr(atom, "operands", ())
    )
    assert any(
        contains_ctor(arg, "callval_sign_a2")
        for atom in implies_atoms
        for arg in getattr(atom, "operands", ())
    )
    assert any(
        contains_ctor(arg, "callval_dump_payload_a2")
        for atom in implies_atoms
        for arg in getattr(atom, "operands", ())
    )

    warranted = {
        (warrant.get("role"), warrant.get("source_function_name"))
        for warrant in assertion.source_warrants
    }
    assert (
        "python.conditional-chain-universe",
        "Serializer.dumps",
    ) in warranted
    assert (
        "python.instance-field-universe",
        "Serializer.__init__",
    ) in warranted


def test_inline_constructor_method_call_temporally_pins_receiver(vendor_path):
    from sugar_lift_py_tests.translate_universe import (
        conditional_chain_universe_for_callee,
        constructor_field_universe_for_callee,
        delegation_universe_for_callee,
    )

    conditional_chain_universe_for_callee.cache_clear()
    constructor_field_universe_for_callee.cache_clear()
    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "vendtemporal_pin",
        '''
def want_bytes(value):
    return value


class Signer:
    def sign(self, value):
        return value


class Serializer:
    def __init__(self, is_text):
        self.is_text_serializer = is_text

    def make_signer(self, salt):
        return Signer()

    def dump_payload(self, obj):
        return obj

    def dumps(self, obj, salt=None):
        payload = want_bytes(self.dump_payload(obj))
        rv = self.make_signer(salt).sign(payload)

        if self.is_text_serializer:
            return rv.decode("utf-8")

        return rv
''',
    )

    out = _lift(
        """
        import vendtemporal_pin

        def test_inline_dumps():
            assert vendtemporal_pin.Serializer(True).dumps(b"payload", None) == "payload"
        """
    )
    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendtemporal_pin.Serializer.dumps" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    def contains_ctor(term, name):
        return getattr(term, "name", None) == name or any(
            contains_ctor(arg, name) for arg in getattr(term, "args", ())
        )

    def walk_formula(formula):
        yield formula
        for operand in getattr(formula, "operands", ()):
            yield from walk_formula(operand)

    implies_atoms = [
        atom
        for atom in walk_formula(assertion.inv)
        if getattr(atom, "kind", None) == "implies"
    ]
    assert implies_atoms
    assert any(
        contains_ctor(arg, "callval_decode_a2")
        for atom in implies_atoms
        for arg in getattr(atom, "operands", ())
    )
    assert any(
        contains_ctor(arg, "callval_sign_a2")
        for atom in implies_atoms
        for arg in getattr(atom, "operands", ())
    )

    warranted = {
        (warrant.get("role"), warrant.get("source_function_name"))
        for warrant in assertion.source_warrants
    }
    assert (
        "python.conditional-chain-universe",
        "Serializer.dumps",
    ) in warranted
    assert (
        "python.instance-field-universe",
        "Serializer.__init__",
    ) in warranted


def test_inline_fluent_chain_emits_phantom_method_terms(vendor_path):
    from sugar_lift_py_tests.layer2 import _iter_conjuncts
    from sugar_lift_py_tests.translate_universe import (
        constructor_field_universe_for_callee,
        delegation_universe_for_callee,
    )

    constructor_field_universe_for_callee.cache_clear()
    delegation_universe_for_callee.cache_clear()
    vendor_path(
        "vendtemporal_chain",
        '''
class Cstr:
    def __init__(self, value):
        self.value = value

    def map(self, suffix):
        return Cstr(self.value + suffix)

    def run(self, suffix):
        return self.value + suffix
''',
    )

    out = _lift(
        """
        import vendtemporal_chain

        def test_fluent_chain():
            assert vendtemporal_chain.Cstr("a").map("b").run("c") == "abc"
        """
    )
    assertion = next(
        (
            d
            for d in out.decls
            if d.name.endswith("::assertion")
            and "vendtemporal_chain.Cstr.run" in d.name
        ),
        None,
    )
    assert assertion is not None, [d.name for d in out.decls]

    def contains_ctor(term, name):
        return getattr(term, "name", None) == name or any(
            contains_ctor(arg, name) for arg in getattr(term, "args", ())
        )

    def str_value(term):
        return getattr(term, "value", None)

    def is_str_concat(term, left_value, right_value):
        if getattr(term, "name", None) != "str.++":
            return False
        args = getattr(term, "args", ())
        return (
            len(args) == 2
            and str_value(args[0]) == left_value
            and str_value(args[1]) == right_value
        )

    def is_nested_concat(term):
        if getattr(term, "name", None) != "str.++":
            return False
        args = getattr(term, "args", ())
        return (
            len(args) == 2
            and is_str_concat(args[0], "a", "b")
            and str_value(args[1]) == "c"
        )

    assert any(
        contains_ctor(side, "callval_run_a2")
        for atom in _iter_conjuncts(assertion.inv)
        for side in getattr(atom, "args", ())
    )
    assert any(
        contains_ctor(side, "callval_map_a2")
        for atom in _iter_conjuncts(assertion.inv)
        for side in getattr(atom, "args", ())
    )
    assert any(
        is_nested_concat(side)
        for atom in _iter_conjuncts(assertion.inv)
        for side in getattr(atom, "args", ())
    )
    assert any(
        contains_ctor(side, "call:vendtemporal_chain.Cstr")
        for atom in _iter_conjuncts(assertion.inv)
        for side in getattr(atom, "args", ())
    )

    warranted = {
        (warrant.get("role"), warrant.get("source_function_name"))
        for warrant in assertion.source_warrants
    }
    assert ("python.delegation-universe", "Cstr.run") in warranted
    assert ("python.delegation-universe", "Cstr.map") in warranted
