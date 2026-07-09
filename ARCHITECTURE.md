# Architecture — linkedin-dev-pipeline

A pipeline that turns GitHub engineering activity into a **knowledge graph**, then
uses an LLM (OpenAI via OpenRouter) to draft LinkedIn content for **human review**
before publishing. The source of truth is the engineering work, not a social-media
calendar.

```
GitHub (your activity, your repos, watched upstream, linkedin-developers/*)
   │
   ▼
Poller ──► SQLite state store (dedup, event log)
   │
   ▼
Knowledge layer (repo context, PR/issue history, review discussion, your style)
   │            ── phase 2: embeddings / RAG (sqlite-vec)
   ▼
Drafter (OpenRouter / OpenAI) ── rotated content categories
   │
   ▼
Drafts (local markdown) ──► Human approval
   │
   ▼
LinkedIn API client (phase 3, official w_member_social scope, your own profile only)
```

## Design principles

1. **Automate preparation, not action.** Drafting, summarizing, recommending —
   automated. Posting, connecting, messaging — human. LinkedIn's ToS is strict on
   automation; this design stays inside it.
2. **One source of truth.** The knowledge graph feeds LinkedIn, a future personal
   site, and a portfolio — all from the same event store.
3. **Teach, don't brag.** Drafts rotate through categories (deep dive, lessons from
   review, architecture, performance, reflection, tips, weekly log) rather than
   "merged another PR."
4. **Polling first, webhooks later.** No public endpoint needed for a personal
   pipeline. Webhooks can be added once a server exists.

## Phased plan

### Phase 1 — Poll + Draft (current)

- GitHub activity poller: your user events, your own repos' issues/PRs/comments,
  watched upstream repos (opportunity scan), linkedin-developers/* repos.
- SQLite state store with dedup (event IDs) so re-runs are idempotent.
- OpenRouter drafter: takes new events + category, produces a LinkedIn draft.
- CLI: `ldp poll`, `ldp draft`, `ldp run` (poll then draft).
- Output: markdown files in `drafts/` for manual review.
- **No LinkedIn API calls yet.**

### Phase 2 — Knowledge graph / RAG

- Index repo context: README, docs/, architecture docs, RFCs, maintainer guides,
  open/merged PRs, your PRs, review comments.
- Embeddings via sqlite-vec (or chromadb) keyed to repo + doc chunk.
- RAG retrieval at draft time so generation is grounded in real context, not
  from-scratch prompting.
- Per-maintainer memory: how each maintainer reviews, what they care about.

### Phase 3 — LinkedIn app + posting

- Step-by-step LinkedIn developer app creation (you do this in the LinkedIn
  portal; we provide the guide and the integration).
- OAuth 2.0 flow for `w_member_social` scope (post to your own profile).
- Approval step: reviewed draft → `ldp publish <draft>` → LinkedIn API.
- **No automated connection requests or messaging.** That violates ToS and is
  out of scope.

### Phase 4 — Human-in-the-loop UI

- Simple local web UI (FastAPI + small frontend) or TUI to:
  - review drafts, edit, approve/reject
  - see what the poller found
  - trigger re-drafts with a different category

### Phase 5 — Higher-order agents

- **Network recommendations:** people you've actually collaborated with
  (reviewers, maintainers who merged your PRs) — surfaced for manual connect.
- **Weekly engineering report:** merged / opened / reviewed / learned, Friday
  digest, convertible to a LinkedIn post.
- **Opportunity finder:** flags new `help-wanted` issues, regressions, and
  discussions in watched upstream repos.
- **Portfolio / query interface:** "who have I interacted with most?", "which
  companies accepted my code?", "suggest 3 repos where my TensorRT work
  transfers."

## Module layout (phase 1)

```
src/ldp/
  __init__.py
  config.py          # pydantic settings, loads config.yaml + env
  models.py          # dataclasses / pydantic models for events, drafts
  store.py           # SQLite state store (events, drafts, dedup)
  github_poller.py   # GitHub client + poller for all source types
  drafter.py         # OpenRouter client + prompt construction
  cli.py             # typer CLI: poll / draft / run / status
```

## Data model (phase 1)

- `events` table: `id` (github event id), `kind`, `source` (user|own_repo|upstream|linkedin),
  `repo`, `number`, `actor`, `payload_json`, `created_at`, `seen_at`.
- `drafts` table: `id`, `event_ids_json`, `category`, `body`, `created_at`, `status`
  (draft|approved|rejected|published).

## Why polling over webhooks (for now)

Webhooks need a public, authenticated endpoint with retry handling. For a single
user on a laptop, a scheduled poll (cron / launchd / manual) against the GitHub
REST API is simpler, cheaper, and has no attack surface. The poller is
idempotent via event-ID dedup, so frequency is harmless. Webhooks remain a
phase-4+ option once a server exists.
