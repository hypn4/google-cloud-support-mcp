"""Configuration, validated at start-up rather than at first use.

A malformed parent discovered on the first tool call reads as an API failure;
discovered at start-up it reads as what it is — a typo in the environment.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings", "get_settings"]

_PARENT = re.compile(r"^(projects|organizations)/[A-Za-z0-9][A-Za-z0-9\-_.]*$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GOOGLE_CLOUD_SUPPORT_MCP_",
        env_file=".env",
        extra="ignore",
    )

    parents: list[str] = Field(
        default_factory=list,
        description="Scopes to query, e.g. ['projects/my-proj', 'organizations/123']",
    )
    quota_project: str | None = Field(
        default=None,
        description="Billing/quota project for user credentials; organization-level calls need it",
    )
    enable_writes: bool = True
    enable_escalation: bool = Field(
        default=False,
        description="Off by default: escalation reaches Google's support organisation directly",
    )
    download_dir: Path = Field(default_factory=lambda: Path(tempfile.gettempdir()))
    max_upload_bytes: int = 10_000_000
    default_page_size: int = 20
    fanout_concurrency: int = 5

    @field_validator("parents")
    @classmethod
    def _validate_parents(cls, value: list[str]) -> list[str]:
        bad = [p for p in value if not _PARENT.match(p)]
        if bad:
            raise ValueError(
                f"Invalid parent(s): {bad}. Each entry must be 'projects/{{id}}' or "
                f"'organizations/{{id}}'."
            )
        return value

    @property
    def organization_parents(self) -> list[str]:
        return [p for p in self.parents if p.startswith("organizations/")]


def get_settings(**overrides) -> Settings:
    return Settings(**overrides)
