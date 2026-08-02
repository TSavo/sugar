# GitHub API budget (identity hub isolation)

> **A GitHub API call must testify to the budget it spends.**
> Infrastructure and agents must not share one rate-limit identity.
> Any shared hub that lets agent polling blind the runner autoscaler is the
> same defect class as a measurement that cannot testify to its conditions.

## What collapsed (2026-08-02)

**Measured root cause:** the runner autoscaler shared **our** GitHub user token
budget. Eight agents polling `gh` all night drained `core remaining` to **0**.
The autoscaler then got **403** on every `GET .../actions/runners` query, went
**blind**, could not scale, and **421 jobs** queued behind **25** static
runners. It looked like the runners were broken. They were fine.

That is a **shared identity hub**: one budget, multiple producers, no isolation —
the exact class we spent the night forbidding elsewhere (load, lease, corpus pin).

Secondary pressure: **~70 merges to main**, each firing a full CI fan-out,
built the backlog the blind autoscaler could not absorb.

## Fix 1 — autoscaler owns its own token (required)

**Location (battleaxe):** `/home/tsavo/.github/runner-autoscaler`  
(repo: `wopr-network/.github`, service `runner-autoscaler`)

Today repo-scoped API uses vault field `ops_pat` on `secret/shared/github`
(`GITHUB_REPO_PAT_FIELD`, default was `ops_pat`). That PAT lives in the same
user-rate-limit pool as agent `gh` auth as `TSavo`.

### What T must put in Vault (credentials this agent cannot mint)

**Preferred:** GitHub App installation for infrastructure only.

1. Create a GitHub App (e.g. `wopr-runner-autoscaler`) on the org / user that
   owns the runners:
   - Permissions (minimum): **Actions** (read), **Administration** /
     self-hosted runners (write/admin as needed for registration), **Metadata**
   - Install on `wopr-network` and on `TSavo/sugar` (and any other
     `GITHUB_REPOS` entries)
2. Prefer **installation access tokens** (App JWT → installation token) so the
   quota is **installation-scoped**, not the human user 5000/hr pool.

**Acceptable interim:** a **machine-user** classic/fine-grained PAT (separate
GitHub user, e.g. `wopr-runner-bot`), never the human `TSavo` oauth/PAT that
agents use.

3. Store the secret in Vault:
   - Path: `secret/shared/github`
   - **New field:** `autoscaler_pat` (or App installation token material under
     a dedicated path if you extend the client)
   - Do **not** reuse `ops_pat` / agent tokens

4. Point the autoscaler at it:

```bash
# /home/tsavo/.github/runner-autoscaler/.env
GITHUB_REPO_PAT_FIELD=autoscaler_pat
```

(Default in config should already be `autoscaler_pat` after the isolation
patch; set explicitly until rolled out.)

5. Restart:

```bash
cd /home/tsavo/.github/runner-autoscaler && bin/start.sh
# or: docker compose up -d --build autoscaler
```

6. **Verify isolation:** agent `gh api rate_limit` remaining should not drop
   when only the autoscaler lists runners; autoscaler logs must not 403 while
   agents are quiet.

Org-scoped registration may still use `runner_registration_pat` — keep that
field **infra-only** as well; never the agent oauth token.

## Fix 2a — meter agent/tooling use (load-gate shape)

```bash
# report only
python3 tools/gh_rate_budget.py
# or
bin/gh-budget

# refuse if remaining < floor (default 500) — exit 79
bin/gh-budget --floor 800

# spend only if budget ok
bin/gh-budget pr view 1 --json url
# equivalent:
python3 tools/gh_rate_budget.py --floor 500 -- wrap -- gh pr view 1 --json url
```

| Exit | Meaning |
| --- | --- |
| 0 | remaining ≥ floor (optional wrapped command ran) |
| **79** | **budget low** — do not spend; wait for reset |
| 2 | cannot measure budget |

**Floor default 500** leaves headroom for the autoscaler and a cancellation
sweep. Raise `GH_RATE_BUDGET_FLOOR` during incidents.

**Agents must not** bare-poll `gh pr view` / `gh api` / `gh run list` in loops.
Prefer `bin/gh-budget`. No polling until reset after a 79.

## Fix 2b — coalesce merge fan-out (policy + soft controls)

Every merge to `main` that triggers a full matrix is a budget and runner
multiplier. Prefer:

1. **Path filters** on per-commit workflows so pure `docs/**` (and other
   non-product paths) do not fan out heavy jobs.
2. **Keep heavy corpus instruments** on `schedule` + `workflow_dispatch` (as
   control-effect-recensus already is) — not on every push.
3. **Batch merges** during a train: fewer tips, fewer identical suite starts.
4. **Do not** reintroduce GitHub `concurrency:` that **drops pending runs** on
   `main` (evidence loss — see `ci.yml` comment). Coalesce by **not starting**
   redundant work, not by discarding queued evidence.

`ci.yml` may use `paths-ignore: ['docs/**']` so documentation-only tips do not
consume a full core matrix; product paths still always run.

## Unstoppable workflow runs (delete, do not cancel)

These runs accept cancel but never change state — no runner will claim them to
process the cancel. **Cancel loops forever; they need admin delete**, not more
cancel API.

| Run ID | Commit | Note |
| --- | --- | --- |
| `25907072649` | `6030866eb` | unstoppable — delete |
| `25907072689` | `6030866eb` | unstoppable — delete |
| `25907063329` | `6030866eb` | unstoppable — delete |

**Delete path (when API budget allows, by infra owner):**

```bash
# Requires admin actions permission; may need UI:
# Repo → Actions → run → ⋯ → Delete workflow run
#
# API (sparingly — this is the budget we just saved):
gh api -X DELETE "/repos/TSavo/sugar/actions/runs/25907072649"
gh api -X DELETE "/repos/TSavo/sugar/actions/runs/25907072689"
gh api -X DELETE "/repos/TSavo/sugar/actions/runs/25907063329"
```

If DELETE is 403/404, use the Actions UI as admin. Document any replacement IDs
here when a future bankruptcy leaves zombies — do not cancel-loop them.

## Related

- Runner autoscaler: battleaxe `/home/tsavo/.github/runner-autoscaler`
- Measurement law (same isolation class): `docs/contributing/measurement-conditions.md`
- Host lease path (shared container bind-mount):  
  `/home/runner/.cache/sugar/binaries/.sugar-heavy-measurement.lease`
