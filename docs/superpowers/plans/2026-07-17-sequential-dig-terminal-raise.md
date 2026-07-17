# Sequential Dig Terminal Raise Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Select an exact terminal exceptional exit as a dig-body fallback.

**Architecture:** Extend the existing reduced-outcome fold; never inspect AST
control flow.

**Tech Stack:** Python 3.14, pytest, Sugar Python lift kit, Black 26.5.1.

## Global Constraints

- No RuntimeEffect or empty success.
- Mixed and incomplete outcomes remain loud.
- Preserve source-order guard folding.
- Use the worktree-local `.venv-lane`.

### Task 1: Terminal raise fallback

- [ ] Add a red guarded-return plus terminal-raise discrimination test.
- [ ] Add a mixed-state bad twin.
- [ ] Recognize `RaiseValue` as `ExceptionalExitValue`.
- [ ] Run focused tests green.
- [ ] Add truthful/lying real-solver witness.

### Task 2: Receipt

- [ ] Replay both named representatives.
- [ ] Run RuntimeEffect invariant and Black 26.5.1.
- [ ] Record conservation and `silent=0`.
