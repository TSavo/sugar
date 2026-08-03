# Merge-Group Trigger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CI dispatchable for future merge-group candidates without enabling a merge queue or requiring the red acid context.

**Architecture:** Extend the independently enrolled workflow-dispatchability test with a small indentation-aware event parser and exact truthful/lying twins. Then add only the top-level `merge_group: types: [checks_requested]` trigger to `ci.yml`.

**Tech Stack:** GitHub Actions YAML, Python 3 standard-library `unittest`, Ruby YAML parser.

## Global Constraints

- Queue activation and required status contexts remain out of scope.
- Main protection stays with zero required contexts.
- Do not add a `pull_request` trigger.
- Do not change acid jobs, fan-out, batching, or concurrency.
- Write the dispatchability tooth before editing the workflow.

---

### Task 1: Pin merge-group dispatchability independently

**Files:**

- Modify: `tests/test_workflow_context_availability.py`
- Test: `tests/test_workflow_context_availability.py`

- [ ] **Step 1: Add the exact discriminator and its twins**

Add an indentation-aware helper that inspects the top-level `on` mapping and returns the configured activity types for a named event. Add fixtures proving that the discriminator:

- accepts top-level `merge_group` with exactly `checks_requested`;
- rejects a missing event;
- rejects `merge_group` nested beneath `push`;
- rejects any activity type other than `checks_requested`.

Add a test applying the same law to `.github/workflows/ci.yml`.

- [ ] **Step 2: Run the tooth before changing `ci.yml` and prove RED**

Run:

```bash
python3 tests/test_workflow_context_availability.py
```

Expected: the fixture discrimination passes and the real-workflow test fails because `ci.yml` has no top-level `merge_group` trigger.

- [ ] **Step 3: Commit the red instrument if a review boundary is useful**

The red evidence may remain in the final implementation commit; the required artifact is the captured failing terminal before the workflow edit.

### Task 2: Add the smallest lawful workflow trigger

**Files:**

- Modify: `.github/workflows/ci.yml`
- Test: `tests/test_workflow_context_availability.py`

- [ ] **Step 1: Add only the top-level event**

Add this sibling beside `push` without changing the existing push branches or path filters:

```yaml
merge_group:
  types: [checks_requested]
```

- [ ] **Step 2: Prove the dispatchability tooth GREEN**

Run:

```bash
python3 tests/test_workflow_context_availability.py
```

Expected: all workflow-context tests pass.

- [ ] **Step 3: Keep syntax and dispatchability as separate evidence**

Run:

```bash
ruby -e 'require "yaml"; paths=Dir[".github/workflows/*.{yml,yaml}"]; paths.each { |p| YAML.load_file(p) }; puts "yaml-ok #{paths.length}"'
python3 -m py_compile tests/test_workflow_context_availability.py
git diff --check
```

Expected: all workflow YAML documents parse, Python compiles, and the diff is clean.

### Task 3: Publish the trigger-only change

**Files:**

- Verify: `.github/workflows/ci.yml`
- Verify: `tests/test_workflow_context_availability.py`
- Verify: `docs/superpowers/specs/2026-08-03-merge-group-trigger-design.md`
- Verify: `docs/superpowers/plans/2026-08-03-merge-group-trigger.md`

- [ ] **Step 1: Commit and preflight the complete branch**

Enumerate every commit and changed file against `origin/main`; confirm there are no deletions, foreign commits, runner-capacity changes, or new category/kind/label/taxonomy/residual vocabulary.

- [ ] **Step 2: Push and open a ready PR**

The PR must state that the trigger makes the acid vector producible for merge-group candidates but does not enable a queue, require a context, or claim the currently red acid test is green.

- [ ] **Step 3: Leave policy unchanged**

Verify branch protection still has zero required status contexts and that no ruleset or merge queue was created.
