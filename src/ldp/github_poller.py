"""GitHub activity poller.

Polls four kinds of sources and emits normalized Event objects:
  - user:        your recent public events (PRs opened/reviewed/merged, issues, comments)
  - own_repo:    issues/PRs/comments on repos under your own account
  - upstream:    watched upstream repos — opportunity scan (help-wanted, good-first-issue)
  - linkedin:    linkedin-developers/* repos you contribute to

Uses PyGithub. Idempotent via event-ID dedup in the Store.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from itertools import islice

from github import Github
from github.GithubException import GithubException

from .config import Config
from .models import Event


def _utc(dt) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class GitHubPoller:
    def __init__(self, cfg: Config):
        if not cfg.github_token:
            raise RuntimeError("GITHUB_TOKEN not set. Put it in .env or the environment.")
        self.cfg = cfg
        self.gh = Github(cfg.github_token)
        self._since = datetime.now(timezone.utc) - timedelta(days=cfg.poll_window_days)

    # ---- public API ----
    def poll_all(self) -> Iterator[Event]:
        yield from self.poll_user_events()
        for repo in self.cfg.own_repos:
            yield from self.poll_own_repo(repo, source="own_repo")
        for repo in self.cfg.linkedin_upstream:
            yield from self.poll_own_repo(repo, source="linkedin")
        for repo in self.cfg.watched_upstream:
            yield from self.poll_upstream_opportunities(repo)

    # ---- user public events ----
    def poll_user_events(self) -> Iterator[Event]:
        try:
            user = self.gh.get_user(self.cfg.github_user)
        except GithubException as e:
            print(f"[poller] could not load user {self.cfg.github_user}: {e}")
            return
        try:
            events = user.get_events()
        except GithubException as e:
            print(f"[poller] could not load events: {e}")
            return

        for ev in events:
            created = _utc(ev.created_at)
            if created < self._since:
                continue
            mapped = self._map_user_event(ev)
            if mapped:
                yield mapped

    def _map_user_event(self, ev) -> Event | None:
        etype = ev.type
        repo_name = ev.repo.name if ev.repo else "unknown/unknown"
        payload = ev.payload or {}
        actor = ev.actor.login if ev.actor else (self.cfg.github_user or "")

        kind = None
        number = None
        title = ""
        url = ""
        body = ""

        if etype == "PullRequestEvent":
            pr = payload.get("pull_request") or {}
            action = payload.get("action")
            number = pr.get("number")
            title = pr.get("title", "")
            url = pr.get("html_url", "")
            body = pr.get("body", "") or ""
            if action == "opened":
                kind = "pr_opened"
            elif action == "closed" and pr.get("merged"):
                kind = "pr_merged"
            elif action == "closed":
                kind = "pr_closed"
            elif action == "reopened":
                kind = "pr_reopened"
        elif etype == "IssuesEvent":
            issue = payload.get("issue") or {}
            action = payload.get("action")
            number = issue.get("number")
            title = issue.get("title", "")
            url = issue.get("html_url", "")
            body = issue.get("body", "") or ""
            if action == "opened":
                kind = "issue_opened"
            elif action == "closed":
                kind = "issue_closed"
            elif action == "reopened":
                kind = "issue_reopened"
        elif etype == "IssueCommentEvent":
            issue = payload.get("issue") or {}
            comment = payload.get("comment") or {}
            number = issue.get("number")
            title = issue.get("title", "")
            url = comment.get("html_url", "") or issue.get("html_url", "")
            body = comment.get("body", "") or ""
            kind = "issue_commented"
        elif etype == "PullRequestReviewEvent":
            pr = payload.get("pull_request") or {}
            review = payload.get("review") or {}
            number = pr.get("number")
            title = pr.get("title", "")
            url = review.get("html_url", "") or pr.get("html_url", "")
            body = review.get("body", "") or ""
            kind = "pr_reviewed"
        elif etype == "PushEvent":
            kind = "push"
            commits = payload.get("commits", [])
            body = f"{len(commits)} commit(s) to {payload.get('ref', '')}"
        elif etype == "ForkEvent":
            kind = "forked"
        elif etype == "WatchEvent":
            kind = "starred"

        if not kind:
            return None

        eid = f"user:{repo_name}#{number}:{etype}:{ev.id}"
        return Event(
            id=eid,
            kind=kind,
            source="user",
            repo=repo_name,
            number=number,
            actor=actor,
            title=title,
            url=url,
            body=body[:4000],
            payload={"raw_type": etype},
            created_at=_utc(ev.created_at),
        )

    # ---- own / linkedin repos: recent issues + PRs ----
    def poll_own_repo(self, repo_name: str, source: str = "own_repo") -> Iterator[Event]:
        try:
            repo = self.gh.get_repo(repo_name)
        except GithubException as e:
            print(f"[poller] could not load repo {repo_name}: {e}")
            return

        # recent pull requests
        try:
            for pr in islice(repo.get_pulls(state="all", sort="updated", direction="desc"), 15):
                updated = _utc(pr.updated_at)
                if updated < self._since:
                    break
                kind = (
                    "pr_merged"
                    if pr.merged
                    else ("pr_opened" if pr.state == "open" else "pr_closed")
                )
                eid = f"{source}:{repo_name}#{pr.number}:pr:{pr.id}"
                yield Event(
                    id=eid,
                    kind=kind,
                    source=source,
                    repo=repo_name,
                    number=pr.number,
                    actor=pr.user.login if pr.user else "",
                    title=pr.title,
                    url=pr.html_url,
                    body=(pr.body or "")[:4000],
                    payload={"state": pr.state, "merged": bool(pr.merged)},
                    created_at=_utc(pr.created_at),
                )
        except GithubException as e:
            print(f"[poller] PRs failed for {repo_name}: {e}")

        # recent issues
        try:
            for issue in islice(repo.get_issues(state="all", sort="updated", direction="desc"), 15):
                if issue.pull_request:  # skip PRs (already covered)
                    continue
                updated = _utc(issue.updated_at)
                if updated < self._since:
                    break
                kind = "issue_opened" if issue.state == "open" else "issue_closed"
                eid = f"{source}:{repo_name}#{issue.number}:issue:{issue.id}"
                yield Event(
                    id=eid,
                    kind=kind,
                    source=source,
                    repo=repo_name,
                    number=issue.number,
                    actor=issue.user.login if issue.user else "",
                    title=issue.title,
                    url=issue.html_url,
                    body=(issue.body or "")[:4000],
                    payload={"state": issue.state, "labels": [lbl.name for lbl in issue.labels]},
                    created_at=_utc(issue.created_at),
                )
        except GithubException as e:
            print(f"[poller] issues failed for {repo_name}: {e}")

    # ---- upstream: opportunity scan ----
    def poll_upstream_opportunities(self, repo_name: str) -> Iterator[Event]:
        try:
            repo = self.gh.get_repo(repo_name)
        except GithubException as e:
            print(f"[poller] upstream {repo_name}: {e}")
            return

        opportunity_labels = {"help wanted", "good first issue", "help-wanted"}
        try:
            for issue in islice(
                repo.get_issues(state="open", sort="created", direction="desc"), 30
            ):
                if issue.pull_request:
                    continue
                created = _utc(issue.created_at)
                if created < self._since:
                    break
                labels = {lbl.name.lower() for lbl in issue.labels}
                if not (labels & opportunity_labels):
                    continue
                eid = f"upstream:{repo_name}#{issue.number}:opportunity:{issue.id}"
                yield Event(
                    id=eid,
                    kind="opportunity",
                    source="upstream",
                    repo=repo_name,
                    number=issue.number,
                    actor=issue.user.login if issue.user else "",
                    title=issue.title,
                    url=issue.html_url,
                    body=(issue.body or "")[:2000],
                    payload={
                        "labels": [lbl.name for lbl in issue.labels],
                        "comments": issue.comments,
                    },
                    created_at=created,
                )
        except GithubException as e:
            print(f"[poller] upstream issues failed for {repo_name}: {e}")
