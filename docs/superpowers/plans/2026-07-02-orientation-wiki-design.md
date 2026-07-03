# Orientation Wiki — Design & Integration

**Problem:** Orientation is the scarce resource and its current stores are weak: ~100 flat memory files (write-once, link-poor, no lint, no supersession), plan docs (durable pitch, perishable receipts), GH issues (human ledger), red instruments (agent interface), and a context window that compacts lossily. The llm-wiki pattern (Karpathy gist, Apr 2026) fills the gap between the flat files and the context window: a compounding, linted, agent-maintained synthesis layer.

**Standards adopted, by tier:**
- Tier 1 (gist core, fixed): three-layer split with immutable sources; index.md catalog contract; append-only grep-able log.md; lint checklist; citations + file-answers-back.
- Tier 2 (de-facto ecosystem): frontmatter `type/title/description/tags/timestamp/sources`; page types entity/concept/summary/synthesis/overview; linter-as-agent.
- Tier 3 (v2/OKF convergence): typed edges `supersedes`/`contradicts`; required `type`; lint reports for orphans/stubs/near-dupes/contradictions.
- Our addition (the teeth, tier 4 — nobody else has it): mechanical lint as a RED INSTRUMENT (exit 1), content-hashed revisions, sources pinned to code by path@commit, claim-grep.

---

## 1. WHERE — two wikis, different substrates, one schema

| | **kit-wiki** | **sugar-wiki** |
|---|---|---|
| Location | `~/.claude/projects/-Users-tsavo/memory/wiki/` | `<repo>/docs/wiki/` |
| Scope | T, doctrine, cross-project decisions, collaboration patterns | sugar architecture, campaign state, audit syntheses, crime/PR history |
| Lifecycle | personal, cross-session, never in a repo PR | versioned WITH the code; changes ride PRs; worktree agents can read it |
| Writer | Kit (coordinator) only | Kit only (workers may PROPOSE pages in PR bodies; Kit files them) |
| Lint runs | session start (cheap local script) | repo CI (a real red instrument beside the frontier auditors) |

**Interaction with MEMORY.md (the compulsion-adjacent layer):** MEMORY.md stays exactly what it is — the always-loaded routing file. Rule of residence:
- **Stays flat + indexed** (always-loaded): `user_*`, `feedback_*` (behavioral law — must apply without a read), plus one-line pointers to wiki overviews.
- **Moves to kit-wiki** (drill-down): `project_*` and `reference_*` synthesis — the 60+ sugar/provekit doctrine files become linted, linked, supersede-able pages. Their MEMORY.md lines collapse to: `- [Sugar orientation](wiki/index.md) — read overview.md at session start when working sugar.`
- MEMORY.md gains ONE new permanent line per wiki pointing at its `overview.md`.

This preserves the three-audience split: red instruments = agent compulsion path; GH issues = human ledger; wiki = the drill-down orientation layer between them.

## 2. SCHEMA — as it will appear in each wiki's CLAUDE.md

```markdown
## Wiki schema (v1 — de-facto llm-wiki frontmatter + v2 typed edges + teeth)

Every page is markdown with YAML frontmatter. Required fields:
  type:        entity | concept | summary | synthesis | overview | decision
  title:       exact page title (unique across the wiki)
  description: one line, used verbatim in index.md
  tags:        [list]
  timestamp:   ISO date of last substantive revision
  sources:     [list] — every claim-bearing page MUST cite ≥1 source:
               - repo paths as path@commit (e.g. sugar-cli/src/cmd_verify.rs@907658d)
               - PRs/issues as sugar#NNNN
               - external URLs
               - other pages as [[wikilinks]]
  rev:         blake3-8 of the body below the frontmatter (updated on every write)
Optional typed edges (v2):
  supersedes:  [[page]] — this page replaces that one; lint requires the target
               to gain `superseded_by:` in the same edit
  contradicts: [[page]] — flagged tension, unresolved on purpose; lint counts these

Files:
  index.md    — catalog: every page, one line each: [[link]] — description (type).
                Grouped by type. Updated in the SAME edit as any page change.
  overview.md — the 1-screen orientation read; regenerated when drift-linted stale.
  log.md      — append-only. Entry prefix: `## [YYYY-MM-DD] <op> | <title>` where
                op ∈ ingest|query|lint|supersede. Greppable: grep "^## \[" log.md.
Laws:
  - Raw sources are immutable; the wiki never restates a COUNT or STATUS that an
    instrument or issue owns — it links and explains WHY (counts are measured
    output, never authored state).
  - Sugar is never naked; a page is never sourceless.
  - One writer (Kit). Workers propose; Kit files.
```

## 3. TEETH — the lint is a red instrument

Split the gist's lint checklist by what is actually mechanical:

**`wiki_lint.py` (deterministic, stdlib-only, exit 1 on violation) — build FIRST, before any pages:**
1. Schema integrity: required frontmatter present, `type` in vocabulary, unique titles.
2. Dangling `[[wikilinks]]` — allowed ONLY if the target appears in `index.md` under a `planned:` stanza (Karpathy's "write this later" marker, made explicit).
3. Orphans: zero inbound links AND not indexed → red.
4. Index coverage: every page in index.md, every index entry resolves, description matches frontmatter.
5. log.md format: every entry matches the prefix grammar.
6. `rev` correctness: recompute blake3 of body, compare — a page edited without a rev bump is red (the memento discipline in miniature: content-address or it didn't happen).
7. Supersession integrity: `supersedes` targets exist and carry `superseded_by` back-links.
8. Staleness (warn-only axis): pages > 60d untouched whose sources are repo paths where the pinned commit is > N merges behind.

**LLM lint pass (probabilistic, on-demand, never green-gating):** contradiction detection between pages, coverage gaps, synthesis drift. Output = `contradicts:` edges and proposed pages — which the mechanical lint then tracks. The LLM proposes; the script holds the floor.

**Claim-grep (tier-4, the doctrine-grep applied to the wiki):** for sources of form `path@commit`, lint verifies the path exists at that commit (`git cat-file -e commit:path`). Later (not v1): verify a named symbol still exists — every wiki claim about code becomes a checkable claim against the code.

**NOW vs LATER:** v1 = checks 1–8 + claim-grep path existence. LATER = symbol-level claim-grep, CID-chained revision history, memento-pinned external sources. Do not build the later teeth speculatively.

## 4. OPERATIONS mapped to our workflow

- **Ingest — sugar-wiki:** at MERGE time, coordinator ritual, bounded to ≤1 page-touch batch per merge: significant merges (instruments, campaign slices, audit results) get a synthesis/summary page or an update to affected entity pages + index + log. Routine drains get a log line only. Audit reports (like tonight's five) are the canonical ingest sources.
- **Ingest — kit-wiki:** at session end (or natural pause), replacing today's ad-hoc `project_*` memory writes: new doctrine/decisions get pages with typed edges instead of new flat files.
- **Query:** session start = read `overview.md` + `index.md` of the relevant wiki (drill only as needed). This SHRINKS the always-loaded surface (MEMORY.md gets shorter, not longer). ctx_search session memory remains the intra-session recall tool; the wiki is the cross-session synthesis — no overlap: ctx is transcript-shaped, wiki is knowledge-shaped.
- **Lint:** sugar-wiki lint runs in repo CI (new red instrument, lives beside the silent-drop frontier); kit-wiki lint runs at session start via the existing session hook surface (cheap, <1s). LLM lint pass: monthly or when the mechanical lint's `contradicts` count moves.

## 5. MIGRATION — first three ingest batches

1. **Batch 1 (sugar-wiki seed, ~10 pages):** tonight's material — `overview.md`, entity pages for the substrate/python-kit/rust-kit/verifier/IR-compilers, concept pages for IDD+red-instruments and floor/temporal/effect algebra, synthesis pages for the five audit reports, decision page for Option B. Sources: the audit outputs, PRs #3011–#3034, plans #2979/#3014/#3015. This is also the lint script's first real corpus — build `wiki_lint.py` first, seed second, red-to-green third.
2. **Batch 2 (sugar-wiki):** the campaign plans + crime board as synthesis pages — each phase epic (#3017, #3025–#3028) gets a concept page carrying the WHY (the plan carries the how; the issue carries the status; the wiki page carries the argument).
3. **Batch 3 (kit-wiki):** migrate `project_sugar_*` + `project_provekit_*` memory files (~60) into pages with supersession links (several are already stale-vs-each-other — the migration IS the first contradiction pass). `user_*`/`feedback_*` stay flat. MEMORY.md shrinks by ~60 lines.

## 6. RISKS

- **Double-bookkeeping / drift between wiki, memory, issues:** killed by the residence rule (each fact has ONE home: behavior→flat memory, status/counts→issues+instruments, why/synthesis→wiki) and by the lint law that pages may not restate counts or statuses — they link. Wiki pages that duplicate an issue's status will rot; pages that explain why an issue exists won't.
- **Maintenance tax:** bounded by design — merge-time ingest is ≤1 batch, routine merges are a log line. If the tax exceeds ~5 min/merge, the schema is wrong; fix the schema, don't skip the ritual (log it as a lint axis: `unfiled_merges`).
- **Stated-verdict territory (the wiki lying about the code):** this is the real danger and the reason for tier-4 teeth. Every claim-bearing page pins `path@commit`; claim-grep makes cited paths checkable; staleness lint flags pages whose pinned commits fall behind. Doctrine-grep applies to the wiki exactly as to axioms: a page is a claim against the code, and the lint is where the code gets to disagree. Until symbol-level claim-grep exists, the mitigation is cultural: wiki = orientation, never authority; authority stays in instruments and proofs.
- **Fork/agent writes corrupting structure:** single-writer law + the lint in CI; a worker PR that edits `docs/wiki/` without passing lint is red like any other instrument violation.

## Definition of done (v1)

`wiki_lint.py` exists and is red-instrument-wired (CI for sugar-wiki, session hook for kit-wiki); both wikis seeded per Batch 1/3; MEMORY.md shrunk with pointers; lint green on seeds; GH issues filed per the tracking law (one epic per wiki + one for the lint instrument).
