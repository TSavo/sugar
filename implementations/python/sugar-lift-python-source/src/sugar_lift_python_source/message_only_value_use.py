"""Sound, conservative reachability slice for unresolved import value-uses.

Manager receipt seating walks a frame's ENTIRE body, but a manager's exit
CONTRACT only depends on the value-uses that reach its suppress/raise decision
(a ``return`` value, a ``raise`` operand, or a control-flow ``test``).  An
unresolved value-use that reaches ONLY a failure-message attribute
(``self._fail_reason = ...``) never influences the contract, so voiding the
whole manager for it is spurious (pytest ``RaisesExc._check_match``'s
``_config.get_verbosity``).

``frame_value_use_is_message_only`` decides, for one value-use coordinate in a
frame, whether it is PROVABLY message-only.  Correctness is ONE-SIDED: a False
(abort, refuse as before) is always safe; a True (defer) must be sound — the
value must not be able to reach any decision/effect sink.  So this is a
conservative forward taint that ABORTS on anything it does not explicitly model
as benign.  It only ever enables the deferral; it never suppresses a real gap.

The benign terminal is an assignment to ``self.<attr>`` for ``attr`` in a small
declared MESSAGE-attribute allowlist — attributes that are, by the manager
contract, only ever read to build a human failure message, never to decide
suppression or the raised exception type.
"""

from __future__ import annotations

from typing import Tuple

# Self-attributes that hold ONLY a human failure message.  A value reaching
# solely one of these never influences the suppress/raise decision.  Grow this
# only for attributes verified message-only in the manager whose frame is being
# sliced; an over-broad entry would let an unresolved decision value construct.
MESSAGE_ATTR_ALLOWLIST = frozenset({"_fail_reason"})

Span = Tuple[int, int, int, int]


def _span_of(node) -> Span:
    s = node.line_col_span()
    return (s.start_line, s.start_col, s.end_line, s.end_col)


def _contains_span(node, span: Span) -> bool:
    """Whether ``span`` lies within ``node``'s own extent."""
    s = _span_of(node)
    return (s[0], s[1]) <= (span[0], span[1]) and (span[2], span[3]) <= (s[2], s[3])


def _iter_child_nodes(node):
    for _name, _idx, child in node.children():
        yield child


def _tainted_names_and_ok(
    statements, tainted_spans: set[Span], tainted_names: set[str]
) -> bool:
    """Forward-propagate taint across a straight-line/branching statement list.

    Returns True while every tainted value observed reaches ONLY a benign
    message sink; returns False the instant a tainted value could reach a
    decision/effect sink or any unmodelled construct.
    """
    from sugar_source_tree.nodes import (
        AnnAssign,
        Assign,
        Attribute,
        Expr,
        If,
        Name,
        Pass,
        Raise,
        Return,
        While,
    )

    def expr_is_tainted(expr) -> bool:
        # Tainted if it IS a marked coordinate, reads a tainted local Name, or
        # transitively contains a tainted subexpression (over-approximation).
        if _span_of(expr) in tainted_spans:
            return True
        if type(expr) is Name and expr.id in tainted_names:
            return True
        for child in _iter_child_nodes(expr):
            if expr_is_tainted(child):
                return True
        return False

    for stmt in statements:
        t = type(stmt)
        if t is Pass:
            continue
        if t in (Assign, AnnAssign):
            targets = stmt.targets if t is Assign else (stmt.target,)
            value = stmt.value
            if value is None:
                continue
            if not expr_is_tainted(value):
                continue
            # A tainted RHS: every target must be benign.
            for target in targets:
                if type(target) is Name:
                    # Taint flows into a local; keep tracking it.
                    tainted_names.add(target.id)
                    continue
                if (
                    type(target) is Attribute
                    and type(target.value) is Name
                    and target.value.id == "self"
                    and target.attr in MESSAGE_ATTR_ALLOWLIST
                ):
                    # Benign terminal: a declared message attribute absorbs it.
                    continue
                # Any other store of a tainted value (self.<decision>, subscript,
                # tuple-unpack, a non-self attribute) is not provably benign.
                return False
            continue
        if t is Expr:
            # A bare expression statement drops its value; a tainted call there
            # is only benign if it cannot escape — but a call may mutate through
            # its arguments, so refuse to prove benign.
            if expr_is_tainted(stmt.value):
                return False
            continue
        if t in (Return, Raise):
            # The decision/effect sinks themselves.
            operands = []
            if t is Return and stmt.value is not None:
                operands.append(stmt.value)
            if t is Raise:
                if stmt.exc is not None:
                    operands.append(stmt.exc)
                if stmt.cause is not None:
                    operands.append(stmt.cause)
            if any(expr_is_tainted(op) for op in operands):
                return False
            continue
        if t in (If, While):
            if expr_is_tainted(stmt.test):
                # A tainted value guards control flow -> decision-reaching.
                return False
            # Branch bodies must also stay benign; a taint set is monotonic, so
            # analyse each branch with the same accumulating names.
            branches = [stmt.body, getattr(stmt, "orelse", ())]
            for branch in branches:
                if not _tainted_names_and_ok(branch, tainted_spans, tainted_names):
                    return False
            continue
        # Any statement kind we do not model (For, With, Try, AugAssign, Return
        # inside comprehensions, yield, global/nonlocal, match, ...) could
        # observe a tainted value in a way this slice does not track.  Refuse to
        # prove message-only.
        if _statement_mentions_tainted(stmt, tainted_spans, tainted_names):
            return False
    return True


def _statement_mentions_tainted(stmt, tainted_spans, tainted_names) -> bool:
    from sugar_source_tree.nodes import Name

    def mentions(node) -> bool:
        if _span_of(node) in tainted_spans:
            return True
        if type(node) is Name and node.id in tainted_names:
            return True
        return any(mentions(child) for child in _iter_child_nodes(node))

    return mentions(stmt)


def frame_value_use_is_message_only(frame, use_span: Span) -> bool:
    """True iff the value-use at ``use_span`` PROVABLY reaches only a declared
    message sink within ``frame``'s body.

    Sound and one-sided: returns False (do not defer; refuse as before) whenever
    it cannot prove benignity.  Never returns True for a value that could reach
    a ``return``, ``raise``, or control-flow test.
    """
    body = getattr(frame, "body", None)
    if not body:
        return False
    # Seed the taint at the smallest enclosing expression whose VALUE is the
    # use.  We taint the exact coordinate; the callable's call result is tainted
    # transitively because the enclosing Call contains the tainted callee.
    tainted_spans = {tuple(use_span)}
    tainted_names: set[str] = set()
    try:
        return _tainted_names_and_ok(list(body), tainted_spans, tainted_names)
    except Exception:
        # Any structural surprise is a refusal to prove, never a silent defer.
        return False
