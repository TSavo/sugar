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

## Hardened structural-only scope

T's hardened ruling supersedes the earlier follow-on split. This PR promotes
every meaning-bearing classifier discovered in `SourceFragment`, not only the
loop/control family.

`SourceFragment` may return a child `SourceFragment`, a list/block of child
fragments, source position, or a raw structural token needed for catalog
selection. It may not decide annotation meaning, qualified-call identity,
binding shape, exception meaning, operator/literal meaning, pytest parameter
meaning, or whole-scope name flow.

The baseline-free instrument derives offenders from behavior: a raw AST
classifier/walker/visitor whose result is not a structural fragment projection
is red. It reports every live function and stays red until the semantic count
is zero; no accepted baseline or count threshold exists.

Semantic families promote to registered Sugars that already terminate in
cited construction or a genuine typed effect:

- annotation context to `AnnotationUnionSugar` and runtime operator Sugars;
- call/qualified-name identity to Call-family Sugars;
- assignment and binding targets to Assign/For/With-family Sugars;
- exception handler types to `TrySugar`;
- Boolean/format literal meaning to `BoolOpSugar` and format Sugars;
- pytest literal parameter rows to `TestFunctionDefSugar`;
- whole-scope name flow to constructor and loop-control Sugars.

Each owner carries a good witness and provenance-matched bad twin. A recognizer
may decline ownership; it may not claim and then return `Incomplete`. The PR
remains non-closing and uses `Part of #5207`.
