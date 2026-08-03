#!/usr/bin/env python3
"""R_construction_consumer_codomain — the fifth hierarchy-lie class, static.

## The class (brown, 2026-08-02)

Construction extended the live graph — new ConstructedTerm leaves, non-binding
unpack, GuardedBinding faces, If branch slots — while CONSUMING DOORS still
assumed the pre-extension closed set. Produce the new inhabitant, leave the
match/door on the old codomain → TypeError aborts the file and erases the
roster. Four instances, 159 files. Walking backwards from broken files found
them; this instrument finds them forwards.

## Question

WHICH TYPES CAN CONSTRUCTION PRODUCE THAT A CONSUMING SLOT CANNOT ACCEPT?

## Method (static AST — no corpus, no battleaxe)

1. **Produced set**
   - Classes whose bases transitively include ``ConstructedTermSugar``
   - Classes returned by ``_construct_sugar`` / sugar constructors as ``Name(...)``
   - Binding-state species: ``GuardedBinding``, ``UnboundBinding``,
     ``LoopProjectedBinding``, and classes joined in ``join_binding_state``
   - Node classes minted as expression currency when construction projects them

2. **Accepted set per door**
   - ``isinstance(x, T)`` / ``isinstance(x, (T, U, ...))`` type names in a
     function that also raises ``TypeError`` or ``SugarNotWritten`` on the
     foreign case (closed door with loud fallthrough)
   - ``require_constructed_term_sugar`` → accepts base ``ConstructedTermSugar``
     (all ConstructedTermSugar descendants covered)
   - ``kind in (...)`` / ``kind == "..."`` closed string sets in the same
     functions that raise on unknown kind

3. **Gap**
   - For a closed type-door: a produced type that is a *sibling* of an accepted
     type (shares an immediate or known family base) but is absent from the
     door's accepted set, and is not covered by a base that the door accepts
   - For a closed kind-door: a ``kind="X"`` literal produced in construction
     sources that never appears in any consumer closed kind set that already
     lists related kinds (Assign/For/… family) — reported as soft candidates

No baseline. Exit 1 while R > 0. Proven zero is legitimate green.

Usage::

    python scripts/construction_consumer_codomain_law.py
    python scripts/construction_consumer_codomain_law.py --python-root PATH
    python scripts/construction_consumer_codomain_law.py --json
"""

from __future__ import annotations

SCOREBOARD_AUTHORITY = False

import argparse
import ast
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterator, NamedTuple, Sequence

# ---------------------------------------------------------------------------
# Roots to scan (kit construction + consumers only)
# ---------------------------------------------------------------------------

# Focused roots: sugar mint package + binding-state / loop construction +
# Expression-currency nodes (ObjectPlaceStateV1 lives in nodes.py; without it
# the dynamic-discharge proxy cannot see Expression._construct_sugar mints).
# (Full sugar-source-tree/src is huge; fifth-lie doors live in these surfaces.)
_DEFAULT_PACKAGES = (
    "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar",
    "implementations/python/sugar-source-tree/src/sugar_source_tree/binding_state.py",
    "implementations/python/sugar-source-tree/src/sugar_source_tree/live_loop_construction.py",
    "implementations/python/sugar-source-tree/src/sugar_source_tree/loop_recurrence.py",
    # Expression._construct_sugar discharge mints (ObjectPlaceStateV1, …)
    "implementations/python/sugar-source-tree/src/sugar_source_tree/nodes.py",
)

# Families known to mint construction currency that doors must totalize over.
_BINDING_STATE_FAMILY = frozenset(
    {
        "Node",
        "UnboundBinding",
        "GuardedBinding",
        "LoopProjectedBinding",
        "BoundBindingStateV1",
        "GuardedBindingStateV1",
        "UnboundBindingStateV1",
        "LoopProjectedBinding",
        "BindingEntryV1",
        "ObjectPlaceStateV1",
    }
)

_CONSTRUCTED_TERM_ROOT = "ConstructedTermSugar"
_SUGAR_ROOT = "Sugar"

_LOUD_RAISES = frozenset({"TypeError", "SugarNotWritten", "ValueError", "RuntimeError"})


class Gap(NamedTuple):
    axis: str
    door: str
    door_path: str
    door_line: int
    produced: str
    accepted: tuple[str, ...]
    note: str
    fix: str

    def to_dict(self) -> dict[str, object]:
        return {
            "axis": self.axis,
            "door": self.door,
            "door_path": self.door_path,
            "door_line": self.door_line,
            "produced": self.produced,
            "accepted": list(self.accepted),
            "note": self.note,
            "fix": self.fix,
        }


class ModuleIndex:
    __slots__ = (
        "path",
        "tree",
        "classes",
        "class_lines",
        "construct_returns",
        "kind_literals",
        # (owner_class, returned_sugar_name, line) for Expression-ish _construct_sugar
        "expression_construct_mints",
    )

    def __init__(self, path: Path, tree: ast.AST) -> None:
        self.path = path
        self.tree = tree
        self.classes: dict[str, set[str]] = {}
        self.class_lines: dict[str, int] = {}
        self.construct_returns: dict[str, set[str]] = defaultdict(set)
        self.kind_literals: set[str] = set()
        self.expression_construct_mints: list[tuple[str, str, int]] = []


def _iter_py_files(roots: Sequence[Path]) -> Iterator[Path]:
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            yield root
            continue
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path


def _base_names(bases: list[ast.expr]) -> set[str]:
    names: set[str] = set()
    for base in bases:
        if isinstance(base, ast.Name):
            names.add(base.id)
        elif isinstance(base, ast.Attribute):
            names.add(base.attr)
    return names


def _name_of(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _isinstance_types(call: ast.Call) -> set[str] | None:
    """Return type names from isinstance(x, T) / isinstance(x, (T, U))."""
    if not isinstance(call.func, ast.Name) or call.func.id != "isinstance":
        return None
    if len(call.args) < 2:
        return None
    second = call.args[1]
    names: set[str] = set()
    if isinstance(second, (ast.Tuple, ast.List)):
        for elt in second.elts:
            n = _name_of(elt)
            if n:
                names.add(n)
    else:
        n = _name_of(second)
        if n:
            names.add(n)
    return names or None


def index_module(path: Path) -> ModuleIndex | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return None
    idx = ModuleIndex(path=path, tree=tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            idx.classes[node.name] = _base_names(node.bases)
            idx.class_lines[node.name] = node.lineno
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if item.name not in {"_construct_sugar", "sugar"}:
                    continue
                for sub in ast.walk(item):
                    if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Call):
                        n = _name_of(sub.value.func)
                        if n:
                            idx.construct_returns[node.name].add(n)
                            # Record mint line for expression-currency scan later
                            # once inheritance of owner is known (second pass).
                            idx.expression_construct_mints.append(
                                (node.name, n, item.lineno)
                            )
        # kind="X" / kind='X' string literals on keyword or compare
        if isinstance(node, ast.keyword) and node.arg == "kind":
            if isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, str
            ):
                idx.kind_literals.add(node.value.value)
        if isinstance(node, ast.Compare):
            left = node.left
            if isinstance(left, ast.Attribute) and left.attr == "kind":
                for op, comp in zip(node.ops, node.comparators):
                    if (
                        isinstance(op, (ast.Eq, ast.NotEq))
                        and isinstance(comp, ast.Constant)
                        and isinstance(comp.value, str)
                    ):
                        idx.kind_literals.add(comp.value)
                    if isinstance(op, (ast.In, ast.NotIn)):
                        if isinstance(comp, (ast.Tuple, ast.List, ast.Set)):
                            for elt in comp.elts:
                                if isinstance(elt, ast.Constant) and isinstance(
                                    elt.value, str
                                ):
                                    idx.kind_literals.add(elt.value)
    return idx


def transitive_bases(
    classes: dict[str, set[str]], name: str, *, cache: dict[str, set[str]]
) -> set[str]:
    if name in cache:
        return cache[name]
    # Placeholder first so inheritance cycles cannot recurse forever.
    cache[name] = set()
    direct = classes.get(name, set())
    acc = set(direct)
    for b in direct:
        acc |= transitive_bases(classes, b, cache=cache)
    cache[name] = acc
    return acc


def all_descendants(classes: dict[str, set[str]], root: str) -> set[str]:
    cache: dict[str, set[str]] = {}
    out: set[str] = set()
    for name in classes:
        if root in transitive_bases(classes, name, cache=cache) or name == root:
            out.add(name)
    return out


class ClosedDoor(NamedTuple):
    path: str
    line: int
    func: str
    accepted_types: frozenset[str]
    accepts_base: frozenset[str]  # bases that cover all descendants
    raises: frozenset[str]
    kind_set: frozenset[str]


def _function_raises_loud(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            n = _name_of(node.exc.func)
            if n in _LOUD_RAISES:
                names.add(n)
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Name):
            if node.exc.id in _LOUD_RAISES:
                names.add(node.exc.id)
    return names


def _function_kind_sets(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    kinds: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Compare):
            continue
        left = node.left
        if not (isinstance(left, ast.Attribute) and left.attr == "kind"):
            continue
        for op, comp in zip(node.ops, node.comparators):
            if isinstance(op, ast.Eq) and isinstance(comp, ast.Constant):
                if isinstance(comp.value, str):
                    kinds.add(comp.value)
            if isinstance(op, ast.In) and isinstance(
                comp, (ast.Tuple, ast.List, ast.Set)
            ):
                for elt in comp.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        kinds.add(elt.value)
    return kinds


def collect_closed_doors(
    indexes: Sequence[ModuleIndex], repo: Path
) -> list[ClosedDoor]:
    doors: list[ClosedDoor] = []
    for idx in indexes:
        for node in ast.walk(idx.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            raises = _function_raises_loud(node)
            if not raises:
                continue
            accepted: set[str] = set()
            accepts_base: set[str] = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    types = _isinstance_types(sub)
                    if types:
                        accepted |= types
                        # require_constructed_term_sugar is a named base door
                    if (
                        isinstance(sub.func, ast.Name)
                        and sub.func.id == "require_constructed_term_sugar"
                    ):
                        accepts_base.add(_CONSTRUCTED_TERM_ROOT)
                        accepted.add(_CONSTRUCTED_TERM_ROOT)
                    if isinstance(sub.func, ast.Attribute) and sub.func.attr == (
                        "require_constructed_term_sugar"
                    ):
                        accepts_base.add(_CONSTRUCTED_TERM_ROOT)
                        accepted.add(_CONSTRUCTED_TERM_ROOT)
            # isinstance(value, ConstructedTermSugar) pattern
            if _CONSTRUCTED_TERM_ROOT in accepted:
                accepts_base.add(_CONSTRUCTED_TERM_ROOT)
            kind_set = _function_kind_sets(node)
            # Closed door: loud raise + (type arms or kind arms)
            if not accepted and not kind_set:
                continue
            # Fifth-lie doors only: binding-state read/project currency and
            # require_constructed_term_sugar. Per-sugar __post_init__/desugar
            # field checks are intentional narrow slots, not closed-family
            # codomains that lag construction.
            _FIFTH_LIE_DOORS = {
                "binding_state_read_node",
                "_construct_binding_projection",
                "require_constructed_term_sugar",
                "join_binding_state",
                "project_loop_post_binding",
                "unwrap_binding_state",
            }
            # Binding-state *currency* species — not bare Node (every walker
            # accepts Node; _substitute_field is substitution plumbing, not a
            # construction→consumer codomain door).
            _BINDING_CURRENCY = {
                "UnboundBinding",
                "GuardedBinding",
                "LoopProjectedBinding",
            }
            is_named = node.name in _FIFTH_LIE_DOORS or (
                "binding_state_read" in node.name
            )
            is_binding_currency_door = bool(accepted & _BINDING_CURRENCY) and (
                "TypeError" in raises or "SugarNotWritten" in raises
            )
            is_require_term = (
                "require_constructed_term" in node.name
                or _CONSTRUCTED_TERM_ROOT in accepts_base
                or _CONSTRUCTED_TERM_ROOT in accepted
            )
            if not (is_named or is_binding_currency_door or is_require_term):
                continue
            # Drop pure field __post_init__ on individual sugars unless named.
            if node.name in {"__post_init__", "desugar", "leaf_sugar", "append_field"}:
                if not is_named and not is_binding_currency_door:
                    continue
            rel = (
                str(idx.path.relative_to(repo))
                if idx.path.is_relative_to(repo)
                else str(idx.path)
            )
            doors.append(
                ClosedDoor(
                    path=rel,
                    line=node.lineno,
                    func=node.name,
                    accepted_types=frozenset(accepted),
                    accepts_base=frozenset(accepts_base),
                    raises=frozenset(raises),
                    kind_set=frozenset(kind_set),
                )
            )
    return doors


def collect_produced(
    indexes: Sequence[ModuleIndex],
    classes: dict[str, set[str]],
) -> tuple[set[str], set[str], set[str]]:
    """Return (constructed_term_types, binding_state_types, construct_minted)."""
    cache: dict[str, set[str]] = {}
    constructed = all_descendants(classes, _CONSTRUCTED_TERM_ROOT)

    minted: set[str] = set()
    for idx in indexes:
        for owner, rets in idx.construct_returns.items():
            for r in rets:
                minted.add(r)
                # Only inheritance-proven ConstructedTermSugar descendants count
                # as term currency. Adding every Sugar mint here hid
                # ConstructedObjectPlaceSugar (Sugar-not-term) from both axes.
                if r not in constructed and r in classes:
                    bases = transitive_bases(classes, r, cache=cache) | {r}
                    if _CONSTRUCTED_TERM_ROOT in bases:
                        constructed.add(r)

    binding: set[str] = set()
    for name in classes:
        if name in _BINDING_STATE_FAMILY:
            binding.add(name)
        bases = transitive_bases(classes, name, cache=cache)
        if bases & _BINDING_STATE_FAMILY or name in _BINDING_STATE_FAMILY:
            # only keep leaf-ish known family names to avoid noise
            if name in _BINDING_STATE_FAMILY or any(
                b in _BINDING_STATE_FAMILY for b in bases
            ):
                if (
                    name.endswith("Binding")
                    or name.endswith("State")
                    or name.endswith("StateV1")
                    or name in _BINDING_STATE_FAMILY
                ):
                    binding.add(name)

    # Explicit family always produced
    binding |= _BINDING_STATE_FAMILY & set(classes.keys())
    # Always include the four core species even if only imported
    binding |= {
        "UnboundBinding",
        "GuardedBinding",
        "LoopProjectedBinding",
        "Node",
    }

    return constructed, binding, minted


def sibling_gap(
    produced: str,
    accepted: frozenset[str],
    accepts_base: frozenset[str],
    classes: dict[str, set[str]],
    family_roots: set[str],
) -> bool:
    """True when produced is in family, not covered by accepted or a base door."""
    cache: dict[str, set[str]] = {}
    prod_bases = transitive_bases(classes, produced, cache=cache) | {produced}
    if accepts_base & prod_bases:
        return False  # base door covers
    if produced in accepted:
        return False
    # covered if any accepted type is a base of produced
    for a in accepted:
        if a in prod_bases:
            return False
    # in family if shares a family root with any accepted type
    if not (prod_bases & family_roots) and produced not in family_roots:
        # also treat ConstructedTermSugar descendants as family
        if _CONSTRUCTED_TERM_ROOT not in prod_bases and produced not in family_roots:
            return False
    # accepted set mentions something in the same family
    family_hit = False
    for a in accepted:
        a_bases = transitive_bases(classes, a, cache=cache) | {a}
        if a_bases & family_roots or a in family_roots:
            family_hit = True
            break
        if _CONSTRUCTED_TERM_ROOT in a_bases or a == _CONSTRUCTED_TERM_ROOT:
            family_hit = True
            break
    if not family_hit and produced not in family_roots:
        # door is not about this family
        return False
    return True


def find_expression_mint_not_term_gaps(
    indexes: Sequence[ModuleIndex],
    classes: dict[str, set[str]],
    constructed_terms: set[str],
    *,
    repo: Path | None = None,
) -> list[Gap]:
    """Dynamic-path static proxy: Expression._construct_sugar mints non-term Sugar.

    AttributeSugar.receiver and peer slots require ConstructedTermSugar at
    discharge. If an Expression node mints a Sugar that is NOT a
    ConstructedTermSugar descendant, the require door TypeErrors at runtime
    while pure isinstance-sibling scans report R=0 (the mint is outside the
    term hierarchy entirely). That is the ConstructedObjectPlaceSugar class —
    sealed board fifth lie on tests/frame/test_arithmetic.py.

    Reach: static AST of Expression-ish ``_construct_sugar`` return Call
    targets. Does NOT follow dynamic getattr/factory variables — those remain
    runtime-only (require_constructed_term_sugar TypeError + board discharge).
    """
    gaps: list[Gap] = []
    cache: dict[str, set[str]] = {}
    expression_roots = {"Expression", "expr"}  # Node expression currency
    sugar_desc = all_descendants(classes, _SUGAR_ROOT)
    # HONEST term set only: inheritance-proven ConstructedTermSugar descendants.
    # Do NOT union with every *Sugar mint name — that hid ObjectPlace pre-promote.
    term_desc = set(constructed_terms) | all_descendants(
        classes, _CONSTRUCTED_TERM_ROOT
    )
    # Re-filter: only names whose bases include ConstructedTermSugar (or are it).
    honest_terms: set[str] = set()
    for name in term_desc:
        bases = transitive_bases(classes, name, cache=cache) | {name}
        if _CONSTRUCTED_TERM_ROOT in bases or name == _CONSTRUCTED_TERM_ROOT:
            honest_terms.add(name)
    term_desc = honest_terms

    for idx in indexes:
        if repo is not None and idx.path.is_relative_to(repo):
            rel = str(idx.path.relative_to(repo))
        else:
            rel = str(idx.path)
        for owner, minted, line in idx.expression_construct_mints:
            owner_bases = transitive_bases(classes, owner, cache=cache) | {owner}
            # Only Expression / expression-state construction currency.
            # Statement sugars (FunctionDef, Assert, …) are not Attribute receivers.
            if not (owner_bases & expression_roots) and "Expression" not in owner_bases:
                if not (
                    owner.endswith("StateV1")
                    or owner.endswith("State")
                    or "Place" in owner
                    or "Expression" in owner
                ):
                    continue
            if minted not in sugar_desc and not minted.endswith("Sugar"):
                continue
            if minted in term_desc or minted == _CONSTRUCTED_TERM_ROOT:
                continue
            # Minted sugar that is not ConstructedTermSugar
            minted_bases = transitive_bases(classes, minted, cache=cache) | {minted}
            if _CONSTRUCTED_TERM_ROOT in minted_bases:
                continue
            # Only construction-currency mints: names that claim nested term
            # testimony (Constructed*, *Place*, *Receiver*). Effect/suspension
            # sugars (YieldSuspensionSugar, YieldFromSugar, …) intentionally
            # sit outside CTS — GeneratorConstructionV1 only. Flagging them as
            # "promote" is a lie; they are refuse-named by design.
            if not _claims_construction_currency(minted):
                continue
            gaps.append(
                Gap(
                    axis="R_expression_construct_not_term",
                    door=f"{owner}._construct_sugar",
                    door_path=rel,
                    door_line=line,
                    produced=minted,
                    accepted=(_CONSTRUCTED_TERM_ROOT,),
                    note=(
                        f"{owner}._construct_sugar mints {minted}, which claims "
                        f"construction currency (Constructed*/Place/Receiver) but "
                        f"is not ConstructedTermSugar. Nested slots "
                        f"(AttributeSugar.receiver, BinOpSugar, …) call "
                        f"require_constructed_term_sugar and TypeError at discharge "
                        f"— dynamic path invisible to pure sibling isinstance scans."
                    ),
                    fix=(
                        f"promote {minted} to ConstructedTermSugar + to_term "
                        f"(slots are truthful; mint missing the base — same as #7099) "
                        f"OR rename/refuse if it is not nested-construction testimony"
                    ),
                )
            )
    return gaps


def _claims_construction_currency(minted: str) -> bool:
    """Heuristic: mint name asserts nested-construction / place / receiver currency.

    ObjectPlace fifth lie: ConstructedObjectPlaceSugar. Peer: ConstructedReceiverRefSugar.
    YieldSuspensionSugar does NOT claim this — suspension boundary only.
    """
    if minted.startswith("Constructed"):
        return True
    if "Place" in minted or "Receiver" in minted:
        return True
    if minted.endswith("PlaceSugar") or minted.endswith("ReceiverSugar"):
        return True
    return False


def find_gaps(
    doors: Sequence[ClosedDoor],
    constructed: set[str],
    binding: set[str],
    classes: dict[str, set[str]],
    kind_literals: set[str],
    indexes: Sequence[ModuleIndex] | None = None,
    *,
    repo: Path | None = None,
) -> list[Gap]:
    gaps: list[Gap] = []
    term_family = {_CONSTRUCTED_TERM_ROOT, _SUGAR_ROOT}
    binding_family = set(_BINDING_STATE_FAMILY)

    if indexes is not None:
        gaps.extend(
            find_expression_mint_not_term_gaps(indexes, classes, constructed, repo=repo)
        )

    # Core binding-state currency (what binding_state_read_node must totalize).
    binding_core = frozenset(
        {
            "Node",
            "UnboundBinding",
            "GuardedBinding",
            "LoopProjectedBinding",
        }
    )

    for door in doors:
        # Type codomain gaps
        if door.accepted_types or door.accepts_base:
            # Base door ConstructedTermSugar totalizes every ConstructedTerm leaf —
            # that is the correct codomain for require_constructed_term_sugar.
            if door.accepts_base & {_CONSTRUCTED_TERM_ROOT}:
                pass  # no ConstructedTerm type gaps on this door
            else:
                candidates: set[str] = set()
                # Closed list of specific *Sugar types without the base: every
                # ConstructedTermSugar leaf is a sibling candidate.
                accepted_sugars = {
                    a for a in door.accepted_types if a.endswith("Sugar")
                }
                if (
                    accepted_sugars
                    and _CONSTRUCTED_TERM_ROOT not in door.accepted_types
                ):
                    candidates |= {
                        c
                        for c in constructed
                        if c.endswith("Sugar") and c != _CONSTRUCTED_TERM_ROOT
                    }
                # Binding-state doors: only the core read currency species.
                if door.accepted_types & binding_core or door.func in {
                    "binding_state_read_node",
                    "_construct_binding_projection",
                }:
                    candidates |= set(binding_core) | (binding & binding_core)
                    # Also any extra Binding* produced in the family that is
                    # clearly a state species construction can mint.
                    candidates |= {
                        b
                        for b in binding
                        if b.endswith("Binding") and not b.endswith("EntryV1")
                    }

                for prod in sorted(candidates):
                    if sibling_gap(
                        prod,
                        door.accepted_types,
                        door.accepts_base,
                        classes,
                        term_family | binding_family | set(binding_core),
                    ):
                        gaps.append(
                            Gap(
                                axis="R_construction_consumer_codomain_gap",
                                door=door.func,
                                door_path=door.path,
                                door_line=door.line,
                                produced=prod,
                                accepted=tuple(
                                    sorted(door.accepted_types | door.accepts_base)
                                ),
                                note=(
                                    f"construction can produce {prod}; door "
                                    f"{door.func} accepts only "
                                    f"{sorted(door.accepted_types | door.accepts_base)} "
                                    f"and raises {sorted(door.raises)}"
                                ),
                                fix=(
                                    f"add {prod} to the isinstance/match arms of "
                                    f"{door.func} (or accept a base that covers it); "
                                    f"never leave a TypeError fallthrough that aborts "
                                    f"the file roster"
                                ),
                            )
                        )

        # Kind codomain (narrow): only doors that both (a) close a kind set of
        # size >= 4 and (b) raise TypeError — grammar arms that abort. Report
        # produced Node-class kinds missing from that set, capped per door.
        if len(door.kind_set) >= 4 and "TypeError" in door.raises:
            missing = sorted(
                k
                for k in kind_literals
                if k not in door.kind_set and k[:1].isupper() and k in classes
            )
            for k in missing[:12]:
                gaps.append(
                    Gap(
                        axis="R_kind_dispatch_codomain_gap",
                        door=door.func,
                        door_path=door.path,
                        door_line=door.line,
                        produced=k,
                        accepted=tuple(sorted(door.kind_set)),
                        note=(
                            f"kind {k!r} is a known Node class and appears in "
                            f"source; door {door.func} closed kind set omits it "
                            f"and raises TypeError"
                        ),
                        fix=(
                            f"add kind {k!r} to {door.func} closed set or refuse "
                            f"it with a named typed gap - not TypeError"
                        ),
                    )
                )
    return gaps


def merge_classes(indexes: Sequence[ModuleIndex]) -> dict[str, set[str]]:
    classes: dict[str, set[str]] = {}
    for idx in indexes:
        for name, bases in idx.classes.items():
            classes.setdefault(name, set()).update(bases)
    return classes


def run(roots: Sequence[Path], repo: Path) -> tuple[list[Gap], dict[str, object]]:
    indexes: list[ModuleIndex] = []
    for path in _iter_py_files(roots):
        idx = index_module(path)
        if idx is not None:
            indexes.append(idx)
    classes = merge_classes(indexes)
    constructed, binding, minted = collect_produced(indexes, classes)
    # Do NOT union every *Sugar mint into constructed. That lie hid
    # ConstructedObjectPlaceSugar (Sugar, not ConstructedTermSugar) from both
    # sibling and expression-mint axes. Only inheritance-proven CTS counts.
    # Unresolved imported bases: keep only names already in `constructed`
    # via all_descendants (which requires a known base edge in this scan).
    doors = collect_closed_doors(indexes, repo)
    kind_literals: set[str] = set()
    for idx in indexes:
        kind_literals |= idx.kind_literals
    gaps = find_gaps(
        doors,
        constructed,
        binding,
        classes,
        kind_literals,
        indexes=indexes,
        repo=repo,
    )
    # Dedup by (door, produced, axis)
    uniq: dict[tuple[str, str, str, int], Gap] = {}
    for g in gaps:
        key = (g.axis, g.door, g.produced, g.door_line)
        uniq[key] = g
    ordered = sorted(
        uniq.values(), key=lambda g: (g.axis, g.door_path, g.door_line, g.produced)
    )
    summary = {
        "modules_indexed": len(indexes),
        "classes": len(classes),
        "constructed_term_types": len(constructed),
        "binding_state_types": len(sorted(binding)),
        "construct_minted": len(minted),
        "closed_doors": len(doors),
        "kind_literals": len(kind_literals),
        "R_construction_consumer_codomain_gap": sum(
            1 for g in ordered if g.axis == "R_construction_consumer_codomain_gap"
        ),
        "R_kind_dispatch_codomain_gap": sum(
            1 for g in ordered if g.axis == "R_kind_dispatch_codomain_gap"
        ),
        "R_expression_construct_not_term": sum(
            1 for g in ordered if g.axis == "R_expression_construct_not_term"
        ),
        "R_total": len(ordered),
    }
    return ordered, summary


def discrimination_self_test() -> bool:
    """Plant lagging doors; prove the instrument goes red then clean.

    Two planted shapes:
    1. binding_state_read_node lagging LoopProjectedBinding (sibling isinstance).
    2. Expression._construct_sugar minting Sugar-not-CTS (dynamic-discharge
       proxy — sealed-board ObjectPlace fifth lie).
    """
    import tempfile

    planted = '''
class GuardedBinding:
    pass

class LoopProjectedBinding:
    """Construction can mint this after loop projection was enrolled."""
    pass

class Node:
    pass

def binding_state_read_node(state):
    if isinstance(state, GuardedBinding):
        return state
    raise TypeError(
        f"binding_state_read_node: got {type(state).__name__}; "
        f"write arm for LoopProjectedBinding"
    )
'''
    clean = """
class GuardedBinding:
    pass

class LoopProjectedBinding:
    pass

class UnboundBinding:
    pass

class Node:
    pass

def binding_state_read_node(state):
    if isinstance(state, Node):
        return state
    if isinstance(state, (UnboundBinding, GuardedBinding)):
        return state
    if isinstance(state, LoopProjectedBinding):
        return state
    raise SugarNotWritten(
        owner="binding_state_read_node",
        blame="unknown",
        observed=type(state).__name__,
        requested="Node|Unbound|Guarded|LoopProjected",
        fix="write arm",
    )
"""
    # Dynamic-discharge proxy plant: Expression mints Sugar outside CTS.
    planted_expr = '''
class Sugar:
    pass

class ConstructedTermSugar(Sugar):
    pass

class Expression:
    pass

class ConstructedObjectPlaceSugar(Sugar):
    """Object place claimed as construction currency but not a term."""
    pass

class ObjectPlaceStateV1(Expression):
    def _construct_sugar(self):
        return ConstructedObjectPlaceSugar()
'''
    clean_expr = '''
class Sugar:
    pass

class ConstructedTermSugar(Sugar):
    pass

class Expression:
    pass

class ConstructedObjectPlaceSugar(ConstructedTermSugar):
    """Promoted: object place IS nested-construction testimony."""
    pass

class ObjectPlaceStateV1(Expression):
    def _construct_sugar(self):
        return ConstructedObjectPlaceSugar()
'''
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        fixture = root / "binding_state.py"
        fixture.write_text(planted, encoding="utf-8")
        red_gaps, red_summary = run((root,), root)
        fixture.write_text(clean, encoding="utf-8")
        green_gaps, green_summary = run((root,), root)

        expr_root = root / "expr_mint"
        expr_root.mkdir()
        expr_fixture = expr_root / "nodes.py"
        expr_fixture.write_text(planted_expr, encoding="utf-8")
        red_expr_gaps, red_expr_summary = run((expr_root,), root)
        expr_fixture.write_text(clean_expr, encoding="utf-8")
        green_expr_gaps, green_expr_summary = run((expr_root,), root)

    red_ok = red_summary["R_total"] >= 1 and any(
        g.produced == "LoopProjectedBinding" for g in red_gaps
    )
    green_ok = green_summary["R_total"] == 0
    expr_red_ok = red_expr_summary.get(
        "R_expression_construct_not_term", 0
    ) >= 1 and any(
        g.produced == "ConstructedObjectPlaceSugar"
        and g.axis == "R_expression_construct_not_term"
        for g in red_expr_gaps
    )
    expr_green_ok = green_expr_summary["R_total"] == 0
    return red_ok and green_ok and expr_red_ok and expr_green_ok


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="repository root (default: four parents up from this script)",
    )
    parser.add_argument(
        "--python-root",
        type=Path,
        action="append",
        default=None,
        help="extra package root or .py file to scan (repeatable)",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="discrimination twin: planted lagging door red; total door green",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.self_test:
        ok = discrimination_self_test()
        print("CONSTRUCTION-CONSUMER-CODOMAIN SELF-TEST " + ("GREEN" if ok else "RED"))
        print(
            json.dumps(
                {
                    "instrument": "R_construction_consumer_codomain",
                    "self_test": ok,
                }
            )
        )
        return 0 if ok else 1

    script = Path(__file__).resolve()
    repo = args.repo_root or script.parents[4]
    roots = [repo / p for p in _DEFAULT_PACKAGES]
    if args.python_root:
        roots.extend(args.python_root)

    gaps, summary = run(roots, repo)

    if args.json:
        print(
            json.dumps(
                {"summary": summary, "gaps": [g.to_dict() for g in gaps]},
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print("construction_consumer_codomain_law")
        print(
            f"  modules={summary['modules_indexed']} classes={summary['classes']} "
            f"constructed_term_types={summary['constructed_term_types']} "
            f"binding_state_types={summary['binding_state_types']} "
            f"closed_doors={summary['closed_doors']}"
        )
        print(
            f"  R_construction_consumer_codomain_gap="
            f"{summary['R_construction_consumer_codomain_gap']}"
        )
        print(
            f"  R_kind_dispatch_codomain_gap="
            f"{summary['R_kind_dispatch_codomain_gap']}"
        )
        print(
            f"  R_expression_construct_not_term="
            f"{summary['R_expression_construct_not_term']}"
        )
        print(f"  R_total={summary['R_total']}")
        if gaps:
            print()
            for g in gaps[:80]:
                print(
                    f"  [{g.axis}] {g.door_path}:{g.door_line} {g.door} "
                    f"produced={g.produced}"
                )
                print(f"    accepted={list(g.accepted)}")
                print(f"    note: {g.note}")
                print(f"    fix:  {g.fix}")
            if len(gaps) > 80:
                print(f"  ... {len(gaps) - 80} more")
        else:
            print()
            print("  ZERO IS BANKABLE EVIDENCE, NOT ABSENCE OF AN INSTRUMENT.")
            print(
                "  R_total=0 under THIS instrument reach (static AST on enrolled"
                " doors + Expression._construct_sugar mint→term proxy)."
                ' Not "the class is closed forever" — remaining gaps may still'
                " be dynamic-only (getattr factories, runtime type mutations)."
                " Those are caught by require_constructed_term_sugar TypeError"
                " at discharge and sealed-board twins, not by this scan."
            )

    return 1 if gaps else 0


if __name__ == "__main__":
    raise SystemExit(main())
