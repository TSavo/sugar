"""Translate-table universe walk (python generalization layer, rung 2a).

A vendor body of the shape ``return <call>.translate(TABLE)`` where TABLE
is a stable module-level ``bytes.maketrans(b"...", b"...")`` binding swears
a complement universe: translate is total, so the output contains NONE of
the surviving from-side characters. Emitted as
``str.chars-not-in-set(subject, forbidden)`` — one more conjunct under the
callee's ``#euf#`` base. The encoder being delegated to (C or python) is
never walked; the claim rests entirely on the translate literals, which is
the whole point: the seam is provable even when the encoder is not.

Soundness gates (each refusal is named, never silent):
- the vendor body must be exactly docstring? + return <call>.translate(NAME)
  (any other statement could affect the result; refuse the walk);
- NAME must have exactly one module-level binding and no global-declaration
  puncture (the same teeth as sugar_lift_python_source.value_pins);
- the binding must be ``bytes.maketrans(<bytes literal>, <bytes literal>)``
  with equal lengths (CPython raises otherwise) and ASCII-only bytes;
- the forbidden set is from_set MINUS to_set: a translate that maps '+'->'/'
  REINTRODUCES '/', so swapped tables yield an empty set and NO universe.
"""

from __future__ import annotations

import ast
import functools
import importlib.util
import sys
from dataclasses import dataclass
from typing import Any, Optional, Tuple

try:
    from sugar_lift_python_source.value_pins import (
        _admission_failure,
        _binding_events,
        _Candidate,
        _global_declarations,
    )
    from sugar_lift_python_source.bind_lifter import (
        _body_source_locator,
        source_memento_of,
    )
except ModuleNotFoundError:  # repo checkout without editable installs
    import sys
    from pathlib import Path

    _SIBLING_SRC = (
        Path(__file__).resolve().parents[3] / "sugar-lift-python-source" / "src"
    )
    if str(_SIBLING_SRC) not in sys.path:
        sys.path.insert(0, str(_SIBLING_SRC))
    # The binding-stability teeth live in ONE place (value_pins); a local
    # mirror here would be the Java lesson's latent-hole scan all over again.
    from sugar_lift_python_source.value_pins import (
        _admission_failure,
        _binding_events,
        _Candidate,
        _global_declarations,
    )
    from sugar_lift_python_source.bind_lifter import (
        _body_source_locator,
        source_memento_of,
    )


@dataclass(frozen=True)
class TranslateUniverse:
    """A walked complement universe over the callee's output. Two kinds:

    - ``chars-not-in-set``: the output CONTAINS none of ``forbidden``
      (derived from a total bytes.translate over a maketrans table);
    - ``no-suffix-chars``: the output ENDS WITH none of ``forbidden``
      (derived from a total .rstrip of a bytes literal -- the
      token-padding family: rstrip(b"=") means no trailing padding,
      ever, for any input).
    - ``no-prefix-chars``: the output STARTS WITH none of ``forbidden``
      (the lstrip twin: lstrip(b"\0") means no leading zero byte).

    Provenance pins the claim to the vendor source."""

    forbidden: str
    module: str
    qualname: str
    source_path: str
    lineno: int
    table_name: str
    kind: str = "chars-not-in-set"
    # ∀⊨sample evidence: how many VENDOR vectors (from the vendor's own test
    # corpus, the same party that swore the body) were evaluated against the
    # walked set, and where they came from. Zero with a None source means no
    # vendor test corpus resolved -- licensed by the body walk alone, said
    # plainly rather than implied.
    vendor_vectors_checked: int = 0
    vendor_vector_source: Optional[str] = None
    # member-of-values payload: the pinned tuple's string elements.
    values: tuple = ()
    # Same-module calls encountered before the returned translate/rstrip
    # surface. These queue recursive digs without changing this universe's
    # own emitted relation.
    queued_calls: tuple = ()
    # Lean SourceMemento: locus + source/template CIDs, never source text.
    source_memento: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class PreludeCall:
    delegate: str
    args: tuple = ()


@dataclass(frozen=True)
class TranslateWalkRefusal:
    callee: str
    reason: str


@dataclass(frozen=True)
class GuardClause:
    """One walked precondition: `if <param> <op> <literal>: raise` means a
    RETURNED value exists only when the guard did NOT fire. param_index is
    positional in the vendor signature; op is the ir comparison symbol of
    the guard test itself (the universe conjunct is its negation,
    instantiated at the callsite's concrete argument)."""

    param_index: int
    param_name: str
    op: str
    literal: object


@dataclass(frozen=True)
class GuardUniverse:
    clauses: tuple
    module: str
    qualname: str
    source_path: str
    lineno: int
    guard_lines: tuple = ()
    vendor_vectors_checked: int = 0
    vendor_vector_source: Optional[str] = None
    source_memento: Optional[dict[str, Any]] = None


_CMP_SYMBOL = {
    ast.Lt: "<",
    ast.LtE: "≤",
    ast.Gt: ">",
    ast.GtE: "≥",
    ast.Eq: "=",
    ast.NotEq: "≠",
    ast.Is: "=",
    ast.IsNot: "≠",
}

_CMP_EVAL = {
    "<": lambda a, b: a < b,
    "≤": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "≥": lambda a, b: a >= b,
    "=": lambda a, b: a == b,
    "≠": lambda a, b: a != b,
}

# `assert P` raises when NOT P: its guard clause is P's negation.
_NEG_OP = {"<": "≥", "≤": ">", ">": "≤", "≥": "<", "=": "≠", "≠": "="}


@functools.lru_cache(maxsize=None)
def guard_universe_for_callee(
    callee: str,
) -> Tuple[Optional[GuardUniverse], Optional[TranslateWalkRefusal]]:
    """Walk the vendor body's guard-then-raise prefix: every leading
    `if <param> <cmpop> <literal>: raise ...` swears that a RETURN value
    only exists when the guard did not fire. A sworn equality about
    callee(<concrete args>) therefore carries the negated guard,
    instantiated at those arguments, as one more conjunct: assert a value
    for a guarded-out input and the conjunction is UNSAT -- you swore a
    return from a call the vendor's own source says raises."""
    resolved = _resolve_vendor_function(callee)
    if resolved is None:
        return None, None
    tree, fn, spec_origin, module_name, fn_name = resolved

    def refuse(reason: str) -> Tuple[None, TranslateWalkRefusal]:
        return None, TranslateWalkRefusal(callee=callee, reason=reason)

    params = [a.arg for a in fn.args.args]
    body = [
        stmt
        for stmt in fn.body
        if not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
    ]
    clauses = []
    guard_lines = []
    for stmt in body:
        # An `assert P` is a guard with the polarity flipped: it RAISES
        # exactly when P is false, where `if T: raise` raises when T is
        # true. Both swear "a return value implies this guard did not
        # fire"; the assert's clause is the NEGATED comparison. (Asserts
        # are assumed enabled — pytest forces them, so the vendor corpus
        # the gate reads runs with them on; under -O the clause can only
        # false-refuse, never falsePass.)
        if isinstance(stmt, ast.Assert):
            guard_test, negate = stmt.test, True
        elif (
            isinstance(stmt, ast.If)
            and len(stmt.body) == 1
            and isinstance(stmt.body[0], ast.Raise)
            and not stmt.orelse
        ):
            guard_test, negate = stmt.test, False
        else:
            break
        if any(isinstance(n, ast.NamedExpr) for n in ast.walk(guard_test)):
            # A walrus guard is NOT a pure test: it rebinds a name, so
            # every clause read after it compares the callsite's argument
            # against a comparison the runtime makes with the REBOUND
            # value (false-refusal direction). The independence argument
            # below holds only for pure tests; refuse the whole walk.
            return refuse(
                "guard-strip: a guard test rebinds via walrus "
                "(NamedExpr); sibling guard claims are no longer "
                "independent of it"
            )
        clause = _guard_clause(guard_test, params)
        if clause is None:
            # Guards are pure tests: the per-guard claim "a value implies
            # this guard did not fire" holds independently of siblings, so
            # an unreadable guard is skipped (its claim is simply not made)
            # rather than poisoning the readable ones.
            continue
        if negate:
            clause = GuardClause(
                param_index=clause.param_index,
                param_name=clause.param_name,
                op=_NEG_OP[clause.op],
                literal=clause.literal,
            )
        clauses.append(clause)
        guard_lines.append(stmt.lineno)
    if not clauses:
        return None, None

    vectors, vector_source = _vendor_call_vectors(module_name, fn_name)
    checked = 0
    for args in vectors:
        for c in clauses:
            if c.param_index < len(args):
                arg = args[c.param_index]
                try:
                    fired = _CMP_EVAL[c.op](arg, c.literal)
                except TypeError:
                    continue
                checked += 1
                if fired:
                    return refuse(
                        "sample-gate: vendor vector args "
                        f"{args!r} fire the guard "
                        f"({c.param_name} {c.op} {c.literal!r}) yet the "
                        "vendor swears a return value; the walk misread "
                        "the body or the vendor contradicts their own source"
                    )

    return (
        GuardUniverse(
            clauses=tuple(clauses),
            module=module_name,
            qualname=f"{module_name}.{fn_name}",
            source_path=spec_origin,
            lineno=fn.lineno,
            guard_lines=tuple(guard_lines),
            vendor_vectors_checked=checked,
            vendor_vector_source=vector_source,
            source_memento=_source_memento_for_resolved_function(fn, spec_origin),
        ),
        None,
    )


@dataclass(frozen=True)
class ConstantUniverse:
    """A function that unconditionally returns one literal: the strongest
    universal there is -- not membership, EQUALITY. The output IS the
    literal for every input that returns at all (a guard-then-raise prefix
    only affects whether it returns, never WHAT). value_kind is 'str' /
    'int' / 'bool' / 'none' / 'bytes' so the emitter builds the right term;
    value is the python literal."""

    value: object
    value_kind: str
    module: str
    qualname: str
    source_path: str
    lineno: int
    vendor_vectors_checked: int = 0
    vendor_vector_source: Optional[str] = None
    source_memento: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class InstanceFieldUniverse:
    """A constructor-stored field returned by an instance method.

    Shape:
      class C:
          def __init__(self, value):
              self.field = value

          def get(self):
              return self.field

    At a callsite where the receiver is known to be ``C(arg)``, the method
    result is exactly that constructor argument. The emitted ProofIR is the
    existing equality shape: ``eq(subject, constructor_args[param_index])``.
    """

    field_name: str
    constructor_param_index: int
    constructor_param_name: str
    module: str
    qualname: str
    constructor_qualname: str
    source_path: str
    lineno: int
    source_memento: Optional[dict[str, Any]] = None
    constructor_source_memento: Optional[dict[str, Any]] = None
    field_projection: Optional[tuple[str, int]] = None
    constructor_default_attr_name: Optional[str] = None
    constructor_default_literal: Optional[object] = None
    constructor_default_literal_kind: Optional[str] = None
    adapter_callee: Optional[str] = None
    helper_callee: Optional[str] = None


@dataclass(frozen=True)
class ConstructorFieldUniverse:
    """A constructor-stored field observed directly at a callsite.

    Shape:
      class C:
          def __init__(self, value):
              self.field = value

    At a callsite where ``obj`` is known to be ``C(arg)`` and the assertion
    mentions ``obj.field``, the field equals that constructor argument.
    """

    field_name: str
    constructor_param_index: int
    constructor_param_name: str
    module: str
    constructor_qualname: str
    source_path: str
    lineno: int
    constructor_source_memento: Optional[dict[str, Any]] = None
    constructor_default_attr_name: Optional[str] = None
    constructor_default_literal: Optional[object] = None
    constructor_default_literal_kind: Optional[str] = None
    forwarder_constructor_qualname: Optional[str] = None
    forwarder_source_memento: Optional[dict[str, Any]] = None
    adapter_callee: Optional[str] = None
    helper_callee: Optional[str] = None


@dataclass(frozen=True)
class _ConstructorFieldAssignment:
    assign: ast.Assign | ast.AnnAssign | ast.Expr
    param_name: str
    default_attr_name: Optional[str] = None
    default_literal: Optional[object] = None
    default_literal_kind: Optional[str] = None
    adapter_callee: Optional[str] = None
    helper_callee: Optional[str] = None


_GUARD_TAINTED = object()


def _strip_guard_prefix(body: list):
    """Split a leading guard prefix off the body: `if X: raise` clauses
    and bare `assert X` statements (an assert IS a guard — it raises
    AssertionError exactly when its test is false, so it only gates
    whether the remaining body runs, never what it computes; the
    vendor's own test corpus runs with asserts enabled, as pytest
    forces, so the gating is real where the evidence comes from).

    Returns (rest, tainted): tainted=True means a stripped guard's TEST
    contains a NamedExpr. A walrus in a guard REBINDS a name before the
    remaining body runs, so any param read downstream is no longer the
    callsite's argument — stripping such a guard is a live falsePass
    (caught 2026-06-12: `if (x := x + 10) > 100: raise` then
    `return x > 5` emitted f(1)==False while the runtime returns True).
    Every caller must refuse the walk when tainted; the invariant this
    preserves is that guard-stripping never changes the binding
    environment of the remaining body. (An assert's failure message
    evaluates only on the raising path, like a raise's arguments, so
    only the test is checked.)"""
    rest = []
    seen_nonguard = False
    tainted = False
    for stmt in body:
        if isinstance(stmt, ast.Assert):
            guard_test = stmt.test
        elif (
            isinstance(stmt, ast.If)
            and len(stmt.body) == 1
            and isinstance(stmt.body[0], ast.Raise)
            and not stmt.orelse
        ):
            guard_test = stmt.test
        else:
            guard_test = None
        if guard_test is not None and not seen_nonguard:
            if any(
                isinstance(n, ast.NamedExpr) for n in ast.walk(guard_test)
            ):
                tainted = True
            continue
        seen_nonguard = True
        rest.append(stmt)
    return rest, tainted


def _constant_return_value(body: list):
    """If the body (sans docstring, sans any leading guard-then-raise
    prefix) is a SINGLE `return <literal>` with NO other return/yield
    anywhere, the function unconditionally returns that literal. Returns
    (value, kind), None for non-candidates, or _GUARD_TAINTED when a
    stripped guard rebinds via walrus (a literal return value cannot be
    rebound, but the uniform invariant — guard-stripping never changes
    the binding environment — is enforced at every strip site rather
    than argued away per family). Guards before the return only gate
    whether it returns; they never change the value, so the equality
    still holds for every input that returns."""
    rest, tainted = _strip_guard_prefix(body)
    if tainted:
        return _GUARD_TAINTED
    # no OTHER return/yield in the whole body would let a different value
    # escape; a single return of a literal is the whole story.
    returns = sum(
        1
        for stmt in body
        for n in ast.walk(stmt)
        if isinstance(n, (ast.Return, ast.Yield, ast.YieldFrom))
    )
    # THE NONE ARM (census: empty 7k, non-return:Pass 17k, bare-return
    # 1.7k, and assert-only bodies from non-return:Assert's 179k): a body
    # that is — after the guard prefix — empty, a bare `pass`, or a bare
    # `return` falls off the end, and CPython defines falling off the end
    # as None, unconditionally. Effect-bearing tails (a call, an
    # assignment) also return None but their CONTRACT is the effect; they
    # stay non-candidates here rather than wearing a vacuous value claim.
    if not rest or (
        len(rest) == 1
        and (
            isinstance(rest[0], ast.Pass)
            or (isinstance(rest[0], ast.Return) and rest[0].value is None)
        )
    ):
        if returns <= 1:  # zero, or the single bare return itself
            return (None, "none")
        return None
    if len(rest) != 1 or not isinstance(rest[0], ast.Return):
        return None
    if returns != 1:
        return None
    vk = _literal_value_kind(rest[0].value)
    if vk is not None:
        return vk
    # collection arm (census return-collection, 54k bodies): a literal
    # tuple/list/dict/set of literal leaves is one fixed value; its
    # canonical content string is the same opaque constant the consumer
    # side builds, so the equality unifies with consumer claims.
    canonical = collection_literal_canonical(rest[0].value)
    if canonical is not None:
        return (canonical, "collection")
    return None


def _literal_value_kind(node):
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool):
            return (v, "bool")
        if isinstance(v, int):
            return (v, "int")
        if isinstance(v, str):
            return (v, "str")
        if v is None:
            return (None, "none")
        if isinstance(v, bytes):
            try:
                v.decode("ascii")
            except UnicodeDecodeError:
                return None
            return (v, "bytes")
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and type(node.operand.value) is int
    ):
        return (-node.operand.value, "int")
    return None


@dataclass(frozen=True)
class PredicateUniverse:
    """Census family return-predicate (24k bodies): a body that returns a
    PURE boolean expression over its parameters. At a CONCRETE callsite the
    expression evaluates to a ground bool -- evaluating the vendor's own
    body at the consumer's input (recompute, not solver-invention) -- so the
    output EQUALS that bool. expr is the ast.expr template; params the
    positional names; the emitter binds args->params and evaluates."""

    expr: object  # ast.expr (boolean over params/literals)
    params: tuple
    module: str
    qualname: str
    source_path: str
    lineno: int
    vendor_vectors_checked: int = 0
    vendor_vector_source: Optional[str] = None


ISINSTANCE_CONCRETE_BUILTINS = {
    "int",
    "str",
    "float",
    "complex",
    "bytes",
    "bytearray",
    "list",
    "tuple",
    "dict",
    "set",
    "frozenset",
    "bool",
    "NoneType",
    "type",
}


@dataclass(frozen=True)
class ReturnIsinstanceUniverse:
    """A body that returns ``isinstance(expr, T)`` swears Boolean equivalence
    between the function result and that predicate. The emitter instantiates
    the returned predicate over the callsite's argument terms and emits the
    existing ProofIR implication/isinstance shape."""

    expr: object  # ast.Call
    params: tuple
    module: str
    qualname: str
    source_path: str
    lineno: int
    source_memento: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class ReturnRegexUniverse:
    """A body that returns whether a static regex fullmatches a parameter.

    The emitted ProofIR is the existing strings-theory atom
    ``str.in-regex(value, pattern)`` guarded by the function's boolean result.
    """

    pattern: str
    param_name: str
    param_index: int
    module: str
    qualname: str
    source_path: str
    lineno: int
    compile_var: Optional[str] = None
    match_kind: str = "fullmatch"
    true_implies_membership: bool = True
    false_implies_nonmembership: bool = True
    source_memento: Optional[dict[str, Any]] = None

    @property
    def membership_pattern(self) -> str:
        return _regex_membership_pattern(self.pattern, self.match_kind)


_MISSING = object()


def _is_pure_predicate(node, params) -> bool:
    """The return expression is a boolean over ONLY parameter names and
    literals, combined with comparisons / and / or / not. Anything else
    (calls, attributes, subscripts, free names) is not purely evaluable at a
    concrete callsite, so it is not a candidate."""
    if isinstance(node, ast.Compare):
        return all(
            _is_pure_operand(x, params)
            for x in [node.left, *node.comparators]
        ) and all(
            isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq))
            for op in node.ops
        )
    if isinstance(node, ast.BoolOp):
        return all(_is_pure_predicate(v, params) for v in node.values)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return _is_pure_predicate(node.operand, params)
    return False


def _is_pure_operand(node, params) -> bool:
    if isinstance(node, ast.Name):
        return node.id in params
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, str, bool)) or node.value is None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return (
            isinstance(node.operand, ast.Constant)
            and type(node.operand.value) is int
        )
    return False


def _operand_value(node, env):
    if isinstance(node, ast.Name):
        return env.get(node.id, _MISSING)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        if isinstance(node.operand, ast.Constant):
            return -node.operand.value
    return _MISSING


def eval_predicate(node, env):
    """Ground-evaluate a pure predicate AST against env (param name -> python
    value). Returns a bool, or None when a value is missing / types mismatch
    (then no universe is emitted at that callsite -- conservative)."""
    try:
        if isinstance(node, ast.Compare):
            left = _operand_value(node.left, env)
            if left is _MISSING:
                return None
            for op, comp in zip(node.ops, node.comparators):
                right = _operand_value(comp, env)
                if right is _MISSING:
                    return None
                if not _CMP_EVAL[_CMP_SYMBOL[type(op)]](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.BoolOp):
            vals = [eval_predicate(v, env) for v in node.values]
            if any(v is None for v in vals):
                return None
            return all(vals) if isinstance(node.op, ast.And) else any(vals)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            v = eval_predicate(node.operand, env)
            return None if v is None else (not v)
    except TypeError:
        return None
    return None


@functools.lru_cache(maxsize=None)
def return_isinstance_universe_for_callee(
    callee: str,
) -> Tuple[Optional[ReturnIsinstanceUniverse], Optional[TranslateWalkRefusal]]:
    resolved = _resolve_vendor_function(callee, allow_methods=True)
    if resolved is None:
        return None, None
    _tree, fn, spec_origin, module_name, fn_name = resolved
    body = _body_without_docstring(fn.body)
    if (
        len(body) != 1
        or not isinstance(body[0], ast.Return)
        or body[0].value is None
    ):
        return None, None
    expr = body[0].value
    if not _is_isinstance_return_call(expr):
        return None, None
    type_arg = expr.args[1]
    if isinstance(type_arg, ast.Tuple):
        return None, TranslateWalkRefusal(
            callee=callee,
            reason=(
                "return-isinstance: tuple-of-types requires a type-union "
                "encoding; refused by name"
            ),
        )
    if isinstance(type_arg, ast.Attribute):
        return None, TranslateWalkRefusal(
            callee=callee,
            reason=(
                "return-isinstance: attribute type expression has unknown "
                "subtype hierarchy; refused by name"
            ),
        )
    if not isinstance(type_arg, ast.Name):
        return None, TranslateWalkRefusal(
            callee=callee,
            reason=(
                "return-isinstance: type argument is not a bare builtin name; "
                "refused by name"
            ),
        )
    if type_arg.id not in ISINSTANCE_CONCRETE_BUILTINS:
        return None, TranslateWalkRefusal(
            callee=callee,
            reason=(
                f"return-isinstance: `{type_arg.id}` is not a recognized "
                "concrete builtin type; type lattice required"
            ),
        )
    if sum(
        1
        for stmt in body
        for n in ast.walk(stmt)
        if isinstance(n, (ast.Return, ast.Yield, ast.YieldFrom))
    ) != 1:
        return None, None
    source_memento = _source_memento_for_resolved_function(fn, spec_origin)
    return (
        ReturnIsinstanceUniverse(
            expr=expr,
            params=tuple(a.arg for a in (*fn.args.posonlyargs, *fn.args.args)),
            module=module_name,
            qualname=f"{module_name}.{fn_name}",
            source_path=spec_origin,
            lineno=fn.lineno,
            source_memento=source_memento,
        ),
        None,
    )


def _is_isinstance_return_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "isinstance"
        and len(node.args) == 2
        and not node.keywords
    )


@functools.lru_cache(maxsize=None)
def return_regex_universe_for_callee(
    callee: str,
) -> Tuple[Optional[ReturnRegexUniverse], Optional[TranslateWalkRefusal]]:
    resolved = _resolve_vendor_function(callee, allow_methods=True)
    if resolved is None:
        return None, None
    tree, fn, spec_origin, module_name, fn_name = resolved
    body = _body_without_docstring(fn.body)
    if (
        not body
        or not isinstance(body[-1], ast.Return)
        or body[-1].value is None
    ):
        return None, None
    if sum(
        1
        for stmt in body
        for n in ast.walk(stmt)
        if isinstance(n, (ast.Return, ast.Yield, ast.YieldFrom))
    ) != 1:
        return None, None

    params = [a.arg for a in (*fn.args.posonlyargs, *fn.args.args)]
    env = _regex_compile_env_for_function(tree, fn_name)
    for stmt in body[:-1]:
        compiled = _regex_compile_assignment(stmt, tree)
        if compiled is None:
            return None, None
        name, pattern = compiled
        refusal = _regex_membership_refusal(pattern, "fullmatch")
        if refusal is not None:
            return None, TranslateWalkRefusal(callee=callee, reason=refusal)
        env[name] = pattern

    matched, refusal = _regex_bool_return(body[-1].value, params, env, tree)
    if refusal is not None:
        return None, TranslateWalkRefusal(callee=callee, reason=refusal)
    if matched is None:
        return None, None
    (
        pattern,
        param_name,
        compile_var,
        match_kind,
        true_implies_membership,
        false_implies_nonmembership,
    ) = matched
    refusal = _regex_membership_refusal(pattern, match_kind)
    if refusal is not None:
        return None, TranslateWalkRefusal(callee=callee, reason=refusal)

    source_memento = _source_memento_for_resolved_function(fn, spec_origin)
    if source_memento is not None:
        source_memento = dict(source_memento)
        source_memento["regex_pattern"] = pattern
        source_memento["regex_param_name"] = param_name
        source_memento["regex_match_kind"] = match_kind
        source_memento["regex_membership_pattern"] = _regex_membership_pattern(
            pattern,
            match_kind,
        )
        source_memento["regex_true_implies_membership"] = true_implies_membership
        source_memento["regex_false_implies_nonmembership"] = (
            false_implies_nonmembership
        )
        if compile_var is not None:
            source_memento["regex_compile_var"] = compile_var
    return (
        ReturnRegexUniverse(
            pattern=pattern,
            param_name=param_name,
            param_index=params.index(param_name),
            module=module_name,
            qualname=f"{module_name}.{fn_name}",
            source_path=spec_origin,
            lineno=body[-1].lineno,
            compile_var=compile_var,
            match_kind=match_kind,
            true_implies_membership=true_implies_membership,
            false_implies_nonmembership=false_implies_nonmembership,
            source_memento=source_memento,
        ),
        None,
    )


_REGEX_ANY_STRING = r"(?:.|\n)*"


def _regex_membership_pattern(pattern: str, match_kind: str) -> str:
    if match_kind == "fullmatch":
        return pattern
    if match_kind == "match":
        return f"(?:{pattern}){_REGEX_ANY_STRING}"
    if match_kind == "search":
        return f"{_REGEX_ANY_STRING}(?:{pattern}){_REGEX_ANY_STRING}"
    return pattern


def _regex_compile_env_for_function(
    tree: ast.Module,
    fn_name: str,
) -> dict[str, str]:
    env: dict[str, str] = {}
    for stmt in tree.body:
        compiled = _regex_compile_assignment(stmt, tree)
        if compiled is not None:
            env[compiled[0]] = compiled[1]
    class_path = fn_name.split(".")[:-1]
    if class_path:
        cls = _find_class_path(tree.body, class_path)
        if cls is not None:
            for stmt in cls.body:
                compiled = _regex_compile_assignment(stmt, tree)
                if compiled is not None:
                    env[compiled[0]] = compiled[1]
    return env


def _regex_compile_assignment(
    stmt: ast.stmt,
    tree: ast.Module,
) -> Optional[tuple[str, str]]:
    if not (
        isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], ast.Name)
        and isinstance(stmt.value, ast.Call)
    ):
        return None
    if _qualified_call_name(stmt.value, tree) != "re.compile":
        return None
    if len(stmt.value.args) != 1 or stmt.value.keywords:
        return None
    pattern = _regex_literal_arg(stmt.value, 0)
    if pattern is None:
        return None
    return stmt.targets[0].id, pattern


def _regex_bool_return(
    node: ast.expr,
    params: list[str],
    env: dict[str, str],
    tree: ast.Module,
) -> tuple[
    Optional[tuple[str, str, Optional[str], str, bool, bool]],
    Optional[str],
]:
    call = _regex_call_from_bool_expr(node)
    if call is not None:
        return _regex_call_membership(call, params, env, tree, True, True)
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
        for value in node.values:
            call = _regex_call_from_bool_expr(value)
            if call is None:
                continue
            matched, refusal = _regex_call_membership(
                call,
                params,
                env,
                tree,
                True,
                False,
            )
            if refusal is not None or matched is not None:
                return matched, refusal
    return None, None


def _regex_fullmatch_bool_return(
    node: ast.expr,
    params: list[str],
    env: dict[str, str],
    tree: ast.Module,
) -> Optional[tuple[str, str, Optional[str]]]:
    matched, refusal = _regex_bool_return(node, params, env, tree)
    if refusal is not None or matched is None:
        return None
    pattern, param_name, compile_var, _match_kind, _true_impl, _false_impl = matched
    return pattern, param_name, compile_var


def _regex_call_membership(
    call: ast.Call,
    params: list[str],
    env: dict[str, str],
    tree: ast.Module,
    true_implies_membership: bool,
    false_implies_nonmembership: bool,
) -> tuple[
    Optional[tuple[str, str, Optional[str], str, bool, bool]],
    Optional[str],
]:
    direct = _qualified_call_name(call, tree)
    direct_methods = {
        "re.fullmatch": "fullmatch",
        "re.match": "match",
        "re.search": "search",
    }
    if direct in direct_methods:
        if len(call.args) != 2 or call.keywords:
            return None, None
        pattern = _regex_pattern_arg(call.args[0], env)
        subject = call.args[1]
        match_kind = direct_methods[direct]
        if pattern is None or not isinstance(subject, ast.Name) or subject.id not in params:
            return None, None
        refusal = _regex_membership_refusal(pattern, match_kind)
        if refusal is not None:
            return None, refusal
        return (
            (
                pattern,
                subject.id,
                call.args[0].id if isinstance(call.args[0], ast.Name) else None,
                match_kind,
                true_implies_membership,
                false_implies_nonmembership,
            ),
            None,
        )
    if not (
        isinstance(call.func, ast.Attribute)
        and call.func.attr in {"fullmatch", "match", "search"}
        and len(call.args) == 1
        and not call.keywords
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id in params
    ):
        return None, None
    compiled = _compiled_regex_pattern(call.func.value, env)
    if compiled is None:
        return None, None
    compile_var, pattern = compiled
    match_kind = call.func.attr
    refusal = _regex_membership_refusal(pattern, match_kind)
    if refusal is not None:
        return None, refusal
    return (
        (
            pattern,
            call.args[0].id,
            compile_var,
            match_kind,
            true_implies_membership,
            false_implies_nonmembership,
        ),
        None,
    )


def _regex_pattern_arg(node: ast.AST, env: dict[str, str]) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return env.get(node.id)
    return None


def _compiled_regex_pattern(
    node: ast.AST,
    env: dict[str, str],
) -> Optional[tuple[str, str]]:
    if isinstance(node, ast.Name):
        pattern = env.get(node.id)
        return (node.id, pattern) if pattern is not None else None
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in {"self", "cls"}
    ):
        pattern = env.get(node.attr)
        return (node.attr, pattern) if pattern is not None else None
    return None


def _regex_call_from_bool_expr(node: ast.expr) -> Optional[ast.Call]:
    if (
        isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and len(node.comparators) == 1
        and isinstance(node.ops[0], (ast.IsNot, ast.NotEq))
    ):
        if isinstance(node.left, ast.Call) and _is_none_literal(node.comparators[0]):
            return node.left
        if isinstance(node.comparators[0], ast.Call) and _is_none_literal(node.left):
            return node.comparators[0]
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "bool"
        and len(node.args) == 1
        and not node.keywords
        and isinstance(node.args[0], ast.Call)
    ):
        return node.args[0]
    return None


def _regex_literal_arg(call: ast.Call, index: int) -> Optional[str]:
    if index >= len(call.args):
        return None
    arg = call.args[index]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    return None


def _qualified_call_name(call: ast.Call, tree: ast.Module) -> Optional[str]:
    path = _attribute_path(call.func)
    if path is None:
        return None
    root, *attrs = path
    module = _stdlib_module_aliases(tree).get(root)
    if module is None:
        return None
    if attrs:
        return ".".join([module, *attrs])
    return module


def _unsupported_regex_literal_reason(pattern: str) -> Optional[str]:
    unsupported = (
        ("(?=", "lookahead"),
        ("(?!", "lookahead"),
        ("(?<=", "lookbehind"),
        ("(?<!", "lookbehind"),
        ("(?P=", "named backreference"),
        ("\\k<", "named backreference"),
        ("(?P<", "named group"),
        ("(?<", "group extension"),
        ("(?>", "atomic group"),
        ("*+", "possessive quantifier"),
        ("++", "possessive quantifier"),
        ("?+", "possessive quantifier"),
        ("(?i", "inline flag"),
        ("(?s", "inline flag"),
        ("(?m", "inline flag"),
        ("(?x", "inline flag"),
        ("(?a", "inline flag"),
        ("(?u", "inline flag"),
        ("(?L", "inline flag"),
    )
    for needle, feature in unsupported:
        if needle in pattern:
            return f"return-regex: regex feature {feature} is not rendered"
    escaped = False
    for ch in pattern:
        if escaped:
            if ch.isdigit():
                return "return-regex: regex feature backreference is not rendered"
            escaped = False
            continue
        if ch == "\\":
            escaped = True
    return None


def _regex_membership_refusal(pattern: str, match_kind: str) -> Optional[str]:
    unsupported = _unsupported_regex_literal_reason(pattern)
    if unsupported is not None:
        return unsupported
    if match_kind == "search" and _regex_has_unescaped_anchor(pattern, {"^", "$"}):
        return (
            "return-regex: search regex anchor cannot be preserved by "
            "substring membership normalization"
        )
    if match_kind == "match" and _regex_has_unescaped_anchor(pattern, {"$"}):
        return (
            "return-regex: match regex end anchor cannot be preserved by "
            "prefix membership normalization"
        )
    return None


def _regex_has_unescaped_anchor(pattern: str, anchors: set[str]) -> bool:
    escaped = False
    in_class = False
    for ch in pattern:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == "[" and not in_class:
            in_class = True
            continue
        if ch == "]" and in_class:
            in_class = False
            continue
        if not in_class and ch in anchors:
            return True
    return False


@functools.lru_cache(maxsize=None)
def predicate_universe_for_callee(
    callee: str,
) -> Tuple[Optional[PredicateUniverse], Optional[TranslateWalkRefusal]]:
    resolved = _resolve_vendor_function(callee)
    if resolved is None:
        return None, None
    tree, fn, spec_origin, module_name, fn_name = resolved
    params = tuple(a.arg for a in fn.args.args)
    body = [
        stmt
        for stmt in fn.body
        if not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
    ]
    rest, tainted = _strip_guard_prefix(body)
    if tainted:
        # The falsePass this refusal closes: a walrus in a stripped guard
        # rebinds a param, so ground-evaluating the return expression at
        # the CALLSITE's argument computes the wrong bool and the emitted
        # equality discharges a wrong claim. Refuse loudly.
        return None, TranslateWalkRefusal(
            callee=callee,
            reason=(
                "guard-strip: a stripped guard test rebinds via walrus "
                "(NamedExpr); the remaining body no longer sees the "
                "callsite's arguments"
            ),
        )
    if (
        len(rest) != 1
        or not isinstance(rest[0], ast.Return)
        or rest[0].value is None
    ):
        return None, None
    expr = rest[0].value
    if not _is_pure_predicate(expr, params):
        return None, None
    returns = sum(
        1
        for stmt in body
        for n in ast.walk(stmt)
        if isinstance(n, (ast.Return, ast.Yield, ast.YieldFrom))
    )
    if returns != 1:
        return None, None
    return (
        PredicateUniverse(
            expr=expr,
            params=params,
            module=module_name,
            qualname=f"{module_name}.{fn_name}",
            source_path=spec_origin,
            lineno=fn.lineno,
        ),
        None,
    )


@functools.lru_cache(maxsize=None)
def constant_universe_for_callee(
    callee: str,
) -> Tuple[Optional[ConstantUniverse], Optional[TranslateWalkRefusal]]:
    """Census family return-constant (34k bodies, the largest backlog item).
    A body that unconditionally returns one literal swears the EQUALITY
    universal: callee(<anything>) == that literal. A consumer asserting any
    other value for any input refutes against it."""
    resolved = _resolve_vendor_function(callee, allow_methods=True)
    if resolved is None:
        return None, None
    tree, fn, spec_origin, module_name, fn_name = resolved
    source_memento = _source_memento_for_resolved_function(fn, spec_origin)

    def refuse(reason):
        return None, TranslateWalkRefusal(callee=callee, reason=reason)

    body = [
        stmt
        for stmt in fn.body
        if not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
    ]
    vk = _constant_return_value(body)
    if vk is _GUARD_TAINTED:
        return refuse(
            "guard-strip: a stripped guard test rebinds via walrus "
            "(NamedExpr); the remaining body no longer sees the "
            "callsite's arguments"
        )
    if vk is None:
        return None, None
    value, kind = vk

    # ∀⊨sample: every vendor vector (expected return) must EQUAL the literal
    # -- it must, since the body always returns it; a mismatch means we
    # misread the body (e.g. a return we missed) -> refuse, never guess.
    vectors, vector_source = _vendor_vectors(module_name, fn_name)
    for vector in vectors:
        if kind in ("str", "bytes") and isinstance(vector, str):
            want = value.decode("ascii") if kind == "bytes" else value
            if vector != want:
                return refuse(
                    f"sample-gate: vendor vector {vector!r} from "
                    f"{vector_source} != the constant {value!r}; the walk "
                    "misread the body or the vendor contradicts their source"
                )

    return (
        ConstantUniverse(
            value=value,
            value_kind=kind,
            module=module_name,
            qualname=f"{module_name}.{fn_name}",
            source_path=spec_origin,
            lineno=fn.lineno,
            vendor_vectors_checked=len(vectors),
            vendor_vector_source=vector_source,
            source_memento=source_memento,
        ),
        None,
    )


@functools.lru_cache(maxsize=None)
def instance_field_universe_for_callee(
    callee: str,
) -> Tuple[Optional[InstanceFieldUniverse], Optional[TranslateWalkRefusal]]:
    """Constructor-field getter universe.

    This family is intentionally narrow: a method returning ``self.a`` composes
    with a constructor body whose only non-docstring statement is
    ``self.a = <constructor-param>``. The callsite still supplies the concrete
    constructor argument; this function only proves which constructor slot the
    getter returns.
    """
    resolved = _resolve_vendor_function(
        callee,
        allow_methods=True,
        allow_property=True,
    )
    if resolved is None:
        return None, None
    tree, fn, spec_origin, module_name, fn_name = resolved
    if "." not in fn_name:
        return None, None
    class_qualname, method_name = fn_name.rsplit(".", 1)
    if method_name == "__init__":
        return None, None

    method_params = _positional_param_names(fn)
    if not method_params or method_params[0] != "self":
        return None, None
    method_body = _body_without_docstring(fn.body)
    if (
        len(method_body) != 1
        or not isinstance(method_body[0], ast.Return)
        or method_body[0].value is None
    ):
        return None, None
    returned = _self_attribute_return(method_body[0].value, method_params[0])
    if returned is None:
        return None, None
    returned_field, field_projection = returned

    cls = _find_class_path(tree.body, class_qualname.split("."), module_name)
    if cls is None:
        return None, None
    init_fn = _find_function_path(
        tree.body,
        [*class_qualname.split("."), "__init__"],
        module_name,
    )
    if init_fn is None or init_fn.decorator_list:
        return None, None
    init_params = _positional_param_names(init_fn)
    if not init_params or init_params[0] != "self":
        return None, None
    field = _constructor_field_assignment(
        init_fn,
        returned_field,
        init_params,
        tree,
        module_name,
    )
    if field is None:
        return None, None
    param_name = field.param_name

    param_index = init_params[1:].index(param_name)
    source_memento = _source_memento_for_resolved_function(fn, spec_origin)
    constructor_source_memento = _source_memento_for_resolved_function(
        init_fn,
        spec_origin,
    )
    if source_memento is None or constructor_source_memento is None:
        return None, None
    return (
        InstanceFieldUniverse(
            field_name=returned_field,
            constructor_param_index=param_index,
            constructor_param_name=param_name,
            module=module_name,
            qualname=f"{module_name}.{fn_name}",
            constructor_qualname=f"{module_name}.{class_qualname}.__init__",
            source_path=spec_origin,
            lineno=fn.lineno,
            source_memento=source_memento,
            constructor_source_memento=constructor_source_memento,
            field_projection=field_projection,
            constructor_default_attr_name=field.default_attr_name,
            constructor_default_literal=field.default_literal,
            constructor_default_literal_kind=field.default_literal_kind,
            adapter_callee=field.adapter_callee,
            helper_callee=field.helper_callee,
        ),
        None,
    )


@functools.lru_cache(maxsize=None)
def constructor_field_universe_for_callee(
    callee: str,
    field_name: str,
) -> Tuple[Optional[ConstructorFieldUniverse], Optional[TranslateWalkRefusal]]:
    resolved = _resolve_vendor_function(f"{callee}.__init__", allow_methods=True)
    if resolved is None:
        return None, None
    tree, init_fn, spec_origin, module_name, fn_name = resolved
    if not fn_name.endswith(".__init__"):
        return None, None
    init_params = _positional_param_names(init_fn)
    if not init_params or init_params[0] != "self":
        return None, None
    field = _constructor_field_assignment(
        init_fn,
        field_name,
        init_params,
        tree,
        module_name,
    )
    if field is None:
        inherited = _constructor_field_from_super_init(
            tree,
            init_fn,
            spec_origin,
            module_name,
            fn_name,
            field_name,
            init_params,
        )
        if inherited is not None:
            return inherited, None
        return None, None
    assign = field.assign
    param_name = field.param_name
    param_index = init_params[1:].index(param_name)
    constructor_source_memento = _source_memento_for_resolved_function(
        init_fn,
        spec_origin,
    )
    if constructor_source_memento is None:
        return None, None
    return (
        ConstructorFieldUniverse(
            field_name=field_name,
            constructor_param_index=param_index,
            constructor_param_name=param_name,
            module=module_name,
            constructor_qualname=f"{module_name}.{fn_name}",
            source_path=spec_origin,
            lineno=assign.lineno,
            constructor_source_memento=constructor_source_memento,
            constructor_default_attr_name=field.default_attr_name,
            constructor_default_literal=field.default_literal,
            constructor_default_literal_kind=field.default_literal_kind,
            adapter_callee=field.adapter_callee,
            helper_callee=field.helper_callee,
        ),
        None,
    )


def _constructor_field_from_super_init(
    tree: ast.Module,
    init_fn: ast.FunctionDef,
    spec_origin: str,
    module_name: str,
    fn_name: str,
    field_name: str,
    init_params: list[str],
) -> Optional[ConstructorFieldUniverse]:
    if "." not in fn_name:
        return None
    class_qualname, _init_name = fn_name.rsplit(".", 1)
    cls = _find_class_path(tree.body, class_qualname.split("."), module_name)
    if cls is None:
        return None
    super_stmt = _single_constructor_super_init(init_fn, init_params)
    if super_stmt is None:
        return None
    base_callee = _same_module_base_constructor_callee(tree, cls, module_name)
    if base_callee is None:
        return None
    base_universe, _base_refusal = constructor_field_universe_for_callee(
        base_callee,
        field_name,
    )
    if base_universe is None:
        return None
    call = super_stmt.value
    if not isinstance(call, ast.Call):
        return None
    base_param_index = base_universe.constructor_param_index
    if base_param_index >= len(call.args):
        return None
    forwarded_arg = call.args[base_param_index]
    if (
        not isinstance(forwarded_arg, ast.Name)
        or forwarded_arg.id not in init_params[1:]
    ):
        return None
    forwarded_param = forwarded_arg.id
    forwarded_index = init_params[1:].index(forwarded_param)
    forwarder_source_memento = _source_memento_for_resolved_function(
        init_fn,
        spec_origin,
    )
    if forwarder_source_memento is None:
        return None
    return ConstructorFieldUniverse(
        field_name=field_name,
        constructor_param_index=forwarded_index,
        constructor_param_name=forwarded_param,
        module=module_name,
        constructor_qualname=base_universe.constructor_qualname,
        source_path=base_universe.source_path,
        lineno=base_universe.lineno,
        constructor_source_memento=base_universe.constructor_source_memento,
        constructor_default_attr_name=base_universe.constructor_default_attr_name,
        constructor_default_literal=base_universe.constructor_default_literal,
        constructor_default_literal_kind=base_universe.constructor_default_literal_kind,
        forwarder_constructor_qualname=f"{module_name}.{fn_name}",
        forwarder_source_memento=forwarder_source_memento,
        adapter_callee=base_universe.adapter_callee,
        helper_callee=base_universe.helper_callee,
    )


def _single_constructor_super_init(
    init_fn: ast.FunctionDef,
    init_params: list[str],
) -> Optional[ast.Expr]:
    super_stmt: Optional[ast.Expr] = None
    for stmt in _body_without_docstring(init_fn.body):
        if _is_super_init_expr(stmt):
            if super_stmt is not None:
                return None
            super_stmt = stmt
            continue
        if _constructor_default_attr_stmt(stmt, init_params) is not None:
            continue
        if _constructor_field_assignment_stmt(stmt, init_params) is not None:
            continue
        return None
    return super_stmt


def _module_call_aliases(tree: ast.Module, module_name: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            aliases[stmt.name] = f"{module_name}.{stmt.name}"
        elif isinstance(stmt, ast.ImportFrom):
            imported_module = _resolved_import_from_module(module_name, stmt)
            if imported_module is None:
                continue
            for alias in stmt.names:
                if alias.name == "*":
                    continue
                aliases[alias.asname or alias.name] = (
                    f"{imported_module}.{alias.name}"
                )
    return aliases


def _resolved_import_from_module(
    module_name: str,
    stmt: ast.ImportFrom,
) -> Optional[str]:
    if stmt.level == 0:
        return stmt.module
    parts = module_name.split(".")
    base = parts[:-stmt.level]
    if not base and parts:
        base = parts[:1]
    if stmt.module:
        base = [*base, *stmt.module.split(".")]
    return ".".join(part for part in base if part)


def _same_module_base_constructor_callee(
    tree: ast.Module,
    cls: ast.ClassDef,
    module_name: str,
) -> Optional[str]:
    if not cls.bases:
        return None
    base = cls.bases[0]
    if not isinstance(base, ast.Name):
        return None
    base_cls = _find_class_path(tree.body, [base.id], module_name)
    if base_cls is None:
        return None
    return f"{module_name}.{base.id}"


def _constructor_field_assignment(
    init_fn: ast.FunctionDef,
    field_name: str,
    init_params: list[str],
    tree: ast.Module,
    module_name: str,
) -> Optional[_ConstructorFieldAssignment]:
    if init_fn.decorator_list:
        return None
    init_body = _body_without_docstring(init_fn.body)
    matched: Optional[_ConstructorFieldAssignment] = None
    default_attrs: dict[str, str] = {}
    call_aliases = _module_call_aliases(tree, module_name)
    tainted_params: set[str] = set()
    for stmt in init_body:
        if _is_super_init_expr(stmt):
            continue
        if _constructor_validation_guard_stmt(stmt):
            continue
        default_attr = _constructor_default_attr_stmt(stmt, init_params)
        if default_attr is not None:
            param_name, attr_name = default_attr
            default_attrs[param_name] = attr_name
            continue
        normalized_param = _constructor_param_normalizer_stmt(
            stmt,
            init_params,
            call_aliases,
        )
        if normalized_param is not None:
            tainted_params.add(normalized_param)
            continue
        field = _constructor_field_assignment_stmt(
            stmt,
            init_params,
            call_aliases,
        )
        if field is None:
            if _constructor_field_call_assignment_stmt(stmt, init_params):
                continue
            return None
        (
            assign,
            assigned_field,
            param_name,
            adapter_callee,
            helper_callee,
            default_literal,
            default_literal_kind,
        ) = field
        if assigned_field == field_name:
            if param_name in tainted_params:
                return None
            matched = _ConstructorFieldAssignment(
                assign=assign,
                param_name=param_name,
                default_attr_name=default_attrs.get(param_name),
                default_literal=default_literal,
                default_literal_kind=default_literal_kind,
                adapter_callee=adapter_callee,
                helper_callee=helper_callee,
            )
    return matched


def _constructor_validation_guard_stmt(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.If)
        and not stmt.orelse
        and len(stmt.body) == 1
        and isinstance(stmt.body[0], ast.Raise)
    )


def _constructor_param_normalizer_stmt(
    stmt: ast.stmt,
    init_params: list[str],
    call_aliases: dict[str, str],
) -> Optional[str]:
    if not isinstance(stmt, ast.If) or len(stmt.body) != 1 or len(stmt.orelse) > 1:
        return None
    param_name = _not_none_guarded_param_name(stmt.test, init_params)
    if param_name is None:
        param_name = _none_guarded_param_name(stmt.test, init_params)
    if param_name is None:
        return None
    if not _constructor_param_rebinds_to_known_value(
        stmt.body[0],
        param_name,
        init_params,
        call_aliases,
    ):
        return None
    if stmt.orelse and not _constructor_param_rebinds_to_known_value(
        stmt.orelse[0],
        param_name,
        init_params,
        call_aliases,
    ):
        return None
    return param_name


def _constructor_param_rebinds_to_known_value(
    stmt: ast.stmt,
    param_name: str,
    init_params: list[str],
    call_aliases: dict[str, str],
) -> bool:
    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
        return False
    target = stmt.targets[0]
    if not isinstance(target, ast.Name) or target.id != param_name:
        return False
    value = stmt.value
    if _literal_value_kind(value) is not None:
        return True
    if isinstance(value, ast.Name) and value.id == param_name:
        return True
    adapter = _constructor_adapter_call(value, init_params, call_aliases)
    if adapter is not None and adapter[0] == param_name:
        return True
    return _constructor_param_default_call(value, init_params)


def _constructor_param_default_call(
    value: ast.expr,
    init_params: list[str],
) -> bool:
    if not isinstance(value, ast.Call) or value.keywords:
        return False
    if isinstance(value.func, ast.Name):
        pass
    elif isinstance(value.func, ast.Attribute):
        if not _constructor_arg_term(value.func.value, init_params):
            return False
    else:
        return False
    return all(
        not isinstance(arg, ast.Starred)
        and _constructor_arg_term(arg, init_params)
        for arg in value.args
    )


def _constructor_arg_term(
    value: ast.expr,
    init_params: list[str],
) -> bool:
    if _literal_value_kind(value) is not None:
        return True
    if isinstance(value, ast.Name):
        return value.id in init_params[1:]
    if isinstance(value, ast.Attribute):
        cur = value
        while isinstance(cur, ast.Attribute):
            cur = cur.value
        return isinstance(cur, ast.Name) and cur.id == init_params[0]
    return False


def _constructor_field_assignment_stmt(
    stmt: ast.stmt,
    init_params: list[str],
    call_aliases: Optional[dict[str, str]] = None,
) -> Optional[
    tuple[
        ast.Assign | ast.AnnAssign | ast.Expr,
        str,
        str,
        Optional[str],
        Optional[str],
        Optional[object],
        Optional[str],
    ]
]:
    object_setattr = _constructor_object_setattr_assignment_stmt(stmt, init_params)
    if object_setattr is not None:
        return object_setattr
    if isinstance(stmt, ast.Assign):
        if len(stmt.targets) != 1:
            return None
        target = stmt.targets[0]
        value = stmt.value
    elif isinstance(stmt, ast.AnnAssign):
        target = stmt.target
        value = stmt.value
    else:
        return None
    assigned_field = _self_attribute_name(target, init_params[0])
    if assigned_field is None:
        return None
    if isinstance(value, ast.Name) and value.id in init_params[1:]:
        return stmt, assigned_field, value.id, None, None, None, None
    adapter = _constructor_adapter_call(value, init_params, call_aliases or {})
    if adapter is not None:
        param_name, adapter_callee = adapter
        return stmt, assigned_field, param_name, adapter_callee, None, None, None
    helper = _constructor_list_adapter_call(value, init_params, call_aliases or {})
    if helper is not None:
        param_name, helper_callee = helper
        return stmt, assigned_field, param_name, None, helper_callee, None, None
    default_literal = _constructor_bool_or_default_literal(value, init_params)
    if default_literal is not None:
        param_name, literal_value, literal_kind = default_literal
        return (
            stmt,
            assigned_field,
            param_name,
            None,
            None,
            literal_value,
            literal_kind,
        )
    return None


def _constructor_object_setattr_assignment_stmt(
    stmt: ast.stmt,
    init_params: list[str],
) -> Optional[
    tuple[
        ast.Expr,
        str,
        str,
        Optional[str],
        Optional[str],
        Optional[object],
        Optional[str],
    ]
]:
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
        return None
    call = stmt.value
    if (
        _static_expr_name(call.func) != "object.__setattr__"
        or call.keywords
        or len(call.args) != 3
    ):
        return None
    owner, field, value = call.args
    if not (
        isinstance(owner, ast.Name)
        and owner.id == init_params[0]
        and isinstance(field, ast.Constant)
        and isinstance(field.value, str)
        and isinstance(value, ast.Name)
        and value.id in init_params[1:]
    ):
        return None
    return stmt, field.value, value.id, None, None, None, None


def _static_expr_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _static_expr_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _constructor_field_call_assignment_stmt(
    stmt: ast.stmt,
    init_params: list[str],
) -> bool:
    if isinstance(stmt, ast.Assign):
        if len(stmt.targets) != 1:
            return False
        target = stmt.targets[0]
        value = stmt.value
    elif isinstance(stmt, ast.AnnAssign):
        target = stmt.target
        value = stmt.value
    else:
        return False
    if _self_attribute_name(target, init_params[0]) is None:
        return False
    return _constructor_param_default_call(value, init_params)


def _constructor_bool_or_default_literal(
    value: ast.expr,
    init_params: list[str],
) -> Optional[tuple[str, object, str]]:
    if (
        not isinstance(value, ast.BoolOp)
        or not isinstance(value.op, ast.Or)
        or len(value.values) != 2
        or not isinstance(value.values[0], ast.Name)
        or value.values[0].id not in init_params[1:]
    ):
        return None
    param_name = value.values[0].id
    literal = _literal_value_kind(value.values[1])
    if literal is not None:
        literal_value, literal_kind = literal
        return param_name, literal_value, literal_kind
    canonical = collection_literal_canonical(value.values[1])
    if canonical is not None:
        return param_name, canonical, "collection"
    return None


def _constructor_adapter_call(
    value: ast.expr,
    init_params: list[str],
    call_aliases: dict[str, str],
) -> Optional[tuple[str, str]]:
    if not (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and not value.keywords
        and len(value.args) == 1
        and not isinstance(value.args[0], ast.Starred)
        and isinstance(value.args[0], ast.Name)
        and value.args[0].id in init_params[1:]
    ):
        return None
    callee = call_aliases.get(value.func.id)
    if callee is None:
        return None
    universe, refusal = bytes_identity_universe_for_callee(callee)
    if refusal is not None or universe is None:
        return None
    return value.args[0].id, callee


def _constructor_list_adapter_call(
    value: ast.expr,
    init_params: list[str],
    call_aliases: dict[str, str],
) -> Optional[tuple[str, str]]:
    if not (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and not value.keywords
        and len(value.args) == 1
        and not isinstance(value.args[0], ast.Starred)
        and isinstance(value.args[0], ast.Name)
        and value.args[0].id in init_params[1:]
    ):
        return None
    callee = call_aliases.get(value.func.id)
    if callee is None:
        return None
    universe, refusal = list_adapter_universe_for_callee(callee)
    if refusal is not None or universe is None:
        return None
    return value.args[0].id, callee


def _constructor_default_attr_stmt(
    stmt: ast.stmt,
    init_params: list[str],
) -> Optional[tuple[str, str]]:
    if not isinstance(stmt, ast.If) or stmt.orelse:
        return None
    param_name = _none_guarded_param_name(stmt.test, init_params)
    if param_name is None or len(stmt.body) != 1:
        return None
    body_stmt = stmt.body[0]
    if not isinstance(body_stmt, ast.Assign) or len(body_stmt.targets) != 1:
        return None
    target = body_stmt.targets[0]
    if not isinstance(target, ast.Name) or target.id != param_name:
        return None
    attr_name = _self_attribute_name(body_stmt.value, init_params[0])
    if attr_name is None:
        return None
    return param_name, attr_name


def _none_guarded_param_name(
    test: ast.expr,
    init_params: list[str],
) -> Optional[str]:
    if (
        not isinstance(test, ast.Compare)
        or len(test.ops) != 1
        or not isinstance(test.ops[0], ast.Is)
        or len(test.comparators) != 1
    ):
        return None
    left = test.left
    right = test.comparators[0]
    if isinstance(left, ast.Name) and _is_none_literal(right):
        param_name = left.id
    elif isinstance(right, ast.Name) and _is_none_literal(left):
        param_name = right.id
    else:
        return None
    if param_name not in init_params[1:]:
        return None
    return param_name


def _not_none_guarded_param_name(
    test: ast.expr,
    init_params: list[str],
) -> Optional[str]:
    if (
        not isinstance(test, ast.Compare)
        or len(test.ops) != 1
        or not isinstance(test.ops[0], ast.IsNot)
        or len(test.comparators) != 1
    ):
        return None
    left = test.left
    right = test.comparators[0]
    if isinstance(left, ast.Name) and _is_none_literal(right):
        param_name = left.id
    elif isinstance(right, ast.Name) and _is_none_literal(left):
        param_name = right.id
    else:
        return None
    if param_name not in init_params[1:]:
        return None
    return param_name


def _is_none_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


@functools.lru_cache(maxsize=None)
def constructor_param_names_for_callee(callee: str) -> Optional[Tuple[str, ...]]:
    resolved = _resolve_vendor_function(f"{callee}.__init__", allow_methods=True)
    if resolved is None:
        return None
    _tree, init_fn, _spec_origin, _module_name, fn_name = resolved
    if not fn_name.endswith(".__init__"):
        return None
    params = _positional_param_names(init_fn)
    if not params or params[0] != "self":
        return None
    return tuple(params[1:])


@functools.lru_cache(maxsize=None)
def constructor_param_defaults_for_callee(
    callee: str,
) -> Optional[Tuple[Optional[Tuple[object, str]], ...]]:
    resolved = _resolve_vendor_function(f"{callee}.__init__", allow_methods=True)
    if resolved is None:
        return None
    _tree, init_fn, _spec_origin, _module_name, fn_name = resolved
    if not fn_name.endswith(".__init__"):
        return None
    params = _positional_param_names(init_fn)
    if not params or params[0] != "self":
        return None
    constructor_params = params[1:]
    defaults: list[Optional[Tuple[object, str]]] = [None for _ in constructor_params]
    ast_defaults = list(init_fn.args.defaults)
    if not ast_defaults:
        return tuple(defaults)
    if len(ast_defaults) > len(constructor_params):
        return None
    start = len(constructor_params) - len(ast_defaults)
    for offset, default_node in enumerate(ast_defaults):
        default = _literal_value_kind(default_node)
        if default is None:
            return None
        defaults[start + offset] = default
    return tuple(defaults)


def _body_without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    return [
        stmt
        for stmt in body
        if not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
    ]


def _positional_param_names(fn: ast.FunctionDef) -> list[str]:
    return [arg.arg for arg in (*fn.args.posonlyargs, *fn.args.args)]


def _self_attribute_name(node: ast.AST, self_name: str) -> Optional[str]:
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == self_name
    ):
        return node.attr
    return None


def _self_attribute_return(
    node: ast.AST,
    self_name: str,
) -> Optional[tuple[str, Optional[tuple[str, int]]]]:
    field_name = _self_attribute_name(node, self_name)
    if field_name is not None:
        return field_name, None
    if not isinstance(node, ast.Subscript):
        return None
    field_name = _self_attribute_name(node.value, self_name)
    if field_name is None:
        return None
    index = _constant_int_index(node.slice)
    if index is None:
        return None
    return field_name, ("index", index)


def _constant_int_index(node: ast.AST) -> Optional[int]:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return int(node.value)
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and type(node.operand.value) is int
    ):
        return -int(node.operand.value)
    return None


def _is_super_init_expr(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
        return False
    call = stmt.value
    if call.keywords:
        return False
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "__init__"
        and isinstance(func.value, ast.Call)
        and isinstance(func.value.func, ast.Name)
        and func.value.func.id == "super"
        and not func.value.args
        and not func.value.keywords
    )


@dataclass(frozen=True)
class BranchLiteralUniverse:
    """Census family non-return:If (75k bodies) and the multi-return
    residual of return-constant: a body whose every Return returns a
    literal swears the DISJUNCTION — output ∈ {walked literals} — with
    no condition evaluation at all. Soundness is control-flow-free: any
    execution that returns at all returns the value of SOME ast.Return
    node (loops, try, with cannot alter a return value in flight), so
    the disjunction over all of them holds for every input. Falling off
    the end (implicit None) is excluded structurally by the terminality
    check: the body's tail must be Return, Raise, or an If whose both
    arms are terminal, recursively — the if/elif/else chain shape.

    All literals must share ONE kind: a disjunction mixing str and int
    equalities over the same subject is the #2103 cross-sort hazard, so
    mixed-kind bodies refuse by name. The vendor's own vectors gate the
    walk (a vendor-sworn expected value outside the walked set means the
    walk misread the body)."""

    values: tuple  # python literal values, deduped, source order
    value_kind: str  # 'str' | 'int' | 'bool' | 'bytes'
    module: str
    qualname: str
    source_path: str
    lineno: int
    vendor_vectors_checked: int = 0
    vendor_vector_source: Optional[str] = None


def _collection_leaf_value(node):
    """The python value of a literal leaf (int/str/bool/None, unary-neg
    int), or the _MISSING sentinel. Mirrors layer2's _literal_leaf_value
    admission EXACTLY — the canonical strings below must byte-match the
    consumer side or the universe equality never unifies with consumer
    terms (a vacuous universe)."""
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, (int, str, bool)) or v is None:
            return v
        return _MISSING
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, int)
        and not isinstance(node.operand.value, bool)
    ):
        return -node.operand.value
    return _MISSING


def collection_literal_canonical(node) -> Optional[str]:
    """THE canonical content string for a collection literal of literal
    leaves — the single source of truth shared by the consumer-side term
    translator (layer2) and the vendor-side constant walk; a local mirror
    on either side is the latent-hole lesson all over again.

    Soundness rule (same as the consumer side has always carried):
    structurally-different literals MUST produce DISTINCT strings (so a
    contradiction is UNSAT) and identical literals the SAME string (so a
    match is SAT). repr-based leaves make 1 and True distinct even though
    python compares them equal — that mismatch can only FALSE-REFUSE a
    claim python would call true, never discharge a wrong one.

    None for any content that is not a literal leaf (computed values,
    unpacking, nesting): content identity cannot be established at lift
    time."""
    if isinstance(node, ast.Dict):
        items = []
        for k, v in zip(node.keys, node.values):
            if k is None:  # dict unpacking (**expr)
                return None
            k_val = _collection_leaf_value(k)
            v_val = _collection_leaf_value(v)
            if k_val is _MISSING or v_val is _MISSING:
                return None
            items.append((k_val, v_val))
        items.sort(key=lambda kv: repr(kv[0]))
        return "dict:" + repr(dict(items))
    if isinstance(node, ast.Set):
        elts = []
        for el in node.elts:
            val = _collection_leaf_value(el)
            if val is _MISSING:
                return None
            elts.append(val)
        # dedupe matching python set semantics, then sort by repr —
        # repr(set(...)) is hash-randomized in CPython and must never be
        # used (breaks content-addressing determinism).
        unique = list({repr(e): e for e in elts}.values())
        unique.sort(key=repr)
        return "set:[" + ", ".join(repr(e) for e in unique) + "]"
    if isinstance(node, (ast.Tuple, ast.List)):
        elts = []
        for el in node.elts:
            val = _collection_leaf_value(el)
            if val is _MISSING:
                return None
            elts.append(val)
        tag = "tuple" if isinstance(node, ast.Tuple) else "list"
        # order-preserving: (1, 2) != (2, 1); tuple != list of same elts
        return f"{tag}:[" + ", ".join(repr(e) for e in elts) + "]"
    return None


def _ifexp_literal_leaves(node):
    """All literal leaves of a (possibly nested) conditional expression,
    or None when any leaf is computed. ``"a" if c else "b"`` is the
    statement-level branch shape in expression form: the value is ONE OF
    the leaves whichever way the condition goes, so the condition —
    walrus included — never needs reading (a rebinding in the condition
    has nothing downstream of itself to poison)."""
    if isinstance(node, ast.IfExp):
        body = _ifexp_literal_leaves(node.body)
        orelse = _ifexp_literal_leaves(node.orelse)
        if body is None or orelse is None:
            return None
        return body + orelse
    vk = _literal_value_kind(node)
    return [vk] if vk is not None else None


def _is_terminal_block(stmts: list) -> bool:
    """A statement list cannot fall off the end iff its last statement is
    a Return, a Raise, or an If whose both arms are themselves terminal
    (the if/elif/else chain). While/For/Try/With tails stay non-terminal
    here — conservative, named in the family residual."""
    if not stmts:
        return False
    last = stmts[-1]
    if isinstance(last, (ast.Return, ast.Raise)):
        return True
    if isinstance(last, ast.If):
        return _is_terminal_block(last.body) and _is_terminal_block(
            last.orelse
        )
    return False


@functools.lru_cache(maxsize=None)
def branch_literal_universe_for_callee(
    callee: str,
) -> Tuple[Optional[BranchLiteralUniverse], Optional[TranslateWalkRefusal]]:
    resolved = _resolve_vendor_function(callee)
    if resolved is None:
        return None, None
    tree, fn, spec_origin, module_name, fn_name = resolved

    def refuse(reason):
        return None, TranslateWalkRefusal(callee=callee, reason=reason)

    body = [
        stmt
        for stmt in fn.body
        if not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
    ]
    rest, tainted = _strip_guard_prefix(body)
    returns = [
        n
        for stmt in body
        for n in ast.walk(stmt)
        if isinstance(n, ast.Return)
    ]
    # the family is the MULTI-VALUE shape: several returns, or one return
    # of a conditional expression (several leaves). A single literal
    # belongs to the constant family (no double emission), and generator
    # bodies return a generator object, never a branch value.
    if not returns or not _is_terminal_block(rest):
        return None, None
    if any(
        isinstance(n, (ast.Yield, ast.YieldFrom))
        for stmt in body
        for n in ast.walk(stmt)
    ):
        return None, None
    leaf_lists = []
    for node in returns:
        if node.value is None:
            if len(returns) < 2:
                return None, None
            return refuse(
                "bare `return` among literal returns: None would mix "
                "kinds in one disjunction (cross-sort)"
            )
        leaves = _ifexp_literal_leaves(node.value)
        if leaves is None:
            return None, None  # a computed branch: not this family
        leaf_lists.append(leaves)
    if sum(len(ls) for ls in leaf_lists) < 2:
        return None, None  # single literal: the constant family's shape
    if tainted:
        return refuse(
            "guard-strip: a stripped guard test rebinds via walrus "
            "(NamedExpr); the remaining body no longer sees the "
            "callsite's arguments"
        )
    values, kinds = [], set()
    for value, kind in (vk for ls in leaf_lists for vk in ls):
        kinds.add(kind)
        if value not in values:
            values.append(value)
    if len(kinds) != 1:
        return refuse(
            f"mixed literal kinds {sorted(kinds)} in one disjunction "
            "over one subject is the cross-sort hazard; refuse"
        )
    kind = kinds.pop()
    if kind == "none":
        return None, None  # all-None multi-return: constant-None territory

    # ∀⊨sample: every vendor-sworn expected value must be IN the set.
    vectors, vector_source = _vendor_vectors(module_name, fn_name)
    checked = 0
    for vector in vectors:
        if kind in ("str", "bytes") and isinstance(vector, str):
            want = (
                [v.decode("ascii") for v in values]
                if kind == "bytes"
                else values
            )
            checked += 1
            if vector not in want:
                return refuse(
                    f"sample-gate: vendor vector {vector!r} from "
                    f"{vector_source} is outside the walked branch set "
                    f"{values!r}; the walk misread the body"
                )

    return (
        BranchLiteralUniverse(
            values=tuple(values),
            value_kind=kind,
            module=module_name,
            qualname=f"{module_name}.{fn_name}",
            source_path=spec_origin,
            lineno=fn.lineno,
            vendor_vectors_checked=checked,
            vendor_vector_source=vector_source,
        ),
        None,
    )


@dataclass(frozen=True)
class DelegationUniverse:
    """Census families pure-delegation (57k bodies) and the param arm of
    return-name (146k bodies): a body that is exactly one ``return``
    forwarding to a parameter or to a same-module function call swears an
    EQUALITY between call terms — the composition-router edge, in EUF,
    with zero new atoms.

    - ``identity``:        ``return <param>`` — callee(args)[i-th param]
      IS the output: eq(subject, call_args[param_index]).
    - ``delegation``:      ``return g(<params/literals>)`` —
      eq(subject, callresult_<module.g>(mapped args)); the consumer's own
      claims about g key to the SAME term, so a contradiction THROUGH the
      delegation edge conjoins and fires UNSAT.
    - ``delegation-splat``: ``def f(*a): return g(*a)`` (optionally
      ``**k`` mirrored) — the delegate receives exactly f's args:
      eq(subject, callresult_<module.g>(call_args)).
    - ``delegation-receiver-method``: ``class C: def f(self, x): return
      self.g(x)`` — eq(callval_f(recv, x), callval_g(recv, x)), then queue
      a recursive source walk over ``C.g`` with the same receiver context.
      This is the Java P5c/Voltron rule in Python shape: receiver-dependent
      values stay receiver-keyed, but the owning class makes the target body
      concrete enough to read.
    - ``delegation-method``: ``return <param|literal>.method(...)``
      (census return-method-call, 113k bodies) —
      eq(subject, callval_<method>(recv, args...)). No body backs a
      method delegate, so the emitter additionally requires every
      mapped term to be a CONCRETE literal at the callsite: the
      equality only ever bridges ground instantiations.

    ∀⊨sample: there is nothing to sample — the body IS the claim (a
    single return of a single forwarding expression; the misread surface
    is the multiple-return case, which the totality check excludes
    structurally). vendor_vectors_checked stays 0 with a None source,
    said plainly: the license is syntactic.

    The walk rests on the same purity tradeoff every call-term already
    carries (same callee + same args → same value), tightened where we
    have evidence: a delegate whose body transitively reaches a
    nondeterminism source REFUSES by name instead of equating."""

    kind: str  # "identity" | "delegation" | "delegation-splat"
    module: str
    qualname: str
    source_path: str
    lineno: int
    param_index: int = 0
    delegate: str = ""  # qualified module.g for the delegation kinds
    args: tuple = ()  # delegation: ("param", idx) | ("lit", value, kind)
    # chain-expr: a nested spec tree ("binop", op, left, right) over the
    # same leaf specs — the returned arithmetic expression as structure
    expr_spec: tuple = ()
    vendor_vectors_checked: int = 0
    vendor_vector_source: Optional[str] = None
    source_memento: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class ConditionalChainBranch:
    conditions: tuple
    expr_spec: tuple


@dataclass(frozen=True)
class ConditionalChainUniverse:
    """A straight-line SSA body with pure assignment branches before return.

    The emitted ProofIR is implication-guarded equality, one branch at a
    time: ``guard => subject == expr``. The guard and expression specs reuse
    the same term constructors as chain-expr/delegation.
    """

    kind: str
    module: str
    qualname: str
    source_path: str
    lineno: int
    branches: tuple
    source_memento: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class BranchSelectedReturnUniverse:
    """A receiver field selects a return-param branch.

    Shape:
      class C:
          def __init__(self, mode):
              self.mode = mode

          def f(self, value):
              if self.mode == "none":
                  return value
              raise TypeError(...)

    The method result equals the returned call argument when the constructor
    field has the selected literal value. The emitter composes this with the
    constructor-field universe for the receiver at the concrete callsite.
    """

    field_name: str
    field_value: object
    field_value_kind: str
    return_param_index: int
    return_param_name: str
    module: str
    qualname: str
    source_path: str
    lineno: int
    source_memento: Optional[dict[str, Any]] = None
    return_adapter_callee: Optional[str] = None


@dataclass(frozen=True)
class BranchSelectedRaiseUniverse:
    """A parameter guard selects a value branch; the complement raises.

    Shape:
      def __getattr__(name):
          if name == "__version__":
              return version()

          raise AttributeError(name)

    At concrete callsites whose argument is not the guarded literal, the
    source warrants the raised-exception relation for the trailing raise.
    """

    param_name: str
    param_index: int
    excluded_value: object
    excluded_value_kind: str
    exception_name: str
    module: str
    qualname: str
    source_path: str
    lineno: int
    source_memento: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class _ReceiverMethodDelegate:
    delegate: str
    args: tuple


@dataclass(frozen=True)
class BytesIdentityUniverse:
    """`want_bytes`-style adapter for concrete bytes callsites.

    Shape:
      if isinstance(s, str):
          s = s.encode(...)
      return s

    When the callsite argument is already a python:bytes literal, the str
    branch is inactive and the return swears an equality between the call
    result and that exact argument. The str-encoding branch is deliberately
    not modeled here.
    """

    param_index: int
    param_name: str
    module: str
    qualname: str
    source_path: str
    lineno: int
    source_memento: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class ListAdapterUniverse:
    """`_make_keys_list`-style adapter for concrete str/bytes callsites.

    Shape:
      if isinstance(secret_key, (str, bytes)):
          return [want_bytes(secret_key)]

      return [want_bytes(s) for s in secret_key]

    For a concrete str/bytes callsite, the iterable branch is inactive and
    the result is a one-element list whose element is the adapter call result.
    The adapter itself is recursively accounted for by BytesIdentityUniverse
    when the argument is concrete bytes.
    """

    param_index: int
    param_name: str
    adapter_callee: str
    module: str
    qualname: str
    source_path: str
    lineno: int
    source_memento: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class RaiseLocusUniverse:
    """Census family non-return:Raise (30k bodies): a body with ZERO
    Return/Yield nodes whose tail is terminal (with zero returns, every
    terminal leaf IS a Raise) never produces a value — every path
    raises. A sworn equality about callee(args) therefore carries the
    canonical contradiction: you swore a return value from a call the
    vendor's own source says always raises. The guard family's
    complement, total instead of clause-wise.

    No binding hazards apply: no value depends on the body's bindings
    because there is no value. Prefix effects and even non-termination
    only strengthen the claim (still no value). Context managers that
    could SUPPRESS the raise force the tail through a With/Try last
    statement, which the terminality check excludes."""

    module: str
    qualname: str
    source_path: str
    lineno: int
    source_memento: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class ExceptionHandlerRaiseUniverse:
    """A try/except path account: when the call is observed to raise, a
    handler that catches the underlying exception and re-raises a concrete
    exception type contributes the same raised-exception relation used by
    pytest.raises, without claiming the whole function never returns."""

    exception_name: str
    module: str
    qualname: str
    source_path: str
    lineno: int
    source_memento: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class ExceptionBoolReturnUniverse:
    """A validator wrapper over an exception-bearing inner call.

    Shape:
      try:
          self.inner(...)
          return True
      except SomeException:
          return False

    The universe does not claim the inner call always raises or always returns.
    It contributes the value relation between the wrapper's False result and
    the existing raised-exception call surface for the inner call.
    """

    exception_name: str
    success_value: bool
    exception_value: bool
    delegate: str
    args: tuple
    module: str
    qualname: str
    source_path: str
    lineno: int
    source_memento: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class SeparatorGuardRaiseUniverse:
    """A receiver field membership guard that raises a concrete exception.

    Shape:
      signed_value = want_bytes(signed_value)
      if self.sep not in signed_value:
          raise BadSignature(...)

    The universe contributes only the guarded raise path. Other paths in the
    method remain source-accounted support until separate universes lift them.
    """

    exception_name: str
    field_name: str
    param_name: str
    param_index: int
    adapter_callee: Optional[str]
    module: str
    qualname: str
    source_path: str
    lineno: int
    source_memento: Optional[dict[str, Any]] = None


@functools.lru_cache(maxsize=None)
def raise_locus_universe_for_callee(
    callee: str,
) -> Tuple[Optional[RaiseLocusUniverse], Optional[TranslateWalkRefusal]]:
    resolved = _resolve_vendor_function(callee, allow_methods=True)
    if resolved is None:
        return None, None
    tree, fn, spec_origin, module_name, fn_name = resolved
    source_memento = _source_memento_for_resolved_function(fn, spec_origin)
    body = [
        stmt
        for stmt in fn.body
        if not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
    ]
    if not body:
        return None, None
    if any(
        isinstance(n, (ast.Return, ast.Yield, ast.YieldFrom))
        for stmt in body
        for n in ast.walk(stmt)
    ):
        return None, None  # a value (or a generator) can exist
    if not _is_terminal_block(body):
        return None, None  # a fall-off path returns None
    return (
        RaiseLocusUniverse(
            module=module_name,
            qualname=f"{module_name}.{fn_name}",
            source_path=spec_origin,
            lineno=fn.lineno,
            source_memento=source_memento,
        ),
        None,
    )


@functools.lru_cache(maxsize=None)
def exception_handler_raise_universe_for_callee(
    callee: str,
) -> Tuple[Optional[ExceptionHandlerRaiseUniverse], Optional[TranslateWalkRefusal]]:
    resolved = _resolve_vendor_function(callee, allow_methods=True)
    if resolved is None:
        return None, None
    _tree, fn, spec_origin, module_name, fn_name = resolved
    source_memento = _source_memento_for_resolved_function(fn, spec_origin)
    body = [
        stmt
        for stmt in fn.body
        if not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
    ]
    candidates: list[tuple[ast.Try, ast.ExceptHandler, ast.Raise, str]] = []
    for stmt in body:
        if not isinstance(stmt, ast.Try):
            continue
        for handler in stmt.handlers:
            raised = _single_handler_raise(handler)
            if raised is None:
                continue
            raise_stmt, exception_name = raised
            candidates.append((stmt, handler, raise_stmt, exception_name))
    if not candidates:
        return None, None
    exception_names = {exception_name for *_prefix, exception_name in candidates}
    if len(exception_names) != 1:
        return (
            None,
            TranslateWalkRefusal(
                callee,
                "exception-handler raise path has multiple raised exception "
                f"types: {sorted(exception_names)!r}",
            ),
        )
    try_stmt, _handler, _raise_stmt, exception_name = candidates[0]
    if source_memento is not None:
        source_memento = dict(source_memento)
        source_memento["source_function_name"] = fn_name
        source_memento["exception_handler_raise_type"] = exception_name
        source_memento["exception_handler_try_line"] = try_stmt.lineno
    return (
        ExceptionHandlerRaiseUniverse(
            exception_name=exception_name,
            module=module_name,
            qualname=f"{module_name}.{fn_name}",
            source_path=spec_origin,
            lineno=fn.lineno,
            source_memento=source_memento,
        ),
        None,
    )


@functools.lru_cache(maxsize=None)
def exception_bool_return_universe_for_callee(
    callee: str,
) -> Tuple[Optional[ExceptionBoolReturnUniverse], Optional[TranslateWalkRefusal]]:
    resolved = _resolve_vendor_function(callee, allow_methods=True)
    if resolved is None:
        return None, None
    _tree, fn, spec_origin, module_name, fn_name = resolved
    if "." not in fn_name:
        return None, None
    class_qualname, _method_name = fn_name.rsplit(".", 1)
    source_memento = _source_memento_for_resolved_function(fn, spec_origin)
    body = [
        stmt
        for stmt in fn.body
        if not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
    ]
    if len(body) != 1 or not isinstance(body[0], ast.Try):
        return None, None
    try_stmt = body[0]
    if try_stmt.orelse or try_stmt.finalbody or len(try_stmt.handlers) != 1:
        return None, None
    if len(try_stmt.body) != 2:
        return None, None
    call_stmt, success_stmt = try_stmt.body
    if not isinstance(call_stmt, ast.Expr) or not isinstance(call_stmt.value, ast.Call):
        return None, None
    delegate_call = call_stmt.value
    if not (
        isinstance(delegate_call.func, ast.Attribute)
        and isinstance(delegate_call.func.value, ast.Name)
        and fn.args.args
        and delegate_call.func.value.id == fn.args.args[0].arg
    ):
        return None, None
    success_value = _return_bool(success_stmt)
    if success_value is None:
        return None, None
    handler = try_stmt.handlers[0]
    exception_name = _exception_handler_type_name(handler)
    if exception_name is None:
        return None, None
    if len(handler.body) != 1:
        return None, None
    exception_value = _return_bool(handler.body[0])
    if exception_value is None or exception_value == success_value:
        return None, None

    params = [arg.arg for arg in fn.args.args]
    specs = []
    for arg in delegate_call.args:
        spec = _resolve_spec(arg, params, {})
        if spec is None:
            return (
                None,
                TranslateWalkRefusal(
                    callee,
                    "exception-bool-return inner call argument is neither a "
                    "parameter nor a literal",
                ),
            )
        specs.append(spec)
    for keyword in delegate_call.keywords:
        if keyword.arg is None:
            return (
                None,
                TranslateWalkRefusal(
                    callee,
                    "exception-bool-return inner call uses **kwargs forwarding; "
                    "the keyword surface is runtime-selected",
                ),
            )
        spec = _resolve_spec(keyword.value, params, {})
        if spec is None:
            return (
                None,
                TranslateWalkRefusal(
                    callee,
                    f"exception-bool-return keyword {keyword.arg!r} is not "
                    "a parameter or literal",
                ),
            )
        specs.append(("kw", keyword.arg, spec))

    delegate = f"{module_name}.{class_qualname}.{delegate_call.func.attr}"
    if source_memento is not None:
        source_memento = dict(source_memento)
        source_memento["source_function_name"] = fn_name
        source_memento["exception_bool_return_exception_type"] = exception_name
        source_memento["exception_bool_return_try_line"] = try_stmt.lineno
        source_memento["exception_bool_return_delegate"] = delegate
        source_memento["exception_bool_return_success_value"] = success_value
        source_memento["exception_bool_return_exception_value"] = exception_value
    return (
        ExceptionBoolReturnUniverse(
            exception_name=exception_name,
            success_value=success_value,
            exception_value=exception_value,
            delegate=delegate,
            args=tuple(specs),
            module=module_name,
            qualname=f"{module_name}.{fn_name}",
            source_path=spec_origin,
            lineno=fn.lineno,
            source_memento=source_memento,
        ),
        None,
    )


@functools.lru_cache(maxsize=None)
def separator_guard_raise_universe_for_callee(
    callee: str,
) -> Tuple[Optional[SeparatorGuardRaiseUniverse], Optional[TranslateWalkRefusal]]:
    resolved = _resolve_vendor_function(callee, allow_methods=True)
    if resolved is None:
        return None, None
    tree, fn, spec_origin, module_name, fn_name = resolved
    params = _positional_param_names(fn)
    if len(params) < 2 or params[0] not in {"self", "cls"}:
        return None, None
    source_memento = _source_memento_for_resolved_function(fn, spec_origin)
    body = _body_without_docstring(fn.body)
    if not body:
        return None, None
    call_aliases = _module_call_aliases(tree, module_name)
    adapter_callee: Optional[str] = None
    adapter_line: Optional[int] = None
    guard_index = 0
    prelude = _param_adapter_rebind(body[0], params, call_aliases)
    if prelude is not None:
        param_name, adapter_callee = prelude
        adapter_line = body[0].lineno
        guard_index = 1
    if guard_index >= len(body) or not isinstance(body[guard_index], ast.If):
        return None, None
    guard = body[guard_index]
    guard_shape = _separator_not_in_guard(
        guard,
        receiver_name=params[0],
        params=params,
    )
    if guard_shape is None:
        return None, None
    field_name, param_name = guard_shape
    if adapter_callee is not None and prelude is not None and prelude[0] != param_name:
        return None, None
    if len(guard.body) != 1 or not isinstance(guard.body[0], ast.Raise):
        return None, None
    exception_name = _raised_exception_name(guard.body[0])
    if exception_name is None:
        return None, None
    if source_memento is not None:
        source_memento = dict(source_memento)
        source_memento["source_function_name"] = fn_name
        source_memento["separator_guard_exception_type"] = exception_name
        source_memento["separator_guard_field_name"] = field_name
        source_memento["separator_guard_param_name"] = param_name
        source_memento["separator_guard_line"] = guard.lineno
        source_memento["separator_guard_raise_line"] = guard.body[0].lineno
        if adapter_callee is not None:
            source_memento["separator_guard_adapter_callee"] = adapter_callee
        if adapter_line is not None:
            source_memento["separator_guard_adapter_line"] = adapter_line
    return (
        SeparatorGuardRaiseUniverse(
            exception_name=exception_name,
            field_name=field_name,
            param_name=param_name,
            param_index=params.index(param_name),
            adapter_callee=adapter_callee,
            module=module_name,
            qualname=f"{module_name}.{fn_name}",
            source_path=spec_origin,
            lineno=guard.lineno,
            source_memento=source_memento,
        ),
        None,
    )


def _param_adapter_rebind(
    stmt: ast.stmt,
    params: list[str],
    call_aliases: dict[str, str],
) -> Optional[tuple[str, str]]:
    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
        return None
    target = stmt.targets[0]
    value = stmt.value
    if not (
        isinstance(target, ast.Name)
        and target.id in params[1:]
        and isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and not value.keywords
        and len(value.args) == 1
        and isinstance(value.args[0], ast.Name)
        and value.args[0].id == target.id
    ):
        return None
    callee = call_aliases.get(value.func.id)
    if callee is None:
        return None
    universe, refusal = bytes_identity_universe_for_callee(callee)
    if refusal is not None or universe is None:
        return None
    return target.id, callee


def _separator_not_in_guard(
    stmt: ast.If,
    *,
    receiver_name: str,
    params: list[str],
) -> Optional[tuple[str, str]]:
    test = stmt.test
    if (
        not isinstance(test, ast.Compare)
        or len(test.ops) != 1
        or not isinstance(test.ops[0], ast.NotIn)
        or len(test.comparators) != 1
    ):
        return None
    field_name = _self_attribute_name(test.left, receiver_name)
    comparator = test.comparators[0]
    if (
        field_name is None
        or not isinstance(comparator, ast.Name)
        or comparator.id not in params[1:]
    ):
        return None
    return field_name, comparator.id


def _return_bool(stmt: ast.stmt) -> Optional[bool]:
    if (
        isinstance(stmt, ast.Return)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, bool)
    ):
        return bool(stmt.value.value)
    return None


def _exception_handler_type_name(handler: ast.ExceptHandler) -> Optional[str]:
    typ = handler.type
    if isinstance(typ, ast.Name):
        return typ.id
    if isinstance(typ, ast.Attribute):
        return typ.attr
    return None


def _single_handler_raise(
    handler: ast.ExceptHandler,
) -> Optional[tuple[ast.Raise, str]]:
    body = [
        stmt
        for stmt in handler.body
        if not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
    ]
    if len(body) != 1 or not isinstance(body[0], ast.Raise):
        return None
    exception_name = _raised_exception_name(body[0])
    if exception_name is None:
        return None
    return body[0], exception_name


def _raised_exception_name(stmt: ast.Raise) -> Optional[str]:
    exc = stmt.exc
    if exc is None:
        return None
    if isinstance(exc, ast.Call):
        exc = exc.func
    if isinstance(exc, ast.Name):
        return exc.id
    if isinstance(exc, ast.Attribute):
        return exc.attr
    return None


def _resolve_spec(node, params, env):
    """A forwarding spec for ``node``: chain names first (shadowing),
    then params, then ascii literals. None for anything computed."""
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        if node.id in params:
            return ("param", params.index(node.id))
        return None
    vk = _literal_value_kind(node)
    if vk is not None:
        return ("lit", vk[0], vk[1])
    return None


def _resolve_delegate_value_spec(node, params, env):
    spec = _resolve_spec(node, params, env)
    if spec is not None:
        return spec
    canonical = collection_literal_canonical(node)
    if canonical is not None:
        return ("lit", canonical, "collection")
    return None


def _resolve_delegate_value_or_receiver_call_spec(
    node,
    params,
    env,
    *,
    tree: Optional[ast.Module],
    module_name: str,
    fn_name: str,
):
    spec = _resolve_delegate_value_spec(node, params, env)
    if spec is not None:
        return spec, None
    field_spec = _receiver_field_spec(node, params)
    if field_spec is not None:
        return field_spec, None
    if tree is not None:
        static_attr_spec = _resolve_static_attribute_value_spec(node, tree)
        if static_attr_spec is not None:
            return static_attr_spec, None
    if tree is None or not isinstance(node, ast.Call):
        return None, None
    method_spec, method_refusal = _method_call_value_spec(
        node,
        params=params,
        env=env,
        tree=tree,
        module_name=module_name,
        fn_name=fn_name,
    )
    if method_refusal is not None:
        return None, method_refusal
    if method_spec is not None:
        return method_spec, None
    call_spec, call_refusal = _function_call_value_spec(
        node,
        params=params,
        env=env,
        tree=tree,
        module_name=module_name,
        fn_name=fn_name,
    )
    if call_refusal is not None:
        return None, call_refusal
    if call_spec is not None:
        return call_spec, None
    dynamic_receiver_refusal = _dynamic_receiver_dispatch_reason(node, params)
    if dynamic_receiver_refusal is not None:
        return None, dynamic_receiver_refusal
    receiver_delegate, receiver_refusal = _receiver_method_delegate_for_call(
        node,
        tree=tree,
        module_name=module_name,
        fn_name=fn_name,
        params=params,
        env=env,
    )
    if receiver_refusal is not None:
        return None, receiver_refusal
    if receiver_delegate is None:
        return None, None
    return (
        (
            "receiver-method-call",
            receiver_delegate.delegate,
            receiver_delegate.args,
        ),
        None,
    )


def _function_call_value_spec(
    value: ast.Call,
    *,
    params: list[str],
    env: dict,
    tree: ast.Module,
    module_name: str,
    fn_name: str,
) -> Tuple[Optional[tuple], Optional[str]]:
    if not isinstance(value.func, ast.Name):
        return None, None
    if any(isinstance(arg, ast.Starred) for arg in value.args):
        return None, (
            "chain function-call assignment uses *args forwarding; the "
            "argument surface is runtime-selected"
        )
    call_aliases = _module_call_aliases(tree, module_name)
    delegate = call_aliases.get(value.func.id)
    if delegate is None:
        if not _stable_module_binding(tree, value.func.id):
            return None, None
        delegate = f"{module_name}.{value.func.id}"
    if delegate == f"{module_name}.{fn_name}":
        return None, "self-delegation: the equality would be vacuous"
    if not _stable_module_binding(tree, value.func.id):
        return None, (
            f"chain function-call assignment target {value.func.id!r} is not "
            "a stable binding in the vendor module"
        )
    specs, specs_refusal = _delegate_call_specs_source_order(
        value,
        params,
        env,
        mirrored_kwargs=None,
        tree=tree,
        module_name=module_name,
        fn_name=fn_name,
        context="chain function-call assignment",
    )
    if specs_refusal is not None:
        return None, specs_refusal
    return ("function-call", delegate, tuple(specs or ())), None


def _constructor_call_value_spec(
    value: ast.Call,
    *,
    params: list[str],
    env: dict,
    tree: ast.Module,
    module_name: str,
    fn_name: str,
) -> Tuple[Optional[tuple], Optional[str]]:
    if not isinstance(value.func, ast.Name):
        return None, None
    class_names = {
        stmt.name for stmt in tree.body if isinstance(stmt, ast.ClassDef)
    }
    if value.func.id not in class_names:
        return None, None
    if any(isinstance(arg, ast.Starred) for arg in value.args):
        return None, (
            "constructor return uses *args forwarding; the constructed "
            "argument surface is runtime-selected"
        )
    if value.keywords:
        return None, (
            "constructor return uses keyword arguments; the constructor "
            "argument surface is not normalized yet"
        )
    specs = []
    for arg in value.args:
        spec = _resolve_expr_spec(
            arg,
            params,
            env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        if spec == "REFUSE-OP":
            return None, (
                "constructor return argument uses an unsupported operator; "
                "the consumer side cannot build the term either"
            )
        if spec is None:
            return None, (
                "constructor return argument is neither a parameter, literal, "
                "receiver field, nor lifted expression"
            )
        specs.append(spec)
    return ("ctor-call", f"call:{module_name}.{value.func.id}", tuple(specs)), None


def _stable_module_binding(tree: ast.Module, name: str) -> bool:
    events = [event for event in _binding_events(tree) if event.name == name]
    return len(events) == 1 and name not in _global_declarations(tree)


def _method_call_value_spec(
    node: ast.Call,
    *,
    params: list[str],
    env: dict,
    tree: ast.Module,
    module_name: str,
    fn_name: str,
) -> Tuple[Optional[tuple], Optional[str]]:
    if not isinstance(node.func, ast.Attribute):
        return None, None
    if (
        params
        and params[0] in {"self", "cls"}
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == params[0]
    ):
        return None, None
    if node.keywords:
        return None, (
            "chain method-call uses keyword arguments; the method call "
            "surface is not normalized yet"
        )
    method = node.func.attr
    if method in _NONDET_ATTRS:
        return None, (
            f"method call .{method} is a nondeterminism marker; its call "
            "terms must not unify"
        )
    receiver, receiver_refusal = _resolve_delegate_value_or_receiver_call_spec(
        node.func.value,
        params,
        env,
        tree=tree,
        module_name=module_name,
        fn_name=fn_name,
    )
    if receiver_refusal is not None:
        return None, receiver_refusal
    if receiver is None:
        return None, None
    specs = [receiver]
    for arg in node.args:
        spec, refusal = _resolve_delegate_value_or_receiver_call_spec(
            arg,
            params,
            env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        if refusal is not None:
            return None, refusal
        if spec is None:
            return None, (
                "chain method-call argument is neither a parameter, literal, "
                "collection literal, chain name, nor nested call"
            )
        specs.append(spec)
    return ("method-call", method, tuple(specs)), None


def _resolve_static_attribute_value_spec(node: ast.AST, tree: ast.Module):
    path = _attribute_path(node)
    if path is None or len(path) < 2:
        return None
    root, *attrs = path
    module = _stdlib_module_aliases(tree).get(root)
    if module is None:
        return None
    return ("lit", f"attr:{'.'.join([module, *attrs])}", "collection")


def _receiver_context_spec(spec):
    """Normalize a spec from a method's full parameter space into the
    callsite's explicit-argument space. ``self`` is supplied by the receiver
    term, so param 0 maps to a receiver placeholder and param N maps to
    call_args[N-1]."""
    if spec is None:
        return None
    if spec[0] == "binop":
        left = _receiver_context_spec(spec[2])
        right = _receiver_context_spec(spec[3])
        if left is None or right is None:
            return None
        return ("binop", spec[1], left, right)
    if spec[0] == "function-call":
        args = tuple(_receiver_context_spec(arg) for arg in spec[2])
        if any(arg is None for arg in args):
            return None
        return ("function-call", spec[1], args)
    if spec[0] == "ctor-call":
        args = tuple(_receiver_context_spec(arg) for arg in spec[2])
        if any(arg is None for arg in args):
            return None
        return ("ctor-call", spec[1], args)
    if spec[0] == "method-call":
        args = tuple(_receiver_context_spec(arg) for arg in spec[2])
        if any(arg is None for arg in args):
            return None
        return ("method-call", spec[1], args)
    if spec[0] == "subscript":
        base = _receiver_context_spec(spec[1])
        index = _receiver_context_spec(spec[2])
        if base is None or index is None:
            return None
        return ("subscript", base, index)
    if spec[0] == "receiver-method-call":
        args = tuple(_receiver_context_spec(arg) for arg in spec[2])
        if any(arg is None for arg in args):
            return None
        return ("receiver-method-call", spec[1], args)
    if spec[0] == "kw":
        value = _receiver_context_spec(spec[2])
        if value is None:
            return None
        return ("kw", spec[1], value)
    if spec[0] == "dict":
        items = []
        for key, value_spec in spec[1]:
            value = _receiver_context_spec(value_spec)
            if value is None:
                return None
            items.append((key, value))
        return ("dict", tuple(items))
    if spec[0] == "receiver-field":
        return spec
    if spec[0] != "param":
        return spec
    index = spec[1]
    if index == 0:
        return ("receiver",)
    return ("param", index - 1)


def _resolve_receiver_context_spec(node, params, env):
    return _receiver_context_spec(_resolve_spec(node, params, env))


def _resolve_receiver_context_arg_spec(
    node,
    *,
    tree: ast.Module,
    module_name: str,
    fn_name: str,
    params: list[str],
    env: dict,
):
    spec = _resolve_receiver_context_spec(node, params, env)
    if spec is not None:
        return spec, None
    if not isinstance(node, ast.Call):
        return None, None
    dynamic_receiver_refusal = _dynamic_receiver_dispatch_reason(node, params)
    if dynamic_receiver_refusal is not None:
        return None, dynamic_receiver_refusal
    receiver_delegate, receiver_refusal = _receiver_method_delegate_for_call(
        node,
        tree=tree,
        module_name=module_name,
        fn_name=fn_name,
        params=params,
        env=env,
    )
    if receiver_refusal is not None:
        return None, receiver_refusal
    if receiver_delegate is None:
        return None, None
    return (
        (
            "receiver-method-call",
            receiver_delegate.delegate,
            receiver_delegate.args,
        ),
        None,
    )


def _resolve_receiver_context_value_spec(
    node,
    *,
    tree: ast.Module,
    module_name: str,
    fn_name: str,
    params: list[str],
    env: dict,
):
    spec, refusal = _resolve_receiver_context_arg_spec(
        node,
        tree=tree,
        module_name=module_name,
        fn_name=fn_name,
        params=params,
        env=env,
    )
    if refusal is not None or spec is not None:
        return spec, refusal
    if not isinstance(node, ast.Dict):
        return None, None

    items = []
    seen_keys = set()
    for key_node, value_node in zip(node.keys, node.values):
        if key_node is None:
            return (
                None,
                "receiver-method delegate keyword dict uses ** unpacking; "
                "the forwarded keys are runtime-selected",
            )
        if not (
            isinstance(key_node, ast.Constant)
            and isinstance(key_node.value, str)
        ):
            return (
                None,
                "receiver-method delegate keyword dict key is not a string "
                "literal; the forwarded argument surface is not stable",
            )
        key = key_node.value
        if key in seen_keys:
            return (
                None,
                "receiver-method delegate keyword dict repeats key "
                f"{key!r}; Python keeps the last value, which this walk "
                "does not normalize yet",
            )
        seen_keys.add(key)
        value_spec, value_refusal = _resolve_receiver_context_value_spec(
            value_node,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
            params=params,
            env=env,
        )
        if value_refusal is not None:
            return None, value_refusal
        if value_spec is None:
            return (
                None,
                "receiver-method delegate keyword dict value for key "
                f"{key!r} is neither a parameter, literal, chain name, "
                "receiver-method call, nor nested literal-key dict",
            )
        items.append((key, value_spec))

    items.sort(key=lambda item: item[0])
    return ("dict", tuple(items)), None


def _receiver_method_delegate_for_call(
    value: ast.Call,
    *,
    tree: ast.Module,
    module_name: str,
    fn_name: str,
    params: list[str],
    env: dict,
) -> Tuple[Optional[_ReceiverMethodDelegate], Optional[str]]:
    if not isinstance(value.func, ast.Attribute):
        return None, None
    class_qualname: Optional[str] = None
    if "." in fn_name:
        class_qualname, current_method = fn_name.rsplit(".", 1)
    else:
        current_method = fn_name
    self_param = params[0] if params else None
    if class_qualname is None or self_param is None:
        return None, None

    delegate_name = value.func.attr
    cls = _find_class_path(tree.body, class_qualname.split("."), module_name)
    if cls is None:
        return (
            None,
            f"receiver-method delegate class {class_qualname} is not a stable "
            "undecorated class in the vendor module",
        )

    if isinstance(value.func.value, ast.Call) and _is_zero_arg_super_call(
        value.func.value
    ):
        inherited, inherited_refusal = _inherited_receiver_method_delegate(
            tree,
            cls,
            module_name,
            delegate_name,
        )
        if inherited_refusal is not None:
            return None, inherited_refusal
        if inherited is None:
            return (
                None,
                f"receiver-method delegate {delegate_name} is not a stable "
                "method on the explicit super() base class",
            )
        delegate_fn, delegate_qualname, delegate_owner_cls = inherited
    elif isinstance(value.func.value, ast.Name) and value.func.value.id == self_param:
        if delegate_name == current_method:
            return None, "self-delegation: the equality would be vacuous"
        delegate_fn = next(
            (
                stmt
                for stmt in cls.body
                if isinstance(stmt, ast.FunctionDef) and stmt.name == delegate_name
            ),
            None,
        )
        delegate_qualname = f"{module_name}.{class_qualname}.{delegate_name}"
        delegate_owner_cls = cls
        if delegate_fn is None:
            if any(
                isinstance(stmt, ast.AsyncFunctionDef)
                and stmt.name == delegate_name
                for stmt in cls.body
            ):
                return (
                    None,
                    f"receiver-method delegate {delegate_name} is async: the call "
                    "term is a coroutine, not the awaited value",
                )
            if _class_member_binding_count(cls, delegate_name) != 0:
                return (
                    None,
                    f"receiver-method delegate {delegate_name} is shadowed in "
                    "the current class body; inherited method lookup would not "
                    "stably denote the base def",
                )
            inherited, inherited_refusal = _inherited_receiver_method_delegate(
                tree,
                cls,
                module_name,
                delegate_name,
            )
            if inherited_refusal is not None:
                return None, inherited_refusal
            if inherited is not None:
                delegate_fn, delegate_qualname, delegate_owner_cls = inherited
            else:
                return (
                    None,
                    f"receiver-method delegate {delegate_name} is not a method in "
                    "the current vendor class or a stable single base class",
                )
    else:
        return None, None
    if delegate_fn is None:
        return (
            None,
            f"receiver-method delegate {delegate_name} is not a method in the "
            "current vendor class",
        )
    if delegate_fn.decorator_list:
        return (
            None,
            f"receiver-method delegate {delegate_name} is decorated; its def "
            "body is not the runtime callable, so determinism evidence cannot "
            "be read from it",
        )
    if _class_member_binding_count(delegate_owner_cls, delegate_name) != 1:
        return (
            None,
            f"receiver-method delegate {delegate_name} is rebound in the class "
            "body; the name does not stably denote the def",
        )
    specs = []
    for arg in value.args:
        spec, refusal = _resolve_receiver_context_arg_spec(
            arg,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
            params=params,
            env=env,
        )
        if refusal is not None:
            return None, refusal
        if spec is None:
            return (
                None,
                "receiver-method delegate argument is neither a parameter, "
                "literal, nor chain name; the forwarded value is not the "
                "callsite's",
            )
        specs.append(spec)
    for keyword in value.keywords:
        if keyword.arg is None:
            return (
                None,
                "receiver-method delegate call uses **kwargs forwarding; "
                "the keyword surface is runtime-selected",
            )
        spec, refusal = _resolve_receiver_context_value_spec(
            keyword.value,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
            params=params,
            env=env,
        )
        if refusal is not None:
            return None, refusal
        if spec is None:
            return (
                None,
                "receiver-method delegate keyword argument is neither a "
                "parameter, literal, chain name, receiver-method call, nor "
                "literal-key dict; the forwarded value is not the callsite's",
            )
        specs.append(("kw", keyword.arg, spec))
    return (
        _ReceiverMethodDelegate(
            delegate=delegate_qualname,
            args=tuple(specs),
        ),
        None,
    )


def _is_zero_arg_super_call(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Name)
        and node.func.id == "super"
        and not node.args
        and not node.keywords
    )


def _inherited_receiver_method_delegate(
    tree: ast.Module,
    cls: ast.ClassDef,
    module_name: str,
    delegate_name: str,
) -> Tuple[Optional[Tuple[ast.FunctionDef, str, ast.ClassDef]], Optional[str]]:
    if not cls.bases:
        return None, None
    if len(cls.bases) != 1:
        return (
            None,
            "receiver-method delegate is inherited through multiple base "
            "classes; MRO-sensitive lookup is not admitted yet",
        )
    base = cls.bases[0]
    resolved = _resolve_receiver_delegate_base_class(tree, base, module_name)
    if resolved is None:
        return None, None
    _base_tree, base_cls, base_module, base_qualname = resolved
    if _class_member_binding_count(base_cls, delegate_name) != 1:
        if any(
            isinstance(stmt, ast.AsyncFunctionDef)
            and stmt.name == delegate_name
            for stmt in base_cls.body
        ):
            return (
                None,
                f"receiver-method delegate {delegate_name} is async on the "
                "base class: the call term is a coroutine, not the awaited value",
            )
        return None, None
    delegate_fn = next(
        (
            stmt
            for stmt in base_cls.body
            if isinstance(stmt, ast.FunctionDef) and stmt.name == delegate_name
        ),
        None,
    )
    if delegate_fn is None:
        return None, None
    if delegate_fn.decorator_list:
        return (
            None,
            f"receiver-method delegate {delegate_name} is decorated on the "
            "base class; its def body is not the runtime callable",
        )
    return (
        delegate_fn,
        f"{base_module}.{base_qualname}.{delegate_name}",
        base_cls,
    ), None


def _resolve_receiver_delegate_base_class(
    tree: ast.Module,
    base: ast.expr,
    module_name: str,
) -> Optional[Tuple[ast.Module, ast.ClassDef, str, str]]:
    while isinstance(base, ast.Subscript):
        base = base.value
    if isinstance(base, ast.Name):
        same_module = _find_class_path(tree.body, [base.id], module_name)
        if same_module is not None:
            return tree, same_module, module_name, base.id
        aliases = _module_call_aliases(tree, module_name)
        alias = aliases.get(base.id)
        if alias is None:
            return None
        resolved = _resolve_vendor_class(alias)
        if resolved is None:
            return None
        base_tree, base_cls, _base_origin, base_module, base_qualname = resolved
        return base_tree, base_cls, base_module, base_qualname
    path = _attribute_path(base)
    if path is None:
        return None
    alias = ".".join(path)
    resolved = _resolve_vendor_class(alias)
    if resolved is None:
        return None
    base_tree, base_cls, _base_origin, base_module, base_qualname = resolved
    return base_tree, base_cls, base_module, base_qualname


def _dynamic_receiver_dispatch_reason(
    value: ast.Call,
    params: list[str],
) -> Optional[str]:
    self_param = params[0] if params else None
    if self_param is None or not isinstance(value.func, ast.Call):
        return None
    dispatch = value.func
    if (
        isinstance(dispatch.func, ast.Name)
        and dispatch.func.id == "getattr"
        and dispatch.args
        and isinstance(dispatch.args[0], ast.Name)
        and dispatch.args[0].id == self_param
    ):
        return (
            "dynamic receiver dispatch via getattr(self, ...); the target "
            "method is runtime-selected and cannot be read as a stable "
            "same-class delegate"
        )
    if (
        isinstance(dispatch.func, ast.Attribute)
        and dispatch.func.attr in {"__getattribute__", "__getattr__"}
        and isinstance(dispatch.func.value, ast.Name)
        and dispatch.func.value.id == self_param
    ):
        return (
            f"dynamic receiver dispatch via self.{dispatch.func.attr}(...); "
            "the target method is runtime-selected and cannot be read as a "
            "stable same-class delegate"
        )
    return None


_BINOP_SPEC_OPS = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.Mod: "%",
}


def _receiver_field_spec(node: ast.AST, params: list[str]) -> Optional[tuple]:
    self_param = params[0] if params else None
    if (
        self_param is not None
        and isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == self_param
    ):
        return ("receiver-field", node.attr)
    return None


def _resolve_expr_spec(
    node,
    params,
    env,
    *,
    tree: Optional[ast.Module] = None,
    module_name: str = "",
    fn_name: str = "",
):
    """A nested spec tree for an arithmetic return expression: leaves are
    forwarding specs, interior nodes are ("binop", op, left, right) with
    op drawn from the SAME operator map the consumer-side term translator
    uses — both sides build the identical ctor or neither does. None for
    operators outside the map or computed leaves; the string "REFUSE-OP"
    marker distinguishes the unsupported-operator case so the caller can
    refuse loudly rather than fall through."""
    if isinstance(node, ast.BinOp):
        op = _BINOP_SPEC_OPS.get(type(node.op))
        if op is None:
            return "REFUSE-OP"
        left = _resolve_expr_spec(
            node.left,
            params,
            env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        right = _resolve_expr_spec(
            node.right,
            params,
            env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        if left in (None, "REFUSE-OP") or right in (None, "REFUSE-OP"):
            return left if left == "REFUSE-OP" else (
                right if right == "REFUSE-OP" else None
            )
        return ("binop", op, left, right)
    if isinstance(node, ast.Subscript):
        base = _resolve_expr_spec(
            node.value,
            params,
            env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        index = _resolve_expr_spec(
            node.slice,
            params,
            env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        if base in (None, "REFUSE-OP") or index in (None, "REFUSE-OP"):
            return None
        return ("subscript", base, index)
    spec = _resolve_spec(node, params, env)
    if spec is not None:
        return spec
    field_spec = _receiver_field_spec(node, params)
    if field_spec is not None:
        return field_spec
    if tree is not None and isinstance(node, ast.Call):
        constructor_spec, constructor_refusal = _constructor_call_value_spec(
            node,
            params=params,
            env=env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        if constructor_refusal is not None:
            return None
        if constructor_spec is not None:
            return constructor_spec
        method_spec, method_refusal = _method_call_value_spec(
            node,
            params=params,
            env=env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        if method_refusal is not None:
            return None
        if method_spec is not None:
            return method_spec
        call_spec, call_refusal = _function_call_value_spec(
            node,
            params=params,
            env=env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        if call_refusal is not None:
            return None
        if call_spec is not None:
            return call_spec
        dynamic_receiver_refusal = _dynamic_receiver_dispatch_reason(node, params)
        if dynamic_receiver_refusal is not None:
            return None
        receiver_delegate, receiver_refusal = _receiver_method_delegate_for_call(
            node,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
            params=params,
            env=env,
        )
        if receiver_refusal is not None or receiver_delegate is None:
            return None
        return (
            "receiver-method-call",
            receiver_delegate.delegate,
            receiver_delegate.args,
        )
    return None


@functools.lru_cache(maxsize=None)
def conditional_chain_universe_for_callee(
    callee: str,
) -> Tuple[Optional[ConditionalChainUniverse], Optional[TranslateWalkRefusal]]:
    resolved = _resolve_vendor_function(callee, allow_methods=True)
    if resolved is None:
        return None, None
    tree, fn, spec_origin, module_name, fn_name = resolved
    source_memento = _source_memento_for_resolved_function(fn, spec_origin)
    params = [a.arg for a in (*fn.args.posonlyargs, *fn.args.args)]
    body = _body_without_docstring(fn.body)
    tail_return = _terminal_if_return_chain_universe(
        callee,
        body,
        params=params,
        tree=tree,
        module_name=module_name,
        fn_name=fn_name,
        source_path=spec_origin,
        source_memento=source_memento,
    )
    if tail_return[0] is not None or tail_return[1] is not None:
        return tail_return
    if not body or not isinstance(body[-1], ast.Return):
        return None, None
    ret = body[-1].value
    if not isinstance(ret, ast.Name):
        return None, None

    saw_branch = False
    scopes: list[tuple[dict, tuple]] = [({}, ())]
    for stmt in body[:-1]:
        next_scopes: list[tuple[dict, tuple]] = []
        if _conditional_chain_simple_assign(stmt):
            for env, conditions in scopes:
                spec, refusal = _conditional_chain_value_spec(
                    stmt.value,
                    params=params,
                    env=env,
                    tree=tree,
                    module_name=module_name,
                    fn_name=fn_name,
                )
                if refusal is not None:
                    return None, TranslateWalkRefusal(callee, refusal)
                if spec is None:
                    return None, None
                new_env = dict(env)
                new_env[stmt.targets[0].id] = spec
                next_scopes.append((new_env, conditions))
            scopes = next_scopes
            continue
        if isinstance(stmt, ast.If) and not stmt.orelse:
            saw_branch = True
            for env, conditions in scopes:
                guard_spec, guard_refusal = _conditional_chain_guard_spec(
                    stmt.test,
                    params=params,
                    env=env,
                    tree=tree,
                    module_name=module_name,
                    fn_name=fn_name,
                )
                if guard_refusal is not None:
                    return None, TranslateWalkRefusal(callee, guard_refusal)
                if guard_spec is None:
                    return None, None
                truth = _conditional_chain_truth(guard_spec)
                if truth is True:
                    then_env = _conditional_chain_apply_assign_block(
                        stmt.body,
                        env,
                        params=params,
                        tree=tree,
                        module_name=module_name,
                        fn_name=fn_name,
                    )
                    if then_env is None:
                        return None, None
                    next_scopes.append((then_env, conditions))
                    continue
                if truth is False:
                    next_scopes.append((dict(env), conditions))
                    continue
                then_env = _conditional_chain_apply_assign_block(
                    stmt.body,
                    env,
                    params=params,
                    tree=tree,
                    module_name=module_name,
                    fn_name=fn_name,
                )
                if then_env is None:
                    return None, None
                next_scopes.append((then_env, (*conditions, guard_spec)))
                next_scopes.append((dict(env), (*conditions, ("not", guard_spec))))
            scopes = next_scopes
            continue
        return None, None
    if not saw_branch:
        return None, None

    branches = []
    for env, conditions in scopes:
        spec = env.get(ret.id)
        if spec is None:
            spec = _resolve_spec(ret, params, env)
        if spec is None:
            return None, None
        branches.append(ConditionalChainBranch(conditions=conditions, expr_spec=spec))
    return (
        ConditionalChainUniverse(
            kind="conditional-chain-expr",
            module=module_name,
            qualname=f"{module_name}.{fn_name}",
            source_path=spec_origin,
            lineno=fn.lineno,
            branches=tuple(branches),
            source_memento=source_memento,
        ),
        None,
    )


def _terminal_if_return_chain_universe(
    callee: str,
    body: list[ast.stmt],
    *,
    params: list[str],
    tree: ast.Module,
    module_name: str,
    fn_name: str,
    source_path: str,
    source_memento: Optional[dict[str, Any]],
) -> Tuple[Optional[ConditionalChainUniverse], Optional[TranslateWalkRefusal]]:
    if len(body) < 2:
        return None, None
    branch = body[-2]
    fallback = body[-1]
    if (
        not isinstance(branch, ast.If)
        or branch.orelse
        or len(branch.body) != 1
        or not isinstance(branch.body[0], ast.Return)
        or not isinstance(fallback, ast.Return)
        or branch.body[0].value is None
        or fallback.value is None
    ):
        return None, None

    scopes: list[tuple[dict, tuple]] = [({}, ())]
    for stmt in body[:-2]:
        next_scopes: list[tuple[dict, tuple]] = []
        if _conditional_chain_simple_assign(stmt):
            for env, conditions in scopes:
                spec, refusal = _conditional_chain_value_spec(
                    stmt.value,
                    params=params,
                    env=env,
                    tree=tree,
                    module_name=module_name,
                    fn_name=fn_name,
                )
                if refusal is not None:
                    return None, TranslateWalkRefusal(callee, refusal)
                if spec is None:
                    return None, None
                new_env = dict(env)
                new_env[stmt.targets[0].id] = spec
                next_scopes.append((new_env, conditions))
            scopes = next_scopes
            continue
        if isinstance(stmt, ast.If) and not stmt.orelse:
            for env, conditions in scopes:
                guard_spec, guard_refusal = _conditional_chain_guard_spec(
                    stmt.test,
                    params=params,
                    env=env,
                    tree=tree,
                    module_name=module_name,
                    fn_name=fn_name,
                )
                if guard_refusal is not None:
                    return None, TranslateWalkRefusal(callee, guard_refusal)
                if guard_spec is None:
                    return None, None
                truth = _conditional_chain_truth(guard_spec)
                if truth is True:
                    then_env = _conditional_chain_apply_assign_block(
                        stmt.body,
                        env,
                        params=params,
                        tree=tree,
                        module_name=module_name,
                        fn_name=fn_name,
                    )
                    if then_env is None:
                        return None, None
                    next_scopes.append((then_env, conditions))
                    continue
                if truth is False:
                    next_scopes.append((dict(env), conditions))
                    continue
                then_env = _conditional_chain_apply_assign_block(
                    stmt.body,
                    env,
                    params=params,
                    tree=tree,
                    module_name=module_name,
                    fn_name=fn_name,
                )
                if then_env is None:
                    return None, None
                next_scopes.append((then_env, (*conditions, guard_spec)))
                next_scopes.append((dict(env), (*conditions, ("not", guard_spec))))
            scopes = next_scopes
            continue
        return None, None

    branches = []
    for env, conditions in scopes:
        guard_spec, guard_refusal = _conditional_chain_guard_spec(
            branch.test,
            params=params,
            env=env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        if guard_refusal is not None:
            return None, TranslateWalkRefusal(callee, guard_refusal)
        if guard_spec is None:
            return None, None
        then_spec, then_refusal = _conditional_chain_value_spec(
            branch.body[0].value,
            params=params,
            env=env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        fallback_spec, fallback_refusal = _conditional_chain_value_spec(
            fallback.value,
            params=params,
            env=env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        refusal = then_refusal or fallback_refusal
        if refusal is not None:
            return None, TranslateWalkRefusal(callee, refusal)
        if then_spec is None or fallback_spec is None:
            return None, None
        truth = _conditional_chain_truth(guard_spec)
        if truth is True:
            branches.append(
                ConditionalChainBranch(
                    conditions=conditions,
                    expr_spec=then_spec,
                )
            )
        elif truth is False:
            branches.append(
                ConditionalChainBranch(
                    conditions=conditions,
                    expr_spec=fallback_spec,
                )
            )
        else:
            branches.append(
                ConditionalChainBranch(
                    conditions=(*conditions, guard_spec),
                    expr_spec=then_spec,
                )
            )
            branches.append(
                ConditionalChainBranch(
                    conditions=(*conditions, ("not", guard_spec)),
                    expr_spec=fallback_spec,
                )
            )

    if not branches:
        return None, None
    return (
        ConditionalChainUniverse(
            kind="conditional-chain-expr",
            module=module_name,
            qualname=f"{module_name}.{fn_name}",
            source_path=source_path,
            lineno=body[0].lineno if body else 0,
            branches=tuple(branches),
            source_memento=source_memento,
        ),
        None,
    )


def _conditional_chain_simple_assign(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], ast.Name)
    )


def _conditional_chain_apply_assign_block(
    body: list[ast.stmt],
    env: dict,
    *,
    params: list[str],
    tree: ast.Module,
    module_name: str,
    fn_name: str,
) -> Optional[dict]:
    out = dict(env)
    for stmt in body:
        if not _conditional_chain_simple_assign(stmt):
            return None
        spec, refusal = _conditional_chain_value_spec(
            stmt.value,
            params=params,
            env=out,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        if refusal is not None or spec is None:
            return None
        out[stmt.targets[0].id] = spec
    return out


def _conditional_chain_value_spec(
    node: ast.AST,
    *,
    params: list[str],
    env: dict,
    tree: ast.Module,
    module_name: str,
    fn_name: str,
) -> Tuple[Optional[tuple], Optional[str]]:
    if isinstance(node, ast.Call):
        stdlib_spec, stdlib_refusal = _stdlib_call_value_spec(
            node,
            params=params,
            env=env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        if stdlib_refusal is not None or stdlib_spec is not None:
            return stdlib_spec, stdlib_refusal
    spec = _resolve_expr_spec(
        node,
        params,
        env,
        tree=tree,
        module_name=module_name,
        fn_name=fn_name,
    )
    if spec == "REFUSE-OP":
        return None, "conditional chain expression uses an unsupported operator"
    return spec, None


def _stdlib_call_value_spec(
    node: ast.Call,
    *,
    params: list[str],
    env: dict,
    tree: ast.Module,
    module_name: str,
    fn_name: str,
) -> Tuple[Optional[tuple], Optional[str]]:
    delegate = _stdlib_call_delegate(node, tree)
    if delegate is None:
        return None, None
    delegate_q, _call_args = delegate
    specs, specs_refusal = _delegate_call_specs_source_order(
        node,
        params,
        env,
        mirrored_kwargs=None,
        tree=tree,
        module_name=module_name,
        fn_name=fn_name,
        context="conditional stdlib bridge call",
    )
    if specs_refusal is not None:
        return None, specs_refusal
    return ("function-call", delegate_q, tuple(specs or ())), None


def _conditional_chain_guard_spec(
    node: ast.AST,
    *,
    params: list[str],
    env: dict,
    tree: ast.Module,
    module_name: str,
    fn_name: str,
) -> Tuple[Optional[tuple], Optional[str]]:
    spec = _resolve_spec(node, params, env)
    if spec is not None:
        return spec, None
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        op = _CMP_SYMBOL.get(type(node.ops[0]))
        if op is None:
            return None, "conditional chain guard compare operator is unsupported"
        left = _conditional_chain_guard_expr_spec(
            node.left,
            params=params,
            env=env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        right = _conditional_chain_guard_expr_spec(
            node.comparators[0],
            params=params,
            env=env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        if left in (None, "REFUSE-OP") or right in (None, "REFUSE-OP"):
            return None, None
        return ("compare", op, left, right), None
    spec = _resolve_expr_spec(
        node,
        params,
        env,
        tree=tree,
        module_name=module_name,
        fn_name=fn_name,
    )
    if spec == "REFUSE-OP":
        return None, "conditional chain guard expression uses an unsupported operator"
    if spec is not None:
        return spec, None
    return None, None


def _conditional_chain_guard_expr_spec(
    node: ast.AST,
    *,
    params: list[str],
    env: dict,
    tree: ast.Module,
    module_name: str,
    fn_name: str,
):
    if isinstance(node, ast.BinOp):
        op = _BINOP_SPEC_OPS.get(type(node.op))
        if op is None:
            return "REFUSE-OP"
        left = _conditional_chain_guard_expr_spec(
            node.left,
            params=params,
            env=env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        right = _conditional_chain_guard_expr_spec(
            node.right,
            params=params,
            env=env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        if left in (None, "REFUSE-OP") or right in (None, "REFUSE-OP"):
            return left if left == "REFUSE-OP" else (
                right if right == "REFUSE-OP" else None
            )
        return ("binop", op, left, right)
    if isinstance(node, ast.Subscript):
        base = _conditional_chain_guard_expr_spec(
            node.value,
            params=params,
            env=env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        index = _conditional_chain_guard_expr_spec(
            node.slice,
            params=params,
            env=env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        if base in (None, "REFUSE-OP") or index in (None, "REFUSE-OP"):
            return None
        return ("subscript", base, index)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "len"
        and not node.keywords
        and len(node.args) == 1
    ):
        inner = _conditional_chain_guard_expr_spec(
            node.args[0],
            params=params,
            env=env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        if inner in (None, "REFUSE-OP"):
            return None
        return ("ctor-call", "str.len", (inner,))
    return _resolve_expr_spec(
        node,
        params,
        env,
        tree=tree,
        module_name=module_name,
        fn_name=fn_name,
    )


def _conditional_chain_truth(spec) -> Optional[bool]:
    if isinstance(spec, tuple) and len(spec) == 3 and spec[0] == "lit":
        if spec[2] == "bool":
            return bool(spec[1])
    return None


@functools.lru_cache(maxsize=None)
def branch_selected_return_universe_for_callee(
    callee: str,
) -> Tuple[Optional[BranchSelectedReturnUniverse], Optional[TranslateWalkRefusal]]:
    resolved = _resolve_vendor_function(callee, allow_methods=True)
    if resolved is None:
        return None, None
    _tree, fn, spec_origin, module_name, fn_name = resolved
    source_memento = _source_memento_for_resolved_function(fn, spec_origin)
    params = [a.arg for a in (*fn.args.posonlyargs, *fn.args.args)]
    if len(params) < 2 or params[0] not in {"self", "cls"}:
        return None, None
    body = _body_without_docstring(fn.body)
    if not body:
        return None, None
    call_aliases = _module_call_aliases(_tree, module_name)
    env: dict[str, tuple] = {}
    branch: Optional[Tuple[str, object, str, int, Optional[str]]] = None
    for index, stmt in enumerate(body):
        if isinstance(stmt, ast.Raise):
            continue
        if not isinstance(stmt, ast.If):
            return None, None
        branch = _branch_selected_return_from_if_chain(
            stmt,
            receiver_name=params[0],
            params=params,
            env=env,
        )
        if branch is not None:
            if any(not isinstance(tail, ast.Raise) for tail in body[index + 1 :]):
                return None, None
            break
        prelude = _non_none_adapter_prelude(stmt, params, call_aliases)
        if prelude is None:
            return None, None
        param_name, adapter_callee = prelude
        env[param_name] = ("adapter", adapter_callee)
    if branch is None:
        return None, None
    (
        field_name,
        field_value,
        field_value_kind,
        return_param_index,
        return_adapter_callee,
    ) = branch
    return (
        BranchSelectedReturnUniverse(
            field_name=field_name,
            field_value=field_value,
            field_value_kind=field_value_kind,
            return_param_index=return_param_index - 1,
            return_param_name=params[return_param_index],
            module=module_name,
            qualname=f"{module_name}.{fn_name}",
            source_path=spec_origin,
            lineno=fn.lineno,
            source_memento=source_memento,
            return_adapter_callee=return_adapter_callee,
        ),
        None,
    )


def _branch_selected_return_from_if_chain(
    stmt: ast.If,
    *,
    receiver_name: str,
    params: list[str],
    env: dict[str, tuple],
) -> Optional[Tuple[str, object, str, int, Optional[str]]]:
    current: ast.If = stmt
    while True:
        selected = _branch_selected_return_from_if(
            current,
            receiver_name=receiver_name,
            params=params,
            env=env,
        )
        if selected is not None:
            return selected
        if len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If):
            current = current.orelse[0]
            continue
        return None


def _branch_selected_return_from_if(
    stmt: ast.If,
    *,
    receiver_name: str,
    params: list[str],
    env: dict[str, tuple],
) -> Optional[Tuple[str, object, str, int, Optional[str]]]:
    field = _self_field_literal_eq(stmt.test, receiver_name)
    if field is None:
        return None
    if len(stmt.body) != 1 or not isinstance(stmt.body[0], ast.Return):
        return None
    value = stmt.body[0].value
    if not isinstance(value, ast.Name):
        return None
    if value.id not in params or value.id == receiver_name:
        return None
    return_param_index = params.index(value.id)
    field_name, field_value, field_value_kind = field
    adapter_callee = None
    spec = env.get(value.id)
    if spec is not None:
        if spec[0] != "adapter":
            return None
        adapter_callee = spec[1]
    return field_name, field_value, field_value_kind, return_param_index, adapter_callee


@functools.lru_cache(maxsize=None)
def branch_selected_raise_universe_for_callee(
    callee: str,
) -> Tuple[Optional[BranchSelectedRaiseUniverse], Optional[TranslateWalkRefusal]]:
    resolved = _resolve_vendor_function(callee, allow_methods=True)
    if resolved is None:
        return None, None
    _tree, fn, spec_origin, module_name, fn_name = resolved
    source_memento = _source_memento_for_resolved_function(fn, spec_origin)
    params = [a.arg for a in (*fn.args.posonlyargs, *fn.args.args)]
    if not params:
        return None, None
    body = _body_without_docstring(fn.body)
    if len(body) != 2 or not isinstance(body[0], ast.If):
        return None, None
    branch_if = body[0]
    if branch_if.orelse:
        return None, None
    guard = _param_literal_eq(branch_if.test, params)
    if guard is None:
        return None, None
    if not _is_terminal_block(branch_if.body):
        return None, None
    if not any(
        isinstance(n, ast.Return)
        for stmt in branch_if.body
        for n in ast.walk(stmt)
    ):
        return None, None
    if not isinstance(body[1], ast.Raise):
        return None, None
    exception_name = _raised_exception_name(body[1])
    if exception_name is None:
        return None, None
    param_name, param_index, excluded_value, excluded_value_kind = guard
    if source_memento is not None:
        source_memento = dict(source_memento)
        source_memento["source_function_name"] = fn_name
        source_memento["branch_param_name"] = param_name
        source_memento["branch_param_index"] = param_index
        source_memento["branch_excluded_value"] = excluded_value
        source_memento["branch_excluded_value_kind"] = excluded_value_kind
        source_memento["branch_if_line"] = branch_if.lineno
        source_memento["branch_raise_line"] = body[1].lineno
        source_memento["branch_raise_exception_type"] = exception_name
    return (
        BranchSelectedRaiseUniverse(
            param_name=param_name,
            param_index=param_index,
            excluded_value=excluded_value,
            excluded_value_kind=excluded_value_kind,
            exception_name=exception_name,
            module=module_name,
            qualname=f"{module_name}.{fn_name}",
            source_path=spec_origin,
            lineno=fn.lineno,
            source_memento=source_memento,
        ),
        None,
    )


def _param_literal_eq(
    node: ast.AST,
    params: list[str],
) -> Optional[Tuple[str, int, object, str]]:
    if (
        not isinstance(node, ast.Compare)
        or len(node.ops) != 1
        or not isinstance(node.ops[0], ast.Eq)
        or len(node.comparators) != 1
    ):
        return None
    if isinstance(node.left, ast.Name) and node.left.id in params:
        literal = _literal_value_kind(node.comparators[0])
        if literal is not None:
            value, value_kind = literal
            return node.left.id, params.index(node.left.id), value, value_kind
    if isinstance(node.comparators[0], ast.Name) and node.comparators[0].id in params:
        literal = _literal_value_kind(node.left)
        if literal is not None:
            value, value_kind = literal
            name = node.comparators[0].id
            return name, params.index(name), value, value_kind
    return None


def _non_none_adapter_prelude(
    stmt: ast.If,
    params: list[str],
    call_aliases: dict[str, str],
) -> Optional[Tuple[str, str]]:
    param_name = _param_none_check_for_branch_prelude(stmt.test)
    adapter_stmt: Optional[ast.stmt] = None
    if param_name is not None:
        if len(stmt.orelse) != 1:
            return None
        adapter_stmt = stmt.orelse[0]
    else:
        param_name = _param_not_none_check_for_branch_prelude(stmt.test)
        if param_name is None or len(stmt.body) != 1:
            return None
        adapter_stmt = stmt.body[0]
    if param_name not in params[1:]:
        return None
    if not (
        isinstance(adapter_stmt, ast.Assign)
        and len(adapter_stmt.targets) == 1
        and isinstance(adapter_stmt.targets[0], ast.Name)
        and adapter_stmt.targets[0].id == param_name
    ):
        return None
    adapter = _adapter_call_over_name(
        adapter_stmt.value,
        param_name,
        call_aliases,
    )
    if adapter is None:
        return None
    return param_name, adapter


def _param_none_check_for_branch_prelude(node: ast.AST) -> Optional[str]:
    if (
        not isinstance(node, ast.Compare)
        or len(node.ops) != 1
        or not isinstance(node.ops[0], ast.Is)
        or len(node.comparators) != 1
    ):
        return None
    return _none_compare_name(node.left, node.comparators[0])


def _param_not_none_check_for_branch_prelude(node: ast.AST) -> Optional[str]:
    if (
        not isinstance(node, ast.Compare)
        or len(node.ops) != 1
        or not isinstance(node.ops[0], ast.IsNot)
        or len(node.comparators) != 1
    ):
        return None
    return _none_compare_name(node.left, node.comparators[0])


def _none_compare_name(left: ast.AST, right: ast.AST) -> Optional[str]:
    if (
        isinstance(left, ast.Name)
        and isinstance(right, ast.Constant)
        and right.value is None
    ):
        return left.id
    if (
        isinstance(right, ast.Name)
        and isinstance(left, ast.Constant)
        and left.value is None
    ):
        return right.id
    return None


def _self_field_literal_eq(
    node: ast.AST,
    receiver_name: str,
) -> Optional[Tuple[str, object, str]]:
    if (
        not isinstance(node, ast.Compare)
        or len(node.ops) != 1
        or not isinstance(node.ops[0], ast.Eq)
        or len(node.comparators) != 1
    ):
        return None
    left = _self_field_name(node.left, receiver_name)
    right_lit = _literal_value_kind(node.comparators[0])
    if left is not None and right_lit is not None:
        value, value_kind = right_lit
        return left, value, value_kind
    right = _self_field_name(node.comparators[0], receiver_name)
    left_lit = _literal_value_kind(node.left)
    if right is not None and left_lit is not None:
        value, value_kind = left_lit
        return right, value, value_kind
    return None


def _self_field_name(node: ast.AST, receiver_name: str) -> Optional[str]:
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == receiver_name
    ):
        return node.attr
    return None


@functools.lru_cache(maxsize=None)
def delegation_universe_for_callee(
    callee: str,
) -> Tuple[Optional[DelegationUniverse], Optional[TranslateWalkRefusal]]:
    resolved = _resolve_vendor_function(callee, allow_methods=True)
    if resolved is None:
        return None, None
    tree, fn, spec_origin, module_name, fn_name = resolved
    source_memento = _source_memento_for_resolved_function(fn, spec_origin)

    def refuse(reason):
        return None, TranslateWalkRefusal(callee=callee, reason=reason)

    def universe(**kw):
        return (
            DelegationUniverse(
                module=module_name,
                qualname=f"{module_name}.{fn_name}",
                source_path=spec_origin,
                lineno=fn.lineno,
                source_memento=source_memento,
                **kw,
            ),
            None,
        )

    params = [a.arg for a in (*fn.args.posonlyargs, *fn.args.args)]
    body = [
        stmt
        for stmt in fn.body
        if not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
    ]
    rest, tainted = _strip_guard_prefix(body)
    if not rest or not isinstance(rest[-1], ast.Return) or rest[-1].value is None:
        return None, None
    value = rest[-1].value
    cast_inner = _transparent_typing_cast_inner(value, tree)
    if cast_inner is not None:
        value = cast_inner
    if not isinstance(value, (ast.Name, ast.Call, ast.BinOp, ast.Subscript)):
        return None, None
    # SSA CHAIN (census return-fn-call, 53k bodies): leading simple
    # assigns are a substitution environment — `x = a; return g(x)`
    # forwards a exactly as `return g(a)` does. Linear, no control flow,
    # so plain left-to-right resolution IS the SSA; a rebound param name
    # shadows correctly (later reads get the new spec). Any other
    # preceding statement shape is another family's body.
    env: dict = {}
    keyword_defaults: list[tuple] = []
    keyword_default_names: set[str] = set()
    for stmt in rest[:-1]:
        kw_default, kw_default_refusal = _kwargs_setdefault_spec(
            stmt,
            kwarg_name=fn.args.kwarg.arg if fn.args.kwarg is not None else None,
            params=params,
            env=env,
        )
        if kw_default_refusal is not None:
            return refuse(kw_default_refusal)
        if kw_default is not None:
            keyword_name = kw_default[1]
            if keyword_name in keyword_default_names:
                return refuse(
                    f"kwargs.setdefault repeats keyword {keyword_name!r}; "
                    "the default surface is not normalized yet"
                )
            keyword_default_names.add(keyword_name)
            keyword_defaults.append(kw_default)
            continue
        if not (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
        ):
            return None, None  # control flow / unpacking: not this family
        if any(isinstance(n, ast.NamedExpr) for n in ast.walk(stmt.value)):
            return refuse(
                "chain assign value rebinds via walrus (NamedExpr); "
                "resolution order is no longer the statement order"
            )
        spec = _resolve_spec(stmt.value, params, env)
        if spec is None and isinstance(stmt.value, ast.BinOp):
            spec = _resolve_expr_spec(
                stmt.value,
                params,
                env,
                tree=tree,
                module_name=module_name,
                fn_name=fn_name,
            )
            if spec == "REFUSE-OP":
                return refuse(
                    "chain assign binop operator outside the lowered set "
                    "(+ - * / %); the consumer side cannot build the term "
                    "either"
                )
        if spec is None and isinstance(stmt.value, ast.Call):
            constructor_spec, constructor_refusal = _constructor_call_value_spec(
                stmt.value,
                params=params,
                env=env,
                tree=tree,
                module_name=module_name,
                fn_name=fn_name,
            )
            if constructor_refusal is not None:
                return refuse(constructor_refusal)
            if constructor_spec is not None:
                spec = constructor_spec
        if spec is None and isinstance(stmt.value, ast.Call):
            call_spec, call_refusal = _function_call_value_spec(
                stmt.value,
                params=params,
                env=env,
                tree=tree,
                module_name=module_name,
                fn_name=fn_name,
            )
            if call_refusal is not None:
                return refuse(call_refusal)
            if call_spec is not None:
                spec = call_spec
        if spec is None and isinstance(stmt.value, ast.Call):
            stdlib_spec, stdlib_refusal = _stdlib_call_value_spec(
                stmt.value,
                params=params,
                env=env,
                tree=tree,
                module_name=module_name,
                fn_name=fn_name,
            )
            if stdlib_refusal is not None:
                return refuse(stdlib_refusal)
            if stdlib_spec is not None:
                spec = stdlib_spec
        if spec is None and isinstance(stmt.value, ast.Call):
            dynamic_receiver_refusal = _dynamic_receiver_dispatch_reason(
                stmt.value,
                params,
            )
            if dynamic_receiver_refusal is not None:
                return refuse(dynamic_receiver_refusal)
            receiver_delegate, receiver_refusal = _receiver_method_delegate_for_call(
                stmt.value,
                tree=tree,
                module_name=module_name,
                fn_name=fn_name,
                params=params,
                env=env,
            )
            if receiver_refusal is not None:
                return refuse(receiver_refusal)
            if receiver_delegate is not None:
                spec = (
                    "receiver-method-call",
                    receiver_delegate.delegate,
                    receiver_delegate.args,
                )
        if spec is None:
            return refuse(
                "chain value is computed (not a parameter, literal, or "
                "chain name); the forwarded value is not the callsite's"
            )
        env[stmt.targets[0].id] = spec
    if tainted:
        return refuse(
            "guard-strip: a stripped guard test rebinds via walrus "
            "(NamedExpr); the remaining body no longer sees the "
            "callsite's arguments"
        )
    returns = sum(
        1
        for stmt in body
        for n in ast.walk(stmt)
        if isinstance(n, (ast.Return, ast.Yield, ast.YieldFrom))
    )
    if returns != 1:
        return None, None

    # arithmetic return (census return-binop, 17k bodies): the returned
    # expression as STRUCTURE — eq(subject, ctor("+", [...])) — using the
    # same operator ctors the consumer-side translator builds, so the
    # terms unify syntactically. + - * lower to real Int arithmetic in
    # the substrate; / and % stay uninterpreted EUF (python float-div and
    # sign-of-mod semantics never enter; the equality is term-level).
    # The EMITTER additionally requires every mapped leaf to be an Int
    # constant: '+' on strings is CONCAT by dispatch, and a string leaf
    # under an arithmetic-lowered ctor would be the cross-sort mislower.
    if isinstance(value, (ast.BinOp, ast.Subscript)):
        expr_spec = _resolve_expr_spec(
            value,
            params,
            env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        if expr_spec == "REFUSE-OP":
            return refuse(
                "binop operator outside the lowered set (+ - * / %); the "
                "consumer side cannot build the term either"
            )
        if expr_spec is None:
            return refuse(
                "binop leaf is neither a parameter, literal, nor chain "
                "name; the computed value is not the callsite's"
            )
        return universe(kind="chain-expr", expr_spec=expr_spec)

    if isinstance(value, ast.Call):
        expr_spec = _resolve_expr_spec(
            value,
            params,
            env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        if expr_spec == "REFUSE-OP":
            return refuse(
                "call return expression uses an unsupported operator; the "
                "consumer side cannot build the term either"
            )
        if (
            isinstance(expr_spec, tuple)
            and expr_spec
            and expr_spec[0] == "ctor-call"
        ):
            return universe(kind="chain-expr", expr_spec=expr_spec)
        receiver_spec = None
        if expr_spec is not None and expr_spec[0] == "method-call":
            method_args = expr_spec[2]
            if method_args:
                receiver_spec = method_args[0]
        if (
            isinstance(receiver_spec, tuple)
            and receiver_spec
            and receiver_spec[0]
            in {
                "function-call",
                "method-call",
                "receiver-method-call",
                "subscript",
                "binop",
            }
        ):
            return universe(kind="chain-expr", expr_spec=expr_spec)

    # identity: return <param>, possibly through the chain; a name that
    # chains to a LITERAL is a constant in forwarding clothes
    if isinstance(value, ast.Name):
        spec = _resolve_spec(value, params, env)
        if spec is None:
            return None, None  # free name: not a forwarding body
        if spec[0] == "receiver-method-call":
            return universe(
                kind="delegation-receiver-method",
                delegate=spec[1],
                args=spec[2],
            )
        if spec[0] == "param":
            return universe(kind="identity", param_index=spec[1])
        if spec[0] == "lit":
            return universe(kind="chain-constant", args=(spec,))
        if spec[0] in {
            "binop",
            "ctor-call",
            "function-call",
            "method-call",
            "subscript",
        }:
            return universe(kind="chain-expr", expr_spec=spec)
        return None, None

    # imported stdlib delegation: return json.loads(<params/literals>). The
    # vendor source owns the forwarding relation, while the stdlib target is a
    # compiler/runtime axiom outside the vendor package. We emit only the same
    # callresult equality shape used by same-module delegation; no source text
    # from the stdlib is copied into the memento.
    stdlib_delegate = _stdlib_call_delegate(value, tree)
    if stdlib_delegate is not None:
        delegate_q, _call_args = stdlib_delegate
        specs, specs_refusal = _delegate_call_specs_source_order(
            value,
            params,
            env,
            mirrored_kwargs=fn.args.kwarg.arg if fn.args.kwarg is not None else None,
            mirrored_kw_defaults=tuple(keyword_defaults),
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
            context="imported-stdlib delegate",
        )
        if specs_refusal is not None:
            return refuse(specs_refusal)
        return universe(kind="delegation-stdlib", delegate=delegate_q, args=tuple(specs))

    # receiver-context method delegation: class C; def f(self, x): return
    # self.g(x). The target body is concrete (same class), but the value remains
    # receiver-dependent, so the emitter uses callval_g(receiver, args...) and
    # queues a recursive source walk over C.g with the same receiver context.
    dynamic_receiver_refusal = _dynamic_receiver_dispatch_reason(value, params)
    if dynamic_receiver_refusal is not None:
        return refuse(dynamic_receiver_refusal)
    receiver_delegate, receiver_refusal = _receiver_method_delegate_for_call(
        value,
        tree=tree,
        module_name=module_name,
        fn_name=fn_name,
        params=params,
        env=env,
    )
    if receiver_refusal is not None:
        return refuse(receiver_refusal)
    if receiver_delegate is not None:
        return universe(
            kind="delegation-receiver-method",
            delegate=receiver_delegate.delegate,
            args=receiver_delegate.args,
        )

    # method delegation: return <param|literal>.method(<params|literals>)
    # (census return-method-call, 113k bodies). Unlike a function
    # delegate there is NO body to read for determinism evidence — the
    # receiver's type is not static — so the license is narrower: the
    # method name must not be a nondeterminism marker, and the EMITTER
    # additionally requires every mapped term to be a concrete literal
    # at the callsite (_euf_args_all_concrete), so the equality only
    # ever bridges ground instantiations. Within that, the forwarding
    # equality is the same documented callval purity tradeoff every
    # method-call assertion already carries.
    if isinstance(value.func, ast.Attribute):
        method = value.func.attr
        if not isinstance(value.func.value, (ast.Name, ast.Constant)):
            return None, None  # computed receivers are other families
        if method in _NONDET_ATTRS:
            return refuse(
                f"method delegate .{method} is a nondeterminism marker; "
                "its call terms must not unify"
            )
        if value.keywords:
            return refuse(
                "keyword arguments in the delegate call are not yet "
                "walked (positional mapping only)"
            )
        specs = []
        for node in (value.func.value, *value.args):
            spec = _resolve_spec(node, params, env)
            if spec is None:
                return refuse(
                    "method-delegate receiver/argument is neither a "
                    "parameter nor an ascii literal; the forwarded value "
                    "is not the callsite's"
                )
            specs.append(spec)
        return universe(
            kind="delegation-method", delegate=method, args=tuple(specs)
        )

    # delegation: return g(...) with g a stable same-module function
    if not isinstance(value.func, ast.Name):
        return None, None  # subscript/lambda callees are other families
    delegate_name = value.func.id
    if delegate_name == fn_name:
        return refuse("self-delegation: the equality would be vacuous")
    delegate_fn = next(
        (
            stmt
            for stmt in tree.body
            if isinstance(stmt, ast.FunctionDef)
            and stmt.name == delegate_name
        ),
        None,
    )
    if delegate_fn is None:
        if any(
            isinstance(stmt, ast.AsyncFunctionDef)
            and stmt.name == delegate_name
            for stmt in tree.body
        ):
            return refuse(
                f"delegate {delegate_name} is async: the call term is a "
                "coroutine, not the awaited value"
            )
        return refuse(
            f"delegate {delegate_name} is not a module-level function "
            "in the vendor module (imported/dynamic delegates are not "
            "walkable from this body alone)"
        )
    if delegate_fn.decorator_list:
        return refuse(
            f"delegate {delegate_name} is decorated; its def body is not "
            "the runtime callable, so determinism evidence cannot be "
            "read from it"
        )
    # binding stability: the name looked up at CALL time must be this def
    # and nothing else — same teeth as the table walks.
    events = [e for e in _binding_events(tree) if e.name == delegate_name]
    if len(events) != 1:
        return refuse(
            f"delegate {delegate_name} has {len(events)} module-level "
            "binding events; the name does not stably denote the def"
        )
    if delegate_name in _global_declarations(tree):
        return refuse(
            f"delegate {delegate_name} is rebindable through a global "
            "declaration puncture"
        )
    module_fns = {
        s.name: s
        for s in tree.body
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if _body_reaches_nondet(delegate_fn, module_fns, depth=3, seen=set()):
        return refuse(
            f"delegate {delegate_name} transitively reaches a "
            "nondeterminism source; equating its call terms would launder "
            "state through EUF"
        )
    delegate_q = f"{module_name}.{delegate_name}"

    # splat forwarding: signature exactly (*a) / (*a, **k), call mirrors it
    fa = fn.args
    is_splat_sig = (
        not fa.posonlyargs
        and not fa.args
        and not fa.kwonlyargs
        and fa.vararg is not None
    )
    if is_splat_sig:
        call_ok = (
            len(value.args) == 1
            and isinstance(value.args[0], ast.Starred)
            and isinstance(value.args[0].value, ast.Name)
            and value.args[0].value.id == fa.vararg.arg
        )
        kw_ok = not value.keywords or (
            fa.kwarg is not None
            and len(value.keywords) == 1
            and value.keywords[0].arg is None
            and isinstance(value.keywords[0].value, ast.Name)
            and value.keywords[0].value.id == fa.kwarg.arg
        )
        if call_ok and kw_ok:
            return universe(kind="delegation-splat", delegate=delegate_q)
        return refuse(
            "splat signature without exact splat forwarding; the "
            "delegate's arguments are not f's arguments"
        )

    if fa.vararg is not None or fa.kwarg is not None:
        return refuse(
            "mixed vararg signature: the positional mapping cannot "
            "account for every callsite shape"
        )
    specs, specs_refusal = _delegate_call_specs_for_signature(
        value,
        delegate_fn,
        params,
        env,
        context="delegate",
    )
    if specs_refusal is not None:
        return refuse(specs_refusal)
    return universe(kind="delegation", delegate=delegate_q, args=tuple(specs))


def _delegate_call_specs_source_order(
    value: ast.Call,
    params: list[str],
    env: dict,
    *,
    mirrored_kwargs: Optional[str],
    mirrored_kw_defaults: tuple[tuple, ...] = (),
    tree: Optional[ast.Module] = None,
    module_name: str = "",
    fn_name: str = "",
    context: str,
) -> Tuple[Optional[list[tuple]], Optional[str]]:
    specs = []
    for arg in value.args:
        spec, refusal = _resolve_delegate_value_or_receiver_call_spec(
            arg,
            params,
            env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        if refusal is not None:
            return None, refusal
        if spec is None:
            return (
                None,
                f"{context} argument is neither a parameter, literal, "
                "collection literal, chain name, nor receiver-method call; "
                "the forwarded value is not the callsite's",
            )
        specs.append(spec)
    for keyword in value.keywords:
        if keyword.arg is None:
            if (
                mirrored_kwargs is not None
                and isinstance(keyword.value, ast.Name)
                and keyword.value.id == mirrored_kwargs
            ):
                specs.extend(mirrored_kw_defaults)
                continue
            return (
                None,
                f"{context} uses **kwargs forwarding that is not an exact "
                "mirror of the function's kwargs parameter",
            )
        spec, refusal = _resolve_delegate_value_or_receiver_call_spec(
            keyword.value,
            params,
            env,
            tree=tree,
            module_name=module_name,
            fn_name=fn_name,
        )
        if refusal is not None:
            return None, refusal
        if spec is None:
            return (
                None,
                f"{context} keyword argument {keyword.arg!r} is neither a "
                "parameter, literal, collection literal, chain name, nor "
                "receiver-method call; the forwarded value is not the "
                "callsite's",
            )
        specs.append(("kw", keyword.arg, spec))
    return specs, None


def _kwargs_setdefault_spec(
    stmt: ast.stmt,
    *,
    kwarg_name: Optional[str],
    params: list[str],
    env: dict,
) -> Tuple[Optional[tuple], Optional[str]]:
    if kwarg_name is None:
        return None, None
    if not (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Attribute)
        and stmt.value.func.attr == "setdefault"
    ):
        return None, None
    call = stmt.value
    if not (
        isinstance(call.func.value, ast.Name)
        and call.func.value.id == kwarg_name
    ):
        return None, (
            "kwargs.setdefault receiver is not the function's **kwargs "
            "parameter"
        )
    if call.keywords or len(call.args) != 2:
        return None, (
            "kwargs.setdefault must have exactly a literal key and default "
            "value"
        )
    key_node, value_node = call.args
    if not (isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)):
        return None, "kwargs.setdefault key is not a string literal"
    spec = _resolve_delegate_value_spec(value_node, params, env)
    if spec is None:
        return None, (
            f"kwargs.setdefault value for {key_node.value!r} is neither a "
            "parameter, literal, collection literal, nor chain name"
        )
    return ("kw", key_node.value, spec), None


def _delegate_call_specs_for_signature(
    value: ast.Call,
    delegate_fn: ast.FunctionDef,
    params: list[str],
    env: dict,
    *,
    context: str,
) -> Tuple[Optional[list[tuple]], Optional[str]]:
    delegate_params = _positional_param_names(delegate_fn)
    slots: list[Optional[tuple]] = [None for _ in delegate_params]
    for index, arg in enumerate(value.args):
        if index >= len(delegate_params):
            return (
                None,
                f"{context} has more positional arguments than the delegate "
                "signature exposes",
            )
        spec = _resolve_delegate_value_spec(arg, params, env)
        if spec is None:
            return (
                None,
                f"{context} argument is neither a parameter, literal, "
                "collection literal, nor chain name; the forwarded value is "
                "not the callsite's",
            )
        slots[index] = spec
    for keyword in value.keywords:
        if keyword.arg is None:
            return (
                None,
                f"{context} uses **kwargs forwarding; the keyword surface is "
                "runtime-selected",
            )
        if keyword.arg not in delegate_params:
            return (
                None,
                f"{context} keyword argument {keyword.arg!r} is not a "
                "positional parameter of the delegate",
            )
        index = delegate_params.index(keyword.arg)
        if slots[index] is not None:
            return (
                None,
                f"{context} keyword argument {keyword.arg!r} duplicates an "
                "already supplied delegate argument",
            )
        spec = _resolve_delegate_value_spec(keyword.value, params, env)
        if spec is None:
            return (
                None,
                f"{context} keyword argument {keyword.arg!r} is neither a "
                "parameter, literal, collection literal, nor chain name; the "
                "forwarded value is not the callsite's",
            )
        slots[index] = spec
    if not any(slot is not None for slot in slots):
        return [], None
    last_supplied = max(index for index, slot in enumerate(slots) if slot is not None)
    if any(slot is None for slot in slots[: last_supplied + 1]):
        return (
            None,
            f"{context} leaves a defaulted positional gap before a supplied "
            "keyword; that call surface is not modeled yet",
        )
    return [slot for slot in slots[: last_supplied + 1] if slot is not None], None


@functools.lru_cache(maxsize=None)
def bytes_identity_universe_for_callee(
    callee: str,
) -> Tuple[Optional[BytesIdentityUniverse], Optional[TranslateWalkRefusal]]:
    resolved = _resolve_vendor_function(callee)
    if resolved is None:
        return None, None
    _tree, fn, spec_origin, module_name, fn_name = resolved
    source_memento = _source_memento_for_resolved_function(fn, spec_origin)
    params = [a.arg for a in (*fn.args.posonlyargs, *fn.args.args)]
    if not params:
        return None, None
    subject = params[0]
    body = [
        stmt
        for stmt in fn.body
        if not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
    ]
    if len(body) != 2:
        return None, None
    guard, ret = body
    if not (
        isinstance(guard, ast.If)
        and not guard.orelse
        and len(guard.body) == 1
        and isinstance(guard.body[0], ast.Assign)
        and isinstance(ret, ast.Return)
        and isinstance(ret.value, ast.Name)
        and ret.value.id == subject
    ):
        return None, None
    if sum(
        1
        for stmt in body
        for n in ast.walk(stmt)
        if isinstance(n, (ast.Return, ast.Yield, ast.YieldFrom))
    ) != 1:
        return None, None
    if any(
        isinstance(n, (ast.Return, ast.Yield, ast.YieldFrom))
        for stmt in body
        for n in ast.walk(stmt)
        if n is not ret
    ):
        return None, None
    if not _is_isinstance_str_guard(guard.test, subject):
        return None, None
    assign = guard.body[0]
    if not (
        len(assign.targets) == 1
        and isinstance(assign.targets[0], ast.Name)
        and assign.targets[0].id == subject
        and _is_param_encode_call(assign.value, subject)
    ):
        return None, None
    return (
        BytesIdentityUniverse(
            param_index=0,
            param_name=subject,
            module=module_name,
            qualname=f"{module_name}.{fn_name}",
            source_path=spec_origin,
            lineno=fn.lineno,
            source_memento=source_memento,
        ),
        None,
    )


@functools.lru_cache(maxsize=None)
def list_adapter_universe_for_callee(
    callee: str,
) -> Tuple[Optional[ListAdapterUniverse], Optional[TranslateWalkRefusal]]:
    resolved = _resolve_vendor_function(callee)
    if resolved is None:
        return None, None
    tree, fn, spec_origin, module_name, fn_name = resolved
    source_memento = _source_memento_for_resolved_function(fn, spec_origin)
    params = [a.arg for a in (*fn.args.posonlyargs, *fn.args.args)]
    if not params:
        return None, None
    subject = params[0]
    body = _body_without_docstring(fn.body)
    if len(body) != 2:
        return None, None
    first, second = body
    if not (
        isinstance(first, ast.If)
        and not first.orelse
        and len(first.body) == 1
        and isinstance(first.body[0], ast.Return)
        and _is_isinstance_str_or_bytes_guard(first.test, subject)
        and isinstance(second, ast.Return)
    ):
        return None, None
    call_aliases = _module_call_aliases(tree, module_name)
    adapter_callee = _single_list_adapter_return_callee(
        first.body[0],
        subject,
        call_aliases,
    )
    if adapter_callee is None:
        return None, None
    iterable_adapter = _iterable_list_adapter_return_callee(
        second,
        subject,
        call_aliases,
    )
    if iterable_adapter != adapter_callee:
        return None, None
    return (
        ListAdapterUniverse(
            param_index=0,
            param_name=subject,
            adapter_callee=adapter_callee,
            module=module_name,
            qualname=f"{module_name}.{fn_name}",
            source_path=spec_origin,
            lineno=fn.lineno,
            source_memento=source_memento,
        ),
        None,
    )


def _is_isinstance_str_guard(node: ast.AST, param_name: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "isinstance"
        and len(node.args) == 2
        and not node.keywords
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == param_name
        and isinstance(node.args[1], ast.Name)
        and node.args[1].id == "str"
    )


def _is_isinstance_str_or_bytes_guard(node: ast.AST, param_name: str) -> bool:
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "isinstance"
        and len(node.args) == 2
        and not node.keywords
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == param_name
    ):
        return False
    typ = node.args[1]
    if isinstance(typ, ast.Name):
        return typ.id in {"str", "bytes"}
    if isinstance(typ, ast.Tuple):
        names = {
            elt.id
            for elt in typ.elts
            if isinstance(elt, ast.Name)
        }
        return {"str", "bytes"} <= names
    return False


def _single_list_adapter_return_callee(
    stmt: ast.Return,
    param_name: str,
    call_aliases: dict[str, str],
) -> Optional[str]:
    value = stmt.value
    if not (
        isinstance(value, ast.List)
        and len(value.elts) == 1
        and isinstance(value.elts[0], ast.Call)
    ):
        return None
    return _adapter_call_over_name(value.elts[0], param_name, call_aliases)


def _iterable_list_adapter_return_callee(
    stmt: ast.Return,
    param_name: str,
    call_aliases: dict[str, str],
) -> Optional[str]:
    value = stmt.value
    if not (
        isinstance(value, ast.ListComp)
        and len(value.generators) == 1
        and isinstance(value.elt, ast.Call)
    ):
        return None
    gen = value.generators[0]
    if (
        gen.ifs
        or gen.is_async
        or not isinstance(gen.target, ast.Name)
        or not isinstance(gen.iter, ast.Name)
        or gen.iter.id != param_name
    ):
        return None
    return _adapter_call_over_name(value.elt, gen.target.id, call_aliases)


def _adapter_call_over_name(
    value: ast.Call,
    arg_name: str,
    call_aliases: dict[str, str],
) -> Optional[str]:
    if not (
        isinstance(value.func, ast.Name)
        and not value.keywords
        and len(value.args) == 1
        and isinstance(value.args[0], ast.Name)
        and value.args[0].id == arg_name
    ):
        return None
    callee = call_aliases.get(value.func.id)
    if callee is None:
        return None
    universe, refusal = bytes_identity_universe_for_callee(callee)
    if refusal is not None or universe is None:
        return None
    return callee


def _is_param_encode_call(node: ast.AST, param_name: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "encode"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == param_name
    )


def _stable_same_module_function(tree: ast.Module, name: str) -> bool:
    fn = next(
        (
            stmt
            for stmt in tree.body
            if isinstance(stmt, ast.FunctionDef)
            and stmt.name == name
        ),
        None,
    )
    if fn is None or fn.decorator_list:
        return False
    events = [e for e in _binding_events(tree) if e.name == name]
    return len(events) == 1 and name not in _global_declarations(tree)


def _stdlib_call_delegate(
    call: ast.Call,
    tree: ast.Module,
) -> Optional[tuple[str, tuple[ast.expr, ...]]]:
    aliases = _stdlib_module_aliases(tree)
    path = _attribute_path(call.func)
    if path is None or len(path) < 2:
        return None
    root, *attrs = path
    module = aliases.get(root)
    if module is None:
        return None
    return ".".join([module, *attrs]), tuple(call.args)


def _transparent_typing_cast_inner(
    node: ast.AST,
    tree: ast.Module,
) -> Optional[ast.expr]:
    if not isinstance(node, ast.Call):
        return None
    if node.keywords or len(node.args) != 2:
        return None
    aliases = _stdlib_module_aliases(tree)
    path = _attribute_path(node.func)
    if path is None:
        return None
    root, *attrs = path
    module = aliases.get(root)
    if module == "typing" and attrs == ["cast"]:
        return node.args[1]
    if module == "typing.cast" and not attrs:
        return node.args[1]
    return None


def _stdlib_module_aliases(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                if _is_stdlib_module(alias.name):
                    aliases[alias.asname or alias.name.split(".", 1)[0]] = alias.name
        elif isinstance(stmt, ast.ImportFrom) and stmt.module is not None:
            if stmt.level != 0 or not _is_stdlib_module(stmt.module):
                continue
            for alias in stmt.names:
                if alias.name == "*":
                    continue
                aliases[alias.asname or alias.name] = f"{stmt.module}.{alias.name}"
    return aliases


def _is_stdlib_module(module_name: str) -> bool:
    root = module_name.split(".", 1)[0]
    return root in getattr(sys, "stdlib_module_names", set())


def _attribute_path(node: ast.AST) -> Optional[list[str]]:
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return None
    parts.append(cur.id)
    return list(reversed(parts))


def _prelude_call_specs(
    body: list,
    tree: ast.Module,
    module_name: str,
    params: list,
    fn_name: str,
) -> tuple:
    env: dict = {}
    calls = []
    for stmt in body[:-1]:
        if not (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
        ):
            continue
        target = stmt.targets[0].id
        value = stmt.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            delegate_name = value.func.id
            if (
                delegate_name != fn_name
                and not value.keywords
                and all(not isinstance(arg, ast.Starred) for arg in value.args)
                and _stable_same_module_function(tree, delegate_name)
            ):
                specs = []
                for arg in value.args:
                    spec = _resolve_spec(arg, params, env)
                    if spec is None:
                        specs = None
                        break
                    specs.append(spec)
                if specs is not None:
                    calls.append(
                        PreludeCall(
                            delegate=f"{module_name}.{delegate_name}",
                            args=tuple(specs),
                        )
                    )
            continue
        spec = _resolve_spec(value, params, env)
        if spec is not None:
            env[target] = spec
    return tuple(calls)


def _guard_clause(test: ast.expr, params: list) -> Optional[GuardClause]:
    if not (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and len(test.comparators) == 1
    ):
        return None
    op_type = type(test.ops[0])
    op = _CMP_SYMBOL.get(op_type)
    if op is None:
        return None
    left, right = test.left, test.comparators[0]
    right_literal = _guard_literal_value(right, op_type)
    if (
        isinstance(left, ast.Name)
        and left.id in params
        and right_literal is not _NO_GUARD_LITERAL
    ):
        return GuardClause(params.index(left.id), left.id, op, right_literal)
    # literal-on-the-left mirror: `if 0 > x: raise` == `x < 0`
    left_literal = _guard_literal_value(left, op_type)
    if (
        isinstance(right, ast.Name)
        and right.id in params
        and left_literal is not _NO_GUARD_LITERAL
    ):
        mirror = {"<": ">", ">": "<", "≤": "≥", "≥": "≤", "=": "=", "≠": "≠"}
        return GuardClause(
            params.index(right.id), right.id, mirror[op], left_literal
        )
    return None


_NO_GUARD_LITERAL = object()


def _guard_literal_value(node: ast.expr, op_type: type) -> object:
    if not isinstance(node, ast.Constant):
        return _NO_GUARD_LITERAL
    value = node.value
    if value is None and op_type in (ast.Eq, ast.NotEq, ast.Is, ast.IsNot):
        return None
    if op_type in (ast.Is, ast.IsNot):
        return _NO_GUARD_LITERAL
    if isinstance(value, (int, str)) and not isinstance(value, bool):
        return value
    return _NO_GUARD_LITERAL


# Non-determinism markers: a body that (transitively, within its module)
# reaches any of these does NOT return the same value for the same args, so
# EUF same-args unification would manufacture a false contradiction (two
# salted hashes of "secret" are unequal). Detection is EVIDENCE-BASED and
# conservative: we drop unification only when we SEE a marker; unknown or
# unresolvable bodies stay "pure" (the current sound-conservative behavior).
_NONDET_ATTRS = frozenset(
    {
        "random", "uniform", "randint", "randrange", "choice", "choices",
        "sample", "shuffle", "getrandbits", "seed", "token_bytes",
        "token_hex", "token_urlsafe", "urandom", "uuid1", "uuid4",
        "now", "utcnow", "today", "time", "monotonic", "perf_counter",
        "gen_salt",
    }
)
_NONDET_MODULES = frozenset({"random", "secrets", "uuid"})


@functools.lru_cache(maxsize=None)
def callee_is_nondeterministic(callee: str) -> bool:
    """True iff the resolved vendor body transitively (same module, bounded
    depth) reaches a non-determinism source. Evidence-based: False on any
    body we cannot resolve, so EUF unification keeps its current
    sound-conservative behavior where we have no evidence."""
    resolved = _resolve_vendor_function(callee)
    if resolved is None:
        return False
    tree, fn, _origin, module_name, _fn_name = resolved
    module_fns = {
        s.name: s
        for s in tree.body
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    return _body_reaches_nondet(fn, module_fns, depth=3, seen=set())


def _body_reaches_nondet(fn, module_fns, depth, seen) -> bool:
    if fn.name in seen or depth <= 0:
        return False
    seen.add(fn.name)
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                if f.attr in _NONDET_ATTRS:
                    return True
                if (
                    isinstance(f.value, ast.Name)
                    and f.value.id in _NONDET_MODULES
                ):
                    return True
            elif isinstance(f, ast.Name):
                if f.id in _NONDET_ATTRS:
                    return True
                callee_fn = module_fns.get(f.id)
                if callee_fn is not None and _body_reaches_nondet(
                    callee_fn, module_fns, depth - 1, seen
                ):
                    return True
    return False


def _resolve_vendor_function(
    callee: str,
    *,
    allow_methods: bool = False,
    allow_property: bool = False,
):
    if "." not in callee:
        return None
    parts = callee.split(".")
    split_points = (
        range(len(parts) - 1, 0, -1) if allow_methods else [len(parts) - 1]
    )
    for split in split_points:
        module_name = ".".join(parts[:split])
        fn_path = parts[split:]
        if not module_name or not fn_path:
            continue
        resolved = _resolve_function_path_in_module(
            module_name,
            fn_path,
            allow_property=allow_property,
        )
        if resolved is not None:
            return resolved
    return None


def _resolve_vendor_class(
    callee: str,
) -> Optional[Tuple[ast.Module, ast.ClassDef, str, str, str]]:
    if "." not in callee:
        return None
    parts = callee.split(".")
    for split in range(len(parts) - 1, 0, -1):
        module_name = ".".join(parts[:split])
        class_path = parts[split:]
        if not module_name or not class_path:
            continue
        resolved = _resolve_class_path_in_module(module_name, class_path)
        if resolved is not None:
            return resolved
    return None


def _resolve_class_path_in_module(module_name: str, class_path: list[str]):
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ValueError):
        return None
    if spec is None or spec.origin in (None, "built-in", "frozen"):
        return None
    if not spec.origin.endswith(".py"):
        return None
    try:
        tree = ast.parse(
            open(spec.origin, encoding="utf-8").read(), filename=spec.origin
        )
    except (OSError, SyntaxError):
        return None
    cls = _find_class_path(tree.body, class_path, module_name)
    if cls is None:
        return None
    return tree, cls, spec.origin, module_name, ".".join(class_path)


def _resolve_function_path_in_module(
    module_name: str,
    fn_path: list[str],
    *,
    allow_property: bool = False,
):
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ValueError):
        return None
    if spec is None or spec.origin in (None, "built-in", "frozen"):
        return None
    if not spec.origin.endswith(".py"):
        return None
    try:
        tree = ast.parse(
            open(spec.origin, encoding="utf-8").read(), filename=spec.origin
        )
    except (OSError, SyntaxError):
        return None
    fn = _find_function_path(tree.body, fn_path, module_name)
    if fn is None:
        return None
    if (
        fn.decorator_list
        and not _is_staticmethod_only(fn)
        and not (allow_property and _is_property_only(fn))
    ):
        # A decorated def is NOT its body: the name binds whatever the
        # decorator returns (caught live 2026-06-12: @negate over
        # `return True` runs False while the body walk swore True — a
        # falsePass through every family). Same non-candidate class as a
        # C extension: the source we can read is not the callable that
        # runs. ``@staticmethod`` is the compiler-provided exception: it
        # removes descriptor binding but preserves the body relation.
        return None
    return tree, fn, spec.origin, module_name, ".".join(fn_path)


def _find_function_path(
    body: list[ast.stmt],
    fn_path: list[str],
    module_name: Optional[str] = None,
) -> Optional[ast.FunctionDef]:
    if not fn_path:
        return None
    current_body = body
    for class_name in fn_path[:-1]:
        cls = next(
            (
                stmt
                for stmt in current_body
                if isinstance(stmt, ast.ClassDef) and stmt.name == class_name
            ),
            None,
        )
        if cls is None or not _class_decorators_preserve_identity(
            current_body,
            cls,
            module_name,
        ):
            return None
        current_body = cls.body
    fn_name = fn_path[-1]
    candidates = [
        stmt
        for stmt in current_body
        if isinstance(stmt, ast.FunctionDef) and stmt.name == fn_name
    ]
    for candidate in candidates:
        if not _is_overload_stub(candidate):
            return candidate
    return candidates[0] if candidates else None


def _is_overload_stub(fn: ast.FunctionDef) -> bool:
    if not (
        len(fn.body) == 1
        and isinstance(fn.body[0], ast.Expr)
        and isinstance(fn.body[0].value, ast.Constant)
        and fn.body[0].value.value is Ellipsis
    ):
        return False
    for decorator in fn.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "overload":
            return True
        if isinstance(decorator, ast.Attribute) and decorator.attr == "overload":
            return True
    return False


def _find_class_path(
    body: list[ast.stmt],
    class_path: list[str],
    module_name: Optional[str] = None,
) -> Optional[ast.ClassDef]:
    if not class_path:
        return None
    current_body = body
    found: Optional[ast.ClassDef] = None
    for class_name in class_path:
        found = next(
            (
                stmt
                for stmt in current_body
                if isinstance(stmt, ast.ClassDef) and stmt.name == class_name
            ),
            None,
        )
        if found is None or not _class_decorators_preserve_identity(
            current_body,
            found,
            module_name,
        ):
            return None
        current_body = found.body
    return found


_METADATA_CLASS_DECORATOR_NAMES = {
    "register_extension_dtype",
    "set_module",
}


def _class_decorators_preserve_identity(
    scope_body: list[ast.stmt],
    cls: ast.ClassDef,
    module_name: Optional[str],
) -> bool:
    return all(
        _class_decorator_preserves_identity(scope_body, decorator, module_name)
        for decorator in cls.decorator_list
    )


def _class_decorator_preserves_identity(
    scope_body: list[ast.stmt],
    decorator: ast.expr,
    module_name: Optional[str],
) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    name = _decorator_name(target)
    if name is None:
        return False
    resolved = _resolve_class_decorator_function(scope_body, target, module_name)
    if resolved is None:
        return False
    metadata_allowed = name.rsplit(".", 1)[-1] in _METADATA_CLASS_DECORATOR_NAMES
    if isinstance(decorator, ast.Call):
        return _function_returns_identity_decorator(
            resolved,
            metadata_allowed=metadata_allowed,
        )
    return _function_preserves_first_arg_identity(
        resolved,
        metadata_allowed=metadata_allowed,
    )


def _decorator_name(node: ast.AST) -> Optional[str]:
    path = _attribute_path(node)
    if path is None:
        return None
    return ".".join(path)


def _resolve_class_decorator_function(
    scope_body: list[ast.stmt],
    target: ast.expr,
    module_name: Optional[str],
) -> Optional[ast.FunctionDef]:
    name = _decorator_name(target)
    if name is None:
        return None
    if "." not in name:
        local = _module_level_function(scope_body, name)
        if local is not None:
            return local
        if module_name is None:
            return None
        aliases = _module_import_aliases(scope_body, module_name)
        qualified = aliases.get(name)
        if qualified is None:
            return None
        return _resolve_qualified_decorator_function(qualified, set())
    parts = name.split(".")
    if module_name is not None:
        aliases = _module_import_aliases(scope_body, module_name)
        alias = aliases.get(parts[0])
        if alias is not None:
            name = ".".join([alias, *parts[1:]])
    return _resolve_qualified_decorator_function(name, set())


def _module_level_function(
    body: list[ast.stmt],
    name: str,
) -> Optional[ast.FunctionDef]:
    for stmt in body:
        if isinstance(stmt, ast.FunctionDef) and stmt.name == name:
            return stmt
    return None


def _module_import_aliases(
    body: list[ast.stmt],
    module_name: str,
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for stmt in body:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                aliases[alias.asname or alias.name.split(".", 1)[0]] = alias.name
        elif isinstance(stmt, ast.ImportFrom):
            imported_module = _resolved_import_from_module(module_name, stmt)
            if imported_module is None:
                continue
            for alias in stmt.names:
                if alias.name == "*":
                    continue
                aliases[alias.asname or alias.name] = (
                    f"{imported_module}.{alias.name}"
                )
    return aliases


def _resolve_qualified_decorator_function(
    qualified: str,
    seen: set[str],
) -> Optional[ast.FunctionDef]:
    if qualified in seen or "." not in qualified:
        return None
    seen.add(qualified)
    module_name, local_name = qualified.rsplit(".", 1)
    parsed = _parse_python_module(module_name)
    if parsed is None:
        return None
    tree, _origin = parsed
    local = _find_function_path(tree.body, [local_name], module_name)
    if local is not None:
        if local.decorator_list and not _function_decorators_preserve_identity(
            tree.body,
            local,
            module_name,
        ):
            return None
        return local
    alias = _module_import_aliases(tree.body, module_name).get(local_name)
    if alias is None:
        return None
    return _resolve_qualified_decorator_function(alias, seen)


def _function_decorators_preserve_identity(
    scope_body: list[ast.stmt],
    fn: ast.FunctionDef,
    module_name: Optional[str],
) -> bool:
    return all(
        _class_decorator_preserves_identity(scope_body, decorator, module_name)
        for decorator in fn.decorator_list
    )


def _parse_python_module(module_name: str) -> Optional[Tuple[ast.Module, str]]:
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ValueError):
        return None
    if spec is None or spec.origin in (None, "built-in", "frozen"):
        return None
    if not spec.origin.endswith(".py"):
        return None
    try:
        return (
            ast.parse(open(spec.origin, encoding="utf-8").read(), filename=spec.origin),
            spec.origin,
        )
    except (OSError, SyntaxError):
        return None


def _function_returns_identity_decorator(
    fn: ast.FunctionDef,
    *,
    metadata_allowed: bool,
) -> bool:
    body = _body_without_docstring(fn.body)
    if len(body) < 2 or not isinstance(body[-1], ast.Return):
        return False
    returned_name = body[-1].value.id if isinstance(body[-1].value, ast.Name) else None
    if returned_name is None:
        return False
    inner = next(
        (
            stmt
            for stmt in body[:-1]
            if isinstance(stmt, ast.FunctionDef) and stmt.name == returned_name
        ),
        None,
    )
    if inner is None:
        return False
    non_inner = [
        stmt
        for stmt in body[:-1]
        if not (isinstance(stmt, ast.FunctionDef) and stmt.name == returned_name)
    ]
    if any(not _identity_decorator_metadata_stmt(stmt, "", False) for stmt in non_inner):
        return False
    return _function_preserves_first_arg_identity(
        inner,
        metadata_allowed=metadata_allowed,
    )


def _function_preserves_first_arg_identity(
    fn: ast.FunctionDef,
    *,
    metadata_allowed: bool,
) -> bool:
    params = _positional_param_names(fn)
    if not params:
        return False
    subject = params[0]
    body = _body_without_docstring(fn.body)
    if not body or not isinstance(body[-1], ast.Return):
        return False
    if not _return_expr_preserves_identity(body[-1].value, subject):
        return False
    return all(
        _identity_decorator_metadata_stmt(stmt, subject, metadata_allowed)
        for stmt in body[:-1]
    )


def _return_expr_preserves_identity(
    expr: Optional[ast.expr],
    subject: str,
) -> bool:
    if isinstance(expr, ast.Name) and expr.id == subject:
        return True
    if isinstance(expr, ast.Call) and expr.args:
        path = _attribute_path(expr.func)
        if path is not None and path[-1] == "cast":
            return _return_expr_preserves_identity(expr.args[-1], subject)
    return False


def _identity_decorator_metadata_stmt(
    stmt: ast.stmt,
    subject: str,
    metadata_allowed: bool,
) -> bool:
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Expr):
        if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            return True
        return metadata_allowed and isinstance(stmt.value, ast.Call)
    if isinstance(stmt, ast.Assign):
        return (
            metadata_allowed
            and all(
                _metadata_assignment_target(target, subject)
                for target in stmt.targets
            )
        )
    if isinstance(stmt, ast.AnnAssign):
        return metadata_allowed and _metadata_assignment_target(stmt.target, subject)
    if isinstance(stmt, ast.If):
        return metadata_allowed and all(
            _identity_decorator_metadata_stmt(child, subject, metadata_allowed)
            for child in [*stmt.body, *stmt.orelse]
        )
    if isinstance(stmt, ast.Try):
        return metadata_allowed and all(
            _identity_decorator_metadata_stmt(child, subject, metadata_allowed)
            for child in [
                *stmt.body,
                *stmt.orelse,
                *stmt.finalbody,
                *(child for handler in stmt.handlers for child in handler.body),
            ]
        )
    return False


def _metadata_assignment_target(target: ast.expr, subject: str) -> bool:
    return (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == subject
        and target.attr in {"__module__", "_module_source"}
    )


def _class_member_binding_count(cls: ast.ClassDef, name: str) -> int:
    count = 0
    for stmt in cls.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if stmt.name == name:
                count += 1
            continue
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    count += 1
        elif isinstance(stmt, ast.AnnAssign):
            if isinstance(stmt.target, ast.Name) and stmt.target.id == name:
                count += 1
        elif isinstance(stmt, ast.AugAssign):
            if isinstance(stmt.target, ast.Name) and stmt.target.id == name:
                count += 1
    return count


def _is_staticmethod_only(fn: ast.FunctionDef) -> bool:
    return bool(fn.decorator_list) and all(
        isinstance(dec, ast.Name) and dec.id == "staticmethod"
        for dec in fn.decorator_list
    )


def _is_property_only(fn: ast.FunctionDef) -> bool:
    return len(fn.decorator_list) == 1 and all(
        isinstance(dec, ast.Name) and dec.id == "property"
        for dec in fn.decorator_list
    )


def _vendor_call_vectors(
    module_name: str, fn_name: str
) -> Tuple[list, Optional[str]]:
    """All-literal argument tuples from the vendor corpus' calls of the
    callee (the guard gate's evidence: a vendor-sworn call must not fire
    a walked guard)."""
    for candidate in (f"test.test_{module_name}", f"test_{module_name}"):
        try:
            spec = importlib.util.find_spec(candidate)
        except (ImportError, ValueError):
            continue
        if spec is None or not spec.origin or not spec.origin.endswith(".py"):
            continue
        try:
            tree = ast.parse(
                open(spec.origin, encoding="utf-8").read(), filename=spec.origin
            )
        except (OSError, SyntaxError):
            continue
        vectors = []
        for node in ast.walk(tree):
            if _is_callee_call(node, fn_name):
                args = []
                ok = True
                for a in node.args:
                    if isinstance(a, ast.Constant) and isinstance(
                        a.value, (int, str)
                    ):
                        args.append(a.value)
                    elif (
                        isinstance(a, ast.UnaryOp)
                        and isinstance(a.op, ast.USub)
                        and isinstance(a.operand, ast.Constant)
                        and type(a.operand.value) is int
                    ):
                        args.append(-a.operand.value)
                    else:
                        ok = False
                        break
                if ok and args:
                    vectors.append(tuple(args))
        return vectors, spec.origin
    return [], None


@functools.lru_cache(maxsize=None)
def translate_universe_for_callee(
    callee: str,
) -> Tuple[Optional[TranslateUniverse], Optional[TranslateWalkRefusal]]:
    """Resolve a dotted callee against installed vendor source and walk the
    translate shape. Returns (universe, None) on success, (None, refusal)
    when the callee matched the family but a gate refused, and (None, None)
    when the callee is simply not translate-shaped (not a candidate; no
    refusal owed)."""
    if "." not in callee:
        return None, None
    module_name, fn_name = callee.rsplit(".", 1)
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ValueError):
        return None, None
    if spec is None or spec.origin in (None, "built-in", "frozen"):
        return None, None
    if not spec.origin.endswith(".py"):
        # Compiled extension: nothing to walk. Not a candidate.
        return None, None
    try:
        source = open(spec.origin, encoding="utf-8").read()
    except OSError:
        return None, None
    try:
        tree = ast.parse(source, filename=spec.origin)
    except SyntaxError:
        return None, None

    fn = next(
        (
            stmt
            for stmt in tree.body
            if isinstance(stmt, ast.FunctionDef) and stmt.name == fn_name
        ),
        None,
    )
    if fn is None:
        return None, None
    source_memento = _source_memento_for_function(fn, spec.origin, source)

    body = [
        stmt
        for stmt in fn.body
        if not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
    ]
    params = [a.arg for a in (*fn.args.posonlyargs, *fn.args.args)]
    prelude_calls = _prelude_call_specs(body, tree, module_name, params, fn_name)
    def refuse(reason: str) -> Tuple[None, TranslateWalkRefusal]:
        return None, TranslateWalkRefusal(callee=callee, reason=reason)

    shape = _translate_return_shape(body)
    if shape is None:
        # return-replace-literals (census family): a SINGLE-char
        # .replace(FROM, TO) as the last op removes FROM from the output
        # entirely (replace is total over its from-string), unless TO is FROM
        # -- the chars-not-in-set complement, same as translate, literals
        # inline so no binding scan.
        replace_pair = _replace_return_shape(body)
        if replace_pair is not None:
            frm, to = replace_pair
            if frm == to:
                return refuse(
                    f"replace({frm!r}, {to!r}) is a no-op; no complement claim"
                )
            forbidden = frm
            vectors, vector_source = _vendor_vectors(module_name, fn_name)
            for vector in vectors:
                if forbidden in vector:
                    return refuse(
                        f"sample-gate: vendor vector {vector!r} from "
                        f"{vector_source} contains the replaced char "
                        f"{forbidden!r}; the walk misread the body or the "
                        "vendor contradicts their own source"
                    )
            return (
                TranslateUniverse(
                    forbidden=forbidden,
                    module=module_name,
                    qualname=f"{module_name}.{fn_name}",
                    source_path=spec.origin,
                    lineno=fn.lineno,
                    table_name="<inline replace from-char>",
                    kind="chars-not-in-set",
                    vendor_vectors_checked=len(vectors),
                    vendor_vector_source=vector_source,
                    source_memento=source_memento,
                ),
                None,
            )
        # return-format (census family): an f-string / "...".format() that
        # starts with literal text guarantees the output STARTS WITH that
        # prefix (placeholders fill after it; the leading literal is
        # invariant). Emitted as prefix-of(prefix, output).
        fmt_prefix = _format_return_prefix(body)
        if fmt_prefix is not None:
            vectors, vector_source = _vendor_vectors(module_name, fn_name)
            for vector in vectors:
                if not vector.startswith(fmt_prefix):
                    return refuse(
                        f"sample-gate: vendor vector {vector!r} from "
                        f"{vector_source} does not start with the format "
                        f"prefix {fmt_prefix!r}; the walk misread the body or "
                        "the vendor contradicts their own source"
                    )
            return (
                TranslateUniverse(
                    forbidden=fmt_prefix,
                    module=module_name,
                    qualname=f"{module_name}.{fn_name}",
                    source_path=spec.origin,
                    lineno=fn.lineno,
                    table_name="<format literal prefix>",
                    kind="prefix",
                    vendor_vectors_checked=len(vectors),
                    vendor_vector_source=vector_source,
                    source_memento=source_memento,
                ),
                None,
            )
        # Second family: total .rstrip/.lstrip of a bytes literal as the LAST
        # operation -- token-padding and integer-byte canonicalization shapes.
        # The claim "output never ends/starts with a stripped char" derives
        # from strip totality ALONE, so preceding statements are irrelevant
        # and no binding scan is needed (the literal is inline).
        leading_strip_literal = _lstrip_return_shape(body)
        if leading_strip_literal is not None:
            try:
                strip_chars = leading_strip_literal.decode("ascii")
            except UnicodeDecodeError:
                return refuse("lstrip bytes are not ASCII; charset atom needs ASCII")
            forbidden = "".join(sorted(set(strip_chars)))
            if not forbidden:
                return refuse("lstrip literal is empty; no claim exists")
            vectors, vector_source = _vendor_vectors(module_name, fn_name)
            for vector in vectors:
                if vector and vector[0] in forbidden:
                    return refuse(
                        f"sample-gate: vendor vector {vector!r} from "
                        f"{vector_source} starts with a stripped char; the "
                        "walk misread the body or the vendor contradicts "
                        "their own source"
                    )
            return (
                TranslateUniverse(
                    forbidden=forbidden,
                    module=module_name,
                    qualname=f"{module_name}.{fn_name}",
                    source_path=spec.origin,
                    lineno=fn.lineno,
                    table_name="<inline lstrip literal>",
                    kind="no-prefix-chars",
                    vendor_vectors_checked=len(vectors),
                    vendor_vector_source=vector_source,
                    queued_calls=prelude_calls,
                    source_memento=source_memento,
                ),
                None,
            )
        strip_literal = _rstrip_return_shape(body)
        if strip_literal is None:
            # Third family: return TABLE[<expr>] over a stable module-level
            # tuple of string literals -- the membership universe (the
            # corpus census's cheapest swearable shape, 15,943 bodies in the
            # top-1000). The returned value is ALWAYS an element of the
            # pinned tuple: subscript either yields an element or raises
            # (no value escapes the table), so membership holds for every
            # input that returns at all. Index expression is irrelevant.
            sub_table = _table_subscript_shape(body)
            if sub_table is None:
                # Fourth family: the table-loop (census: 17,781 bodies).
                # acc = []/"" ; for ...: acc.append(TABLE[i]) / acc += ... ;
                # return sep.join(acc) / acc. Every accumulated piece is an
                # element of a pinned table (or a literal), so every output
                # char is in the union of their chars -- the POSITIVE
                # chars-in-set universe. Widening the set is the safe
                # direction (output ⊆ S stays true for any S ⊇ truth), so
                # join separators and literal appends just add their chars.
                loop_result = _table_loop_charset(body, tree)
                if loop_result is None:
                    # No family matched: not a candidate, no refusal owed.
                    return None, None
                allowed, loop_refusal = loop_result
                if loop_refusal is not None:
                    return refuse(loop_refusal)
                vectors, vector_source = _vendor_vectors(module_name, fn_name)
                for vector in vectors:
                    stray = sorted(set(vector) - set(allowed))
                    if stray:
                        return refuse(
                            f"sample-gate: vendor vector {vector!r} from "
                            f"{vector_source} contains chars {stray!r} "
                            "outside the walked table union; the walk "
                            "misread the body or the vendor contradicts "
                            "their own source"
                        )
                return (
                    TranslateUniverse(
                        forbidden=allowed,
                        module=module_name,
                        qualname=f"{module_name}.{fn_name}",
                        source_path=spec.origin,
                        lineno=fn.lineno,
                        table_name="<table-loop union>",
                        kind="chars-in-set",
                        vendor_vectors_checked=len(vectors),
                        vendor_vector_source=vector_source,
                        source_memento=source_memento,
                    ),
                    None,
                )
            values_node, _line = _module_binding_tuple(tree, sub_table)
            if values_node is None:
                return refuse(
                    f"subscript table '{sub_table}' has no single "
                    "module-level tuple-literal binding (mutable or computed "
                    "tables cannot pin)"
                )
            tbl_candidate = _Candidate(
                name=sub_table, value=values_node, line=_line, confession=None
            )
            tbl_events = [
                e for e in _binding_events(tree) if e.name == sub_table
            ]
            tbl_failure = _admission_failure(
                tbl_candidate,
                tbl_events,
                _global_declarations(tree).get(sub_table),
            )
            if tbl_failure is not None:
                return refuse(
                    f"subscript table '{sub_table}' is not stable: {tbl_failure}"
                )
            values = []
            for el in values_node.elts:
                if isinstance(el, ast.Constant) and isinstance(el.value, str):
                    values.append(el.value)
                else:
                    return refuse(
                        f"subscript table '{sub_table}' is not all-string "
                        "literals (mixed/non-string tables are vNext, refused "
                        "by name)"
                    )
            if not values:
                return refuse(f"subscript table '{sub_table}' is empty")
            vectors, vector_source = _vendor_vectors(module_name, fn_name)
            for vector in vectors:
                if vector not in values:
                    return refuse(
                        f"sample-gate: vendor vector {vector!r} from "
                        f"{vector_source} is not in the walked table; the "
                        "walk misread the body or the vendor contradicts "
                        "their own source"
                    )
            return (
                TranslateUniverse(
                    forbidden="",
                    module=module_name,
                    qualname=f"{module_name}.{fn_name}",
                    source_path=spec.origin,
                    lineno=fn.lineno,
                    table_name=sub_table,
                    kind="member-of-values",
                    vendor_vectors_checked=len(vectors),
                    vendor_vector_source=vector_source,
                    values=tuple(values),
                    source_memento=source_memento,
                ),
                None,
            )
        try:
            strip_chars = strip_literal.decode("ascii")
        except UnicodeDecodeError:
            return refuse("rstrip bytes are not ASCII; charset atom needs ASCII")
        forbidden = "".join(sorted(set(strip_chars)))
        if not forbidden:
            return refuse("rstrip literal is empty; no claim exists")
        vectors, vector_source = _vendor_vectors(module_name, fn_name)
        for vector in vectors:
            if vector and vector[-1] in forbidden:
                return refuse(
                    f"sample-gate: vendor vector {vector!r} from "
                    f"{vector_source} ends with a stripped char; the walk "
                    "misread the body or the vendor contradicts their own "
                    "source"
                )
        return (
            TranslateUniverse(
                forbidden=forbidden,
                module=module_name,
                qualname=f"{module_name}.{fn_name}",
                source_path=spec.origin,
                lineno=fn.lineno,
                table_name="<inline rstrip literal>",
                kind="no-suffix-chars",
                vendor_vectors_checked=len(vectors),
                vendor_vector_source=vector_source,
                queued_calls=prelude_calls,
                source_memento=source_memento,
            ),
            None,
        )
    table_name = shape

    table_call, table_line = _module_binding_call(tree, table_name)
    if table_call is None:
        return refuse(
            f"translate table '{table_name}' has no single module-level "
            "call binding"
        )
    candidate = _Candidate(
        name=table_name, value=table_call, line=table_line, confession=None
    )
    events = [e for e in _binding_events(tree) if e.name == table_name]
    failure = _admission_failure(
        candidate, events, _global_declarations(tree).get(table_name)
    )
    if failure is not None:
        return refuse(f"translate table '{table_name}' is not stable: {failure}")

    pair = _maketrans_byte_literals(table_call)
    if pair is None:
        return refuse(
            f"translate table '{table_name}' is not "
            "bytes.maketrans(<bytes literal>, <bytes literal>)"
        )
    frm, to = pair
    if len(frm) != len(to):
        return refuse("maketrans from/to lengths differ")
    try:
        frm_s = frm.decode("ascii")
        to_s = to.decode("ascii")
    except UnicodeDecodeError:
        return refuse("maketrans bytes are not ASCII; charset atom needs ASCII")

    # from MINUS to: a mapped-away char that some other mapping writes back
    # is NOT forbidden in the output. Swapped tables yield the empty set.
    forbidden = "".join(sorted(set(frm_s) - set(to_s)))
    if not forbidden:
        return refuse(
            "translate table reintroduces every mapped char (swap-shaped); "
            "no complement universe exists"
        )

    # ∀⊨SAMPLE (the gate): the walked universe must be consistent with every
    # vector the VENDOR's own test corpus swears at this surface -- the same
    # party that wrote the body, evaluated by ground computation, no solver.
    # Consumer claims are NOT gate evidence: a consumer contradicting the
    # universe is the refutation working, decided by check. A violating
    # VENDOR vector means our walk misread the body (or the vendor
    # contradicts their own source); the universe is refused.
    vectors, vector_source = _vendor_vectors(module_name, fn_name)
    for vector in vectors:
        violating = sorted(set(ch for ch in forbidden if ch in vector))
        if violating:
            return refuse(
                f"sample-gate: vendor vector {vector!r} from "
                f"{vector_source} contains forbidden {violating!r}; the walk "
                "misread the body or the vendor contradicts their own source"
            )

    return (
        TranslateUniverse(
            forbidden=forbidden,
            module=module_name,
            qualname=f"{module_name}.{fn_name}",
            source_path=spec.origin,
            lineno=fn.lineno,
            table_name=table_name,
            vendor_vectors_checked=len(vectors),
            vendor_vector_source=vector_source,
            source_memento=source_memento,
        ),
        None,
    )


def _source_memento_for_function(
    fn: ast.FunctionDef,
    source_path: str,
    source: str,
) -> Optional[dict[str, Any]]:
    try:
        full = _body_source_locator(fn, source_path, source.splitlines(keepends=True))
        return dict(source_memento_of(full))
    except Exception:
        return None


def _source_memento_for_resolved_function(
    fn: ast.FunctionDef,
    source_path: str,
) -> Optional[dict[str, Any]]:
    try:
        source = open(source_path, encoding="utf-8").read()
    except OSError:
        return None
    return _source_memento_for_function(fn, source_path, source)


def _vendor_vectors(
    module_name: str, fn_name: str
) -> Tuple[list, Optional[str]]:
    """Sworn expected-value vectors for the callee surface, extracted from
    the vendor's own test corpus (CPython convention: test.test_<module>;
    sibling convention: test_<module>). A vector is the str/bytes literal a
    vendor assertion equates with a call of the callee. Extraction is an
    ast scan (calls of fn_name compared/assertEqual'd against a literal);
    what it cannot read it does not invent -- the gate runs over what is
    sworn AND extractable, and reports the count."""
    for candidate in (f"test.test_{module_name}", f"test_{module_name}"):
        try:
            spec = importlib.util.find_spec(candidate)
        except (ImportError, ValueError):
            continue
        if spec is None or not spec.origin or not spec.origin.endswith(".py"):
            continue
        try:
            tree = ast.parse(
                open(spec.origin, encoding="utf-8").read(), filename=spec.origin
            )
        except (OSError, SyntaxError):
            continue
        return _extract_vectors(tree, fn_name), spec.origin
    return [], None


def _is_callee_call(node: ast.AST, fn_name: str) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == fn_name
    if isinstance(func, ast.Attribute):
        return func.attr == fn_name
    return False


def _literal_text(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return node.value
        if isinstance(node.value, bytes):
            try:
                return node.value.decode("ascii")
            except UnicodeDecodeError:
                return None
    return None


def _extract_vectors(tree: ast.Module, fn_name: str) -> list:
    vectors = []
    for node in ast.walk(tree):
        operands: list = []
        if isinstance(node, ast.Compare) and len(node.comparators) == 1:
            if isinstance(node.ops[0], (ast.Eq, ast.NotEq)) and isinstance(
                node.ops[0], ast.Eq
            ):
                operands = [node.left, node.comparators[0]]
        elif isinstance(node, ast.Call) and len(node.args) >= 2:
            # assertEqual / assertEquals, plus the aliased-helper pattern
            # CPython itself uses (eq = self.assertEqual; eq(call, expected)):
            # ANY 2+-arg call pairing a callee-call with a literal is read as
            # an expected-value vector. Over-extraction is the SAFE direction
            # here -- a spurious vector can only make the gate stricter
            # (refuse a universe), never license one.
            operands = list(node.args[:2])
        if len(operands) != 2:
            continue
        a, b = operands
        if _is_callee_call(a, fn_name):
            literal = _literal_text(b)
        elif _is_callee_call(b, fn_name):
            literal = _literal_text(a)
        else:
            continue
        if literal is not None:
            vectors.append(literal)
    return vectors


def _table_loop_charset(body: list, tree: ast.Module):
    """Match: acc-init, one for-loop accumulating table elements / literals,
    return join(acc) or acc. Returns (allowed_charset, None) on success,
    (None, reason) when the shape matched but a piece refuses, or None when
    the body is not table-loop shaped at all."""
    if len(body) != 3:
        return None
    init, loop, ret = body
    if not (
        isinstance(init, ast.Assign)
        and len(init.targets) == 1
        and isinstance(init.targets[0], ast.Name)
    ):
        return None
    acc = init.targets[0].id
    is_list = isinstance(init.value, ast.List) and not init.value.elts
    is_str = isinstance(init.value, ast.Constant) and init.value.value == ""
    if not (is_list or is_str):
        return None
    if not isinstance(loop, (ast.For,)):
        return None
    if not isinstance(ret, ast.Return) or ret.value is None:
        return None

    chars: set = set()

    # the return: "sep".join(acc) for list accumulators, bare acc for str
    rv = ret.value
    if (
        isinstance(rv, ast.Call)
        and isinstance(rv.func, ast.Attribute)
        and rv.func.attr == "join"
        and isinstance(rv.func.value, ast.Constant)
        and isinstance(rv.func.value.value, str)
        and len(rv.args) == 1
        and isinstance(rv.args[0], ast.Name)
        and rv.args[0].id == acc
    ):
        chars.update(rv.func.value.value)
    elif isinstance(rv, ast.Name) and rv.id == acc and is_str:
        pass
    else:
        return None

    # every write to acc inside the loop must be append(TABLE[i]) /
    # += TABLE[i] / a string literal; ANY other write anywhere refuses
    writes = []
    for node in ast.walk(loop):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and isinstance(node.value.func.value, ast.Name)
            and node.value.func.value.id == acc
        ):
            if node.value.func.attr != "append" or len(node.value.args) != 1:
                return None, f"accumulator method '{node.value.func.attr}' is not a readable append"
            writes.append(node.value.args[0])
        elif (
            isinstance(node, ast.AugAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == acc
        ):
            if not isinstance(node.op, ast.Add):
                return None, "accumulator augmented with a non-concatenation op"
            writes.append(node.value)
        elif (
            isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == acc for t in node.targets
            )
        ):
            return None, "accumulator reassigned inside the loop"
    if not writes:
        return None

    for src in writes:
        piece = _table_piece_chars(src, tree)
        if piece is None:
            return None, "accumulated piece is not a pinned-table element or string literal"
        ok, payload = piece
        if not ok:
            return None, payload
        chars.update(payload)
    return "".join(sorted(chars)), None


def _table_piece_chars(src: ast.expr, tree: ast.Module):
    """Chars contributed by one accumulated piece: a string literal, or
    TABLE[<expr>] over a stable pinned str/tuple-of-str table. Returns
    (True, chars) / (False, refusal-reason) / None (not piece-shaped)."""
    if isinstance(src, ast.Constant) and isinstance(src.value, str):
        return True, src.value
    if (
        isinstance(src, ast.Subscript)
        and isinstance(src.value, ast.Name)
        and not isinstance(src.slice, ast.Slice)
    ):
        name = src.value.id
        binding = None
        for stmt in tree.body:
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and stmt.targets[0].id == name
            ):
                if binding is not None:
                    return False, f"table '{name}' bound more than once"
                binding = stmt
        if binding is None:
            return False, f"table '{name}' has no module-level binding"
        candidate = _Candidate(
            name=name, value=binding.value, line=binding.lineno, confession=None
        )
        events = [e for e in _binding_events(tree) if e.name == name]
        failure = _admission_failure(
            candidate, events, _global_declarations(tree).get(name)
        )
        if failure is not None:
            return False, f"table '{name}' is not stable: {failure}"
        v = binding.value
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            return True, v.value
        if isinstance(v, ast.Tuple) and all(
            isinstance(el, ast.Constant) and isinstance(el.value, str)
            for el in v.elts
        ):
            return True, "".join(el.value for el in v.elts)
        return False, f"table '{name}' is not a str or tuple-of-str literal"
    return None


def _format_return_prefix(body: list) -> Optional[str]:
    """Census family return-format: a body whose last op is a string format
    (f-string, or "...".format(...)) starting with LITERAL text. The output
    is guaranteed to START WITH that literal prefix -- placeholders fill in
    after it, but the leading literal is invariant. Returns the non-empty
    prefix or None (format starts with a placeholder, or not a format)."""
    if not body or not isinstance(body[-1], ast.Return):
        return None
    value = body[-1].value
    if isinstance(value, ast.JoinedStr):
        if (
            value.values
            and isinstance(value.values[0], ast.Constant)
            and isinstance(value.values[0].value, str)
        ):
            return value.values[0].value or None
        return None
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "format"
        and isinstance(value.func.value, ast.Constant)
        and isinstance(value.func.value.value, str)
    ):
        import string

        try:
            first = next(string.Formatter().parse(value.func.value.value), None)
        except ValueError:
            return None
        return (first[0] if first else None) or None
    return None


def _table_subscript_shape(body: list) -> Optional[str]:
    """Match exactly one statement: return NAME[<expr>]. Returns NAME."""
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return None
    value = body[0].value
    if (
        isinstance(value, ast.Subscript)
        and isinstance(value.value, ast.Name)
        and not isinstance(value.slice, ast.Slice)
    ):
        return value.value.id
    return None


def _module_binding_tuple(
    tree: ast.Module, name: str
) -> Tuple[Optional[ast.Tuple], int]:
    binding: Optional[ast.Tuple] = None
    line = 0
    for stmt in tree.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and stmt.targets[0].id == name
        ):
            if binding is not None:
                return None, 0
            if isinstance(stmt.value, ast.Tuple):
                binding = stmt.value
                line = stmt.lineno
            else:
                return None, 0
    return binding, line


def _rstrip_return_shape(body: list) -> Optional[bytes]:
    """Match a body whose LAST statement is return <expr>.rstrip(<bytes
    literal>). rstrip totality makes preceding statements irrelevant to the
    no-trailing-chars claim. Returns the stripped bytes literal."""
    if not body or not isinstance(body[-1], ast.Return):
        return None
    value = body[-1].value
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "rstrip"
        and len(value.args) == 1
        and not value.keywords
        and isinstance(value.args[0], ast.Constant)
        and isinstance(value.args[0].value, bytes)
    ):
        return value.args[0].value
    return None


def _lstrip_return_shape(body: list) -> Optional[bytes]:
    """Match a body whose LAST statement is return <expr>.lstrip(<bytes
    literal>). lstrip totality makes preceding statements irrelevant to the
    no-leading-chars claim. Returns the stripped bytes literal."""
    if not body or not isinstance(body[-1], ast.Return):
        return None
    value = body[-1].value
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "lstrip"
        and len(value.args) == 1
        and not value.keywords
        and isinstance(value.args[0], ast.Constant)
        and isinstance(value.args[0].value, bytes)
    ):
        return value.args[0].value
    return None


def _replace_return_shape(body: list):
    """Match a body whose LAST statement is return <expr>.replace(FROM, TO)
    with FROM, TO single-character string literals. replace is total over
    its from-string, so a SINGLE-char replace removes that char from the
    output entirely (unless TO reintroduces it) -- the same complement
    guarantee as translate, no binding scan needed (literals inline).
    Returns (from_char, to_char) or None."""
    if not body or not isinstance(body[-1], ast.Return):
        return None
    value = body[-1].value
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "replace"
        and len(value.args) == 2
        and not value.keywords
        and all(
            isinstance(a, ast.Constant) and isinstance(a.value, str)
            and len(a.value) == 1
            for a in value.args
        )
    ):
        return value.args[0].value, value.args[1].value
    return None


def _translate_return_shape(body: list) -> Optional[str]:
    """Match exactly one statement: return <call>.translate(NAME).
    Returns NAME, or None when the body is not translate-shaped."""
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return None
    value = body[0].value
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "translate"
        and isinstance(value.func.value, ast.Call)
        and len(value.args) == 1
        and not value.keywords
        and isinstance(value.args[0], ast.Name)
    ):
        return value.args[0].id
    return None


def _module_binding_call(
    tree: ast.Module, name: str
) -> Tuple[Optional[ast.Call], int]:
    binding: Optional[ast.Call] = None
    line = 0
    for stmt in tree.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and stmt.targets[0].id == name
        ):
            if binding is not None:
                return None, 0
            if isinstance(stmt.value, ast.Call):
                binding = stmt.value
                line = stmt.lineno
            else:
                return None, 0
    return binding, line


def _maketrans_byte_literals(
    call: ast.Call,
) -> Optional[Tuple[bytes, bytes]]:
    func = call.func
    is_maketrans = (
        isinstance(func, ast.Attribute)
        and func.attr == "maketrans"
        and isinstance(func.value, ast.Name)
        and func.value.id in ("bytes", "bytearray")
    )
    if not is_maketrans or len(call.args) != 2 or call.keywords:
        return None
    frm, to = call.args
    if (
        isinstance(frm, ast.Constant)
        and isinstance(frm.value, bytes)
        and isinstance(to, ast.Constant)
        and isinstance(to.value, bytes)
    ):
        return frm.value, to.value
    return None
