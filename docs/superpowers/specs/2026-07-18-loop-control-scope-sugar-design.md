# Loop Control Scope Sugar Design

## Goal

Finish #5202 correctly by moving loop/control/break/comprehension scope
classification out of `factory/source_fragment.py` and into an explicit
`LoopControlScopeSugar` recognizer. Delete the factory walker and preserve all
existing classifications without suppression.

## Boundary

`SourceFragment` remains the raw Python grammar membrane: it may expose source
fragments and syntax facts, but it may not walk a tree to construct semantic
loop/control testimony. `LoopControlScopeSugar` owns the supported loop,
control-block, and comprehension-target shapes and produces the existing typed
`LoopControlScopeClassification`. The five current consumers call that Sugar
recognizer:

- `ForSugar`
- `ForElseSugar`
- `WhileSugar`
- `TrySugar`
- comprehension clause construction

Unsupported shapes stay unowned and loud. No effect, empty success, fallback,
or relocated factory helper is introduced.

## Side-door sweep

The PR inventories every `source_fragment.py` site matching the #5204 STEP 1
families:

- `isinstance(..., ast.*)`
- `ast.walk`
- `ast.NodeVisitor` / `ast.NodeTransformer`
- IR or floor-value construction
- `.reduce`

The loop/control classifier is promoted in this lane. Other matches are
reported by exact line and grouped as grammar access, annotation marking,
scope/data-flow classification, or construction. They are not silently blessed
merely because they live in the factory package.

## Verification

Red-first tests require:

1. `SourceFragment.classify_loop_control_scope` is absent.
2. `LoopControlScopeSugar` owns the loop, block, and comprehension-target
   shapes used by the current consumers.
3. Existing outer-break, finally-terminal, carried-name, mutation, and target
   binding testimony is conserved.
4. #5204 STEP 1's zero-tolerance instrument is green for
   `source_fragment.py` once the instrument lands.

All raise/error twins write testimony to files; terminal output contains only
test counts and offender tags.

## Scope

This PR promotes only the #5207 loop/control family. Every other discovered
side door is reported for follow-on STEP 2 lanes. The PR is non-closing and
uses `Part of #5207`.
