# linkedin-dev-pipeline

An engineering knowledge graph that drafts LinkedIn content from your GitHub
activity — **human-in-the-loop**, never auto-posting. Built so that contributing
to open source becomes the source of truth, and LinkedIn becomes the
distribution channel for the lessons, not a personal-brand treadmill.

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the full design and phased plan.

## What it does (phase 1)

- Polls GitHub for your activity: your public events, your own repos,
  `linkedin-developers/*` repos you contribute to, and watched upstream repos
  (tensorflow, ultralytics, pytorch, roboflow, rust-libp2p) for opportunities.
- Stores events in a local SQLite DB with dedup (idempotent re-runs).
- Drafts LinkedIn posts via OpenAI on OpenRouter, rotating through content
  categories (technical deep dive, lessons from review, architecture, etc.).
- Writes drafts to `drafts/*.md` for you to review and post manually.

**What it does NOT do:** post to LinkedIn, send connection requests, or message
anyone. Those stay manual (and inside LinkedIn's ToS). LinkedIn API posting is
phase 3, scoped to your own profile only.

## Setup

### 1. Prerequisites

- Python 3.10+
- A GitHub personal access token (scopes: `repo`, `read:org`, `read:user`, `gist`)
- An OpenRouter API key (https://openrouter.ai/keys)

### 2. Install

```bash
git clone https://github.com/davidnichols-ops/linkedin-dev-pipeline.git
cd linkedin-dev-pipeline
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. Configure

```bash
cp .env.example .env
# edit .env: set GITHUB_TOKEN and OPENROUTER_API_KEY

cp config.example.yaml config.yaml
# edit config.yaml: set your repos, watched upstream, poll window
```

Environment variables override `config.yaml` for secrets.

### 4. Run

```bash
# poll GitHub and store new events
ldp poll

# see what's in the store
ldp status

# draft a LinkedIn post from recent events
ldp draft

# force a specific category
ldp draft -c lessons_from_code_review

# poll then draft in one step
ldp run

# list drafts
ldp drafts

# approve a draft (marks it ready to post manually)
ldp approve <draft-id-prefix>
```

Drafts land in `drafts/` as markdown files with a YAML front-matter block
(id, category, status, event ids). Edit them freely, then post to LinkedIn
yourself.

## Scheduling (optional)

Poll on a schedule with cron or launchd. Example crontab entry (every 6 hours):

```cron
0 */6 * * * cd /path/to/linkedin-dev-pipeline && .venv/bin/ldp poll >> ldp.log 2>&1
```

Then run `ldp draft` manually when you want to generate a post.

## LinkedIn developer app (phase 3 prep)

Posting to LinkedIn requires a LinkedIn developer app. **You must create this
yourself** (it's tied to your LinkedIn account and you accept the ToS). Steps:

1. Go to https://www.linkedin.com/developers/apps/new
2. Create an app:
   - App name: `linkedin-dev-pipeline`
   - LinkedIn Page: associate with your personal page (or create one)
   - App logo + description
3. In the app, under **Products**, request access to **"Sign In with LinkedIn
   using OpenID Connect"** and **"Share on LinkedIn"** (the
   `w_member_social` scope).
4. Under **Auth**, note your **Client ID** and **Client Secret**.
5. Set redirect URL to `http://localhost:8000/callback` (for local dev).
6. Verify the app (LinkedIn usually requires the app URL to be reachable; for
   local dev the redirect flow still works for personal testing).
7. Put the credentials in `.env`:
   ```
   LINKEDIN_CLIENT_ID=...
   LINKEDIN_CLIENT_SECRET=...
   LINKEDIN_REDIRECT_URI=http://localhost:8000/callback
   ```

Phase 3 will add an OAuth flow (`ldp linkedin auth`) and a
`ldp publish <draft>` command that posts an approved draft to your own profile
via the `w_member_social` scope. **No connection-request or messaging
automation will be built** — that violates LinkedIn's ToS.

## Project layout

```
src/ldp/
  config.py          # pydantic config + env overrides
  models.py          # Event / Draft dataclasses
  store.py           # SQLite state store (events, drafts, dedup)
  github_poller.py   # GitHub activity poller (4 source types)
  drafter.py         # OpenRouter / OpenAI drafter
  cli.py             # typer CLI: poll / draft / run / status / drafts / approve
```

## Roadmap

- **Phase 1** (current): poll + draft to local files.
- **Phase 2**: knowledge graph / RAG over repo context (sqlite-vec embeddings).
- **Phase 3**: LinkedIn app + OAuth + `ldp publish` (own profile only).
- **Phase 4**: human-in-the-loop review UI (local web or TUI).
- **Phase 5**: network recommendations, weekly engineering report,
  opportunity finder, portfolio query interface.

## License

MIT
