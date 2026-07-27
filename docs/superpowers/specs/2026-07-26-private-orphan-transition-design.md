# Private Orphan Transition Detector Design

## Rule

Compare two Python source trees package by package. Report a finding only when
a private module-level definition exists in both trees, has at least one
syntax-authenticated reference in the before tree, and has zero such references
in the after tree. Deleting the definition together with its callers is lawful.
Definitions already unreferenced before the transition are outside the
population.

This is late telemetry. It is not enrolled in CI by this change.

## Syntax model

Parse Python with `ast`. A reference is a load of the definition name, an
attribute reference, an import or re-export, a string member of `__all__`, or a
string literal used as the attribute name in `getattr`, `setattr`, `hasattr`, or
`delattr`. Decorator registration, class/member attachment, and explicit
entry-point tables naturally contain load expressions and therefore count.
Reference locations retain package-relative path, line, and column so a finding
can name the lost before-tree sites.

The candidate population is module-level functions and classes whose names
begin with one underscore but are not magic names. Public names are excluded by
construction. Framework hooks and authenticated dynamic dispatch declarations
are excluded only when syntax proves the declaration: protocol/override or
framework decorators, fixture decorators, `__all__`, and authenticated dynamic
attribute operations. There is no symbol whitelist.

Package ownership comes from Python package roots under
`implementations/python/*/src`; references are counted across the whole owning
distribution, including its tests where present. A same-named private
definition in another package cannot satisfy the reference floor.

## Interface and output

The audit accepts `--before REV` and `--after REV`, reads both trees through
Git, and exits nonzero when findings exist. Each finding names the surviving
definition in the after tree and every lost reference site from the before
tree. Summary output reports the number of package transitions and orphan
transitions measured.

## Acceptance

Focused tests cover all six required cases:

1. `b7feb76b8` compared with itself keeps `_has_non_higher_order_return` green.
2. The real transition to `b273c4d05` is red and names both the helper and its
   deleted reference sites.
3. Removing the helper with its caller is green.
4. A newly exported or registered zero-direct-call definition is green.
5. Replacing a direct reference with a valid import/re-export is green.
6. Finding output names the changed definition and lost reference locations.

A second synthetic lying twin removes the caller of a different live private
helper and must report that helper, proving the audit is not specialized to the
historical symbol.

Before shipping, run the detector across recent real first-parent history. Ship
only if findings are few and each is explainable as the intended merge-loss
signature. Otherwise bank the negative result and stop without weakening the
detector.

## Constraints

- No CI wiring.
- No handwritten symbol whitelist or vendor arm.
- No broad local test or corpus run.
- Focused tests only, with `PYTHONUNBUFFERED=1` when using `bin/bpytest`.
- Capture command status before any output pipeline.
