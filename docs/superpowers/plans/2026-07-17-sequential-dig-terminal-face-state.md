# Sequential Dig Terminal Face State Implementation Plan

**Goal:** Construct exact dig-body selection from terminal reduced faces that
also carry branch-local state.

**Architecture:** Extend the reduced-outcome fold using `GuardedFaces`
exit/continuation testimony; never infer control flow from AST shape.

**Tech Stack:** Python 3.14, pytest, Sugar Python lift kit, Black 26.5.1.

## Constraints

- No `RuntimeEffect` or empty success.
- Continuing, opaque, and incomplete state stays loud.
- Preserve source-order guarded exit folding.
- Use only the worktree-local `.venv-lane`.

### Task 1: Red discrimination

- [x] Add a terminal-face local-state test that currently panics.
- [x] Add a continuing-face state bad twin.
- [x] Run the focused tests red.

### Task 2: Construction

- [x] Classify branch-local state from reduced face/guard testimony.
- [x] Keep all unproven mixed state on the existing loud path.
- [x] Run focused regression tests green.

### Task 3: Receipts

- [x] Replay the named NumPy representative and record conservation.
- [x] Run a fresh truthful/lying solver witness on final rebase.
- [x] Run the RuntimeEffect constructor census and Black 26.5.1.
- [ ] Commit, push, open a non-closing draft PR, then mark ready.
