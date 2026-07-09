"""Configuration: loads config.yaml with environment-variable overrides."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

load_dotenv()

DEFAULT_CONFIG_NAME = "config.yaml"


class Config(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    github_user: str = "davidnichols-ops"
    own_repos: list[str] = Field(default_factory=list)
    watched_upstream: list[str] = Field(default_factory=list)
    linkedin_upstream: list[str] = Field(default_factory=list)
    poll_window_days: int = 7
    draft_model: str = "openai/gpt-4o-mini"
    drafts_dir: str = "drafts"
    state_db: str = "data/ldp.sqlite"
    content_categories: list[str] = Field(
        default_factory=lambda: [
            "technical_deep_dive",
            "lessons_from_code_review",
            "architecture_reflection",
            "performance_investigation",
            "open_source_reflection",
            "small_engineering_tip",
            "weekly_engineering_log",
        ]
    )

    # secrets (env only)
    github_token: str | None = Field(default=None, alias="GITHUB_TOKEN")
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    openrouter_model: str | None = Field(default=None, alias="OPENROUTER_MODEL")
    linkedin_client_id: str | None = Field(default=None, alias="LINKEDIN_CLIENT_ID")
    linkedin_client_secret: str | None = Field(default=None, alias="LINKEDIN_CLIENT_SECRET")
    linkedin_redirect_uri: str | None = Field(
        default="http://localhost:8000/callback", alias="LINKEDIN_REDIRECT_URI"
    )
    linkedin_access_token: str | None = Field(default=None, alias="LINKEDIN_ACCESS_TOKEN")

    @property
    def effective_draft_model(self) -> str:
        return self.openrouter_model or self.draft_model


def load_config(path: Path | None = None) -> Config:
    """Load config from yaml, then overlay environment variables."""
    cfg_path = path or Path(DEFAULT_CONFIG_NAME)
    data: dict = {}
    if cfg_path.exists():
        data = yaml.safe_load(cfg_path.read_text()) or {}

    # env overrides for secrets
    env_map = {
        "GITHUB_TOKEN": "github_token",
        "OPENROUTER_API_KEY": "openrouter_api_key",
        "OPENROUTER_MODEL": "openrouter_model",
        "LINKEDIN_CLIENT_ID": "linkedin_client_id",
        "LINKEDIN_CLIENT_SECRET": "linkedin_client_secret",
        "LINKEDIN_REDIRECT_URI": "linkedin_redirect_uri",
        "LINKEDIN_ACCESS_TOKEN": "linkedin_access_token",
    }
    for env_key, field in env_map.items():
        val = os.environ.get(env_key)
        if val:
            data[field] = val

    return Config(**data)
