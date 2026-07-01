"""Unit tests for the inline predicate -> unittest assertion mapping."""

from __future__ import annotations

from sugar_emit_python_unittest import predicate_table as pt


def _atomic(name: str, *args: dict) -> dict:
    return {"kind": "atomic", "name": name, "args": list(args)}


def _var(name: str) -> dict:
    return {"kind": "var", "name": name}


def test_binary_predicates_render_native_unittest_assertions() -> None:
    assert (
        pt.render(_atomic("concept:eq", _var("a"), _var("b")))
        == "self.assertEqual(a, b)"
    )
    assert (
        pt.render(_atomic("concept:ne", _var("a"), _var("b")))
        == "self.assertNotEqual(a, b)"
    )
    assert (
        pt.render(_atomic("concept:lt", _var("a"), _var("b")))
        == "self.assertTrue(a < b)"
    )
    assert (
        pt.render(_atomic("concept:ge", _var("a"), _var("b")))
        == "self.assertTrue(a >= b)"
    )


def test_option_predicates_render_none_assertions() -> None:
    assert (
        pt.render(_atomic("concept:option-is-some", _var("x")))
        == "self.assertIsNotNone(x)"
    )
    assert (
        pt.render(_atomic("concept:option-is-none", _var("x")))
        == "self.assertIsNone(x)"
    )


def test_fallible_err_renders_assert_raises_block() -> None:
    rendered = pt.render(_atomic("concept:fallible-err", _var("call")))

    assert rendered == "with self.assertRaises(Exception):\n    call()"


def test_unsupported_predicate_or_bad_arity_returns_none() -> None:
    assert pt.render(_atomic("concept:mystery", _var("x"))) is None
    assert pt.render(_atomic("concept:eq", _var("x"))) is None
