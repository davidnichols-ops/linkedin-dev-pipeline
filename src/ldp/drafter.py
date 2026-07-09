"""OpenRouter drafter: turns events into LinkedIn post drafts.

Calls OpenRouter's OpenAI-compatible chat completions endpoint. Constructs a
prompt that rotates through content categories and instructs the model to
teach rather than brag. Drafts are returned for human review — never posted.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import httpx

from .config import Config
from .models import Draft, Event

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

CATEGORY_GUIDE = {
    "technical_deep_dive": "A focused technical explanation of a problem, its root cause, and how it was solved. Teach the reader something concrete.",
    "lessons_from_code_review": "What a maintainer's review feedback taught you. Be specific about the change requested and the principle behind it.",
    "architecture_reflection": "A reflection on how a piece of a codebase is structured and why it's interesting or surprising.",
    "performance_investigation": "A performance issue you investigated: symptom, measurement, root cause, fix, and the lesson.",
    "open_source_reflection": "A broader reflection on contributing to open source — process, community, or a specific interaction.",
    "small_engineering_tip": "One small, immediately useful engineering tip drawn from recent work.",
    "weekly_engineering_log": "A concise weekly log: merged, opened, reviewed, learned. Grouped, not bragging.",
}

SYSTEM_PROMPT = """You are a ghostwriter for a senior software engineer who contributes to
large open-source projects (TensorFlow, Ultralytics, PyTorch, Roboflow, rust-libp2p, and
LinkedIn's open-source repos). You draft LinkedIn posts from GitHub activity.

Hard rules:
- Teach, don't brag. Never write "I merged another PR!" or empty self-promotion.
- Every post must teach the reader something concrete or share a genuine lesson.
- Use plain, direct language. No hype words ("game-changing", "thrilled", "excited").
- Keep it tight: 3-6 short paragraphs or a short bulleted breakdown.
- Use the engineer's first-person voice but stay understated.
- Do not invent technical details. Only use facts present in the provided activity.
- If the activity is too thin to write a good post, return exactly: NOT_ENOUGH_CONTEXT
- Output ONLY the post text. No preamble, no hashtags unless they fit naturally (max 3).

The post should read like a thoughtful engineer sharing real work, not a marketer."""


def _build_user_prompt(events: list[Event], category: str) -> str:
    guide = CATEGORY_GUIDE.get(category, "A thoughtful engineering post.")
    lines = [
        f"Content category for this draft: {category}",
        f"Category intent: {guide}",
        "",
        "Recent GitHub activity:",
    ]
    for ev in events:
        lines.append(f"- [{ev.kind}] {ev.repo}#{ev.number} — {ev.title}")
        if ev.url:
            lines.append(f"  url: {ev.url}")
        if ev.body:
            snippet = ev.body.strip().replace("\n", " ")[:500]
            lines.append(f"  body: {snippet}")
        if ev.payload:
            extra = {
                k: v
                for k, v in ev.payload.items()
                if k in ("labels", "state", "merged", "comments")
            }
            if extra:
                lines.append(f"  meta: {json.dumps(extra)}")
    lines.append("")
    lines.append("Write one LinkedIn post in the category above, grounded in this activity.")
    return "\n".join(lines)


class Drafter:
    def __init__(self, cfg: Config):
        if not cfg.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set. Put it in .env or the environment.")
        self.cfg = cfg
        self.model = cfg.effective_draft_model
        self.client = httpx.Client(timeout=60.0)

    def draft(self, events: list[Event], category: str | None = None) -> Draft | None:
        if not events:
            return None
        cat = category or self._pick_category(events)
        user_prompt = _build_user_prompt(events, cat)
        body = self._call(user_prompt)
        if not body or body.strip() == "NOT_ENOUGH_CONTEXT":
            return None
        return Draft(
            id=str(uuid.uuid4()),
            event_ids=[e.id for e in events],
            category=cat,
            body=body.strip(),
            created_at=datetime.now(timezone.utc),
        )

    def _pick_category(self, events: list[Event]) -> str:
        """Pick a category heuristically from the event mix."""
        kinds = {e.kind for e in events}
        if "pr_reviewed" in kinds:
            return "lessons_from_code_review"
        if "pr_merged" in kinds:
            return "technical_deep_dive"
        if "opportunity" in kinds:
            return "open_source_reflection"
        if "issue_opened" in kinds or "issue_commented" in kinds:
            return "architecture_reflection"
        return "small_engineering_tip"

    def _call(self, user_prompt: str) -> str:
        resp = self.client.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {self.cfg.openrouter_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/davidnichols-ops/linkedin-dev-pipeline",
                "X-Title": "linkedin-dev-pipeline",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
                "max_tokens": 900,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> Drafter:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
