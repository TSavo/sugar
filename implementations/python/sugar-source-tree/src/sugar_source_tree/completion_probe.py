"""PROBE (#5940): the probe subjects — If, While, the Call family, one BinOp.

These stand in for the kit's real sugars (``sugar_lift_py_tests.sugar.*``)
so the inversion can be measured in isolation. Each class documents what
the corresponding sugar's ``owns`` was, and what of it survived here.

Before / after, per subject
---------------------------

``IfSugar.owns``::

    return site.observed == "If"

becomes ``completes = If`` — the whole predicate was shape re-derivation,
and it is now the declaration. ``owns`` is DELETED, not stubbed.

``WhileSugar.owns``::

    if site.observed != "While": return False
    if site.while_orelse_count() != 0: return False
    return True

The shape leg becomes ``completes = While``. The orelse leg was never a
semantic question about THIS sugar — it was the boundary with
``WhileElseSugar``. Here the two are one closed family over ``While``,
partitioned by the node's own typed field: ``bool(node.orelse)``. The
partition is exhaustive by inspection (a tuple is empty or it is not),
so the gap arm is unreachable for While — measured below, not assumed.

``MethodCallSugar.owns``::

    site.observed == "Call"
    and site.call_receiver() is not None
    and site.call_qualified_target_name() != "os.exit"
    and not site.call_has_keywords()

Shape leg -> ``completes = Call``. Receiver leg -> ``isinstance(node.func,
Attribute)`` — the node already holds the answer as a typed field; the
three-step projection through call_receiver() is gone. The keyword leg is
the family boundary with KeywordCall, stated as the partition. The
``os.exit`` leg is deliberately NOT ported: it is a fact about ANOTHER
sugar's territory expressed as a name string, not a fact this node's
fields hold — the probe keeps it out and reports it as residue that would
have to live as one more family cell (an OsCall member refining on
``func.value.id == "os"``), exactly like len below.

Measurement CLI
---------------

::

    python -m sugar_source_tree.completion_probe PATH [PATH ...]

Walks every file, asks ``node.sugar()`` on every If/While/Call/BinOp
node, and reports resolved / gap counts per class and per completion.
Ambiguity and silence are both structural zeros: an ambiguous family
panics the RUN (it is a defect in the probe, not a row in the report),
and every subject node lands in exactly one bucket or the run dies.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import ClassVar, Optional

from .completion import Completion, CompletionAmbiguous, CompletionGap
from .nodes import Attribute, BinOp, Call, If, Name, Node, While
from .operators import Add
from .panic import SourceTreePanic
from .tree import SourceFile


# -- If: one completion, owns deleted ---------------------------------------


class IfCompletion(Completion):
    """``if``/``elif``/``else``. Sole: an If can only complete as if-shaped
    sugar. The old ``owns`` body (``site.observed == "If"``) is the
    declaration below; nothing else survived because nothing else existed.

    OUTCOME 1 RECEIPT: this class carries NO state — no fields, no
    ``new()`` construction work, nothing ``__init__``-shaped. The meaning
    side (IfSugar.desugar: reduce the test, then binary_conditional over
    the two bodies) is expressible entirely over node fields, shown by
    ``reduction`` below. A stateless all-classmethod class keyed to one
    node class is definitionally a method suite OF that node class:
    the collapse is ``If`` gaining these methods and this class ceasing
    to exist. IfSugar's fields (condition/then/else_body as SugarBody)
    are the node's test/body/orelse wrapped with a role — and the role
    is a function of grammar position the node class already states."""

    completes: ClassVar[type] = If

    @classmethod
    def reduction(cls, node: If) -> tuple:
        """The desugar plan, from node fields ALONE — the emptied-class
        demonstration. Roles are grammar positions: test is a TERM ask,
        the bodies are STATEMENT asks. Nothing here reads sugar-held
        state, because there is none to read."""
        return (
            "binary_conditional",
            ("term", node.test),
            ("statements", node.body),
            ("statements", node.orelse) if node.orelse else None,
        )


# -- While: a closed 2-family over one typed field --------------------------


class WhileCompletion(Completion):
    """``while`` with empty ``orelse`` — WhileSugar's territory."""

    completes: ClassVar[type] = While
    sole: ClassVar[bool] = False

    @classmethod
    def refines(cls, node: While) -> bool:
        return not node.orelse


class WhileElseCompletion(Completion):
    """``while ... else:`` — WhileElseSugar's territory. The other cell of
    the partition; together the two are exhaustive over While."""

    completes: ClassVar[type] = While
    sole: ClassVar[bool] = False

    @classmethod
    def refines(cls, node: While) -> bool:
        return bool(node.orelse)


# -- Call: the closed family, partitioned by the node's own fields ----------
#
# Partition coordinates, all fields the Call already holds:
#   keywords nonempty?            -> KeywordCall
#   func isinstance Attribute?    -> MethodCall
#   func isinstance Name, "len"?  -> LenCall
#   func isinstance Name, other?  -> PlainCall
#   func anything else, no kw     -> NOBODY: the gap arm, measured below
#     (computed callables: subscripted, called-result, lambda callees —
#      today's factory has ComputedCallableSugar etc.; the probe leaves
#      the cell open on purpose to exercise the gap arm on real corpus)


class KeywordCallCompletion(Completion):
    completes: ClassVar[type] = Call
    sole: ClassVar[bool] = False

    @classmethod
    def refines(cls, node: Call) -> bool:
        return bool(node.keywords)


class MethodCallCompletion(Completion):
    completes: ClassVar[type] = Call
    sole: ClassVar[bool] = False

    @classmethod
    def refines(cls, node: Call) -> bool:
        return not node.keywords and isinstance(node.func, Attribute)


class LenCallCompletion(Completion):
    completes: ClassVar[type] = Call
    sole: ClassVar[bool] = False

    @classmethod
    def refines(cls, node: Call) -> bool:
        func = node.func
        return not node.keywords and isinstance(func, Name) and func.id == "len"


class PlainCallCompletion(Completion):
    completes: ClassVar[type] = Call
    sole: ClassVar[bool] = False

    @classmethod
    def refines(cls, node: Call) -> bool:
        func = node.func
        return not node.keywords and isinstance(func, Name) and func.id != "len"


# -- BinOp: operand-type refinement via the node's typed op field -----------
#
# One member on purpose: every non-Add BinOp exercises the gap arm, which
# is the honest state of a probe that ported one of the operator sugars.


class AddOpCompletion(Completion):
    """``a + b``. Old owns: ``site.observed == "BinOp" and
    site.operator_kind() == "Add"`` — two string compares become the
    declaration plus one isinstance on the operator class the node holds."""

    completes: ClassVar[type] = BinOp
    sole: ClassVar[bool] = False

    @classmethod
    def refines(cls, node: BinOp) -> bool:
        return isinstance(node.op, Add)


PROBE_SUBJECTS: tuple[type, ...] = (If, While, Call, BinOp)


# -- measurement ------------------------------------------------------------


def measure(paths: list[Path], backend=None) -> int:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(
                f for f in sorted(p.rglob("*.py")) if "__pycache__" not in f.parts
            )
        else:
            files.append(p)
    files.sort()

    resolved: Counter[str] = Counter()  # completion name -> count
    gaps: Counter[str] = Counter()  # node class -> gap count
    subject_totals: Counter[str] = Counter()
    parse_failures = 0
    parsed = 0

    for path in files:
        try:
            file = SourceFile.from_path(path, backend=backend)
        except (SourceTreePanic, Exception) as err:  # parse-side, recorded loudly
            parse_failures += 1
            print(f"PARSE-FAIL {path}: {str(err).splitlines()[0]}", file=sys.stderr)
            continue
        parsed += 1
        for node in file.nodes():
            if not isinstance(node, PROBE_SUBJECTS):
                continue
            cls_name = type(node).__name__
            subject_totals[cls_name] += 1
            try:
                completion = node.sugar()
            except CompletionGap:
                gaps[cls_name] += 1  # the loud arm, counted — never silence
                continue
            # CompletionAmbiguous deliberately NOT caught: an ambiguous
            # family is a probe defect and must kill the run.
            resolved[completion.__name__] += 1

    total = sum(subject_totals.values())
    accounted = sum(resolved.values()) + sum(gaps.values())
    print(f"files parsed:   {parsed}  (parse failures: {parse_failures})")
    print(f"subject nodes:  {total}")
    for name, count in sorted(subject_totals.items()):
        print(f"  {name}: {count}")
    print(f"resolved:       {sum(resolved.values())}")
    for name, count in sorted(resolved.items()):
        print(f"  {name}: {count}")
    print(f"gap arm:        {sum(gaps.values())}")
    for name, count in sorted(gaps.items()):
        print(f"  {name}: {count}")
    print(f"ambiguous:      0 (an ambiguous family kills the run; it did not)")
    print(f"silent:         {total - accounted} (must be 0)")
    return 0 if total == accounted else 1


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)
    return measure(args.paths)


if __name__ == "__main__":
    sys.exit(main())
