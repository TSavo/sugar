# SPDX-License-Identifier: Apache-2.0
"""The generic assertion-vocabulary lift fold.

numpy.testing, pandas.testing, sklearn.utils._testing -- each is a vocabulary of
assert helpers, and each "seat" was the SAME fold over a different vocabulary
table. This module is that fold, ONCE; a seat is now `AssertionVocab(...)` + a
one-line `partial`. The four lifters were never four lifters.

An ``AssertionVocab`` is the table:

  equality    -- helpers asserting EXACT equality -> lifted as ``relation`` (``=``).
  truth       -- helpers asserting truthiness of one arg -> lifted via the bool-expr
                 lifter (numpy's ``assert_``).
  approx      -- helpers asserting a TOLERANCE relation (``a ~= b``) -> LOUD REFUSE:
                 lifting as ``=`` would false-pass. (Recovering the real inequality
                 is a later step; for now the trichotomy refuses loudly.)
  other       -- helpers recognised but not lifted in v0 -> claim + refuse, so
                 nothing real is silently skipped.

  harmless_kwargs    -- kwargs that DON'T change the relation (presentational).
                        Any kwarg outside this set on an equality call -> refuse
                        ("may change the relation").
  require_true_kwargs -- kwargs that must be PRESENT and ``True`` for an equality
                        lift (pandas's ``check_exact``: approximate by default).

Everything else -- SSA scoping, callsite keying, the mixed-body permitted set,
the soundness discipline -- is shared, lifted from the pytest seat's machinery.
"""

from __future__ import annotations

import ast
from collections import OrderedDict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

import sugar_lift_py_tests.layer2 as _l2
from sugar_lift_py_tests.layer2 import (
    Layer2Output,
    LiftWarning,
    _ValueScope,
    _call_key,
    _callsite_contract_base,
    _call_origin_from_expr,
    _call_result_term,
    _canonical_term_sig,
    _comparison_from_symbol,
    _Ctor,
    _euf_args_all_concrete,
    _iter_test_functions,
    _lift_assertion_stmt_scoped,
    _strip_self,
    _translate_bool_expr_scoped,
    _translate_term_scoped,
    _unparse,
)
from sugar_lift_py_tests.ir import (
    ContractDecl,
    Term,
    Formula,
    and_,
    ctor,
    gt,
    lt,
    make_var,
    real_lit,
)


@dataclass(frozen=True)
class ToleranceSpec:
    """How to lift a member of ``approx`` as a real-arithmetic tolerance bound,
    instead of loud-refusing it.

    A ``decimal``-kind assertion (numpy's ``assert_array_almost_equal`` /
    ``assert_almost_equal``) holds iff ``|actual - desired| < 1.5 * 10**(-decimal)``.
    The bound is an EXACT decimal (a power-of-ten times 1.5), so it rides into the
    contract as a canonical decimal string with no float in sight. The relation is
    lifted two-sided -- ``-T < (a-b) ∧ (a-b) < T`` -- which needs only the already-
    interpreted ``-`` operator and ``<``; no ``abs`` term is required.

    ``name``            the assert function this spec governs.
    ``decimal_param``   the parameter carrying the precision (kwarg name); it may
                        also arrive as ``decimal_pos`` (positional index).
    ``decimal_default`` numpy's default precision when the param is omitted.
    """

    name: str
    kind: str = "decimal"
    decimal_param: str = "decimal"
    decimal_pos: int = 2
    decimal_default: int = 7


@dataclass(frozen=True)
class AssertionVocab:
    """The per-library table the generic fold is parameterized by."""

    label: str
    equality: FrozenSet[str] = frozenset()
    truth: FrozenSet[str] = frozenset()
    approx: FrozenSet[str] = frozenset()
    other: FrozenSet[str] = frozenset()
    harmless_kwargs: FrozenSet[str] = frozenset({"err_msg", "verbose"})
    require_true_kwargs: FrozenSet[str] = frozenset()
    relation: str = "="
    # Members of ``approx`` that ARE liftable as a real-arithmetic tolerance bound
    # (the rest of ``approx`` -- e.g. the ULP family -- stays loud-refused).
    tolerances: Tuple[ToleranceSpec, ...] = ()

    @property
    def all(self) -> FrozenSet[str]:
        return self.equality | self.truth | self.approx | self.other

    def tolerance_for(self, name: str) -> "Optional[ToleranceSpec]":
        for t in self.tolerances:
            if t.name == name:
                return t
        return None


def _call_name(func: ast.expr) -> Optional[str]:
    """Final callee name for ``assert_x(...)`` (bare ``Name``) and
    ``mod.assert_x(...)`` (``Attribute``); None otherwise."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _assertion_name(stmt: ast.stmt, vocab: AssertionVocab) -> Optional[str]:
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        name = _call_name(stmt.value.func)
        if name in vocab.all:
            return name
    return None


def _kwarg_is_true(call: ast.Call, name: str) -> bool:
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant) and kw.value.value is True:
            return True
    return False


def _decimal_tol_strings(decimal: int) -> Tuple[str, str]:
    """Exact ``(+T, -T)`` decimal strings for ``|a-b| < 1.5 * 10**(-decimal)``.

    ``1.5 * 10**(-decimal)`` is an exact decimal, so ``Decimal`` renders it with
    no rounding: the bound is content-addressable verbatim."""
    val = Decimal("15") * (Decimal(10) ** (-decimal - 1))
    return format(val, "f"), format(-val, "f")


def _read_int_literal_arg(call: ast.Call, kw_name: str, pos_index: int) -> Optional[int]:
    """Read an integer-literal argument by keyword name or positional index.
    Returns None if absent; raises ValueError if present but not an int literal
    (so the tolerance is not computable and the assertion is loud-refused)."""
    for kw in call.keywords:
        if kw.arg == kw_name:
            v = kw.value
            if isinstance(v, ast.Constant) and isinstance(v.value, int) and not isinstance(v.value, bool):
                return v.value
            raise ValueError(f"`{kw_name}` is not an integer literal; tolerance not computable")
    if len(call.args) > pos_index:
        a = call.args[pos_index]
        if isinstance(a, ast.Constant) and isinstance(a.value, int) and not isinstance(a.value, bool):
            return a.value
        raise ValueError(f"positional `{kw_name}` is not an integer literal; tolerance not computable")
    return None


def _lift_assertion_scoped(
    call: ast.Call, scope: _ValueScope, call_vars, vocab: AssertionVocab
) -> Formula:
    """Lift one vocabulary assertion call. Raises ValueError (loud, recorded as a
    skip) for approximate / relation-altering / unsupported forms so they are
    NEVER silently lifted as exact equality."""
    name = _call_name(call.func)
    if name in vocab.equality:
        if len(call.args) < 2:
            raise ValueError(f"{name} expects at least 2 positional args")
        kw = {k.arg for k in call.keywords}
        extra = kw - vocab.harmless_kwargs
        if extra:
            raise ValueError(
                f"{name}: keyword arg(s) {sorted(extra)} may change the relation; "
                "not liftable as exact equality"
            )
        for rk in vocab.require_true_kwargs:
            if not _kwarg_is_true(call, rk):
                raise ValueError(
                    f"`{name}` is approximate by default; refused as exact equality "
                    f"unless {rk}=True is pinned"
                )
        l = _translate_term_scoped(call.args[0], scope, call_vars)
        r = _translate_term_scoped(call.args[1], scope, call_vars)
        return _comparison_from_symbol(vocab.relation, l, r)
    if name in vocab.truth:
        if len(call.args) < 1:
            raise ValueError(f"{name} expects 1 positional arg")
        return _translate_bool_expr_scoped(call.args[0], scope, call_vars)
    if name in vocab.approx:
        spec = vocab.tolerance_for(name)
        if spec is None:
            # Approximate, but with no liftable tolerance shape (e.g. the ULP
            # family -- ULP distance is not algebraic). Refuse loudly.
            raise ValueError(
                f"approximate assertion `{name}` is not exact equality "
                "(a ~= b within tolerance); refused to avoid false-pass"
            )
        if len(call.args) < 2:
            raise ValueError(f"{name} expects at least 2 positional args")
        kw = {k.arg for k in call.keywords}
        extra = kw - vocab.harmless_kwargs - {spec.decimal_param}
        if extra:
            raise ValueError(
                f"{name}: keyword arg(s) {sorted(extra)} may change the tolerance; "
                "not liftable as a fixed bound"
            )
        decimal = _read_int_literal_arg(call, spec.decimal_param, spec.decimal_pos)
        if decimal is None:
            decimal = spec.decimal_default
        pos, neg = _decimal_tol_strings(decimal)
        a = _translate_term_scoped(call.args[0], scope, call_vars)
        b = _translate_term_scoped(call.args[1], scope, call_vars)
        diff = ctor("-", [a, b])
        # |a - b| < T  <=>  -T < (a - b) ∧ (a - b) < T  (two-sided; no abs needed)
        return and_([gt(diff, real_lit(neg)), lt(diff, real_lit(pos))])
    raise ValueError(f"assertion `{name}` not lifted in v0")


def _subject_call(stmt: ast.stmt, vocab: AssertionVocab) -> Optional[ast.Call]:
    """The library call WHOSE RESULT is under test, for callsite-keying."""
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        if _call_name(stmt.value.func) in vocab.equality:
            for arg in stmt.value.args[:2]:
                if isinstance(arg, ast.Call):
                    return arg
    if isinstance(stmt, ast.Assert) and isinstance(stmt.test, ast.Compare):
        for operand in [stmt.test.left, *stmt.test.comparators]:
            if isinstance(operand, ast.Call):
                return operand
    return None


def _callsite_base(call, scope, call_vars, source_path: str) -> Optional[str]:
    origin = _call_origin_from_expr(call)
    if origin is None:
        return None
    euf_term = _call_result_term(call, origin, scope, call_vars)
    if not (
        euf_term is not None
        and isinstance(euf_term, _Ctor)
        and euf_term.args
        and _euf_args_all_concrete(euf_term)
    ):
        return None
    origin.arg_sig = _canonical_term_sig(euf_term)
    return _callsite_contract_base(origin, source_path)


def _unsupported_stmt(stmt: ast.stmt, vocab: AssertionVocab) -> Optional[str]:
    if isinstance(stmt, ast.Assert) or isinstance(stmt, ast.Pass):
        return None
    if _assertion_name(stmt, vocab) is not None:
        return None
    if isinstance(stmt, ast.Assign):
        for tgt in stmt.targets:
            if not isinstance(tgt, ast.Name):
                return (
                    f"non-simple assignment target `{_unparse(tgt)[:60]}` "
                    "(subscript/attribute mutation is not soundly liftable)"
                )
        return None
    if isinstance(stmt, ast.AnnAssign):
        if not isinstance(stmt.target, ast.Name):
            return f"non-simple annotated-assignment target `{_unparse(stmt.target)[:60]}`"
        return None
    if isinstance(stmt, ast.Expr):
        return (
            f"non-assertion expression statement `{_unparse(stmt)[:60]}` "
            "(a side-effecting call could mutate a bound value)"
        )
    return f"unsupported statement kind `{type(stmt).__name__}`"


def _classify(
    body: Sequence[ast.stmt],
    test_name: str,
    source_path: str,
    out: Layer2Output,
    vocab: AssertionVocab,
) -> bool:
    if not any(_assertion_name(s, vocab) is not None for s in body):
        return False

    pfx = f"layer2 {vocab.label}"
    unsupported = [r for s in body if (r := _unsupported_stmt(s, vocab)) is not None]
    if unsupported:
        out.claimed_tests.add(test_name)
        out.seen += 1
        for reason in unsupported:
            out.warnings.append(LiftWarning(source_path, test_name, f"{pfx}: LOUD REFUSAL -- {reason}"))
        return True

    ssa_current: Dict[str, Term] = {}
    ssa_versions: Dict[str, int] = {}
    skipped: List[str] = []

    call_vars = {}
    for stmt in body:
        for c in ast.walk(stmt):
            if isinstance(c, ast.Call):
                k = _call_key(c)
                if k not in call_vars:
                    call_vars[k] = make_var(f"__call${c.lineno}${c.col_offset}")

    keyed: List = []
    for stmt in body:
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            target = stmt.targets[0].id if isinstance(stmt, ast.Assign) else stmt.target.id
            version = ssa_versions.get(target, 0)
            ssa_versions[target] = version + 1
            ssa_current[target] = make_var(f"{target}${version}")
            continue
        if isinstance(stmt, ast.Pass):
            continue
        scope = _ValueScope(current=dict(ssa_current))
        try:
            if _assertion_name(stmt, vocab) is not None:
                atom = _lift_assertion_scoped(stmt.value, scope, call_vars, vocab)
            else:
                atom = _lift_assertion_stmt_scoped(stmt, scope, call_vars)
        except ValueError as e:
            skipped.append(f"`{_unparse(stmt)[:60]}`: {e}")
            continue
        subject = _subject_call(stmt, vocab)
        base = _callsite_base(subject, scope, call_vars, source_path) if subject is not None else None
        name = f"{base}::assertion" if base is not None else test_name
        keyed.append((name, atom))

    if not keyed:
        out.claimed_tests.add(test_name)
        out.seen += 1
        out.warnings.append(
            LiftWarning(source_path, test_name, f"{pfx}: 0 assertions liftable; skipped: {'; '.join(skipped)}")
        )
        return True

    out.claimed_tests.add(test_name)
    out.seen += 1
    groups: "OrderedDict[str, List]" = OrderedDict()
    for name, atom in keyed:
        groups.setdefault(name, []).append(atom)
    for name, atoms_g in groups.items():
        inv = atoms_g[0] if len(atoms_g) == 1 else and_(atoms_g)
        out.decls.append(ContractDecl(name=name, inv=inv))
    out.lifted += 1
    if skipped:
        out.warnings.append(
            LiftWarning(source_path, test_name, f"{pfx}: {len(skipped)} assertion(s) skipped from conjunction: {'; '.join(skipped)}")
        )
    return True


def lift_file_assertions(source: str, source_path: str, vocab: AssertionVocab) -> Layer2Output:
    """Public entry: lift ``vocab``'s assertions from a test file."""
    out = Layer2Output()
    try:
        tree = ast.parse(source, filename=source_path)
    except SyntaxError as e:
        out.warnings.append(LiftWarning(source_path, "<file>", f"layer2 {vocab.label}: failed to parse: {e}"))
        return out
    prev_aliases = _l2._CURRENT_MODULE_ALIASES
    _l2._CURRENT_MODULE_ALIASES = _l2._collect_module_aliases(tree)
    try:
        for fn, class_name in _iter_test_functions(tree):
            test_name = f"{class_name}::{fn.name}" if class_name else fn.name
            body = _strip_self(fn.body, fn)
            _classify(body, test_name, source_path, out, vocab)
    finally:
        _l2._CURRENT_MODULE_ALIASES = prev_aliases
    return out
